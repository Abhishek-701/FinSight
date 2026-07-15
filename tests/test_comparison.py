"""V5.3 tests for cross-company valuation comparison: deterministic routing (no LLM call) and
ticker-scoped compute_metric extraction. All offline."""

import unittest

from app.agent.router_llm import route_tools
from app.tools import compute


class ComparisonRoutingTests(unittest.TestCase):
    def test_two_company_valuation_question_routes_to_comparison(self):
        plan = route_tools("Is Apple or NVIDIA more expensive?")
        self.assertEqual(plan.get("intent"), "comparison")
        self.assertEqual(plan["strategy"], "deterministic")
        tools = [a["tool"] for a in plan["actions"]]
        self.assertEqual(tools[0], "facts_lookup")
        self.assertEqual(tools.count("market_quote"), 2)
        self.assertEqual(tools.count("compute_metric"), 4)  # pe_ratio + ps_ratio per ticker
        self.assertEqual(tools[-1], "synthesize_report")

    def test_compute_metric_actions_are_ticker_scoped(self):
        plan = route_tools("Compare AAPL vs NVDA valuation")
        compute_actions = [a for a in plan["actions"] if a["tool"] == "compute_metric"]
        tickers = {a["args"]["ticker"] for a in compute_actions}
        self.assertEqual(tickers, {"AAPL", "NVDA"})

    def test_single_company_valuation_is_unaffected(self):
        plan = route_tools("Is NVIDIA expensive right now?")
        self.assertNotEqual(plan.get("intent"), "comparison")

    def test_screener_superlative_takes_priority_over_comparison(self):
        # "which company has the lowest P/S ratio" mentions no specific tickers (decompose over
        # all active companies via SUPERLATIVE_RE) and should stay a screener question.
        plan = route_tools("Which company has the lowest P/S ratio?")
        self.assertNotEqual(plan.get("intent"), "comparison")

    def test_comparison_capped_at_max_tickers(self):
        from app import config
        route = {"mode": "decompose", "tickers": ["AAPL", "JPM", "WMT", "KO", "NVDA"]}
        plan = route_tools("Are Apple, JPMorgan, Walmart, Coca-Cola or NVIDIA more expensive?", route)
        market_quotes = [a for a in plan["actions"] if a["tool"] == "market_quote"]
        self.assertEqual(len(market_quotes), config.COMPARISON_MAX_TICKERS)


class ComputeMetricTickerScopingTests(unittest.TestCase):
    def _quote_chunk(self, ticker, price):
        return {"chunk_id": f"{ticker}-MKT-1", "ticker": ticker, "kind": "market",
                "data": {"price": price}}

    def _xbrl_chunk(self, ticker, concept, value):
        return {
            "chunk_id": f"{ticker}-XBRL-1", "ticker": ticker, "kind": "xbrl",
            "facts": [{"concept": concept, "label": "annual_recent", "value_scaled": value}],
        }

    def test_ticker_scoping_picks_the_right_companys_price(self):
        evidence = [
            self._quote_chunk("AAPL", 200.0),
            self._quote_chunk("NVDA", 100.0),
            self._xbrl_chunk("AAPL", "us-gaap:EarningsPerShareDiluted", 5.0),
            self._xbrl_chunk("NVDA", "us-gaap:EarningsPerShareDiluted", 2.0),
        ]
        aapl_result = compute.compute_metric("pe_ratio", evidence=evidence, ticker="AAPL")
        nvda_result = compute.compute_metric("pe_ratio", evidence=evidence, ticker="NVDA")
        self.assertEqual(aapl_result["status"], "ok")
        self.assertEqual(nvda_result["status"], "ok")
        self.assertAlmostEqual(aapl_result["data"]["value"], 200.0 / 5.0)
        self.assertAlmostEqual(nvda_result["data"]["value"], 100.0 / 2.0)

    def test_no_ticker_keeps_first_match_behavior(self):
        evidence = [
            self._quote_chunk("AAPL", 200.0),
            self._xbrl_chunk("AAPL", "us-gaap:EarningsPerShareDiluted", 5.0),
        ]
        result = compute.compute_metric("pe_ratio", evidence=evidence)
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(result["data"]["value"], 40.0)

    def test_ticker_with_no_matching_evidence_falls_back_to_full_pool(self):
        evidence = [
            self._quote_chunk("AAPL", 200.0),
            self._xbrl_chunk("AAPL", "us-gaap:EarningsPerShareDiluted", 5.0),
        ]
        # "ZZZZ" isn't in the evidence at all — scoping to it would leave nothing, so this
        # should fall back to the unscoped pool rather than erroring.
        result = compute.compute_metric("pe_ratio", evidence=evidence, ticker="ZZZZ")
        self.assertEqual(result["status"], "ok")


if __name__ == "__main__":
    unittest.main()
