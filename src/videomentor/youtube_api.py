"""YouTube Data API v3, read-only, for dates yt-dlp can't see.

Playlist creation dates and the date each video was added to a playlist. Sign-in
is Google's desktop-app flow: a browser opens, you sign in yourself, and the
browser comes back to a one-shot server on 127.0.0.1. The Google app stays in
"Testing", so the sign-in expires after 7 days; that shows up as state "expired"
and everything else keeps working.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from .config import library_home

SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
API = "https://www.googleapis.com/youtube/v3"


class NotSetUp(Exception):
    """No OAuth client file yet (docs/setup.md)."""


class SignInNeeded(Exception):
    """Never signed in, or the 7-day Testing sign-in expired: run `vm youtube-login`."""


class ApiError(Exception):
    pass


def client_path() -> Path:
    return library_home() / "secrets" / "youtube-oauth-client.json"


def token_path() -> Path:
    return library_home() / "secrets" / "youtube-token.json"


def load_client() -> dict:
    try:
        data = json.loads(client_path().read_text())
    except FileNotFoundError:
        raise NotSetUp(str(client_path())) from None
    return data.get("installed") or data.get("web") or data


def _load_token() -> dict | None:
    try:
        return json.loads(token_path().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save_token(token: dict) -> None:
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(token, indent=2))
    path.chmod(0o600)


def state() -> dict:
    """not_set_up, signed_out, expired or ok, with a line you can act on."""
    if not client_path().exists():
        return {"state": "not_set_up", "message": "YouTube API not set up."}
    token = _load_token()
    if not token or not token.get("refresh_token"):
        return {"state": "signed_out", "message": "Run `vm youtube-login` on the Mac."}
    if token.get("expired"):
        return {
            "state": "expired",
            "message": "YouTube sign-in expired (it lasts 7 days). Run `vm youtube-login` on the Mac.",
            "signed_in_at": token.get("signed_in_at"),
        }
    return {
        "state": "ok",
        "message": "Signed in to YouTube.",
        "signed_in_at": token.get("signed_in_at"),
    }


# --- HTTP (module-level so tests can replace them) ---------------------------


def _post_form(url: str, data: dict) -> dict:
    req = urllib.request.Request(url, data=urlencode(data).encode(), method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except (json.JSONDecodeError, ValueError):
            body = {"error": f"http_{e.code}"}
        return {"error": body.get("error", f"http_{e.code}"), "status": e.code}


def _get_json(url: str, access_token: str) -> tuple[int, dict]:
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {access_token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except (json.JSONDecodeError, ValueError):
            return e.code, {}


# --- sign-in -----------------------------------------------------------------


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def login(open_url: Callable[[str], None], timeout_s: float = 300) -> dict:
    """Run the browser sign-in and save a refresh token. Returns state()."""
    client = load_client()
    verifier = secrets.token_urlsafe(64)
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    expected_state = secrets.token_urlsafe(16)
    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server API
            query = parse_qs(urlparse(self.path).query)
            if "code" in query or "error" in query:
                result.update({k: v[0] for k, v in query.items()})
                body = (
                    "<h2>VideoMentor is signed in.</h2><p>You can close this tab.</p>"
                    if "code" in query
                    else "<h2>Sign-in was cancelled.</h2>"
                )
            else:
                body = "<p>Waiting for Google…</p>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):  # keep the terminal quiet
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 1
    redirect = f"http://127.0.0.1:{server.server_port}"
    url = (
        client.get("auth_uri", "https://accounts.google.com/o/oauth2/auth")
        + "?"
        + urlencode(
            {
                "client_id": client["client_id"],
                "redirect_uri": redirect,
                "response_type": "code",
                "scope": SCOPE,
                "access_type": "offline",
                "prompt": "consent",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": expected_state,
            }
        )
    )
    try:
        open_url(url)
        deadline = time.monotonic() + timeout_s
        while not result and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()

    if not result:
        raise SignInNeeded("Timed out waiting for the browser sign-in.")
    if result.get("error"):
        raise SignInNeeded(f"Google said: {result['error']}")
    if result.get("state") != expected_state:
        raise SignInNeeded("The sign-in reply didn't match this request. Try again.")

    reply = _post_form(
        client.get("token_uri", "https://oauth2.googleapis.com/token"),
        {
            "code": result["code"],
            "client_id": client["client_id"],
            "client_secret": client.get("client_secret", ""),
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect,
        },
    )
    if "refresh_token" not in reply:
        raise SignInNeeded(f"Google didn't return a sign-in token: {reply.get('error', 'unknown')}")
    _save_token(
        {
            "refresh_token": reply["refresh_token"],
            "access_token": reply.get("access_token"),
            "expires_at": time.time() + float(reply.get("expires_in", 0)),
            "signed_in_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "expired": False,
        }
    )
    return state()


def access_token(force_refresh: bool = False) -> str:
    """A valid access token, refreshing it when needed."""
    client = load_client()
    token = _load_token()
    if not token or not token.get("refresh_token"):
        raise SignInNeeded("Not signed in to YouTube.")
    if token.get("expired"):
        raise SignInNeeded("YouTube sign-in expired.")
    if (
        not force_refresh
        and token.get("access_token")
        and token.get("expires_at", 0) > time.time() + 60
    ):
        return token["access_token"]
    reply = _post_form(
        client.get("token_uri", "https://oauth2.googleapis.com/token"),
        {
            "client_id": client["client_id"],
            "client_secret": client.get("client_secret", ""),
            "refresh_token": token["refresh_token"],
            "grant_type": "refresh_token",
        },
    )
    if "access_token" not in reply:
        if reply.get("error") in ("invalid_grant", "unauthorized_client"):
            token["expired"] = True
            _save_token(token)
            raise SignInNeeded("YouTube sign-in expired.")
        raise ApiError(f"token refresh failed: {reply.get('error', 'unknown')}")
    token["access_token"] = reply["access_token"]
    token["expires_at"] = time.time() + float(reply.get("expires_in", 3600))
    _save_token(token)
    return token["access_token"]


def get(resource: str, params: dict) -> dict:
    url = f"{API}/{resource}?{urlencode(params)}"
    status, body = _get_json(url, access_token())
    if status == 401:
        status, body = _get_json(url, access_token(force_refresh=True))
    if status != 200:
        message = (body.get("error") or {}).get("message") if isinstance(body, dict) else None
        raise ApiError(f"{resource}: HTTP {status} {message or ''}".strip())
    return body


# --- what we read ------------------------------------------------------------


def playlists_meta(ids: list[str]) -> dict[str, dict]:
    """Created date, item count and privacy for playlists, 50 per request."""
    out: dict[str, dict] = {}
    for i in range(0, len(ids), 50):
        body = get(
            "playlists",
            {
                "part": "snippet,contentDetails,status",
                "id": ",".join(ids[i : i + 50]),
                "maxResults": 50,
            },
        )
        for p in body.get("items", []):
            out[p["id"]] = {
                "created_at": p.get("snippet", {}).get("publishedAt"),
                "title": p.get("snippet", {}).get("title"),
                "item_count": p.get("contentDetails", {}).get("itemCount"),
                "privacy": p.get("status", {}).get("privacyStatus"),
            }
    return out


def playlist_added_dates(playlist_id: str, max_pages: int = 40) -> dict[str, str]:
    """video id -> when it was added to the playlist."""
    out: dict[str, str] = {}
    params = {"part": "snippet,contentDetails", "playlistId": playlist_id, "maxResults": 50}
    for _ in range(max_pages):
        body = get("playlistItems", params)
        for it in body.get("items", []):
            vid = it.get("contentDetails", {}).get("videoId")
            added = it.get("snippet", {}).get("publishedAt")
            if vid and added:
                out[vid] = added
        token = body.get("nextPageToken")
        if not token:
            break
        params = params | {"pageToken": token}
    return out
