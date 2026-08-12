"""FastAPI credential issuer + reviewer UI.

Routes
------
GET  /                  → marketing / sign-in
GET  /login             → start GitHub OAuth
GET  /callback          → finish OAuth, set session cookie
GET  /review            → dashboard (needs session)
POST /approve           → end-to-end: resolve PR sha → mint MDOC →
                         run prover → POST to backend
GET  /logout            → clear session

Public/internal
GET  /issuer/pubkey     → JSON {pkx, pky} used by the backend's verifier
GET  /dev/credential    → DEV_MODE=1 bypass for tests

Required env vars (for real OAuth):
  GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET
  REQUIRED_ORG      — only members of this GitHub org get credentials
  BASE_URL          — e.g. http://localhost:8000 (must match GitHub app callback)
  BACKEND_URL       — e.g. http://localhost:8001
  WASM_DIR          — built browser prover (default ./prover/wasm/dist)
  CIRCUIT_PATH      — cached circuit blob served to the browser
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

# Load .env from the project root and from issuer/ (issuer/ wins if both exist).
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), override=True)

import httpx
from fastapi import Cookie, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
from mdoc_builder import (
    Attribute,
    build_mdoc,
    issuer_public_key_hex,
    load_or_create_issuer_key,
)
import spec_gate
from spec_checker import fetch_pr_files, run_spec_check
from synthesizer import create_github_pr, synthesize_code
from templates import (
    approve_result_page,
    dashboard_page,
    login_page,
    pr_review_page,
    synthesize_page,
)

CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
REQUIRED_ORG = os.environ.get("REQUIRED_ORG", "myorg")
# Fallback: also accept outside collaborators on this repo (owner/repo format).
REQUIRED_REPO = os.environ.get("REQUIRED_REPO", "")
ISSUER_KEY_PATH = os.environ.get("ISSUER_KEY_PATH", "issuer_key.pem")
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8001")
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _resolve(path: str) -> str:
    """Resolve a path relative to the project root when it's not absolute."""
    return path if os.path.isabs(path) else os.path.join(_PROJECT_ROOT, path)


# Circuit hash doubles as the asset filename, so the browser can cache it
# immutably. Proving happens client-side now; the issuer only serves the blob.
CIRCUIT_HASH = os.environ.get(
    "CIRCUIT_HASH",
    "8d079211715200ff06c5109639245502bfe94aa869908d31176aae4016182121",
)
CIRCUIT_PATH = _resolve(os.environ.get("CIRCUIT_PATH", f"./prover/circuits/{CIRCUIT_HASH}"))
WASM_DIR = _resolve(os.environ.get("WASM_DIR", "./prover/wasm/dist"))
PSEUDONYM_KEY_PATH = _resolve(os.environ.get("PSEUDONYM_KEY_PATH", "./.secrets/pseudonym-key.bin"))

# The claim proved about the credential. Must match the backend's expectation.
CLAIM_NS = os.environ.get("CLAIM_NS", "org.example.reviewer")
CLAIM_ID = os.environ.get("CLAIM_ID", "role")

# P-256 field prime, for range-checking device public keys the browser sends.
_P256_P = 2**256 - 2**224 + 2**192 + 2**96 - 1


class CredentialRequest(BaseModel):
    """Body of POST /approve/credential. The device public key is generated in
    the browser; the matching private key never leaves it."""

    pr_slug: str
    device_pk_x: str
    device_pk_y: str


