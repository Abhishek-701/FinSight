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

    def test_whatif_phrasings_route_to_portfolio_whatif(self):
        for q in [
            "What if I bought 10 more shares of AAPL?",
            "What if I sold 5 shares of JPM?",
            "What if I doubled my top holding?",
            "What if I trimmed my top holding by half?",
        ]:
            plan = route_tools(q)
            self.assertEqual(plan.get("intent"), "portfolio_whatif", q)
            tools = [a["tool"] for a in plan["actions"]]
            self.assertEqual(tools, ["portfolio_whatif", "synthesize_report"], q)

    def test_holdings_topic_phrasings_route_to_portfolio_filings(self):
        for q in [
            "Which of my holdings is most exposed to risk?",
            "Do any of my holdings have rate exposure?",
        ]:
            plan = route_tools(q)
            self.assertEqual(plan.get("intent"), "portfolio_filings", q)
            tools = [a["tool"] for a in plan["actions"]]
            self.assertEqual(tools, ["portfolio_filings", "synthesize_report"], q)

    def test_holdings_topic_checked_before_plain_portfolio_intent(self):
        # "my holdings" alone matches PORTFOLIO_INTENT_RE too; the more specific topical
        # regex must win so this gets filing evidence, not just the portfolio snapshot.
        plan = route_tools("Which of my holdings has the most rate exposure?")
        self.assertEqual(plan.get("intent"), "portfolio_filings")


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
        for tool in ("portfolio_context", "portfolio_whatif", "portfolio_filings"):
            self.assertNotIn("client_id", TOOL_REGISTRY[tool].arg_spec, tool)

    def test_client_id_injected_for_whatif_and_filings_tools_too(self):
        for tool_name in ("portfolio_whatif", "portfolio_filings"):
            captured = {}
            def fake_handler(**kwargs):
                captured.update(kwargs)
                return {"status": "ok", "evidence": []}
            with patch.dict(TOOL_REGISTRY, {tool_name: type(TOOL_REGISTRY[tool_name])(
                tool_name, "test", fake_handler, arg_spec={}
            )}):
                executor.execute(
                    [{"tool": tool_name}],
                    {"question": "q", "route": {}, "client_id": "real-client-42"},
                )
            self.assertEqual(captured.get("client_id"), "real-client-42", tool_name)


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


class PortfolioWhatifToolTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_whatif_tool.sqlite3"

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        self._tmpdir.cleanup()
        from app.tools import market
        market._QUOTE_CACHE.pop("AAPL", None)

    def test_missing_client_id_returns_refusal(self):
        result = portfolio_ctx.portfolio_whatif_tool(client_id=None, question="what if I bought 1 share of AAPL")
        self.assertEqual(result["status"], "missing_client_id")

    def test_empty_portfolio_returns_refusal(self):
        result = portfolio_ctx.portfolio_whatif_tool(client_id="nobody", question="what if I bought 1 share of AAPL")
        self.assertEqual(result["status"], "empty_portfolio")

    def test_unparseable_question_returns_refusal(self):
        from app.tools import market
        market._QUOTE_CACHE["AAPL"] = {
            "ticker": "AAPL", "company": "Apple", "price": 200.0, "previous_close": 198.0,
            "change": 2.0, "change_percent": 1.0, "market_cap": 3e12, "currency": "USD",
            "source": "yfinance", "as_of": "2026-07-12T00:00:00+00:00",
            "disclaimer": config.MARKET_DISCLAIMER,
        }
        portfolio.set_holding("client-y", "AAPL", 10)
        result = portfolio_ctx.portfolio_whatif_tool(client_id="client-y", question="what if the market crashes")
        self.assertEqual(result["status"], "unparseable_whatif")

    def test_valid_trade_builds_whatif_chunk(self):
        from app.tools import market
        market._QUOTE_CACHE["AAPL"] = {
            "ticker": "AAPL", "company": "Apple", "price": 200.0, "previous_close": 198.0,
            "change": 2.0, "change_percent": 1.0, "market_cap": 3e12, "currency": "USD",
            "source": "yfinance", "as_of": "2026-07-12T00:00:00+00:00",
            "disclaimer": config.MARKET_DISCLAIMER,
        }
        portfolio.set_holding("client-y", "AAPL", 10)
        result = portfolio_ctx.portfolio_whatif_tool(
            client_id="client-y", question="what if I bought 10 more shares of AAPL"
        )
        self.assertEqual(result["status"], "ok")
        chunk = result["evidence"][0]
        self.assertEqual(chunk["kind"], "portfolio_whatif")
        self.assertTrue(chunk["chunk_id"].startswith("WIF-client-y"))
        self.assertIn("not executed", chunk["text"])


class PortfolioFilingsToolTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_portfolio_filings.sqlite3"

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        self._tmpdir.cleanup()
        from app.tools import market
        market._QUOTE_CACHE.pop("AAPL", None)

    def test_missing_client_id_returns_refusal(self):
        result = portfolio_ctx.portfolio_filings(client_id=None, question="which of my holdings has risk?")
        self.assertEqual(result["status"], "missing_client_id")

    def test_empty_portfolio_returns_refusal(self):
        result = portfolio_ctx.portfolio_filings(client_id="nobody", question="which of my holdings has risk?")
        self.assertEqual(result["status"], "empty_portfolio")

    def test_holding_outside_corpus_returns_no_covered_holdings(self):
        portfolio.set_holding("client-z", "ZZZZ", 5)
        with patch("app.tools.portfolio_ctx.portfolio.analyze", return_value={
            "client_id": "client-z", "as_of": "2026-01-01T00:00:00+00:00",
            "holdings": [{"ticker": "ZZZZ", "company": "Zzzz", "shares": 5, "cost_basis": None,
                          "price": 10.0, "value": 50.0, "weight": 1.0, "day_change_pct": 0.0,
                          "day_change_value": 0.0, "unrealized_pl": None, "unrealized_pl_pct": None,
                          "market_status": "ok"}],
            "total_value": 50.0, "total_day_change": 0.0, "total_unrealized_pl": None,
            "concentration": {"top_ticker": "ZZZZ", "top_weight": 1.0, "top3_weight": 1.0,
                              "hhi": 10000.0, "band": "concentrated"},
        }):
            result = portfolio_ctx.portfolio_filings(client_id="client-z", question="which of my holdings has risk?")
        self.assertEqual(result["status"], "no_covered_holdings")
        self.assertEqual(len(result["evidence"]), 1)  # portfolio chunk only, no filing chunks

    def test_covered_holding_searches_filings_and_bounds_ticker_count(self):
        with patch("app.tools.portfolio_ctx.portfolio.analyze", return_value={
            "client_id": "client-z", "as_of": "2026-01-01T00:00:00+00:00",
            "holdings": [{"ticker": "AAPL", "company": "Apple", "shares": 5, "cost_basis": None,
                          "price": 200.0, "value": 1000.0, "weight": 1.0, "day_change_pct": 0.0,
                          "day_change_value": 0.0, "unrealized_pl": None, "unrealized_pl_pct": None,
                          "market_status": "ok"}],
            "total_value": 1000.0, "total_day_change": 0.0, "total_unrealized_pl": None,
            "concentration": {"top_ticker": "AAPL", "top_weight": 1.0, "top3_weight": 1.0,
                              "hhi": 10000.0, "band": "concentrated"},
        }), patch("app.tools.portfolio_ctx.retrieve.retrieve", return_value={
            "top_sim": 0.9, "chunks": [{"chunk_id": "AAPL-0001"}],
        }) as mock_retrieve:
            result = portfolio_ctx.portfolio_filings(client_id="client-z", question="AAPL risk factors")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["tickers_searched"], ["AAPL"])
        chunk_ids = [c.get("chunk_id") for c in result["evidence"]]
        self.assertIn("AAPL-0001", chunk_ids)
        mock_retrieve.assert_called_once()


if __name__ == "__main__":
    unittest.main()
