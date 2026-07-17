import tempfile
import unittest
from pathlib import Path

from app import audit, config


class AuditStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_audit.sqlite3"

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        self._tmpdir.cleanup()

    def test_record_with_full_event_roundtrips(self):
        audit.record({
            "request_id": "req-1",
            "session_id": "sess-1",
            "client_id": "client-a",
            "question": "Is NVDA expensive?",
            "contextualized_question": "Is NVIDIA expensive?",
            "citations": ["NVDA-CALC-pe_ratio"],
            "tool_calls": [{"tool": "market_quote", "status": "ok"}],
            "refused": False,
            "elapsed_ms": 1234,
        })
        rows = audit.recent(limit=10)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["request_id"], "req-1")
        self.assertEqual(row["client_id"], "client-a")
        self.assertEqual(row["citations"], ["NVDA-CALC-pe_ratio"])
        self.assertEqual(row["tool_calls"], [{"tool": "market_quote", "status": "ok"}])
        self.assertFalse(row["refused"])
        self.assertEqual(row["elapsed_ms"], 1234)

    def test_record_with_partial_event_shape_does_not_raise(self):
        # This is the exact shape the non-streaming chat path passes today (main.py) —
        # no request_id/client_id/elapsed_ms until V6.2 wires those in.
        audit.record({
            "session_id": "sess-1",
            "question": "Is AAPL expensive?",
            "contextualized_question": "Is AAPL expensive?",
            "citations": [],
            "tool_calls": [],
            "refused": False,
        })
        row = audit.recent(limit=1)[0]
        self.assertIsNone(row["request_id"])
        self.assertIsNone(row["client_id"])
        self.assertIsNone(row["elapsed_ms"])
        self.assertEqual(row["citations"], [])

    def test_refused_true_roundtrips(self):
        audit.record({"session_id": "sess-1", "question": "q", "refused": True})
        self.assertTrue(audit.recent(limit=1)[0]["refused"])

    def test_recent_orders_newest_first(self):
        audit.record({"session_id": "s", "question": "first"})
        audit.record({"session_id": "s", "question": "second"})
        rows = audit.recent(limit=10)
        self.assertEqual(rows[0]["question"], "second")
        self.assertEqual(rows[1]["question"], "first")

    def test_status_reports_backend_and_row_count(self):
        audit.record({"session_id": "s", "question": "q"})
        status = audit.status()
        self.assertEqual(status["backend"], "sqlite")
        self.assertEqual(status["rows"], 1)


if __name__ == "__main__":
    unittest.main()
