"""Offline test for the V6.2 on_done wiring: the streaming /api/chat path previously never
persisted the assistant message or wrote an audit record (only the non-streaming branch did).
research.stream_events's on_done hook (app/research.py) now fires once with the finished
answer text, and app/main.py's chat endpoint uses it to append the session message + audit."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import audit, config
from app.agent import session as session_store
from app.main import app

client = TestClient(app)


def _fake_stream_events(question, conversation_context=None, client_id=None, on_done=None):
    yield 'event: token\ndata: {"text": "The answer is 42."}\n\n'
    payload = {
        "citations": ["AAPL-CALC-pe_ratio"],
        "gaps": [],
        "refused": False,
        "plan": {},
        "tool_calls": [{"tool": "market_quote", "status": "ok"}],
        "question": question,
        "contextualized_question": question,
        "elapsed_ms": 123,
    }
    if on_done:
        on_done({**payload, "answer_text": "The answer is 42."})
    yield f"event: done\ndata: {json.dumps(payload)}\n\n"


class StreamOnDoneTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_stream_done.sqlite3"

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        self._tmpdir.cleanup()

    def _post_streaming_chat(self):
        with patch("app.main.research.stream_events", side_effect=_fake_stream_events):
            return client.post("/api/chat", json={
                "message": "What is the P/E?", "client_id": "client-a", "stream": True,
            })

    def _session_id_from(self, resp) -> str:
        for line in resp.text.splitlines():
            if line.startswith("data:") and '"session_id"' in line:
                return json.loads(line[len("data:"):])["session_id"]
        raise AssertionError("no session event found in SSE stream")

    def test_on_done_persists_assistant_message_exactly_once(self):
        resp = self._post_streaming_chat()
        self.assertEqual(resp.status_code, 200)
        sid = self._session_id_from(resp)
        history = session_store.history(sid)
        self.assertEqual([m["role"] for m in history], ["user", "assistant"])
        self.assertEqual(history[1]["content"], "The answer is 42.")

    def test_on_done_writes_an_audit_row(self):
        self._post_streaming_chat()
        row = audit.recent(limit=1)[0]
        self.assertEqual(row["client_id"], "client-a")
        self.assertEqual(row["citations"], ["AAPL-CALC-pe_ratio"])
        self.assertFalse(row["refused"])
        self.assertEqual(row["elapsed_ms"], 123)


if __name__ == "__main__":
    unittest.main()
