"""Offline test for GET /health's V6.1 additions (database connectivity check, metrics_store
key) — runs against the real sqlite default, no mocking needed since storage.connect() always
succeeds locally.
"""

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)


class HealthEndpointTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_health.sqlite3"

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        self._tmpdir.cleanup()

    def test_database_key_reports_sqlite_ok(self):
        body = client.get("/health").json()
        self.assertIn("database", body)
        self.assertEqual(body["database"]["backend"], "sqlite")
        self.assertTrue(body["database"]["ok"])
        self.assertIn("latency_ms", body["database"])

    def test_metrics_store_key_present(self):
        body = client.get("/health").json()
        self.assertIn("metrics_store", body)
        self.assertEqual(body["metrics_store"]["backend"], "sqlite")

    def test_audit_log_key_reports_new_shape(self):
        body = client.get("/health").json()
        self.assertIn("rows", body["audit_log"])
        self.assertEqual(body["audit_log"]["backend"], "sqlite")


if __name__ == "__main__":
    unittest.main()