def _load_or_create_pseudonym_key(path: str) -> bytes:
    """32-byte HMAC key for per-PR pseudonyms.

    PSEUDONYM_KEY_B64 wins over the file, because this key must be *stable*: it
    is what makes a reviewer's pseudonym consistent within a PR. A serverless
    instance that generated its own would hand the same reviewer a different
    pseudonym per request, which reads as several reviewers approving. So
    generation is a local-development convenience only, and a read-only
    filesystem is an error rather than a silent fresh key.
    """
    b64 = os.environ.get("PSEUDONYM_KEY_B64", "").strip()
    if b64:
        key = base64.b64decode(b64, validate=True)
        if len(key) != 32:
            raise RuntimeError(
                f"PSEUDONYM_KEY_B64 decodes to {len(key)} bytes, expected 32"
            )
        return key

    if os.path.exists(path):
        return open(path, "rb").read()

    key = secrets.token_bytes(32)
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(key)
        os.chmod(path, 0o600)
    except OSError as e:
        raise RuntimeError(
            f"No pseudonym key: PSEUDONYM_KEY_B64 is unset and {path} is not "
            f"writable ({e}). Set PSEUDONYM_KEY_B64 to 32 base64-encoded bytes. "
            "A per-instance key would make one reviewer look like many."
        ) from e
    return key


_PSEUDONYM_KEY = _load_or_create_pseudonym_key(PSEUDONYM_KEY_PATH)


def _pseudonym_for(user_id: int | str, pr_key: str) -> str:
    """HMAC-SHA256(secret, user_id:pr_key) → 6 hex chars.

    Stable per (reviewer, PR); unlinkable across PRs; unforgeable to anyone
    who doesn't hold the issuer's pseudonym key.
    """
    msg = f"{user_id}:{pr_key}".encode()
    return hmac.new(_PSEUDONYM_KEY, msg, hashlib.sha256).hexdigest()[:6]


def _bucket_years(years: float) -> str:
    """Privacy bucket so exact join date isn't disclosed."""
    if years < 1:
        return "<1y"
    if years < 2:
        return "1y+"
    if years < 5:
        return f"{int(years)}y+"
    if years < 10:
        return "5y+"
    return "10y+"


async def _compute_reputation(session: dict) -> dict:
    """Reputation signals from OAuth data — bucketed for privacy.

    Returns a dict of strings ready for display. Values are coarse on
    purpose: exact dates and counts would let an observer triangulate
    identity from the pseudonym.
    """
    role = "maintainer" if session["role"] == "admin" else "reviewer"
    rep = {"role": role, "org": session["org"]}

    token = session.get("access_token")
    if not token or token == "DEV_NO_TOKEN":
        return rep

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {token}",
                         "Accept": "application/vnd.github+json"},
            )
            if r.status_code == 200:
                u = r.json()
                from datetime import datetime, timezone
                created = datetime.fromisoformat(
                    u["created_at"].replace("Z", "+00:00")
                )
                years = (datetime.now(timezone.utc) - created).days / 365.25
                rep["account_age"] = _bucket_years(years)
                # public_repos is a coarse activity signal; bucket aggressively.
                pr_count = int(u.get("public_repos", 0))
                if pr_count >= 100:
                    rep["activity"] = "100+ public repos"
                elif pr_count >= 50:
                    rep["activity"] = "50+ public repos"
                elif pr_count >= 10:
                    rep["activity"] = "10+ public repos"
    except Exception:
        pass
    return rep

async def _authorize_for_repo(
    token: str, login: str, owner: str, repo: str,
) -> tuple[str, str, str] | None:
    """Return (org, role, access_type) if authorized, else None.

    access_type is "org" for org members, "collaborator" for outside contributors.
    Checks org membership first; falls back to push-level collaborator access.
    """
    if token == "DEV_NO_TOKEN":
        return REQUIRED_ORG or owner, "admin", "org"
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient(timeout=10) as client:
        if REQUIRED_ORG:
            m = await client.get(
                f"https://api.github.com/orgs/{REQUIRED_ORG}/memberships/{login}",
                headers=headers,
            )
            if m.status_code == 200:
                return REQUIRED_ORG, m.json().get("role", "member"), "org"
        # Fallback: any user with push access to the repo can review it.
        r = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}",
            headers=headers,
        )
        if r.status_code == 200 and r.json().get("permissions", {}).get("push"):
            return owner, "member", "collaborator"
    return None


app = FastAPI(title="Veridict Issuer")
issuer_key = load_or_create_issuer_key(ISSUER_KEY_PATH)
db.init_db()

