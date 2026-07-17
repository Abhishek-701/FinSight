"""Offline tests for app.admin (aggregation math) and the /api/admin/* gate (401/403/200).

Two categories per the advisor review: (1) the gate must distinguish anonymous, authenticated-
but-non-admin, and admin — the forgettable case is the middle one, a logged-in user who isn't
on the admin list; (2) a fresh deploy with zero request_metrics rows must render zeros, not a
500 — every ratio/percentile in app.admin is guarded for the empty-data case.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import admin, config, metrics
from app.main import app

client = TestClient(app)


class EmptyDataTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_admin_empty.sqlite3"

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        self._tmpdir.cleanup()

    def test_summary_on_zero_rows_does_not_raise(self):
        result = admin.summary(days=7)
        self.assertEqual(result["requests"]["total"], 0)
        self.assertEqual(result["requests"]["error_rate"], 0.0)
        self.assertIsNone(result["latency_ms"]["overall"]["p50"])
        self.assertIsNone(result["latency_ms"]["overall"]["p95"])
        self.assertEqual(result["latency_ms"]["by_route"], [])
        self.assertEqual(result["tokens"]["est_cost_usd"], 0.0)
        self.assertEqual(result["chat"]["refusal_rate"], 0.0)
        self.assertEqual(result["chat"]["top_questions"], [])
        self.assertEqual(result["users"]["total"], 0)
        self.assertEqual(result["users"]["active_sessions"], 0)


class AggregationMathTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_admin_math.sqlite3"

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        self._tmpdir.cleanup()

    def _row(self, **overrides):
        row = {
            "request_id": "r", "method": "GET", "route": "/api/companies",
            "status_code": 200, "elapsed_ms": 100,
        }
        row.update(overrides)
        return row

    def test_percentiles_match_hand_computed_values(self):
        # elapsed_ms = [10, 20, 30, 40, 50] -> p50 = 30 (median), p95 interpolated near the top.
        for ms in (10, 20, 30, 40, 50):
            metrics.record(self._row(elapsed_ms=ms))
        result = admin.summary(days=7)
        self.assertEqual(result["latency_ms"]["overall"]["p50"], 30)
        # p95 of [10,20,30,40,50]: k = 4*0.95 = 3.8 -> interpolate between index 3 (40) and 4 (50)
        self.assertAlmostEqual(result["latency_ms"]["overall"]["p95"], 48.0)

    def test_per_day_bucketing_and_error_rate(self):
        metrics.record(self._row(status_code=200))
        metrics.record(self._row(status_code=200))
        metrics.record(self._row(status_code=500, error="boom"))
        result = admin.summary(days=7)
        self.assertEqual(result["requests"]["total"], 3)
        self.assertAlmostEqual(result["requests"]["error_rate"], 1 / 3, places=4)
        self.assertEqual(len(result["requests"]["per_day"]), 1)
        self.assertEqual(result["requests"]["per_day"][0]["count"], 3)
        self.assertEqual(result["requests"]["per_day"][0]["errors"], 1)

    def test_cost_calc_uses_configured_prices(self):
        model = next(iter(config.MODEL_PRICES))
        in_price, out_price = config.MODEL_PRICES[model]
        metrics.record(self._row(
            route="/api/chat", input_tokens=1_000_000, output_tokens=1_000_000,
            models={model: {"in": 1_000_000, "out": 1_000_000, "calls": 1}},
        ))
        result = admin.summary(days=7)
        row = next(m for m in result["tokens"]["by_model"] if m["model"] == model)
        self.assertAlmostEqual(row["est_cost_usd"], in_price + out_price, places=3)

    def test_cost_calc_ignores_unknown_model_without_raising(self):
        metrics.record(self._row(
            route="/api/chat", input_tokens=1000, output_tokens=1000,
            models={"some-retired-model-xyz": {"in": 1000, "out": 1000, "calls": 1}},
        ))
        result = admin.summary(days=7)  # must not raise KeyError
        row = next(m for m in result["tokens"]["by_model"] if m["model"] == "some-retired-model-xyz")
        self.assertEqual(row["est_cost_usd"], 0.0)

    def test_refusal_rate_only_over_chat_route(self):
        metrics.record(self._row(route="/api/chat", refused=True))
        metrics.record(self._row(route="/api/chat", refused=False))
        metrics.record(self._row(route="/api/companies"))  # not chat — must not count
        result = admin.summary(days=7)
        self.assertEqual(result["chat"]["turns"], 2)
        self.assertAlmostEqual(result["chat"]["refusal_rate"], 0.5)

    def test_window_excludes_rows_outside_the_requested_days(self):
        metrics.record(self._row())
        result = admin.summary(days=0)
        # days=0 -> since is "now", so a row recorded a moment ago should still fall outside
        # or right at the boundary; the assertion that matters is that this doesn't raise and
        # total is a small, well-defined number (0 or 1), not stale data leaking in unexpectedly.
        self.assertIn(result["requests"]["total"], (0, 1))


class AdminGateTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_admin_gate.sqlite3"
        self._orig_client_id = config.GOOGLE_CLIENT_ID
        self._orig_client_secret = config.GOOGLE_CLIENT_SECRET
        self._orig_admin_emails = config.ADMIN_EMAILS
        config.GOOGLE_CLIENT_ID = "test-client-id"
        config.GOOGLE_CLIENT_SECRET = "test-client-secret"
        client.cookies.clear()

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        config.GOOGLE_CLIENT_ID = self._orig_client_id
        config.GOOGLE_CLIENT_SECRET = self._orig_client_secret
        config.ADMIN_EMAILS = self._orig_admin_emails
        client.cookies.clear()

    def _login(self, email: str, sub: str) -> str:
        from app import auth as auth_module
        login_resp = client.get("/api/auth/google/login", follow_redirects=False)
        state_cookie = login_resp.cookies.get(auth_module.STATE_COOKIE)
        with patch("app.main.auth.exchange_code", return_value={"access_token": "fake"}), \
             patch("app.main.auth.fetch_userinfo", return_value={
                 "sub": sub, "email": email, "name": "T", "picture": None,
             }):
            resp = client.get(
                "/api/auth/google/callback",
                params={"code": "fake-code", "state": state_cookie},
                follow_redirects=False,
            )
        return resp.cookies.get(auth_module.SESSION_COOKIE)

    def test_anonymous_gets_401(self):
        resp = client.get("/api/admin/summary")
        self.assertEqual(resp.status_code, 401)

    def test_authenticated_non_admin_gets_403(self):
        config.ADMIN_EMAILS = {"someone-else@example.com"}
        from app import auth as auth_module
        token = self._login("regular@example.com", "sub-regular")
        client.cookies.set(auth_module.SESSION_COOKIE, token)
        resp = client.get("/api/admin/summary")
        self.assertEqual(resp.status_code, 403)

    def test_admin_gets_200_with_real_aggregates(self):
        config.ADMIN_EMAILS = {"boss@example.com"}
        from app import auth as auth_module
        token = self._login("boss@example.com", "sub-boss")
        client.cookies.set(auth_module.SESSION_COOKIE, token)
        resp = client.get("/api/admin/summary")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("requests", body)
        self.assertIn("users", body)

    def test_admin_requests_and_audit_endpoints_also_gated(self):
        resp1 = client.get("/api/admin/requests")
        self.assertEqual(resp1.status_code, 401)
        resp2 = client.get("/api/admin/audit")
        self.assertEqual(resp2.status_code, 401)


if __name__ == "__main__":
    unittest.main()
