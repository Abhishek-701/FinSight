"""Offline tests for the V6.2 request_logging middleware in app/main.py: does it record a
request_metrics row for /api/* paths (app/metrics.py), skip non-api paths, capture errors from
unhandled exceptions, and finalize streaming responses only after the body fully drains."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import config, metrics
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


class MetricsMiddlewareTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_mw.sqlite3"

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        self._tmpdir.cleanup()

    def test_ordinary_api_request_records_a_row(self):
        resp = client.get("/api/companies")
        self.assertEqual(resp.status_code, 200)
        rows = metrics.recent(limit=10)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["route"], "/api/companies")
        self.assertEqual(row["method"], "GET")
        self.assertEqual(row["status_code"], 200)
        self.assertIsNotNone(row["request_id"])
        self.assertIsInstance(row["elapsed_ms"], int)

    def test_non_api_path_is_not_recorded(self):
        resp = client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(metrics.recent(limit=10), [])

    def test_raising_route_returns_500_and_records_the_error(self):
        with patch("app.main.universe.active_companies", side_effect=RuntimeError("boom")):
            resp = client.get("/api/companies")
        self.assertEqual(resp.status_code, 500)
        row = metrics.recent(limit=1)[0]
        self.assertEqual(row["status_code"], 500)
        self.assertEqual(row["error"], "boom")

    def test_streaming_response_is_recorded_after_body_drains(self):
        def fake_stream(question, conversation_context=None, client_id=None, on_done=None):
            yield 'event: token\ndata: {"text": "hi"}\n\n'
            yield 'event: done\ndata: {"citations": [], "refused": false}\n\n'

        with patch("app.main.research.stream_events", side_effect=fake_stream):
            resp = client.get("/api/stream", params={"q": "test question"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("hi", resp.text)  # TestClient fully drains the body before returning
        rows = metrics.recent(limit=10)
        routes = [r["route"] for r in rows]
        self.assertIn("/api/stream", routes)


if __name__ == "__main__":
    unittest.main()
