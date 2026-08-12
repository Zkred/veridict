"""AI code synthesis via Claude API + GitHub PR creation via GitHub App."""
from __future__ import annotations

import base64
import os
import re
import time

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

_SYSTEM = """\
You are a secure software engineer specialising in formally verified code.
Given a specification, generate three Python files.

Output ONLY files in this exact format (no prose before or after):
--- filename: path/to/file.py ---
<file contents>
--- end ---

Generate exactly these three files:

1. Implementation file (e.g. rate_limiter.py)
   - Full type annotations
   - Minimal, correct, readable

2. Test file (test_*.py)
   - pytest tests that directly verify each requirement in the spec
   - CRITICAL: every test must only call the implementation with VALID inputs
     that satisfy the implementation's own preconditions (e.g. if rate must be
     positive, never call with rate=0). Test invalid inputs only in tests
     explicitly named test_*invalid* or test_*raises*, using pytest.raises.
   - All assertions on numeric results must match the implementation exactly —
     do NOT assume float == int without a tolerance (use pytest.approx)

3. Z3 formal properties file (z3_*.py)
   - MUST start with exactly: from z3 import *
   - This is mandatory — Z3 symbols (Solver, And, Not, unsat, Int, Real,
     Bool, ForAll, Implies, ToReal, ArithRef, etc.) are only available
     via that wildcard import. Never qualify them as z3.Solver etc.
   - Defines the core data model symbolically using Z3 sorts and functions
   - States each key invariant from the spec as a Z3 proposition
   - Proves each invariant by asserting the NEGATION is UNSAT:
       s = Solver()
       s.add(<negation of invariant>)
       assert s.check() == unsat, "Invariant N violated: <description>"
   - Ends with: print("All Z3 properties verified.")
   - On failure: the AssertionError propagates (exit non-zero)
   - Keep it self-contained — do NOT import the implementation
   - The Z3 file proves the SPECIFICATION is logically consistent and
     the invariants hold for all possible inputs symbolically"""


async def synthesize_code(spec: str) -> dict[str, str]:
    """Call Claude API with spec; return {filename: content} dict."""
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed — run: pip install anthropic")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured in .env")

    client = anthropic.AsyncAnthropic(api_key=api_key)
    msg = await client.messages.create(
        model=ANTHROPIC_MODEL,
        # max_tokens bounds thinking *and* response text together, and thinking is
        # on by default on current models. 4096 truncated multi-file synthesis
        # mid-file; 16000 is the documented default for non-streaming requests.
        max_tokens=16000,
        system=_SYSTEM,
        messages=[{"role": "user", "content": f"Specification:\n\n{spec.strip()}"}],
    )

    # Safety classifiers can decline a request: HTTP 200 with stop_reason
    # "refusal" and no usable content. Check before reading blocks.
    if msg.stop_reason == "refusal":
        raise RuntimeError(
            "Claude declined to synthesise this specification. Rephrase the spec "
            "and try again."
        )
    if msg.stop_reason == "max_tokens":
        raise RuntimeError(
            "Synthesis output was truncated at max_tokens. Narrow the "
            "specification or raise max_tokens."
        )

    # Do not index content[0]: with thinking enabled the first block is a
    # thinking block, not text. Take the text blocks.
    text = "".join(b.text for b in msg.content if b.type == "text")
    if not text:
        raise RuntimeError(f"no text content in response (stop_reason={msg.stop_reason})")
    return _parse_files(text)


def _parse_files(text: str) -> dict[str, str]:
    files: dict[str, str] = {}
    for m in re.finditer(
        r"---\s*filename:\s*(.+?)\s*---\n(.*?)---\s*end\s*---", text, re.DOTALL
    ):
        files[m.group(1).strip()] = m.group(2)
    return files


