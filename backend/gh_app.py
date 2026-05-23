"""GitHub App authentication helper.

Mints an app JWT (signed with the private key), exchanges it for an
installation access token, caches the token until ~5 minutes before its
expiry. The installation token authorizes API calls as the bot user
(@{app-slug}[bot]) instead of any human account.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
import jwt


class GitHubApp:
    def __init__(self, app_id: str, private_key_path: str, installation_id: str):
        self.app_id = app_id
        self.installation_id = installation_id
        with open(private_key_path, "rb") as fh:
            self._private_key = fh.read()
        self._token: Optional[str] = None
        self._token_exp: float = 0.0

    def _mint_jwt(self) -> str:
        now = int(time.time())
        return jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": str(self.app_id)},
            self._private_key,
            algorithm="RS256",
        )

    async def installation_token(self) -> str:
        if self._token and time.time() < self._token_exp - 300:
            return self._token
        app_jwt = self._mint_jwt()
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"https://api.github.com/app/installations/{self.installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {app_jwt}",
                    "Accept": "application/vnd.github+json",
                },
            )
            r.raise_for_status()
            data = r.json()
        self._token = data["token"]
        # expires_at is ISO 8601; parse to seconds-since-epoch.
        self._token_exp = datetime.strptime(
            data["expires_at"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc).timestamp()
        return self._token


_singleton: Optional[GitHubApp] = None


def _resolve(path: str) -> str:
    """Resolve relative paths against the project root (parent of backend/)."""
    if not path or os.path.isabs(path):
        return path
    return os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), path)


def get_app() -> Optional[GitHubApp]:
    """Returns the singleton App if configured, else None."""
    global _singleton
    if _singleton is not None:
        return _singleton
    app_id = os.environ.get("GITHUB_APP_ID", "").strip()
    key_path = _resolve(os.environ.get("GITHUB_APP_PRIVATE_KEY_PATH", "").strip())
    inst_id = os.environ.get("GITHUB_APP_INSTALLATION_ID", "").strip()
    if not (app_id and key_path and inst_id and os.path.exists(key_path)):
        return None
    _singleton = GitHubApp(app_id, key_path, inst_id)
    return _singleton
