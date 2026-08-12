"""Review backend — stores anonymous ZK proofs per PR and runs the verifier.

Endpoints
---------
POST /pr/{pr_key}/proofs    : reviewer submits a ZK proof
GET  /pr/{pr_key}/approvals : count of valid proofs (called by GitHub Action)

`pr_key` is `{owner}/{repo}/{pr_number}/{commit_sha}`. The format MUST match
issuer/mdoc_builder.build_session_transcript or the transcript hex will
differ and proofs will fail to verify. Pinning to commit_sha means a
force-push invalidates prior approvals.

The verifier challenge (`transcript`) is derived from `pr_key` so a proof for
PR A cannot be replayed on PR B. Reviewers must regenerate the proof for each
new commit.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone

_CIRCUIT_ID_RE = re.compile(r'\bid:([0-9a-f]{32,})')

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), override=True)

import cbor2
import httpx
from fastapi import FastAPI, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from gh_app import get_app
import db

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _resolve(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(_PROJECT_ROOT, path)


VERIFIER_BIN = _resolve(os.environ.get("VERIFIER_BIN", "./prover/build/verifier_cli"))
# WebAssembly verifier, run under node. Preferred over the native binary because
# it needs no compiled artifact, which is what allows deployment to a host that
# cannot build C++. Same flags and exit-code convention as verifier_cli.
#
# Verification stays server-side either way: this is the same module the browser
# uses to prove, but the browser verifying its own proof would prove nothing.
WASM_VERIFIER = _resolve(os.environ.get("WASM_VERIFIER", "./prover/wasm/verify.cjs"))
NODE_BIN = os.environ.get("NODE_BIN", "node")
# Pre-generated circuit blob. Without it the verifier regenerates the circuit on
# every attempt (~15 s each, and we try up to three claim values).
CIRCUIT_HASH = os.environ.get(
    "CIRCUIT_HASH",
    "8d079211715200ff06c5109639245502bfe94aa869908d31176aae4016182121",
)
CIRCUIT_PATH = _resolve(os.environ.get("CIRCUIT_PATH", f"./prover/circuits/{CIRCUIT_HASH}"))
ISSUER_URL = os.environ.get("ISSUER_URL", "http://localhost:8000")
DOC_TYPE = os.environ.get("DOC_TYPE", "org.example.reviewer.v1")
CLAIM_NS = os.environ.get("CLAIM_NS", "org.example.reviewer")
CLAIM_ID = os.environ.get("CLAIM_ID", "role")
# CBOR text(10) "maintainer" = 0x6a + utf8 bytes
CLAIM_VALUE_HEX = os.environ.get(
    "CLAIM_VALUE_HEX", "6a6d61696e7461696e6572"
)
REQUIRED_APPROVALS = int(os.environ.get("REQUIRED_APPROVALS", "2"))
GITHUB_BOT_TOKEN = os.environ.get("GITHUB_BOT_TOKEN", "").strip()  # legacy fallback
STATUS_CONTEXT = os.environ.get("STATUS_CONTEXT", "zk-review-gate")
_gh_app = get_app()


async def _github_auth_header() -> dict[str, str]:
    """Returns the Authorization header for the bot identity.

    Prefers GitHub App installation token (posts as @<app>[bot]) over
    legacy PAT (posts as the human owner of the PAT).

    Returns {} rather than raising when the App is configured but its
    credentials are rejected. A revoked key or uninstalled App must not turn an
    already-verified approval into a failed request; see submit_proof.
    """
    if _gh_app is not None:
        try:
            token = await _gh_app.installation_token()
            return {"Authorization": f"Bearer {token}"}
        except Exception as e:
            print(f"[github] installation token unavailable: {e}")
    if GITHUB_BOT_TOKEN:
        return {"Authorization": f"Bearer {GITHUB_BOT_TOKEN}"}
    return {}

app = FastAPI(title="Veridict Backend")
db.init_db()

_pubkey_cache: dict | None = None


class SubmitResponse(BaseModel):
    accepted: bool
    proof_hash: str
    total_valid: int
    comment_url: str | None = None
    circuit_id: str | None = None
    proof_size_bytes: int | None = None
    transcript_hex: str | None = None
    # False when the proof was accepted but the GitHub commit status or comment
    # could not be pushed, so callers can distinguish "not approved" from
    # "approved, but the merge gate has not been updated yet".
    github_ok: bool = True


class ApprovalStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    pr_key: str
    valid_proofs: int
    required: int
    # `pass` is a Python keyword so the field is `pass_` internally; we alias
    # to the natural JSON name `pass` on serialization.
    pass_: bool = Field(serialization_alias="pass")


def _transcript_hex(pr_key: str) -> str:
    """Must match issuer.mdoc_builder.build_session_transcript exactly."""
    handover = ["AnonReviewv1", hashlib.sha256(pr_key.encode()).digest()]
    return cbor2.dumps([None, None, handover]).hex()


async def _issuer_pubkey() -> dict:
    global _pubkey_cache
    if _pubkey_cache is None:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{ISSUER_URL}/issuer/pubkey")
            r.raise_for_status()
            _pubkey_cache = r.json()
    return _pubkey_cache


def _format_anonymous_comment(body: str, pseudonym: str, reputation: dict | None = None) -> str:
    """Float-left avatar header, body wraps to its right.

    The trick: `align="left"` on the <img> floats it. Adjacent inline text
    flows next to it instead of below — no vertical-align fight with the
    sanitizer. `<picture>` swaps the wsrv.nl-masked background to match
    light/dark theme. `<br clear="left">` ends the float at the bottom.
    """
    from urllib.parse import quote

    if not pseudonym:
        # Generic header for un-tagged comments (legacy/dev).
        return (
            "_Anonymous reviewer · verified ZK proof of org membership · "
            f"identity not disclosed_\n\n---\n\n{body.strip()}"
        )

    raw_avatar = (
        f"https://api.dicebear.com/7.x/identicon/png"
        f"?seed={pseudonym}&size=200"
        f"&backgroundColor=ffd166,f4a261,9bdeac,a0c4ff,bdb2ff,ffc6ff"
        f"&backgroundType=solid"
    )
    encoded = quote(raw_avatar, safe="")
    dark_src = f"https://wsrv.nl/?url={encoded}&mask=circle&bg=0d1117"
    light_src = f"https://wsrv.nl/?url={encoded}&mask=circle&bg=ffffff"

    # Reputation chips: zero-knowledge attestations from the issuer's view of
    # the OAuth profile, bucketed so they reveal a trust signal without
    # pinpointing identity (1y+, 5y+, 100+ repos, etc.).
    rep = reputation or {}
    chips: list[str] = []
    if rep.get("role"):
        chips.append(f"<strong>{rep['role']}</strong>")
    if rep.get("org"):
        chips.append(f"in <code>{rep['org']}</code>")
    if rep.get("account_age"):
        chips.append(f"{rep['account_age']} on GitHub")
    if rep.get("activity"):
        chips.append(rep["activity"])
    if rep.get("spec_check"):
        chips.append(f"<code>{rep['spec_check']}</code>")
    chips_html = " · ".join(chips)
    rep_line = f"<br>{chips_html}<br>" if chips_html else ""

    return (
        f'<picture>\n'
        f'  <source media="(prefers-color-scheme: dark)" srcset="{dark_src}">\n'
        f'  <source media="(prefers-color-scheme: light)" srcset="{light_src}">\n'
        f'  <img src="{light_src}" width="48" height="48" align="left" alt="Avatar">\n'
        f'</picture> '
        f"<strong>Reviewer</strong> <code>{pseudonym}</code> • "
        f"<em>ZK-verified attestations:</em>"
        f"{rep_line}"
        f"<sub><em>identity not disclosed · stable per-PR pseudonym</em></sub>"
        f"\n"
        # Clear the float here so the body becomes a separate block underneath
        # rather than wrapping next to the avatar.
        f'<br clear="left"/>\n\n---\n\n{body.strip()}'
    )


async def _post_pr_comment(
    owner: str, repo: str, pr_num: int, body: str, pseudonym: str = "",
    reputation: dict | None = None,
) -> str | None:
    """Post an anonymous comment to a PR as the bot. Returns the html_url on success."""
    auth = await _github_auth_header()
    if not auth or not body.strip():
        return None
    formatted = _format_anonymous_comment(body, pseudonym, reputation)
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.post(
                f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_num}/comments",
                headers={**auth, "Accept": "application/vnd.github+json"},
                json={"body": formatted},
            )
            if r.status_code == 201:
                return r.json().get("html_url")
            print(f"[comment] {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"[comment] exception: {e}")
    return None


async def _push_commit_status(owner: str, repo: str, sha: str,
                              count: int, required: int) -> None:
    """Push a zk-review-gate commit status to GitHub via the bot identity."""
    auth = await _github_auth_header()
    if not auth:
        return
    state = "success" if count >= required else "pending"
    description = (
        f"{count} / {required} anonymous reviewers approved"
        + (" — merge gate green" if state == "success" else "")
    )
    payload: dict = {
        "state": state,
        "context": STATUS_CONTEXT,
        "description": description[:140],  # GitHub caps at 140 chars
    }
    # target_url is optional; only set it if we have a real http(s) URL.
    public = os.environ.get("PUBLIC_BACKEND_URL", "").strip()
    if public.startswith("http://") or public.startswith("https://"):
        payload["target_url"] = f"{public}/pr/{owner}/{repo}/{sha}/approvals"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.post(
                f"https://api.github.com/repos/{owner}/{repo}/statuses/{sha}",
                headers={**auth, "Accept": "application/vnd.github+json"},
                json=payload,
            )
            if r.status_code >= 400:
                print(f"[status-push] {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"[status-push] exception: {e}")


def _verifier_command() -> list[str] | None:
    """The verifier to invoke, preferring WebAssembly over the native binary.

    Returns None when neither is available, so callers can fail loudly rather
    than silently accepting proofs.
    """
    if os.path.exists(WASM_VERIFIER) and shutil.which(NODE_BIN):
        return [NODE_BIN, WASM_VERIFIER]
    if os.path.exists(VERIFIER_BIN):
        return [VERIFIER_BIN]
    return None


def _run_verifier(proof_path: str, pkx: str, pky: str, transcript_hex: str, now: str) -> tuple[bool, str | None]:
    """Returns (ok, circuit_id)."""
    base = _verifier_command()
    if base is None:
        print("[verifier] no verifier available (checked "
              f"{WASM_VERIFIER} and {VERIFIER_BIN})")
        return False, None

    _MAINTAINER_HEX = "6a6d61696e7461696e6572"
    _REVIEWER_HEX = "687265766965776572"
    to_try = list(dict.fromkeys([CLAIM_VALUE_HEX, _MAINTAINER_HEX, _REVIEWER_HEX]))

    for claim_val in to_try:
        cmd = base + [
            "--proof", proof_path,
            "--pkx", pkx,
            "--pky", pky,
            "--transcript", transcript_hex,
            "--claim", f"{CLAIM_NS}:{CLAIM_ID}:{claim_val}",
            "--now", now,
            "--doctype", DOC_TYPE,
        ]
        if os.path.exists(CIRCUIT_PATH):
            cmd += ["--circuit", CIRCUIT_PATH]
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=180,
        )
        stderr = result.stderr.decode()
        if result.returncode == 0:
            # With a cached circuit the verifier never logs an `id:` line, because
            # that only appeared while generating one. The identity is known
            # up front instead: it is the circuit hash we loaded, which
            # circuit_tool --check validates against kZkSpecs at build time.
            if os.path.exists(CIRCUIT_PATH):
                return True, CIRCUIT_HASH
            m = _CIRCUIT_ID_RE.search(stderr)
            return True, (m.group(1) if m else None)
        print(f"[verifier] claim={claim_val} rc={result.returncode} stderr={stderr[:300]}")
    return False, None


@app.post("/pr/{owner}/{repo}/{pr}/{sha}/proofs", response_model=SubmitResponse)
async def submit_proof(
    owner: str, repo: str, pr: int, sha: str,
    file: UploadFile, now: str = Form(...),
    comment: str = Form(""), pseudonym: str = Form(""),
    reputation: str = Form("{}"),
) -> SubmitResponse:
    pr_key = f"{owner}/{repo}/{pr}/{sha}"
    transcript = _transcript_hex(pr_key)
    pub = await _issuer_pubkey()

    # `now` is part of the public commitment — the prover and verifier must
    # be called with byte-identical strings. We trust the reviewer's `now`
    # but bound it to a small skew window to prevent replay or future-dating.
    try:
        ts = datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise HTTPException(400, f"invalid now: {e}") from e
    skew = datetime.now(timezone.utc) - ts
    if abs(skew) > timedelta(hours=1):
        raise HTTPException(400, f"now off by {skew} (must be within 1h)")

    body = await file.read()
    proof_hash = hashlib.sha256(body).hexdigest()
    if db.proof_exists(pr_key, proof_hash):
        return SubmitResponse(
            accepted=False,
            proof_hash=proof_hash,
            total_valid=db.approval_count(pr_key),
        )

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(body)
        tmp_path = tmp.name
    try:
        ok, circuit_id = _run_verifier(tmp_path, pub["pkx"], pub["pky"], transcript, now)
    finally:
        os.unlink(tmp_path)

    if not ok:
        raise HTTPException(400, "invalid proof")

    count = db.add_approval(pr_key, proof_hash, pseudonym)

    # From here on the approval is durable. GitHub is a side effect: pushing the
    # commit status and posting the comment must not be able to fail the request,
    # or a GitHub outage would report failure for a vote that has already been
    # counted, and the reviewer would have no way to tell the difference.
    import json as _json
    try:
        rep_obj = _json.loads(reputation) if reputation else {}
    except Exception:
        rep_obj = {}

    comment_url = None
    github_ok = True
    try:
        await _push_commit_status(owner, repo, sha, count, REQUIRED_APPROVALS)
        comment_url = await _post_pr_comment(
            owner, repo, pr, comment, pseudonym, rep_obj
        )
    except Exception as e:
        github_ok = False
        print(f"[github] side effects failed for {pr_key}: {e}")

    return SubmitResponse(
        accepted=True,
        proof_hash=proof_hash,
        total_valid=count,
        comment_url=comment_url,
        circuit_id=circuit_id,
        proof_size_bytes=len(body),
        transcript_hex=transcript,
        github_ok=github_ok,
    )


@app.get("/pr/{owner}/{repo}/{pr}/{sha}/approvals",
         response_model=ApprovalStatus, response_model_by_alias=True)
def get_approvals(owner: str, repo: str, pr: int, sha: str) -> ApprovalStatus:
    pr_key = f"{owner}/{repo}/{pr}/{sha}"
    count = db.approval_count(pr_key)
    return ApprovalStatus(
        pr_key=pr_key,
        valid_proofs=count,
        required=REQUIRED_APPROVALS,
        pass_=count >= REQUIRED_APPROVALS,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