# Serve bot-avatar.svg/png and any other shared assets under /static/...
# so we can reuse the GitHub App icon as the website logo + favicon.
_ASSETS_DIR = _resolve("assets")
if os.path.isdir(_ASSETS_DIR):
    app.mount("/static", StaticFiles(directory=_ASSETS_DIR), name="static")

# The compiled browser prover (veridict_prover.js + .wasm). Built by
# prover/wasm/build.sh; the emscripten glue resolves the .wasm relative to its
# own URL, so both must live under the same prefix.
if os.path.isdir(WASM_DIR):
    app.mount("/wasm", StaticFiles(directory=WASM_DIR), name="wasm")

# Browser-side proving scripts (device key handling + worker).
_BROWSER_JS_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_BROWSER_JS_DIR):
    app.mount("/js", StaticFiles(directory=_BROWSER_JS_DIR), name="js")


@app.get("/circuit/{circuit_hash}")
def circuit_asset(circuit_hash: str) -> Response:
    """Serves the ZK circuit blob, content-addressed by circuit hash.

    Immutable caching is safe precisely because the filename is the hash: a
    different circuit is a different URL. Saves re-downloading 316 KB per proof.
    """
    if circuit_hash != CIRCUIT_HASH or not os.path.exists(CIRCUIT_PATH):
        raise HTTPException(404, "unknown circuit")
    return FileResponse(
        CIRCUIT_PATH,
        media_type="application/octet-stream",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get("/favicon.svg")
def favicon_svg() -> Response:
    path = os.path.join(_ASSETS_DIR, "bot-avatar.svg")
    return FileResponse(path, media_type="image/svg+xml")


@app.get("/favicon.ico")
def favicon_ico() -> Response:
    # Browsers fall back to .ico when no .svg link is honoured. Serve the
    # PNG (browsers accept it under .ico content type in practice).
    path = os.path.join(_ASSETS_DIR, "bot-avatar.png")
    return FileResponse(path, media_type="image/png")


# ----- public endpoints used by the backend ----------------------------


@app.get("/issuer/pubkey")
def issuer_pubkey() -> dict:
    pkx, pky = issuer_public_key_hex(issuer_key)
    return {"pkx": pkx, "pky": pky}


# ----- OAuth flow ------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def root(session: str | None = Cookie(default=None)) -> HTMLResponse:
    if session and db.get_session(session):
        return RedirectResponse("/review")
    return HTMLResponse(login_page())


@app.get("/login")
def login() -> RedirectResponse:
    if not CLIENT_ID:
        # If OAuth isn't configured, fall through to /dev/login (DEV_MODE=1)
        # or surface a clear error.
        if os.environ.get("DEV_MODE") == "1":
            return RedirectResponse("/dev/login")
        raise HTTPException(500, "GITHUB_CLIENT_ID not configured")
    state = secrets.token_urlsafe(16)
    db.add_oauth_state(state, time.time())
    url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={BASE_URL}/callback"
        "&scope=read:org"
        f"&state={state}"
    )
    return RedirectResponse(url)


@app.get("/dev/login")
def dev_login(login: str = "demo-reviewer", role: str = "admin") -> Response:
    """Bypass GitHub OAuth for UI demos. Only enabled when DEV_MODE=1."""
    if os.environ.get("DEV_MODE") != "1":
        raise HTTPException(404)
    sid = secrets.token_urlsafe(24)
    db.set_session(sid, {
        "login": login,
        "user_id": f"dev:{login}",
        "role": role,
        "org": REQUIRED_ORG or "demo-org",
        "access_token": "DEV_NO_TOKEN",
        "ts": time.time(),
    }, time.time())
    resp = RedirectResponse("/review")
    resp.set_cookie("session", sid, httponly=True, samesite="lax", max_age=3600)
    return resp


