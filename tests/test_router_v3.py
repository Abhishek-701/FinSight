import unittest
from unittest.mock import patch

from app import config, research, router
from app.agent import router_plan
from app.tools import market
from app.tools.filings import facts_lookup


def _null_action(**overrides) -> dict:
    base = {"tool": None, "ticker": None, "metric": None, "metrics": None,
            "period": None, "order": None, "question": None}
    base.update(overrides)
    return base


class DeterministicV3RouterTests(unittest.TestCase):
    """USE_LLM_ROUTER=0 — exercises the regex-only V3 fallback branches."""

    def setUp(self):
        self._orig = config.USE_LLM_ROUTER
        config.USE_LLM_ROUTER = False

    def tearDown(self):
        config.USE_LLM_ROUTER = self._orig

    def test_valuation_question_plans_facts_quote_computes_and_screen_in_order(self):
        question = "Is NVIDIA expensive right now?"
        plan = research.plan(question, router.route(question))
        self.assertEqual(plan["intent"], "valuation")
        tools = [a["tool"] for a in plan["actions"]]
        self.assertEqual(tools, ["facts_lookup", "market_quote", "compute_metric",
                                  "compute_metric", "screen_companies", "synthesize_report"])
        facts_action = plan["actions"][0]
        self.assertEqual(facts_action["args"]["metrics"], config.VALUATION_FACT_METRICS)

    def test_explain_move_question_plans_history_quote_compute_and_overridden_rag(self):
        question = "Why is NVIDIA down this month?"
        plan = research.plan(question, router.route(question))
        self.assertEqual(plan["intent"], "explain_move")
        tools = [a["tool"] for a in plan["actions"]]
        self.assertEqual(tools, ["market_history", "market_quote", "compute_metric",
                                  "filing_rag", "synthesize_report"])
        history_action = plan["actions"][0]
        self.assertEqual(history_action["args"]["period"], "1mo")
        rag_action = next(a for a in plan["actions"] if a["tool"] == "filing_rag")
        self.assertIn("risk factors", rag_action["args"]["question"])

    def test_insight_question_plans_company_insight_and_rag(self):
        question = "Give me an insight brief on Apple"
        plan = research.plan(question, router.route(question))
        self.assertEqual(plan["intent"], "insight")
        tools = [a["tool"] for a in plan["actions"]]
        self.assertIn("company_insight", tools)
        self.assertIn("filing_rag", tools)
        self.assertEqual(tools[-1], "synthesize_report")

    def test_lowest_ps_ratio_still_plans_screen_companies_not_valuation(self):
        question = "Which company has the lowest P/S ratio?"
        plan = research.plan(question, router.route(question))
        self.assertNotEqual(plan.get("intent"), "valuation")
        tools = [a["tool"] for a in plan["actions"]]
        self.assertIn("screen_companies", tools)
        self.assertNotIn("compute_metric", tools)

    def test_valuation_question_not_swallowed_by_summary_shortcut(self):
        question = "tell me about NVIDIA's valuation"
        route = router.route(question)
        self.assertFalse(research._is_summary_question(question, route))

    def test_plan_bounded_and_ends_with_synthesize_report(self):
        question = "Why is NVIDIA down this month?"
        plan = research.plan(question, router.route(question))
        self.assertLessEqual(len(plan["actions"]), config.AGENT_MAX_STEPS)
        self.assertEqual(plan["actions"][-1]["tool"], "synthesize_report")

    def test_facts_lookup_accepts_explicit_metrics(self):
        result = facts_lookup(question="is NVDA expensive",
                              route={"mode": "single", "tickers": ["NVDA"]},
                              metrics=["eps_diluted"])
        self.assertEqual(result["status"], "hit")
        self.assertTrue(result["evidence"])
        self.assertEqual(result["metrics"], ["eps_diluted"])


