"""V4.3 wiring tests: router intent detection, executor's server-side client_id injection
(the actual security boundary — a plan must never choose whose portfolio it reads), and the
portfolio_context tool's refusal/evidence shapes. All offline — no live LLM or market calls."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config, portfolio
from app.agent import executor
from app.agent.router_llm import route_tools
from app.tools import portfolio_ctx
from app.tools.registry import TOOL_REGISTRY


class PortfolioRouterTests(unittest.TestCase):
    def test_portfolio_phrasings_route_to_portfolio_context(self):
        for q in [
            "How is my portfolio doing?",
            "Explain my portfolio today",
            "What is my P&L?",
            "How concentrated am I?",
            "Show me my holdings",
        ]:
            plan = route_tools(q)
            self.assertEqual(plan.get("intent"), "portfolio", q)
            tools = [a["tool"] for a in plan["actions"]]
            self.assertEqual(tools, ["portfolio_context", "synthesize_report"], q)

    def test_portfolio_check_runs_before_clarify_short_circuit(self):
        # "How is my portfolio doing?" names no company -> router.route() alone would say
        # "clarify"; route_tools() must catch the portfolio intent before that fires.
        from app import router
        self.assertEqual(router.route("How is my portfolio doing?")["mode"], "clarify")
        plan = route_tools("How is my portfolio doing?")
        self.assertEqual(plan["strategy"], "deterministic")
        self.assertEqual(plan.get("intent"), "portfolio")

    def test_unrelated_question_does_not_trigger_portfolio_intent(self):
        plan = route_tools("What was Apple's revenue last year?")
        self.assertNotEqual(plan.get("intent"), "portfolio")


class ExecutorClientIdInjectionTests(unittest.TestCase):
    """The security-relevant boundary: client_id must come from the executor's context,
    never from a plan, even a maliciously/buggily crafted one."""

    def test_client_id_injected_from_context(self):
        captured = {}
        def fake_handler(**kwargs):
            captured.update(kwargs)
            return {"status": "ok", "evidence": []}
        with patch.dict(TOOL_REGISTRY, {"portfolio_context": type(TOOL_REGISTRY["portfolio_context"])(
            "portfolio_context", "test", fake_handler, arg_spec={}
        )}):
            executor.execute(
                [{"tool": "portfolio_context"}],
                {"question": "q", "route": {}, "client_id": "real-client-42"},
            )
        self.assertEqual(captured.get("client_id"), "real-client-42")

    def test_plan_supplied_client_id_is_overridden_not_trusted(self):
        # Even if an action dict somehow carries a client_id in its args (shouldn't happen —
        # registry.py's arg_spec for this tool has no client_id key — but the executor must
        # not trust it even so), the executor's context value wins.
        captured = {}
        def fake_handler(**kwargs):
            captured.update(kwargs)
            return {"status": "ok", "evidence": []}
        with patch.dict(TOOL_REGISTRY, {"portfolio_context": type(TOOL_REGISTRY["portfolio_context"])(
            "portfolio_context", "test", fake_handler, arg_spec={}
        )}):
            executor.execute(
                [{"tool": "portfolio_context", "args": {"client_id": "attacker-supplied"}}],
                {"question": "q", "route": {}, "client_id": "real-client-42"},
            )
        self.assertEqual(captured.get("client_id"), "real-client-42")

    def test_missing_context_client_id_passes_none_not_a_crash(self):
        captured = {}
        def fake_handler(**kwargs):
            captured.update(kwargs)
            return {"status": "ok", "evidence": []}
        with patch.dict(TOOL_REGISTRY, {"portfolio_context": type(TOOL_REGISTRY["portfolio_context"])(
            "portfolio_context", "test", fake_handler, arg_spec={}
        )}):
            executor.execute([{"tool": "portfolio_context"}], {"question": "q", "route": {}})
        self.assertIsNone(captured.get("client_id"))

    def test_registry_arg_spec_has_no_client_id_key(self):
        # Belt-and-suspenders: even if executor's override were ever removed, validate_args()
        # would strip an LLM-supplied client_id since it's not in the allowed key set.
        self.assertNotIn("client_id", TOOL_REGISTRY["portfolio_context"].arg_spec)


class PortfolioContextToolTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_portfolio_ctx.sqlite3"

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        self._tmpdir.cleanup()

    def test_missing_client_id_returns_refusal_meta(self):
        result = portfolio_ctx.portfolio_context(client_id=None, route={"mode": "clarify"})
        self.assertEqual(result["status"], "missing_client_id")
        self.assertTrue(result["meta"]["refused"])
        self.assertEqual(result["meta"]["refusal_reason"], "missing_client_id")
        self.assertEqual(result["evidence"], [])

    def test_empty_portfolio_returns_refusal_meta(self):
        result = portfolio_ctx.portfolio_context(client_id="nobody-here", route={"mode": "clarify"})
        self.assertEqual(result["status"], "empty_portfolio")
        self.assertTrue(result["meta"]["refused"])
        self.assertEqual(result["meta"]["refusal_reason"], "empty_portfolio")

    @patch("app.tools.portfolio_ctx.news_tool.news_headlines")
    def test_nonempty_portfolio_builds_port_chunk_and_top_mover_news(self, mock_news):
        mock_news.return_value = {"evidence": [{"chunk_id": "AAPL-NEWS-x", "kind": "news"}]}
        from app.tools import market
        market._QUOTE_CACHE["AAPL"] = {
            "ticker": "AAPL", "company": "Apple", "price": 200.0, "previous_close": 198.0,
            "change": 2.0, "change_percent": 1.0, "market_cap": 3e12, "currency": "USD",
            "source": "yfinance", "as_of": "2026-07-12T00:00:00+00:00",
            "disclaimer": config.MARKET_DISCLAIMER,
        }
        portfolio.set_holding("client-x", "AAPL", 10, cost_basis=150.0)
        try:
            result = portfolio_ctx.portfolio_context(client_id="client-x", route={"mode": "clarify"})
        finally:
            market._QUOTE_CACHE.pop("AAPL", None)

        self.assertEqual(result["status"], "ok")
        port_chunks = [c for c in result["evidence"] if c["kind"] == "portfolio"]
        self.assertEqual(len(port_chunks), 1)
        self.assertTrue(port_chunks[0]["chunk_id"].startswith("PORT-client-x"))
        self.assertIn("AAPL", port_chunks[0]["text"])
        news_chunks = [c for c in result["evidence"] if c["kind"] == "news"]
        self.assertEqual(len(news_chunks), 1)  # top-mover news bundled in

    def test_build_portfolio_chunk_states_missing_cost_basis_honestly(self):
        analysis = {
            "client_id": "c1", "as_of": "2026-01-01T00:00:00+00:00",
            "holdings": [{
                "ticker": "KO", "company": "Coca-Cola", "shares": 5, "cost_basis": None,
                "price": 60.0, "value": 300.0, "weight": 1.0, "day_change_pct": 0.01,
                "day_change_value": 3.0, "unrealized_pl": None, "unrealized_pl_pct": None,
                "market_status": "ok",
            }],
            "total_value": 300.0, "total_day_change": 3.0, "total_unrealized_pl": None,
            "concentration": {"top_ticker": "KO", "top_weight": 1.0, "top3_weight": 1.0,
                              "hhi": 10000.0, "band": "concentrated"},
        }
        chunk = portfolio_ctx.build_portfolio_chunk(analysis)
        self.assertIn("not available (no cost basis entered)", chunk["text"])
        self.assertNotIn("None", chunk["text"])  # never leak a raw None into the prompt text


if __name__ == "__main__":
    unittest.main()