@app.get("/callback", response_class=HTMLResponse)
async def callback(code: str, state: str) -> Response:
    if not db.pop_oauth_state(state):
        return HTMLResponse(login_page(error="invalid oauth state"), status_code=400)

    async with httpx.AsyncClient(timeout=10) as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": code,
            },
        )
        access_token = token_resp.json().get("access_token")
        if not access_token:
            return HTMLResponse(login_page(error="token exchange failed"), 400)

        headers = {"Authorization": f"Bearer {access_token}",
                   "Accept": "application/vnd.github+json"}
        user = (await client.get("https://api.github.com/user", headers=headers)).json()

    # Defer org/repo authorization to review time when we know the target repo.
    sid = secrets.token_urlsafe(24)
    db.set_session(sid, {
        "login": user["login"],
        "user_id": user["id"],
        "role": "member",
        "org": "",
        "access_token": access_token,
        "ts": time.time(),
    }, time.time())
    resp = RedirectResponse("/review")
    resp.set_cookie("session", sid, httponly=True, samesite="lax", max_age=3600)
    return resp


@app.get("/logout")
async def logout(session: str | None = Cookie(default=None)) -> RedirectResponse:
    """Revoke the GitHub OAuth grant so next sign-in re-prompts for permission."""
    token = None
    if session:
        _s = db.get_session(session)
        if _s:
            token = _s.get("access_token")
            db.delete_session(session)
        if token and token != "DEV_NO_TOKEN" and CLIENT_ID and CLIENT_SECRET:
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    await client.request(
                        "DELETE",
                        f"https://api.github.com/applications/{CLIENT_ID}/grant",
                        auth=(CLIENT_ID, CLIENT_SECRET),
                        json={"access_token": token},
                        headers={"Accept": "application/vnd.github+json"},
                    )
            except Exception:
                pass  # best-effort revoke; user is logged out locally either way
    resp = RedirectResponse("/")
    resp.delete_cookie("session")
    return resp


# ----- reviewer UI -----------------------------------------------------


def _session_or_redirect(session: str | None) -> dict:
    s = db.get_session(session) if session else None
    if not s:
        raise HTTPException(303, headers={"Location": "/"})
    return s


@app.get("/review", response_class=HTMLResponse)
def review_dashboard(session: str | None = Cookie(default=None)) -> HTMLResponse:
    s = _session_or_redirect(session)
    return HTMLResponse(dashboard_page(
        s["login"], s["role"], s["org"] or REQUIRED_ORG or "—",
        access_type=s.get("access_type", "org"),
    ))


@app.get("/review/load", response_class=HTMLResponse)
async def review_load(pr: str, session: str | None = Cookie(default=None)) -> HTMLResponse:
    """Fetch PR metadata + diff from GitHub, render a review page."""
    s = _session_or_redirect(session)
    try:
        owner, repo, pr_num, sha = _parse_pr_input(pr)
    except ValueError as e:
        return HTMLResponse(dashboard_page(
            s["login"], s["role"], s["org"], message=f"bad PR input: {e}",
        ), 400)

    token = s["access_token"]

    # Authorize: org member OR repo collaborator with push access.
    auth = await _authorize_for_repo(token, s["login"], owner, repo)
    if auth is None:
        return HTMLResponse(dashboard_page(
            s["login"], s["role"], s["org"] or REQUIRED_ORG,
            message=f"@{s['login']} is not a member of {REQUIRED_ORG} and does not have collaborator access to {owner}/{repo}.",
        ), 403)
    org, role, access_type = auth
    db.set_session(session, {**s, "org": org, "role": role, "access_type": access_type}, time.time())
    s = {**s, "org": org, "role": role, "access_type": access_type}

    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json"}
    if token == "DEV_NO_TOKEN":
        headers.pop("Authorization")

    async with httpx.AsyncClient(timeout=15) as client:
        pr_resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_num}",
            headers=headers,
        )
        if pr_resp.status_code != 200:
            return HTMLResponse(dashboard_page(
                s["login"], s["role"], s["org"],
                message=f"GitHub {pr_resp.status_code} on {owner}/{repo}#{pr_num}",
            ), 400)
        pr_data = pr_resp.json()
        sha = sha or pr_data["head"]["sha"]

        files_resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_num}/files",
            headers=headers,
            params={"per_page": 100},
        )
        files = files_resp.json() if files_resp.status_code == 200 else []

    # Fetch full content + run spec check asynchronously (non-blocking for
    # non-Python PRs — run_spec_check itself is CPU-bound but fast).
    py_contents = await fetch_pr_files(owner, repo, sha, files, token)
    loop = asyncio.get_event_loop()
    spec_check = await loop.run_in_executor(None, run_spec_check, py_contents)

    return HTMLResponse(pr_review_page(
        user_login=s["login"],
        owner=owner, repo=repo, pr_num=pr_num, sha=sha,
        pr=pr_data, files=files,
        spec_check=spec_check,
    ))


