"""Google OAuth login + multi-user identity (V6.3) — sqlite by default, Postgres when
DATABASE_URL is set (app.storage).

Identity is verified via Google's userinfo endpoint over a server-to-server HTTPS call (the
access token never touches the browser), not by locally verifying the id_token's JWT signature
against Google's JWKS — equivalent trust, zero crypto dependency. `google_sub` (not email, which
can change) is the stable key on the `users` row; `users.id` is a fresh uuid4 that becomes the
effective client_id for an authenticated request (see resolve_client_id below).

Login is entirely additive: anonymous client_id mode (app.lib.clientId's localStorage UUID on
the frontend) keeps working with zero setup. Nothing about the anonymous path changes; a caller
that never logs in is unaffected by any of this module.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, Request

from app import config, storage

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

SESSION_COOKIE = "finsight_session"
STATE_COOKIE = "finsight_oauth_state"
_SESSION_TTL_DAYS = 30


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _init_schema(conn: storage._TranslatingConnection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS users ("
        "id TEXT PRIMARY KEY, google_sub TEXT NOT NULL UNIQUE, email TEXT NOT NULL, "
        "name TEXT, picture TEXT, claimed_client_id TEXT, "
        "created_at TEXT NOT NULL, last_login_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS auth_sessions ("
        "token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, "
        "created_at TEXT NOT NULL, expires_at TEXT NOT NULL)"
    )


def _connect() -> storage._TranslatingConnection:
    return storage.connect(config.SESSION_DB_PATH, init=_init_schema)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_configured() -> bool:
    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)


def is_admin(user: dict | None) -> bool:
    return bool(user) and user["email"].lower() in config.ADMIN_EMAILS


def login_url(state: str) -> str:
    params = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": f"{config.BASE_URL}/api/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    """POST the authorization code to Google's token endpoint; returns the token response
    (contains access_token). Raises httpx.HTTPStatusError on failure — caller redirects to an
    error page rather than letting this 500."""
    resp = httpx.post(_TOKEN_URL, data={
        "code": code,
        "client_id": config.GOOGLE_CLIENT_ID,
        "client_secret": config.GOOGLE_CLIENT_SECRET,
        "redirect_uri": f"{config.BASE_URL}/api/auth/google/callback",
        "grant_type": "authorization_code",
    }, timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_userinfo(access_token: str) -> dict:
    """GET the authenticated user's profile from Google — this IS the identity verification
    step: the access_token only came from Google's token endpoint in the prior server-to-server
    exchange, so a successful response here is proof of who signed in, without needing to
    locally verify an id_token's JWT signature against Google's JWKS."""
    resp = httpx.get(
        _USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _row_to_user(row: tuple) -> dict:
    uid, email, name, picture, claimed_client_id = row
    return {
        "id": uid, "email": email, "name": name, "picture": picture,
        "claimed_client_id": claimed_client_id,
    }


def get_user(user_id: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, email, name, picture, claimed_client_id FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()
    return _row_to_user(row) if row else None


def upsert_user(info: dict) -> dict:
    """Insert or update by google_sub (the stable key — email can change). Returns the user row."""
    sub, email = info["sub"], info["email"]
    name, picture = info.get("name"), info.get("picture")
    now = _now()
    conn = _connect()
    try:
        with conn:
            row = conn.execute("SELECT id FROM users WHERE google_sub = ?", (sub,)).fetchone()
            if row:
                user_id = row[0]
                conn.execute(
                    "UPDATE users SET email = ?, name = ?, picture = ?, last_login_at = ? "
                    "WHERE id = ?",
                    (email, name, picture, now, user_id),
                )
            else:
                user_id = uuid.uuid4().hex
                conn.execute(
                    "INSERT INTO users (id, google_sub, email, name, picture, claimed_client_id, "
                    "created_at, last_login_at) VALUES (?, ?, ?, ?, ?, NULL, ?, ?)",
                    (user_id, sub, email, name, picture, now, now),
                )
    finally:
        conn.close()
    return get_user(user_id)


def create_session(user_id: str) -> str:
    """Returns the raw token (goes in the cookie); only its sha256 hash is stored, so a stolen
    DB row can't be replayed as a cookie."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    expires = now + timedelta(days=_SESSION_TTL_DAYS)
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO auth_sessions (token_hash, user_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    _hash(token), user_id,
                    now.replace(microsecond=0).isoformat(),
                    expires.replace(microsecond=0).isoformat(),
                ),
            )
    finally:
        conn.close()
    return token


def revoke_session(token: str) -> None:
    conn = _connect()
    try:
        with conn:
            conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (_hash(token),))
    finally:
        conn.close()


def current_user(request: Request) -> dict | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT user_id, expires_at FROM auth_sessions WHERE token_hash = ?",
            (_hash(token),),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    user_id, expires_at = row
    if expires_at < _now():
        return None
    return get_user(user_id)


def resolve_client_id(request: Request, supplied: str | None) -> str | None:
    """The identity a request acts as: the authenticated user's id when a valid session cookie
    is present (ignoring whatever client_id the caller supplied in the body/query — a logged-in
    caller can't act as anyone else), else the client-supplied anonymous UUID unchanged."""
    user = current_user(request)
    return user["id"] if user else supplied


def require_user(request: Request) -> dict:
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="login_required")
    return user


def count_users() -> int:
    conn = _connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


def count_active_sessions() -> int:
    conn = _connect()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM auth_sessions WHERE expires_at > ?", (_now(),),
        ).fetchone()[0]
    finally:
        conn.close()


def claim(user: dict, anon_client_id: str) -> dict:
    """Re-key anonymous portfolio/watchlist/message rows to this user, once, right after first
    login. Returns the updated user row.

    Security: `anon_client_id` is just a client-supplied string with no proof of ownership — it
    is NOT verified to be an actual anonymous, unclaimed identity. Without the check below, a
    first-login attacker could pass a VICTIM's own `users.id` (itself a bare uuid4, structurally
    indistinguishable from an anonymous client_id) and this function would happily re-key the
    victim's portfolio/watchlist/chat history onto the attacker's account. So: reject outright if
    the supplied id belongs to any registered user, and reject a no-op self-claim.
    """
    if user.get("claimed_client_id"):
        raise HTTPException(status_code=409, detail="already_claimed")
    if anon_client_id == user["id"]:
        raise HTTPException(status_code=400, detail="invalid_client_id")
    conn = _connect()
    try:
        is_a_real_user = conn.execute(
            "SELECT 1 FROM users WHERE id = ?", (anon_client_id,),
        ).fetchone()
        if is_a_real_user:
            raise HTTPException(status_code=400, detail="invalid_client_id")
        with conn:
            # Known limitation, not engineered around: if the caller already holds rows under
            # their OWN user.id for the same ticker (only possible by using the product between
            # login and calling claim, which the normal UI flow never does), this UPDATE can hit
            # a PRIMARY KEY(client_id, ticker) conflict and raise. No data corruption either way.
            conn.execute(
                "UPDATE portfolio SET client_id = ? WHERE client_id = ?",
                (user["id"], anon_client_id),
            )
            conn.execute(
                "UPDATE watchlist SET client_id = ? WHERE client_id = ?",
                (user["id"], anon_client_id),
            )
            conn.execute(
                "UPDATE messages SET client_id = ? WHERE client_id = ?",
                (user["id"], anon_client_id),
            )
            conn.execute(
                "UPDATE users SET claimed_client_id = ? WHERE id = ?",
                (anon_client_id, user["id"]),
            )
    finally:
        conn.close()
    return get_user(user["id"])
