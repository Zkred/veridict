"""Formal spec gate, sourced from CI rather than executed by the issuer.

Why move it
-----------
The issuer used to fetch a PR's Python files and run mypy, pytest and Z3 itself,
in the same process that holds the credential signing key. That means executing
attacker-influenced code next to a secret: a synthesised PR only has to contain
a `conftest.py` that reads the environment to exfiltrate the issuer key. It is a
real exfiltration path, not a theoretical one, and it gets worse on a serverless
host where the same environment also carries the database URL.

Running the checks in the reviewed repository's own CI fixes that. GitHub Actions
already provides an isolated, per-run sandbox, the result is attested by GitHub,
and the issuer only has to read a verdict.

Trust model
-----------
The verdict is a check run on the head commit, which raises an obvious question:
who can create one? Anyone with a token that has `checks:write` on the repo,
including a collaborator with their own GitHub App. So a name match is not
enough — a check run named `veridict-spec-gate` reporting success proves nothing
on its own.

The gate therefore only accepts check runs created by GitHub Actions itself
(`app.slug == "github-actions"`). An attacker cannot register an app under that
slug. `SPEC_GATE_TRUSTED_APP_IDS` allows additional app ids for deployments that
run their checks somewhere other than Actions.

Modes (SPEC_GATE_MODE)
----------------------
  ci-required   Only a trusted, successful CI check run permits issuance.
                The correct setting for a real deployment.
  ci-preferred  Use the CI verdict when present; fall back to running the checks
                in-process when the repository has no gate workflow yet. Default,
                because requiring CI outright would block every repository that
                has not adopted the workflow.
  local         Run the checks in-process, as before. Keeps the exfiltration path
                open; useful only for local development.
"""

from __future__ import annotations

import os

import httpx

CHECK_NAME = os.environ.get("SPEC_GATE_CHECK_NAME", "veridict-spec-gate")
MODE = os.environ.get("SPEC_GATE_MODE", "ci-preferred").strip().lower()
TRUSTED_APP_SLUG = os.environ.get("SPEC_GATE_TRUSTED_APP_SLUG", "github-actions")
TRUSTED_APP_IDS = {
    int(x) for x in os.environ.get("SPEC_GATE_TRUSTED_APP_IDS", "").replace(",", " ").split()
    if x.strip().isdigit()
}


def _is_trusted(app: dict) -> bool:
    if app.get("slug") == TRUSTED_APP_SLUG:
        return True
    app_id = app.get("id")
    return isinstance(app_id, int) and app_id in TRUSTED_APP_IDS


def evaluate_check_runs(
    payload: dict,
    check_name: str = CHECK_NAME,
) -> dict:
    """Interprets a /check-runs response. Pure, so it can be tested on fixtures.

    Returns:
      found        a check run with this name exists from a trusted creator
      passed       ...and its conclusion is success
      reason       human-readable explanation
      details_url  link to the run, when available
      untrusted    a name match existed but its creator was not trusted
    """
    runs = payload.get("check_runs") or []
    named = [r for r in runs if r.get("name") == check_name]
    if not named:
        return {
            "found": False,
            "passed": False,
            "untrusted": False,
            "reason": f"no {check_name!r} check run on this commit",
            "details_url": None,
        }

    trusted = [r for r in named if _is_trusted(r.get("app") or {})]
    if not trusted:
        creators = sorted({(r.get("app") or {}).get("slug") or "?" for r in named})
        return {
            "found": False,
            "passed": False,
            "untrusted": True,
            "reason": (
                f"{check_name!r} exists but was created by {', '.join(creators)}, "
                f"not {TRUSTED_APP_SLUG}. Ignoring it: anyone with checks:write "
                "could otherwise self-report a passing gate."
            ),
            "details_url": None,
        }

    # Re-runs produce several check runs with the same name, so pick the newest
    # explicitly rather than trusting the API's ordering. Getting this wrong would
    # let a stale success outrank a later failure.
    def _recency(r: dict) -> str:
        return r.get("completed_at") or r.get("started_at") or ""

    run = max(trusted, key=_recency)
    conclusion = run.get("conclusion")
    status = run.get("status")
    if status != "completed":
        return {
            "found": True,
            "passed": False,
            "untrusted": False,
            "reason": f"{check_name!r} is still {status!r}; wait for CI to finish",
            "details_url": run.get("html_url"),
        }
    return {
        "found": True,
        "passed": conclusion == "success",
        "untrusted": False,
        "reason": f"{check_name!r} concluded {conclusion!r}",
        "details_url": run.get("html_url"),
    }


async def fetch_ci_verdict(
    owner: str, repo: str, sha: str, token: str | None,
) -> dict:
    """Reads the spec gate verdict for a commit. Never raises."""
    headers = {"Accept": "application/vnd.github+json"}
    if token and token != "DEV_NO_TOKEN":
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}/check-runs"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, headers=headers, params={"per_page": 100})
        if r.status_code != 200:
            return {
                "found": False,
                "passed": False,
                "untrusted": False,
                "reason": f"check-runs API returned {r.status_code}",
                "details_url": None,
            }
        return evaluate_check_runs(r.json())
    except Exception as e:  # network trouble must not read as a passing gate
        return {
            "found": False,
            "passed": False,
            "untrusted": False,
            "reason": f"could not read check runs: {e}",
            "details_url": None,
        }
