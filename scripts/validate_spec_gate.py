#!/usr/bin/env python3
"""Tests the CI spec-gate verdict logic.

The security property under test: a check run only counts if GitHub Actions
created it. Without that, anyone holding a `checks:write` token on the repository
could publish a check run named `veridict-spec-gate` with conclusion success and
walk an unverified PR straight through the gate.

    python3 scripts/validate_spec_gate.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "issuer"))

import spec_gate  # noqa: E402

failures: list[str] = []


def check(ok: bool, label: str) -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        failures.append(label)


def run(name: str, conclusion: str, app_slug: str, status: str = "completed",
        completed_at: str = "2026-01-01T00:00:00Z") -> dict:
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "completed_at": completed_at,
        "html_url": "https://github.com/o/r/runs/1",
        "app": {"slug": app_slug, "id": 15368 if app_slug == "github-actions" else 999},
    }


def main() -> int:
    print("=== spec gate verdict logic ===")

    v = spec_gate.evaluate_check_runs({"check_runs": []})
    check(v["found"] is False and v["passed"] is False, "no check runs -> not found")

    v = spec_gate.evaluate_check_runs(
        {"check_runs": [run("veridict-spec-gate", "success", "github-actions")]}
    )
    check(v["found"] and v["passed"], "Actions run with success -> passes")

    v = spec_gate.evaluate_check_runs(
        {"check_runs": [run("veridict-spec-gate", "failure", "github-actions")]}
    )
    check(v["found"] and not v["passed"], "Actions run with failure -> blocked")

    v = spec_gate.evaluate_check_runs(
        {"check_runs": [run("veridict-spec-gate", None, "github-actions", "in_progress")]}
    )
    check(v["found"] and not v["passed"], "still running -> blocked")

    # The attack: a success reported by something other than Actions.
    v = spec_gate.evaluate_check_runs(
        {"check_runs": [run("veridict-spec-gate", "success", "attacker-app")]}
    )
    check(
        v["passed"] is False and v["untrusted"] is True,
        "success from an untrusted app -> REJECTED (spoof blocked)",
    )

    # A trusted run alongside a spoofed one must still be honoured.
    v = spec_gate.evaluate_check_runs({
        "check_runs": [
            run("veridict-spec-gate", "success", "github-actions"),
            run("veridict-spec-gate", "success", "attacker-app"),
        ]
    })
    check(v["passed"] is True, "trusted run alongside a spoof -> passes on the trusted one")

    # A spoofed success must not mask a genuine failure.
    v = spec_gate.evaluate_check_runs({
        "check_runs": [
            run("veridict-spec-gate", "failure", "github-actions"),
            run("veridict-spec-gate", "success", "attacker-app"),
        ]
    })
    check(v["passed"] is False, "spoofed success cannot override a real failure")

    v = spec_gate.evaluate_check_runs(
        {"check_runs": [run("some-other-check", "success", "github-actions")]}
    )
    check(v["found"] is False, "unrelated passing check is not the gate")

    # Re-runs: the newest verdict wins regardless of the order the API returns.
    older_success = run("veridict-spec-gate", "success", "github-actions",
                        completed_at="2026-01-01T00:00:00Z")
    newer_failure = run("veridict-spec-gate", "failure", "github-actions",
                        completed_at="2026-06-01T00:00:00Z")
    v = spec_gate.evaluate_check_runs({"check_runs": [older_success, newer_failure]})
    check(v["passed"] is False, "stale success does not outrank a newer failure")
    v = spec_gate.evaluate_check_runs({"check_runs": [newer_failure, older_success]})
    check(v["passed"] is False, "...and order in the response does not change that")

    older_failure = run("veridict-spec-gate", "failure", "github-actions",
                        completed_at="2026-01-01T00:00:00Z")
    newer_success = run("veridict-spec-gate", "success", "github-actions",
                        completed_at="2026-06-01T00:00:00Z")
    v = spec_gate.evaluate_check_runs({"check_runs": [older_failure, newer_success]})
    check(v["passed"] is True, "a fixed-and-re-run gate passes on the newer success")

    print()
    print("=== against the live GitHub API (demo PR has no gate workflow) ===")
    verdict = asyncio.run(spec_gate.fetch_ci_verdict(
        "vayu-network", "anonymous-review-demo",
        "6937907935c526df76502e97c16a1451d40f6f3c", None,
    ))
    check(verdict["found"] is False and verdict["passed"] is False,
          f"live fetch reports no gate: {verdict['reason']}")

    # Network failure must never read as a pass.
    verdict = asyncio.run(spec_gate.fetch_ci_verdict(
        "nonexistent-owner-xyz", "nonexistent-repo-xyz", "0" * 40, None,
    ))
    check(verdict["passed"] is False, "unreachable/404 repo -> not a pass")

    print()
    if failures:
        print(f"  {len(failures)} FAILURES: {failures}")
        return 1
    print("  all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
