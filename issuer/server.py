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
  PROVER_BIN        — path to prover_cli (default ./prover/build/prover_cli)
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import re
import secrets
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

# Load .env from the project root and from issuer/ (issuer/ wins if both exist).
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), override=True)

import httpx
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Cookie, FastAPI, Form, HTTPException, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import db
from mdoc_builder import (
    Attribute,
    build_mdoc,
    issuer_public_key_hex,
    load_or_create_issuer_key,
)
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


PROVER_BIN = _resolve(os.environ.get("PROVER_BIN", "./prover/build/prover_cli"))
PSEUDONYM_KEY_PATH = _resolve(os.environ.get("PSEUDONYM_KEY_PATH", "./.secrets/pseudonym-key.bin"))


def _load_or_create_pseudonym_key(path: str) -> bytes:
    """32-byte HMAC key, persisted on disk so pseudonyms stay stable
    across restarts but cannot be derived by outsiders."""
    if os.path.exists(path):
        return open(path, "rb").read()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    key = secrets.token_bytes(32)
    with open(path, "wb") as fh:
        fh.write(key)
    os.chmod(path, 0o600)
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


@app.post("/approve", response_class=HTMLResponse)
async def approve(
    pr_slug: str = Form(...),
    reviewed: str = Form(None),
    comment: str = Form(""),
    session: str | None = Cookie(default=None),
) -> HTMLResponse:
    s = _session_or_redirect(session)
    if reviewed != "yes":
        return HTMLResponse(dashboard_page(
            s["login"], s["role"], s["org"],
            message="Load the PR and tick 'I've reviewed these changes' before approving.",
        ), 400)
    try:
        owner, repo, pr_num, sha = _parse_pr_input(pr_slug)
    except ValueError as e:
        return HTMLResponse(dashboard_page(
            s["login"], s["role"], s["org"],
            message=f"bad PR input: {e}",
        ), 400)

    # If no SHA in the slug, resolve from GitHub. In dev login there's no
    # access token, so a SHA must be provided directly.
    if sha is None:
        if s["access_token"] == "DEV_NO_TOKEN":
            return HTMLResponse(dashboard_page(
                s["login"], s["role"], s["org"],
                message="dev login: include a SHA, e.g. myorg/myrepo/42/abc123",
            ), 400)
        async with httpx.AsyncClient(timeout=10) as client:
            pr = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_num}",
                headers={"Authorization": f"Bearer {s['access_token']}",
                         "Accept": "application/vnd.github+json"},
            )
            if pr.status_code != 200:
                return HTMLResponse(dashboard_page(
                    s["login"], s["role"], s["org"],
                    message=f"GitHub returned {pr.status_code} for {pr_slug}",
                ), 400)
            sha = pr.json()["head"]["sha"]

    pr_key = f"{owner}/{repo}/{pr_num}/{sha}"
    user_id = s.get("user_id", s["login"])
    if db.is_issued(pr_key, user_id):
        return HTMLResponse(dashboard_page(
            s["login"], s["role"], s["org"],
            message="You have already approved this PR — one vote per reviewer per commit.",
        ), 400)

    # Re-check authorization at approve time (session org/role may be stale).
    auth = await _authorize_for_repo(s["access_token"], s["login"], owner, repo)
    if auth is None:
        return HTMLResponse(dashboard_page(
            s["login"], s["role"], s["org"] or REQUIRED_ORG,
            message=f"@{s['login']} is not authorized to approve PRs on {owner}/{repo}.",
        ), 403)
    _org, _gh_role, _access_type = auth
    s = {**s, "org": _org, "role": _gh_role, "access_type": _access_type}

    role = "maintainer" if s["role"] == "admin" else "reviewer"
    started = time.monotonic()

    # Fetch PR files and re-run spec check server-side (cannot trust client).
    token = s["access_token"]
    gh_headers = {"Authorization": f"Bearer {token}",
                  "Accept": "application/vnd.github+json"}
    if token == "DEV_NO_TOKEN":
        gh_headers.pop("Authorization")
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
        return HTMLResponse(dashboard_page(
            s["login"], s["role"], s["org"],
            message=(
                "Spec check failed — fix mypy and pytest errors before "
                f"requesting anonymous approval. "
                f"mypy: {'✓' if spec_check.get('mypy_ok') else '✗'}  "
                f"pytest: {'✓' if spec_check.get('pytest_ok') else '✗'}"
            ),
        ), 422)

    # 1. Mint MDOC bound to this pr_key
    device_key = ec.generate_private_key(ec.SECP256R1())
    mdoc_bytes, transcript = build_mdoc(
        [Attribute("role", role), Attribute("org", s["org"])],
        issuer_key, device_key, pr_key=pr_key,
    )

    # 2. Run prover server-side
    now = (datetime.now(timezone.utc) + timedelta(seconds=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    prover_start = time.monotonic()
    proof_path = await _generate_proof(mdoc_bytes, transcript, role, now)
    prover_ms = int((time.monotonic() - prover_start) * 1000)
    proof_size_bytes = os.path.getsize(proof_path)

    # 3. Submit to backend
    pseudonym = _pseudonym_for(s.get("user_id", s["login"]), pr_key)
    reputation = await _compute_reputation(s)
    if not spec_check.get("skipped"):
        parts = ["mypy ✓", "pytest ✓"] if spec_check.get("has_tests") else ["mypy ✓"]
        if spec_check.get("has_z3"):
            parts.append("z3 ✓")
        reputation["spec_check"] = " · ".join(parts)
    import json as _json
    async with httpx.AsyncClient(timeout=120) as client:
        with open(proof_path, "rb") as fh:
            r = await client.post(
                f"{BACKEND_URL}/pr/{pr_key}/proofs",
                files={"file": fh},
                data={
                    "now": now, "comment": comment, "pseudonym": pseudonym,
                    "reputation": _json.dumps(reputation),
                },
            )
        if r.status_code >= 400:
            return HTMLResponse(dashboard_page(
                s["login"], s["role"], s["org"],
                message=f"backend rejected proof: {r.status_code} {r.text}",
            ), 502)
        submit = r.json()
        db.mark_issued(pr_key, user_id)

        status = await client.get(f"{BACKEND_URL}/pr/{pr_key}/approvals")
        approvals = status.json()

    os.unlink(proof_path)
    took_ms = int((time.monotonic() - started) * 1000)
    pkx, _ = issuer_public_key_hex(issuer_key)
    return HTMLResponse(approve_result_page(
        login=s["login"],
        pr_key=pr_key,
        count=approvals["valid_proofs"],
        required=approvals["required"],
        passed=approvals["pass"],
        proof_hash=submit["proof_hash"],
        took_ms=took_ms,
        comment_url=submit.get("comment_url"),
        circuit_id=submit.get("circuit_id"),
        proof_size_bytes=proof_size_bytes,
        transcript_hex=transcript.hex(),
        prover_ms=prover_ms,
        issuer_pkx=pkx,
    ))


async def _generate_proof(
    mdoc_bytes: bytes, transcript: bytes, role: str, now: str,
) -> str:
    pkx, pky = issuer_public_key_hex(issuer_key)
    # CBOR-encode the role text manually (parser expects raw CBOR bytes).
    role_cbor_hex = _cbor_text_hex(role)
    claim = f"org.example.reviewer:role:{role_cbor_hex}"

    with tempfile.NamedTemporaryFile(suffix=".mdoc", delete=False) as mdoc_f:
        mdoc_f.write(mdoc_bytes)
        mdoc_path = mdoc_f.name
    proof_path = tempfile.NamedTemporaryFile(suffix=".proof", delete=False).name

    cmd = [
        PROVER_BIN,
        "--mdoc", mdoc_path,
        "--pkx", pkx, "--pky", pky,
        "--transcript", transcript.hex(),
        "--claim", claim,
        "--now", now,
        "--out", proof_path,
    ]
    # Run in a thread to keep the event loop unblocked during the ~10s compile.
    proc = await asyncio.get_event_loop().run_in_executor(
        None, lambda: subprocess.run(cmd, capture_output=True, timeout=180),
    )
    os.unlink(mdoc_path)
    if proc.returncode != 0:
        raise HTTPException(500, f"prover failed: {proc.stderr.decode()[:500]}")
    return proof_path


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
    device_key = ec.generate_private_key(ec.SECP256R1())
    mdoc_bytes, transcript = build_mdoc(
        [Attribute("role", role), Attribute("org", REQUIRED_ORG)],
        issuer_key, device_key, pr_key=pr_key,
    )
    return Response(
        content=mdoc_bytes,
        media_type="application/cbor",
        headers={"X-Transcript-Hex": transcript.hex()},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