async def _evaluate_spec_gate(
    owner: str, repo: str, pr_num: int, sha: str,
    token: str, gh_headers: dict,
) -> tuple[dict, str | None]:
    """Resolves the formal spec gate for a commit.

    Returns (spec_check, error_message). A non-None error means issuance is
    refused. See issuer/spec_gate.py for why the CI-sourced verdict is preferred:
    running mypy and pytest on PR contents inside the issuer executes
    attacker-influenced code in the process holding the signing key.
    """
    if spec_gate.MODE in ("ci-required", "ci-preferred"):
        verdict = await spec_gate.fetch_ci_verdict(owner, repo, sha, token)
        if verdict["passed"]:
            return (
                {"passed": True, "skipped": False, "source": "ci",
                 "details_url": verdict.get("details_url")},
                None,
            )
        if verdict["found"] or spec_gate.MODE == "ci-required":
            # A found-but-failing gate is a hard no. In ci-required, so is a
            # missing one: absence of evidence must not read as a pass.
            return {}, (
                f"CI spec gate did not pass: {verdict['reason']}. "
                "Fix the checks and push again before requesting approval."
            )
        print(f"[spec-gate] falling back to in-process checks: {verdict['reason']}")

    # Fallback / local mode: fetch the PR's Python files and check them here.
    async with httpx.AsyncClient(timeout=15) as client:
        files_resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_num}/files",
            headers=gh_headers, params={"per_page": 100},
        )
        files = files_resp.json() if files_resp.status_code == 200 else []
    py_contents = await fetch_pr_files(owner, repo, sha, files, token)
    loop = asyncio.get_event_loop()
    spec_check = await loop.run_in_executor(None, run_spec_check, py_contents)

    if not spec_check.get("passed") and not spec_check.get("skipped"):
        return {}, (
            "Spec check failed — fix mypy and pytest errors before "
            "requesting anonymous approval. "
            f"mypy: {'✓' if spec_check.get('mypy_ok') else '✗'}  "
            f"pytest: {'✓' if spec_check.get('pytest_ok') else '✗'}"
        )
    return spec_check, None