class LlmRouterTests(unittest.TestCase):
    """USE_LLM_ROUTER=1 with app.agent.router_plan.llm_route mocked — no network calls."""

    def setUp(self):
        self._orig = config.USE_LLM_ROUTER
        config.USE_LLM_ROUTER = True
        router_plan._PLAN_CACHE.clear()

    def tearDown(self):
        config.USE_LLM_ROUTER = self._orig
        router_plan._PLAN_CACHE.clear()

    def test_valid_llm_plan_passes_through(self):
        question = "Is NVDA's P/E ratio too high?"
        raw = {
            "intent": "valuation",
            "actions": [
                _null_action(tool="facts_lookup", metrics=["eps_diluted"]),
                _null_action(tool="market_quote", ticker="NVDA"),
                _null_action(tool="compute_metric", metric="pe_ratio"),
            ],
        }
        with patch("app.agent.router_plan.llm_route", return_value=raw):
            plan = research.plan(question, router.route(question))
        self.assertEqual(plan["strategy"], "llm_router")
        self.assertEqual(plan["intent"], "valuation")
        tools = [a["tool"] for a in plan["actions"]]
        self.assertEqual(tools, ["facts_lookup", "market_quote", "compute_metric", "synthesize_report"])

    def test_unknown_tool_falls_back_to_deterministic(self):
        question = "Is NVDA's P/E ratio too high?"
        raw = {"intent": "valuation", "actions": [_null_action(tool="delete_everything")]}
        with patch("app.agent.router_plan.llm_route", return_value=raw):
            plan = research.plan(question, router.route(question))
        self.assertEqual(plan["strategy"], "deterministic")

    def test_compute_before_evidence_is_reordered(self):
        question = "Is NVDA's P/E ratio too high?"
        raw = {
            "intent": "valuation",
            "actions": [
                _null_action(tool="compute_metric", metric="pe_ratio"),
                _null_action(tool="market_quote", ticker="NVDA"),
            ],
        }
        with patch("app.agent.router_plan.llm_route", return_value=raw):
            plan = research.plan(question, router.route(question))
        tools = [a["tool"] for a in plan["actions"]]
        self.assertEqual(tools, ["market_quote", "compute_metric", "synthesize_report"])

    def test_compute_with_no_evidence_action_falls_back(self):
        question = "Is NVDA's P/E ratio too high?"
        raw = {"intent": "valuation", "actions": [_null_action(tool="compute_metric", metric="pe_ratio")]}
        with patch("app.agent.router_plan.llm_route", return_value=raw):
            plan = research.plan(question, router.route(question))
        self.assertEqual(plan["strategy"], "deterministic")

    def test_invalid_enum_value_falls_back(self):
        # market_quote's ticker is intentionally unconstrained (V4.1: yfinance serves any
        # ticker regardless of filing coverage), so use a field that's still enum-validated —
        # market_history's period — to exercise the invalid-value fallback path.
        question = "Is NVDA's P/E ratio too high?"
        raw = {"intent": "valuation", "actions": [
            _null_action(tool="market_history", ticker="NVDA", period="10years"),
        ]}
        with patch("app.agent.router_plan.llm_route", return_value=raw):
            plan = research.plan(question, router.route(question))
        self.assertEqual(plan["strategy"], "deterministic")

    def test_llm_route_exception_falls_back(self):
        question = "Is NVDA's P/E ratio too high?"
        with patch("app.agent.router_plan.llm_route", side_effect=RuntimeError("boom")):
            plan = research.plan(question, router.route(question))
        self.assertEqual(plan["strategy"], "deterministic")

    def test_screener_superlative_never_calls_llm_router(self):
        question = "Which company has the lowest P/S ratio?"
        with patch("app.agent.router_plan.llm_route") as mock_route:
            plan = research.plan(question, router.route(question))
        mock_route.assert_not_called()
        tools = [a["tool"] for a in plan["actions"]]
        self.assertIn("screen_companies", tools)


class RefusalMergeFixTests(unittest.TestCase):
    """When explain_move's filing_rag is threshold-refused, market/compute evidence must survive."""

    def setUp(self):
        market._QUOTE_CACHE["NVDA"] = {
            "ticker": "NVDA", "company": "NVIDIA", "price": 100.0, "previous_close": 105.0,
            "change": -5.0, "change_percent": -4.76, "market_cap": 2_500_000_000_000.0,
            "currency": "USD", "source": "yfinance", "as_of": "2026-07-08T00:00:00+00:00",
            "disclaimer": config.MARKET_DISCLAIMER,
        }
        market._HISTORY_CACHE[("NVDA", "1mo")] = {
            "ticker": "NVDA", "company": "NVIDIA", "period": "1mo",
            "rows": [
                {"date": "2026-06-08", "open": 108.0, "high": 112.0, "low": 107.0, "close": 110.0, "volume": 100},
                {"date": "2026-07-08", "open": 101.0, "high": 103.0, "low": 99.0, "close": 100.0, "volume": 100},
            ],
            "source": "yfinance", "as_of": "2026-07-08T00:00:00+00:00", "disclaimer": config.MARKET_DISCLAIMER,
        }

    def tearDown(self):
        market._QUOTE_CACHE.pop("NVDA", None)
        market._HISTORY_CACHE.pop(("NVDA", "1mo"), None)

    def test_explain_move_refused_rag_does_not_drop_market_evidence(self):
        route = {"mode": "single", "tickers": ["NVDA"]}
        research_plan = {
            "intent": "explain_move",
            "actions": [
                {"tool": "market_history", "args": {"ticker": "NVDA", "period": "1mo"}},
                {"tool": "market_quote", "args": {"ticker": "NVDA"}},
                {"tool": "compute_metric", "args": {"metric": "price_change"}},
                {"tool": "filing_rag", "args": {"question": "NVIDIA risk factors demand competition"}},
                {"tool": "synthesize_report"},
            ],
        }
        refused_meta = {
            "route": route, "sub_queries": [], "retrieval": [], "refused": True,
            "refusal_reason": "threshold", "answer": "refused text",
        }
        with patch("app.research.prepare", return_value=refused_meta):
            meta, tool_calls = research._prepare_with_tools(
                "Why is NVIDIA down this month?", route, research_plan)
        self.assertFalse(meta.get("refused"))
        ids = [c["chunk_id"] for c in meta["context_chunks"]]
        self.assertTrue(any("-MKT-" in cid for cid in ids), ids)
        self.assertTrue(any("-CALC-" in cid for cid in ids), ids)


if __name__ == "__main__":
    unittest.main()
