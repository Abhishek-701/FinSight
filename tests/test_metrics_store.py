import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app import config, metrics


class MetricsStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_metrics.sqlite3"

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        self._tmpdir.cleanup()

    def _row(self, **overrides):
        row = {
            "request_id": "req-1",
            "method": "GET",
            "route": "/api/companies",
            "status_code": 200,
            "elapsed_ms": 42,
        }
        row.update(overrides)
        return row

    def test_record_with_required_fields_only(self):
        metrics.record(self._row())
        rows = metrics.recent(limit=10)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["request_id"], "req-1")
        self.assertEqual(row["route"], "/api/companies")
        self.assertEqual(row["status_code"], 200)
        self.assertEqual(row["elapsed_ms"], 42)
        self.assertEqual(row["llm_calls"], 0)
        self.assertEqual(row["input_tokens"], 0)
        self.assertEqual(row["models"], {})
        self.assertIsNone(row["client_id"])
        self.assertIsNone(row["refused"])
        self.assertIsNone(row["error"])

    def test_record_with_full_fields(self):
        metrics.record(self._row(
            route="/api/chat",
            client_id="client-a",
            llm_calls=3,
            input_tokens=500,
            output_tokens=200,
            embed_tokens=10,
            models={"claude-sonnet-4-6": {"in": 500, "out": 200, "calls": 3}},
            refused=False,
            error=None,
        ))
        row = metrics.recent(limit=1)[0]
        self.assertEqual(row["llm_calls"], 3)
        self.assertEqual(row["input_tokens"], 500)
        self.assertEqual(row["models"], {"claude-sonnet-4-6": {"in": 500, "out": 200, "calls": 3}})
        self.assertFalse(row["refused"])

    def test_error_row_roundtrips(self):
        metrics.record(self._row(status_code=500, error="tool_not_allowed"))
        row = metrics.recent(limit=1)[0]
        self.assertEqual(row["status_code"], 500)
        self.assertEqual(row["error"], "tool_not_allowed")

    def test_recent_orders_newest_first(self):
        metrics.record(self._row(request_id="req-1"))
        metrics.record(self._row(request_id="req-2"))
        rows = metrics.recent(limit=10)
        self.assertEqual(rows[0]["request_id"], "req-2")
        self.assertEqual(rows[1]["request_id"], "req-1")

    def test_window_filters_by_created_at(self):
        metrics.record(self._row(request_id="req-old"))
        future = (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0).isoformat()
        rows = metrics.window(future)
        self.assertEqual(rows, [])
        past = (datetime.now(UTC) - timedelta(days=1)).replace(microsecond=0).isoformat()
        rows = metrics.window(past)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["request_id"], "req-old")

    def test_status_reports_backend_and_row_count(self):
        metrics.record(self._row())
        status = metrics.status()
        self.assertEqual(status["backend"], "sqlite")
        self.assertEqual(status["rows"], 1)


if __name__ == "__main__":
    unittest.main()
