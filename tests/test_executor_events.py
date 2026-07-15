"""V5.1 tests for the executor's live-event generator: ordering and parity with execute()."""

import unittest
from unittest.mock import patch

from app.agent import executor
from app.tools.registry import TOOL_REGISTRY, ToolSpec


class ExecutorEventsTests(unittest.TestCase):
    def test_events_order_and_shape_for_a_two_step_plan(self):
        def ok_handler(**kwargs):
            return {"status": "ok", "evidence": [{"chunk_id": "X-1"}]}

        with patch.dict(TOOL_REGISTRY, {
            "market_quote": ToolSpec("market_quote", "test", ok_handler, arg_spec={}),
        }):
            actions = [
                {"tool": "market_quote", "args": {"ticker": "AAPL"}},
                {"tool": "synthesize_report"},
            ]
            events = list(executor.execute_events(actions, {"question": "q", "route": {}}))

        kinds = [k for k, _ in events]
        self.assertEqual(kinds, ["tool_start", "tool_result", "result"])
        self.assertEqual(events[0][1], {"tool": "market_quote"})
        self.assertEqual(events[1][1]["tool"], "market_quote")
        self.assertEqual(events[1][1]["status"], "ok")
        tool_calls, evidence = events[2][1]
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(evidence, [{"chunk_id": "X-1"}])

    def test_execute_wrapper_matches_final_events_result(self):
        def ok_handler(**kwargs):
            return {"status": "ok", "evidence": []}

        with patch.dict(TOOL_REGISTRY, {
            "market_quote": ToolSpec("market_quote", "test", ok_handler, arg_spec={}),
        }):
            actions = [{"tool": "market_quote", "args": {"ticker": "AAPL"}}]
            context = {"question": "q", "route": {}}
            via_execute = executor.execute(actions, dict(context))
            via_events = next(
                p for k, p in executor.execute_events(actions, dict(context)) if k == "result"
            )
        self.assertEqual(via_execute, via_events)

    def test_synthesize_report_step_yields_no_tool_events(self):
        events = list(executor.execute_events(
            [{"tool": "synthesize_report"}], {"question": "q", "route": {}}
        ))
        self.assertEqual([k for k, _ in events], ["result"])


if __name__ == "__main__":
    unittest.main()
