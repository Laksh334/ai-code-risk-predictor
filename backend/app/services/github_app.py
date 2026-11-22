"""C2 - Talking to GitHub as a GitHub App: webhook signatures, auth tokens, PR comments.

Auth flow for a GitHub App:
  1. sign a short-lived JWT with the App's private key (RS256)       -> proves "I am the App"
  2. exchange it for an installation token for one repo's installation -> valid ~1 hour
  3. use that token to comment on the PR
For local testing a personal access token (GITHUB_TOKEN) can be used instead.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from pathlib import Path

import httpx
import jwt

from app.config import settings

API_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def verify_signature(body: bytes, signature_header: str | None, secret: str) -> bool:
    """GitHub sends X-Hub-Signature-256: sha256=HMAC(secret, raw body).
    compare_digest avoids leaking the signature through timing differences."""
    if not secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.removeprefix("sha256="))


class GitHubNotConfigured(Exception):
    pass


class GitHubClient:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        # `transport` lets tests replace GitHub with a fake server.
        self._http = httpx.Client(base_url=settings.github_api_url, headers=API_HEADERS,
                                  timeout=20, transport=transport)
        self._tokens: dict[int, tuple[str, float]] = {}  # installation id -> (token, expiry)

    @property
    def configured(self) -> bool:
        return bool(settings.github_token or (settings.github_app_id and self._private_key()))

    @staticmethod
    def _private_key() -> str:
        if settings.github_private_key_path:
            return Path(settings.github_private_key_path).read_text()
        return settings.github_private_key.replace("\\n", "\n")

    def app_jwt(self) -> str:
        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + 540, "iss": settings.github_app_id}  # max 10 min
        return jwt.encode(payload, self._private_key(), algorithm="RS256")

    def _token(self, installation_id: int | None) -> str:
        if settings.github_app_id and installation_id:
            token, expires = self._tokens.get(installation_id, ("", 0.0))
            if time.time() < expires - 60:
                return token
            r = self._http.post(f"/app/installations/{installation_id}/access_tokens",
                                headers={"Authorization": f"Bearer {self.app_jwt()}"})
            r.raise_for_status()
            token = r.json()["token"]
            self._tokens[installation_id] = (token, time.time() + 3300)  # tokens live 1h
            return token
        if settings.github_token:
            return settings.github_token
        raise GitHubNotConfigured("No GitHub App installation or GITHUB_TOKEN configured")

    def upsert_pr_comment(self, full_name: str, pr_number: int, body: str,
                          installation_id: int | None, comment_id: int | None = None) -> int:
        """Update our earlier comment on this PR if there is one, else create a new one.
        Returns the comment id."""
        auth = {"Authorization": f"Bearer {self._token(installation_id)}"}
        if comment_id:
            r = self._http.patch(f"/repos/{full_name}/issues/comments/{comment_id}",
                                 json={"body": body}, headers=auth)
            if r.status_code != 404:  # 404 = comment was deleted -> post a new one
                r.raise_for_status()
                return int(r.json()["id"])
        r = self._http.post(f"/repos/{full_name}/issues/{pr_number}/comments", json={"body": body}, headers=auth)
        r.raise_for_status()
        return int(r.json()["id"])


_client: GitHubClient | None = None


def get_client() -> GitHubClient:
    global _client
    if _client is None:
        _client = GitHubClient()
    return _client


def set_client(client: GitHubClient | None) -> None:
    """Tests: swap in a client that talks to a fake GitHub."""
    global _client
    _client = client
