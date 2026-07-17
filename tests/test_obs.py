import json
import logging
import unittest

from app import obs


class ObsAccumulatorTests(unittest.TestCase):
    def tearDown(self):
        obs.request_ctx.set(None)

    def test_no_op_when_context_unset(self):
        obs.request_ctx.set(None)
        obs.add_llm_usage("claude-sonnet-4-6", 100, 50)
        obs.add_embed_tokens(10)
        obs.set_extra("client_id", "c1")
        self.assertIsNone(obs.get_request_id())
        snap = obs.snapshot()
        self.assertEqual(snap["llm_calls"], 0)
        self.assertEqual(snap["models"], {})

    def test_seed_then_accumulate_across_multiple_calls(self):
        obs.seed("req-1")
        obs.add_llm_usage("claude-sonnet-4-6", 100, 50)
        obs.add_llm_usage("claude-sonnet-4-6", 200, 75)
        obs.add_llm_usage("claude-haiku-4-5", 30, 10)
        obs.add_embed_tokens(5)
        obs.add_embed_tokens(7)
        obs.set_extra("client_id", "c1")
        obs.set_extra("refused", True)

        snap = obs.snapshot()
        self.assertEqual(snap["request_id"], "req-1")
        self.assertEqual(snap["llm_calls"], 3)
        self.assertEqual(snap["input_tokens"], 330)
        self.assertEqual(snap["output_tokens"], 135)
        self.assertEqual(snap["embed_tokens"], 12)
        self.assertEqual(snap["models"]["claude-sonnet-4-6"], {"in": 300, "out": 125, "calls": 2})
        self.assertEqual(snap["models"]["claude-haiku-4-5"], {"in": 30, "out": 10, "calls": 1})
        self.assertEqual(snap["extra"], {"client_id": "c1", "refused": True})

    def test_get_request_id_reflects_seeded_context(self):
        obs.seed("req-xyz")
        self.assertEqual(obs.get_request_id(), "req-xyz")

    def test_snapshot_is_a_copy_not_a_live_reference(self):
        obs.seed("req-1")
        snap = obs.snapshot()
        obs.add_llm_usage("m", 1, 1)
        self.assertEqual(snap["llm_calls"], 0)  # earlier snapshot unaffected


class JsonFormatterTests(unittest.TestCase):
    def test_formatter_output_is_valid_json_with_request_id(self):
        obs.seed("req-log-1")
        logger = logging.getLogger("test.obs.formatter")
        logger.propagate = False
        logger.handlers = []
        handler = logging.StreamHandler()
        handler.setFormatter(obs._JsonFormatter())
        handler.addFilter(obs._RequestIdFilter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        record = logging.LogRecord(
            name="test.obs.formatter", level=logging.INFO, pathname=__file__, lineno=1,
            msg="hello %s", args=("world",), exc_info=None,
        )
        for f in handler.filters:
            f.filter(record)
        formatted = handler.formatter.format(record)
        payload = json.loads(formatted)
        self.assertEqual(payload["message"], "hello world")
        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["request_id"], "req-log-1")

    def test_formatter_reports_none_request_id_outside_a_request(self):
        obs.request_ctx.set(None)
        record = logging.LogRecord(
            name="test.obs.formatter", level=logging.INFO, pathname=__file__, lineno=1,
            msg="no request", args=(), exc_info=None,
        )
        obs._RequestIdFilter().filter(record)
        formatted = obs._JsonFormatter().format(record)
        payload = json.loads(formatted)
        self.assertIsNone(payload["request_id"])


if __name__ == "__main__":
    unittest.main()