async def _get_app_token() -> str:
    """Mint a GitHub App installation token from env vars."""
    import jwt  # pyjwt[crypto]
    import httpx

    app_id = os.environ.get("GITHUB_APP_ID", "")
    inst_id = os.environ.get("GITHUB_APP_INSTALLATION_ID", "")

    # GITHUB_APP_PRIVATE_KEY_B64 first: a serverless deployment has nowhere to put
    # a .pem, so the key travels as an environment variable. The path is the
    # local-development fallback.
    key_b64 = os.environ.get("GITHUB_APP_PRIVATE_KEY_B64", "").strip()
    private_key: str | None = None
    if key_b64:
        private_key = base64.b64decode(key_b64, validate=True).decode()
    else:
        key_path = os.environ.get("GITHUB_APP_PRIVATE_KEY_PATH", "")
        if key_path:
            # Relative paths in .env are relative to the project root.
            if not os.path.isabs(key_path):
                key_path = os.path.join(os.path.dirname(__file__), "..", key_path)
            if os.path.exists(key_path):
                private_key = open(key_path).read()

    if not (app_id and inst_id and private_key):
        raise RuntimeError(
            "GitHub App not configured — set GITHUB_APP_ID, "
            "GITHUB_APP_INSTALLATION_ID, and either "
            "GITHUB_APP_PRIVATE_KEY_B64 or GITHUB_APP_PRIVATE_KEY_PATH"
        )
    now = int(time.time())
    jwt_token = jwt.encode(
        {"iat": now - 60, "exp": now + 600, "iss": str(app_id)},
        private_key, algorithm="RS256",
    )
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"https://api.github.com/app/installations/{inst_id}/access_tokens",
            headers={"Authorization": f"Bearer {jwt_token}",
                     "Accept": "application/vnd.github+json"},
        )
        r.raise_for_status()
        return r.json()["token"]


async def create_github_pr(
    owner: str, repo: str, files: dict[str, str], spec_summary: str,
) -> tuple[int, str]:
    """Create branch + files + PR via GitHub App. Returns (pr_number, pr_url).

    Requires the GitHub App to have contents:write + pull_requests:write
    permissions on the target repo.
    """
    import httpx

    token = await _get_app_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    branch = f"ai-synthesis/{int(time.time())}"

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}", headers=headers
        )
        r.raise_for_status()
        default_branch = r.json()["default_branch"]

        r = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{default_branch}",
            headers=headers,
        )
        r.raise_for_status()
        base_sha = r.json()["object"]["sha"]

        r = await client.post(
            f"https://api.github.com/repos/{owner}/{repo}/git/refs",
            headers=headers,
            json={"ref": f"refs/heads/{branch}", "sha": base_sha},
        )
        r.raise_for_status()

        for path, content in files.items():
            r = await client.put(
                f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
                headers=headers,
                json={
                    "message": f"ai-synthesis: add {path}",
                    "content": base64.b64encode(content.encode()).decode(),
                    "branch": branch,
                },
            )
            if r.status_code not in (200, 201):
                raise RuntimeError(
                    f"GitHub {r.status_code} creating {path}: {r.text[:200]}"
                )

        pr_body = (
            "## AI-Synthesized Code\n\n"
            f"Generated from specification:\n\n> {spec_summary[:400]}\n\n"
            "### Verification chain\n\n"
            "1. **Spec check** — mypy + pytest run automatically during review\n"
            "2. **ZK proof** — only org-credentialed reviewers can approve; identity not disclosed\n"
            "3. **Merge gate** — branch protection requires N anonymous approvals\n\n"
            "*This PR was synthesized by an AI and must pass formal spec checks before merge.*"
        )
        r = await client.post(
            f"https://api.github.com/repos/{owner}/{repo}/pulls",
            headers=headers,
            json={
                "title": f"[AI Synthesis] {spec_summary[:60]}",
                "body": pr_body,
                "head": branch,
                "base": default_branch,
            },
        )
        r.raise_for_status()
        data = r.json()
        return data["number"], data["html_url"]