@app.post("/approve/credential")
async def approve_credential(
    body: CredentialRequest,
    session: str | None = Cookie(default=None),
) -> JSONResponse:
    """Issues an MDOC bound to a device key the browser holds.

    This replaced the old server-side proving path entirely. The issuer still
    gates on org membership and the spec check, but proving now happens in the
    reviewer's browser, so the issuer never holds the device private key and
    cannot fabricate an approval.
    """
    s = db.get_session(session) if session else None
    if s is None:
        return JSONResponse({"error": "not signed in"}, 401)

    def err(msg: str, code: int) -> JSONResponse:
        return JSONResponse({"error": msg}, code)

    try:
        device_pub_x = int(body.device_pk_x, 16)
        device_pub_y = int(body.device_pk_y, 16)
    except ValueError:
        return err("device_pk_x / device_pk_y must be hex", 400)
    if not (0 < device_pub_x < _P256_P and 0 < device_pub_y < _P256_P):
        return err("device public key coordinates out of range", 400)

    try:
        owner, repo, pr_num, sha = _parse_pr_input(body.pr_slug)
    except ValueError as e:
        return err(f"bad PR input: {e}", 400)

    # If no SHA in the slug, resolve from GitHub. In dev login there's no
    # access token, so a SHA must be provided directly.
    if sha is None:
        if s["access_token"] == "DEV_NO_TOKEN":
            return err("dev login: include a SHA, e.g. myorg/myrepo/42/abc123", 400)
        async with httpx.AsyncClient(timeout=10) as client:
            pr = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_num}",
                headers={"Authorization": f"Bearer {s['access_token']}",
                         "Accept": "application/vnd.github+json"},
            )
            if pr.status_code != 200:
                return err(f"GitHub returned {pr.status_code} for {body.pr_slug}", 400)
            sha = pr.json()["head"]["sha"]

    pr_key = f"{owner}/{repo}/{pr_num}/{sha}"
    user_id = s.get("user_id", s["login"])
    if db.is_issued(pr_key, user_id):
        return err(
            "You have already approved this PR — one vote per reviewer per commit.",
            409,
        )

    # Re-check authorization at approve time (session org/role may be stale).
    auth = await _authorize_for_repo(s["access_token"], s["login"], owner, repo)
    if auth is None:
        return err(
            f"@{s['login']} is not authorized to approve PRs on {owner}/{repo}.", 403
        )
    _org, _gh_role, _access_type = auth
    s = {**s, "org": _org, "role": _gh_role, "access_type": _access_type}

    role = "maintainer" if s["role"] == "admin" else "reviewer"

    # Fetch PR files and re-run spec check server-side (cannot trust client).
    token = s["access_token"]
    gh_headers = {"Authorization": f"Bearer {token}",
                  "Accept": "application/vnd.github+json"}
    if token == "DEV_NO_TOKEN":
        gh_headers.pop("Authorization")

    spec_check, gate_err = await _evaluate_spec_gate(
        owner, repo, pr_num, sha, token, gh_headers
    )
    if gate_err is not None:
        return err(gate_err, 422)

    # Mint an MDOC around the device public key the browser generated. The issuer
    # never sees the matching private key, so it cannot forge an approval on this
    # reviewer's behalf. The document comes back with a placeholder device
    # signature that only the holder can fill in.
    unsigned = build_mdoc(
        [Attribute("role", role), Attribute("org", s["org"])],
        issuer_key,
        device_pub_x=device_pub_x,
        device_pub_y=device_pub_y,
        pr_key=pr_key,
    )

    now = (datetime.now(timezone.utc) + timedelta(seconds=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    pseudonym = _pseudonym_for(user_id, pr_key)
    reputation = await _compute_reputation(s)
    if spec_check.get("source") == "ci":
        # The verdict came from the repository's own CI, so name that rather than
        # implying the issuer ran the tools itself.
        reputation["spec_check"] = f"{spec_gate.CHECK_NAME} ✓ (CI)"
    elif not spec_check.get("skipped"):
        parts = ["mypy ✓", "pytest ✓"] if spec_check.get("has_tests") else ["mypy ✓"]
        if spec_check.get("has_z3"):
            parts.append("z3 ✓")
        reputation["spec_check"] = " · ".join(parts)

    # Everything the backend must be able to trust stays here. The browser gets
    # only what it needs to prove, and posts the proof back with this token.
    token = secrets.token_urlsafe(24)
    db.put_ephemeral(f"pending:{token}", {
        "pr_key": pr_key,
        "user_id": str(user_id),
        "login": s["login"],
        "now": now,
        "pseudonym": pseudonym,
        "reputation": reputation,
        "transcript_hex": unsigned.transcript.hex(),
        "started": time.time(),
    }, time.time())

    pkx, pky = issuer_public_key_hex(issuer_key)
    return JSONResponse({
        "token": token,
        "mdoc_b64": base64.b64encode(unsigned.mdoc).decode(),
        "device_tbs_b64": base64.b64encode(unsigned.device_tbs).decode(),
        "sig_offset": unsigned.sig_offset,
        "transcript_hex": unsigned.transcript.hex(),
        "now": now,
        "issuer_pkx": pkx,
        "issuer_pky": pky,
        "claim_ns": CLAIM_NS,
        "claim_id": CLAIM_ID,
        "claim_cbor_hex": _cbor_text_hex(role),
        "circuit_url": f"/circuit/{CIRCUIT_HASH}",
        "pr_key": pr_key,
    })


@app.post("/approve/submit")
async def approve_submit(
    token: str = Form(...),
    comment: str = Form(""),
    prover_ms: int = Form(0),
    file: UploadFile = File(...),
    session: str | None = Cookie(default=None),
) -> JSONResponse:
    """Accepts a browser-generated proof and forwards it to the backend.

    The proof travels through the issuer rather than straight to the backend so
    the pseudonym and reputation chips stay server-computed. A browser posting
    directly could otherwise claim any pseudonym it liked.
    """
    s = db.get_session(session) if session else None
    if s is None:
        return JSONResponse({"error": "not signed in"}, 401)

    pending = db.pop_ephemeral(f"pending:{token}")
    if pending is None:
        return JSONResponse({"error": "unknown or already-used token"}, 400)
    if pending["user_id"] != str(s.get("user_id", s["login"])):
        return JSONResponse({"error": "token does not belong to this session"}, 403)

    pr_key = pending["pr_key"]
    proof_bytes = await file.read()
    if not proof_bytes:
        return JSONResponse({"error": "empty proof"}, 400)

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{BACKEND_URL}/pr/{pr_key}/proofs",
            files={"file": ("proof.bin", proof_bytes)},
            data={
                "now": pending["now"],
                "comment": comment,
                "pseudonym": pending["pseudonym"],
                "reputation": json.dumps(pending["reputation"]),
            },
        )
        if r.status_code >= 400:
            return JSONResponse(
                {"error": f"backend rejected proof: {r.status_code} {r.text[:300]}"},
                502,
            )
        submit = r.json()
        db.mark_issued(pr_key, pending["user_id"])

        status = await client.get(f"{BACKEND_URL}/pr/{pr_key}/approvals")
        approvals = status.json()

    pkx, _ = issuer_public_key_hex(issuer_key)
    result_token = secrets.token_urlsafe(24)
    db.put_ephemeral(f"result:{result_token}", {
        "login": pending["login"],
        "pr_key": pr_key,
        "count": approvals["valid_proofs"],
        "required": approvals["required"],
        "passed": approvals["pass"],
        "proof_hash": submit["proof_hash"],
        "took_ms": int((time.time() - pending["started"]) * 1000),
        "comment_url": submit.get("comment_url"),
        "circuit_id": submit.get("circuit_id"),
        "proof_size_bytes": len(proof_bytes),
        "transcript_hex": pending["transcript_hex"],
        "prover_ms": prover_ms,
        "issuer_pkx": pkx,
    }, time.time())

    return JSONResponse({"ok": True, "redirect": f"/approve/result/{result_token}"})


@app.get("/approve/result/{result_token}", response_class=HTMLResponse)
def approve_result(result_token: str) -> HTMLResponse:
    r = db.get_ephemeral(f"result:{result_token}")
    if r is None:
        return HTMLResponse(
            dashboard_page("", "", "", message="That result link has expired."), 404
        )
    return HTMLResponse(approve_result_page(**r))


_PR_URL_RE = re.compile(
    r"^(?:(?:https?://)?github\.com/)?"  # optional URL prefix (scheme optional)
    r"([^/\s]+)/([^/\s]+)"              # owner/repo
    r"(?:/(?:pull|pulls))?/"            # optional /pull or /pulls
    r"(\d+)"                            # PR number
    r"(?:/([0-9a-f]{7,40}))?"           # optional SHA (4-part form)
    r"(?:/.*)?$",                       # ignore /files, /commits, etc
    re.IGNORECASE,
)


def _parse_pr_input(raw: str) -> tuple[str, str, int, str | None]:
    """Accepts any of:
      https://github.com/owner/repo/pull/42
      https://github.com/owner/repo/pull/42/files
      owner/repo/42
      owner/repo/42/<sha>
    Returns (owner, repo, pr_num, sha_or_None).
    """
    m = _PR_URL_RE.match(raw.strip().rstrip("/"))
    if not m:
        raise ValueError(
            "expected a PR URL or owner/repo/N (optionally /SHA)"
        )
    owner, repo, num, sha = m.groups()
    return owner, repo, int(num), sha


_REPO_URL_RE = re.compile(
    r"^(?:(?:https?://)?github\.com/)?"
    r"([^/\s]+)/([^/\s]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)


def _parse_repo_input(raw: str) -> tuple[str, str] | None:
    """Accept 'owner/repo' or any GitHub repo URL. Returns (owner, repo) or None."""
    m = _REPO_URL_RE.match(raw.strip())
    if not m:
        return None
    return m.group(1), m.group(2)


def _cbor_text_hex(s: str) -> str:
    """Minimal CBOR text-string encoding (text(<24) only — fine for role names)."""
    b = s.encode("utf-8")
    if len(b) >= 24:
        raise ValueError("role string too long for the simple CBOR encoder")
    return bytes([0x60 | len(b)]).hex() + b.hex()


# ----- AI synthesis ----------------------------------------------------


@app.get("/synthesize", response_class=HTMLResponse)
def synthesize_get(session: str | None = Cookie(default=None)) -> HTMLResponse:
    s = _session_or_redirect(session)
    return HTMLResponse(synthesize_page(s["login"]))


@app.post("/synthesize", response_class=HTMLResponse)
async def synthesize_post(
    spec: str = Form(...),
    repo: str = Form(...),
    session: str | None = Cookie(default=None),
) -> Response:
    s = _session_or_redirect(session)

    if not spec.strip():
        return HTMLResponse(synthesize_page(s["login"], error="Spec cannot be empty."))

    repo = _parse_repo_input(repo)
    if repo is None:
        return HTMLResponse(synthesize_page(
            s["login"],
            error="Could not parse repo — use 'owner/repo' or a GitHub URL.",
        ))
    owner_r, repo_r = repo

    try:
        files = await synthesize_code(spec)
    except RuntimeError as e:
        return HTMLResponse(synthesize_page(s["login"], error=str(e)), 500)
    if not files:
        return HTMLResponse(synthesize_page(
            s["login"],
            error="Claude returned no files. Try a more specific spec.",
        ), 500)

    spec_summary = spec.strip().splitlines()[0][:120]
    try:
        pr_num, _pr_url = await create_github_pr(owner_r, repo_r, files, spec_summary)
    except Exception as e:
        return HTMLResponse(synthesize_page(
            s["login"],
            error=f"Failed to create GitHub PR: {e}",
        ), 502)

    # Hand off to the review flow so the reviewer can inspect + approve the
    # AI-generated code immediately.
    return RedirectResponse(
        f"/review/load?pr={owner_r}/{repo_r}/{pr_num}",
        status_code=303,
    )


# ----- dev bypass ------------------------------------------------------


@app.get("/dev/credential")
def dev_credential(
    role: str = "maintainer",
    pr_key: str = "myorg/myrepo/42/abc123",
) -> Response:
    if os.environ.get("DEV_MODE") != "1":
        raise HTTPException(404)

    # Test fixture for scripts/demo.sh, which needs a complete provable MDOC from
    # a single HTTP call. This is the one place the issuer still generates a
    # device key, and it is a throwaway: DEV_MODE only, never reachable from the
    # approval path, where the key is always the browser's. Imported locally so
    # the dependency does not read as part of the production flow.
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    from mdoc_builder import splice_device_signature

    device_key = ec.generate_private_key(ec.SECP256R1())
    pub = device_key.public_key().public_numbers()
    unsigned = build_mdoc(
        [Attribute("role", role), Attribute("org", REQUIRED_ORG)],
        issuer_key, device_pub_x=pub.x, device_pub_y=pub.y, pr_key=pr_key,
    )
    der = device_key.sign(unsigned.device_tbs, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    mdoc_bytes = splice_device_signature(
        unsigned, r.to_bytes(32, "big") + s.to_bytes(32, "big")
    )
    return Response(
        content=mdoc_bytes,
        media_type="application/cbor",
        headers={"X-Transcript-Hex": unsigned.transcript.hex()},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
