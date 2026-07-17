"""Offline tests for the V6.3 auth routes and their effect on the client_id-scoped endpoints —
exchange_code/fetch_userinfo are monkeypatched so no real Google call is ever made. The OAuth
round-trip against real Google infrastructure (redirect_uri registration, cookie Secure behind
Render's proxy) is the deploy-time step and isn't verifiable here; what IS verified here is the
security-relevant behavior: identity resolution overriding a client-supplied id, and session
ownership blocking cross-user reads and continuations.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import auth as auth_module
from app import config
from app.main import app

client = TestClient(app)


def _login(email="user@example.com", sub="sub-1") -> str:
    """Drives the real callback route (state-cookie + monkeypatched Google calls) and returns
    the session cookie value set on success."""
    login_resp = client.get("/api/auth/google/login", follow_redirects=False)
    state_cookie = login_resp.cookies.get(auth_module.STATE_COOKIE)
    with patch("app.main.auth.exchange_code", return_value={"access_token": "fake-token"}), \
         patch("app.main.auth.fetch_userinfo", return_value={
             "sub": sub, "email": email, "name": "Test User", "picture": None,
         }):
        callback_resp = client.get(
            "/api/auth/google/callback",
            params={"code": "fake-code", "state": state_cookie},
            follow_redirects=False,
        )
    return callback_resp.cookies.get(auth_module.SESSION_COOKIE)


class AuthRouteTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_auth_routes.sqlite3"
        self._orig_client_id = config.GOOGLE_CLIENT_ID
        self._orig_client_secret = config.GOOGLE_CLIENT_SECRET
        config.GOOGLE_CLIENT_ID = "test-client-id"
        config.GOOGLE_CLIENT_SECRET = "test-client-secret"
        client.cookies.clear()

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        config.GOOGLE_CLIENT_ID = self._orig_client_id
        config.GOOGLE_CLIENT_SECRET = self._orig_client_secret
        client.cookies.clear()

    def test_login_404_when_oauth_not_configured(self):
        config.GOOGLE_CLIENT_ID = ""
        resp = client.get("/api/auth/google/login", follow_redirects=False)
        self.assertEqual(resp.status_code, 404)

    def test_callback_state_mismatch_redirects_to_error(self):
        client.get("/api/auth/google/login", follow_redirects=False)
        resp = client.get(
            "/api/auth/google/callback",
            params={"code": "x", "state": "wrong-state"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 307)
        self.assertIn("auth_error=1", resp.headers["location"])
        self.assertNotIn(auth_module.SESSION_COOKIE, resp.cookies)

    def test_happy_path_login_sets_cookie_and_me_reports_user(self):
        token = _login(email="me@example.com")
        self.assertIsNotNone(token)
        client.cookies.set(auth_module.SESSION_COOKIE, token)
        me = client.get("/api/auth/me").json()
        self.assertIsNotNone(me["user"])
        self.assertEqual(me["user"]["email"], "me@example.com")
        self.assertFalse(me["user"]["claimed"])

    def test_me_reports_anonymous_when_no_cookie(self):
        me = client.get("/api/auth/me").json()
        self.assertIsNone(me["user"])
        self.assertFalse(me["is_admin"])

    def test_logout_revokes_session(self):
        token = _login()
        client.cookies.set(auth_module.SESSION_COOKIE, token)
        client.post("/api/auth/logout")
        me = client.get("/api/auth/me").json()
        self.assertIsNone(me["user"])

    def test_claim_requires_login(self):
        resp = client.post("/api/auth/claim", json={"client_id": "anon-1"})
        self.assertEqual(resp.status_code, 401)

    def test_claim_rejects_another_users_id_via_the_endpoint(self):
        victim_token = _login(email="victim@example.com", sub="sub-victim")
        client.cookies.set(auth_module.SESSION_COOKIE, victim_token)
        client.post("/api/watchlist", json={"client_id": "ignored-authed-overrides", "ticker": "NVDA"})
        me = client.get("/api/auth/me").json()
        victim_id = me["user"]["id"]
        client.cookies.clear()

        attacker_token = _login(email="attacker@example.com", sub="sub-attacker")
        client.cookies.set(auth_module.SESSION_COOKIE, attacker_token)
        resp = client.post("/api/auth/claim", json={"client_id": victim_id})
        self.assertEqual(resp.status_code, 400)

        victim_items = client.get(f"/api/watchlist?client_id={victim_id}").json()["items"]
        # Attacker's cookie is still active, but resolve_client_id ignores the client_id query
        # param for an authenticated caller — so this reads the ATTACKER's own (empty) watchlist,
        # not the victim's. Confirms both the claim rejection AND that an authed GET can't be
        # redirected at another identity via the query string either.
        self.assertEqual(victim_items, [])


class ResolveClientIdEndpointTests(unittest.TestCase):
    """Confirms auth.resolve_client_id is actually wired into the client_id-scoped endpoints,
    not just unit-tested in isolation — an authenticated caller must always act as themselves,
    regardless of what client_id they put in the request body/query."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_resolve_endpoint.sqlite3"
        self._orig_client_id = config.GOOGLE_CLIENT_ID
        self._orig_client_secret = config.GOOGLE_CLIENT_SECRET
        config.GOOGLE_CLIENT_ID = "test-client-id"
        config.GOOGLE_CLIENT_SECRET = "test-client-secret"
        client.cookies.clear()

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        config.GOOGLE_CLIENT_ID = self._orig_client_id
        config.GOOGLE_CLIENT_SECRET = self._orig_client_secret
        client.cookies.clear()

    def test_authenticated_watchlist_write_ignores_supplied_client_id(self):
        token = _login(email="owner@example.com")
        client.cookies.set(auth_module.SESSION_COOKIE, token)
        me = client.get("/api/auth/me").json()
        own_id = me["user"]["id"]

        resp = client.post("/api/watchlist", json={
            "client_id": "someone-elses-anon-uuid", "ticker": "AAPL",
        })
        self.assertEqual(resp.status_code, 200)

        own_items = client.get(f"/api/watchlist?client_id={own_id}").json()["items"]
        self.assertEqual([i["ticker"] for i in own_items], ["AAPL"])
        # Still authenticated: querying with a *different* supplied client_id must ALSO resolve
        # to the caller's own identity and return the same data — proving resolve_client_id
        # fully overrides the supplied value for reads too, not just writes.
        foreign_items = client.get(
            "/api/watchlist?client_id=someone-elses-anon-uuid"
        ).json()["items"]
        self.assertEqual([i["ticker"] for i in foreign_items], ["AAPL"])

        # Only once logged OUT does the raw supplied client_id get used again, and that
        # anonymous identity has (correctly) never had anything written to it.
        client.cookies.clear()
        truly_anon_items = client.get(
            "/api/watchlist?client_id=someone-elses-anon-uuid"
        ).json()["items"]
        self.assertEqual(truly_anon_items, [])

    def test_anonymous_watchlist_write_still_uses_supplied_client_id(self):
        resp = client.post("/api/watchlist", json={"client_id": "anon-plain", "ticker": "KO"})
        self.assertEqual(resp.status_code, 200)
        items = client.get("/api/watchlist?client_id=anon-plain").json()["items"]
        self.assertEqual([i["ticker"] for i in items], ["KO"])


class SessionOwnershipEndpointTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_session_ownership.sqlite3"
        client.cookies.clear()

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        client.cookies.clear()

    def test_cross_anon_user_cannot_read_another_sessions_transcript(self):
        with patch("app.main.research.run", return_value={
            "answer": "hi", "citations": [], "tool_calls": [], "refused": False,
            "elapsed_ms": 1, "contextualized_question": "hi",
        }):
            chat_resp = client.post("/api/chat", json={
                "message": "hi", "client_id": "client-a", "stream": False,
            })
        sid = chat_resp.json()["session_id"]

        own_read = client.get(f"/api/sessions/{sid}", params={"client_id": "client-a"})
        self.assertEqual(own_read.status_code, 200)

        other_read = client.get(f"/api/sessions/{sid}", params={"client_id": "client-b"})
        self.assertEqual(other_read.status_code, 404)

    def test_cross_anon_user_cannot_continue_another_users_chat_session(self):
        with patch("app.main.research.run", return_value={
            "answer": "hi", "citations": [], "tool_calls": [], "refused": False,
            "elapsed_ms": 1, "contextualized_question": "hi",
        }):
            chat_resp = client.post("/api/chat", json={
                "message": "hi", "client_id": "client-a", "stream": False,
            })
        sid = chat_resp.json()["session_id"]

        with patch("app.main.research.run", return_value={
            "answer": "should not happen", "citations": [], "tool_calls": [], "refused": False,
            "elapsed_ms": 1, "contextualized_question": "nope",
        }):
            resp = client.post("/api/chat", json={
                "message": "let me in", "session_id": sid, "client_id": "client-b",
                "stream": False,
            })
        self.assertEqual(resp.status_code, 404)

    def test_legacy_unowned_session_still_readable_without_client_id(self):
        from app.agent import session as session_store
        sid = session_store.new_session_id()
        session_store.append(sid, "user", "old message")  # no client_id — legacy shape
        resp = client.get(f"/api/sessions/{sid}")
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
