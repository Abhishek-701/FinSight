"""Offline tests for app.auth: the V6.3 security-critical core (identity resolution, session
cookie verification, and the claim-on-first-login merge) — the part the advisor flagged as
needing to be airtight before any OAuth plumbing or frontend work, since a bug here lets an
authenticated user read or steal another user's data. No real Google calls are made; exchange_code
and fetch_userinfo are exercised in test_auth_routes.py with httpx mocked at the module boundary.
"""

import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from app import auth, config, portfolio, watchlist
from app.agent import session


class _FakeRequest:
    """Duck-types the one attribute auth.current_user()/resolve_client_id() touch."""

    def __init__(self, cookies: dict | None = None):
        self.cookies = cookies or {}


class AuthStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_auth.sqlite3"

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        self._tmpdir.cleanup()

    def _login(self, sub="sub-1", email="a@example.com", name="A") -> dict:
        return auth.upsert_user({"sub": sub, "email": email, "name": name, "picture": None})

    def test_upsert_user_creates_then_updates_same_google_sub(self):
        u1 = self._login(email="old@example.com", name="Old Name")
        u2 = self._login(email="new@example.com", name="New Name")
        self.assertEqual(u1["id"], u2["id"])
        self.assertEqual(u2["email"], "new@example.com")
        self.assertEqual(u2["name"], "New Name")

    def test_different_google_sub_creates_different_user(self):
        u1 = self._login(sub="sub-1")
        u2 = self._login(sub="sub-2")
        self.assertNotEqual(u1["id"], u2["id"])

    def test_session_cookie_roundtrip(self):
        user = self._login()
        token = auth.create_session(user["id"])
        req = _FakeRequest({auth.SESSION_COOKIE: token})
        found = auth.current_user(req)
        self.assertIsNotNone(found)
        self.assertEqual(found["id"], user["id"])

    def test_current_user_none_for_missing_cookie(self):
        self.assertIsNone(auth.current_user(_FakeRequest()))

    def test_current_user_none_for_bogus_token(self):
        req = _FakeRequest({auth.SESSION_COOKIE: "not-a-real-token"})
        self.assertIsNone(auth.current_user(req))

    def test_revoke_session_invalidates_token(self):
        user = self._login()
        token = auth.create_session(user["id"])
        auth.revoke_session(token)
        req = _FakeRequest({auth.SESSION_COOKIE: token})
        self.assertIsNone(auth.current_user(req))


class ResolveClientIdTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_resolve.sqlite3"

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        self._tmpdir.cleanup()

    def test_anonymous_request_keeps_supplied_client_id(self):
        resolved = auth.resolve_client_id(_FakeRequest(), "anon-uuid-123")
        self.assertEqual(resolved, "anon-uuid-123")

    def test_anonymous_request_with_no_supplied_id_returns_none(self):
        self.assertIsNone(auth.resolve_client_id(_FakeRequest(), None))

    def test_authenticated_request_ignores_supplied_client_id(self):
        user = auth.upsert_user({"sub": "sub-x", "email": "x@example.com"})
        token = auth.create_session(user["id"])
        req = _FakeRequest({auth.SESSION_COOKIE: token})
        # The caller supplies someone else's identity in the body — resolve_client_id must
        # ignore it entirely and return the AUTHENTICATED user's own id instead.
        resolved = auth.resolve_client_id(req, "someone-elses-anon-uuid")
        self.assertEqual(resolved, user["id"])


class ClaimSecurityTests(unittest.TestCase):
    """The advisor-flagged core: claim() must only ever re-key a genuinely anonymous identity,
    never another registered user's account."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_claim.sqlite3"
        # In the real app, portfolio/watchlist tables always exist before claim() is reachable
        # (the frontend hits GET /api/portfolio and /api/watchlist on load, well before a user
        # could log in). Mirror that here so claim()'s UPDATEs have a table to act on even in
        # tests that don't otherwise touch those modules.
        watchlist.items("bootstrap")
        portfolio.items("bootstrap")
        session.history("bootstrap")

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        self._tmpdir.cleanup()

    def test_claim_rekeys_anonymous_portfolio_and_watchlist(self):
        watchlist.add("anon-1", "AAPL")
        portfolio.set_holding("anon-1", "AAPL", 10)
        session.append("sess-1", "user", "hello", client_id="anon-1")

        user = auth.upsert_user({"sub": "sub-1", "email": "u@example.com"})
        result = auth.claim(user, "anon-1")

        self.assertEqual(result["claimed_client_id"], "anon-1")
        self.assertEqual([i["ticker"] for i in watchlist.items(user["id"])], ["AAPL"])
        self.assertEqual([i["ticker"] for i in portfolio.items(user["id"])], ["AAPL"])
        self.assertEqual(session.owner("sess-1"), user["id"])
        # Old identity's rows are gone (moved, not copied).
        self.assertEqual(watchlist.items("anon-1"), [])
        self.assertEqual(portfolio.items("anon-1"), [])

    def test_claim_twice_is_rejected(self):
        user = auth.upsert_user({"sub": "sub-1", "email": "u@example.com"})
        auth.claim(user, "anon-1")
        user_after = auth.get_user(user["id"])
        with self.assertRaises(HTTPException) as ctx:
            auth.claim(user_after, "anon-2")
        self.assertEqual(ctx.exception.status_code, 409)

    def test_cannot_claim_another_registered_users_id(self):
        # The exact attack the advisor flagged: victim's watchlist must be seeded under
        # victim.id (a users.id), and an attacker calling claim() with that id must be
        # rejected, leaving the victim's data untouched.
        victim = auth.upsert_user({"sub": "sub-victim", "email": "victim@example.com"})
        watchlist.add(victim["id"], "NVDA")
        portfolio.set_holding(victim["id"], "NVDA", 5)

        attacker = auth.upsert_user({"sub": "sub-attacker", "email": "attacker@example.com"})
        with self.assertRaises(HTTPException) as ctx:
            auth.claim(attacker, victim["id"])
        self.assertEqual(ctx.exception.status_code, 400)

        # Victim's data must be completely untouched.
        self.assertEqual([i["ticker"] for i in watchlist.items(victim["id"])], ["NVDA"])
        self.assertEqual([i["ticker"] for i in portfolio.items(victim["id"])], ["NVDA"])
        # Attacker gained nothing.
        self.assertEqual(watchlist.items(attacker["id"]), [])

    def test_cannot_self_claim(self):
        user = auth.upsert_user({"sub": "sub-1", "email": "u@example.com"})
        with self.assertRaises(HTTPException) as ctx:
            auth.claim(user, user["id"])
        self.assertEqual(ctx.exception.status_code, 400)


class SessionOwnershipTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_session_owner.sqlite3"

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        self._tmpdir.cleanup()

    def test_unowned_legacy_session_has_none_owner(self):
        session.append("sess-legacy", "user", "hi")  # no client_id — pre-V6.3 shape
        self.assertIsNone(session.owner("sess-legacy"))

    def test_owned_session_reports_its_owner(self):
        session.append("sess-a", "user", "hi", client_id="client-a")
        self.assertEqual(session.owner("sess-a"), "client-a")


if __name__ == "__main__":
    unittest.main()
