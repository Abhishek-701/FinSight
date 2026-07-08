import unittest

from app import corpus, research, router
from app.research import CITATION_RE
from app.tools.compute import compute_metric
from app.tools.screen import screen_companies


class OfflineProductTests(unittest.TestCase):
    def test_xbrl_only_question_short_circuits_rag_plan(self):
        question = "What was NVIDIA's total revenue?"
        plan = research.plan(question, router.route(question))
        tools = [action["tool"] for action in plan["actions"]]
        self.assertIn("facts_lookup", tools)
        self.assertNotIn("filing_rag", tools)

    def test_segment_question_uses_rag_not_xbrl(self):
        question = "What was NVIDIA's Data Center segment revenue?"
        plan = research.plan(question, router.route(question))
        tools = [action["tool"] for action in plan["actions"]]
        self.assertNotIn("facts_lookup", tools)
        self.assertIn("filing_rag", tools)

    def test_hybrid_question_plans_market_and_compute(self):
        question = "Compare Apple's current market cap to its latest reported revenue."
        plan = research.plan(question, router.route(question))
        tools = [action["tool"] for action in plan["actions"]]
        self.assertIn("facts_lookup", tools)
        self.assertIn("market_quote", tools)
        self.assertIn("compute_metric", tools)

    def test_compute_metric_emits_citable_evidence(self):
        evidence = [
            {
                "kind": "xbrl",
                "ticker": "AAPL",
                "company": "Apple",
                "chunk_id": "AAPL-XBRL-Revenue",
                "facts": [{"concept": "us-gaap:Revenues", "label": "annual_recent",
                           "value_scaled": 400_000_000_000}],
            },
            {
                "kind": "market",
                "chunk_id": "AAPL-MKT-TEST",
                "data": {"market_cap": 4_000_000_000_000},
            },
        ]
        result = compute_metric("market_cap_to_revenue", evidence=evidence)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["value"], 10)
        self.assertEqual(result["evidence"][0]["kind"], "compute")

    def test_corpus_status_has_version(self):
        status = corpus.status()
        self.assertIn("corpus_version", status)
        self.assertIn("manifest_count", status)

    def test_derived_metric_superlative_plans_screen_companies(self):
        question = "Which company has the highest operating margin?"
        plan = research.plan(question, router.route(question))
        tools = [action["tool"] for action in plan["actions"]]
        self.assertIn("screen_companies", tools)
        self.assertNotIn("market_quote", tools)
        screen_action = next(a for a in plan["actions"] if a["tool"] == "screen_companies")
        self.assertEqual(screen_action["args"], {"metric": "operating_margin", "order": "desc"})

    def test_raw_metric_superlative_unaffected_by_screener(self):
        question = "Which of the six companies reported the highest R&D spend?"
        plan = research.plan(question, router.route(question))
        tools = [action["tool"] for action in plan["actions"]]
        self.assertNotIn("screen_companies", tools)
        self.assertIn("facts_lookup", tools)
        self.assertIn("multi_company_compare", tools)

    def test_lowest_ps_ratio_plans_ascending_screen(self):
        question = "Which company has the lowest P/S ratio?"
        plan = research.plan(question, router.route(question))
        screen_action = next(a for a in plan["actions"] if a["tool"] == "screen_companies")
        self.assertEqual(screen_action["args"], {"metric": "ps_ratio", "order": "asc"})
        self.assertLessEqual(len(plan["actions"]), 12)
        self.assertEqual(plan["actions"][-1]["tool"], "synthesize_report")

    def test_screen_companies_offline_evidence_is_citable(self):
        result = screen_companies(metric="net_margin", order="desc")
        self.assertEqual(result["status"], "ok")
        chunk = result["evidence"][0]
        self.assertTrue(CITATION_RE.match(f"[{chunk['chunk_id']}]"))
        self.assertEqual(chunk["kind"], "screen")
        values = [r["value"] for r in chunk["data"]["rows"] if r["value"] is not None]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_screen_companies_unsupported_metric(self):
        result = screen_companies(metric="not_a_real_metric")
        self.assertEqual(result["status"], "unsupported")

    def test_compute_pe_ratio_from_price_and_eps(self):
        evidence = [
            {"kind": "market", "ticker": "NVDA", "company": "NVIDIA", "chunk_id": "NVDA-MKT-Q",
             "data": {"price": 120.0}},
            {"kind": "xbrl", "ticker": "NVDA", "company": "NVIDIA", "chunk_id": "NVDA-XBRL-EPS",
             "facts": [{"concept": "us-gaap:EarningsPerShareDiluted", "label": "annual_recent",
                        "value_scaled": 3.0}]},
        ]
        result = compute_metric("pe_ratio", evidence=evidence)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["value"], 40.0)
        self.assertEqual(result["data"]["formula"], "price / eps_diluted")
        self.assertEqual(result["evidence"][0]["kind"], "compute")
        self.assertIn("-CALC-pe_ratio", result["evidence"][0]["chunk_id"])

    def test_compute_pe_ratio_falls_back_to_market_cap_over_net_income(self):
        evidence = [
            {"kind": "market", "ticker": "NVDA", "company": "NVIDIA", "chunk_id": "NVDA-MKT-Q",
             "data": {"market_cap": 3_000_000_000_000}},
            {"kind": "xbrl", "ticker": "NVDA", "company": "NVIDIA", "chunk_id": "NVDA-XBRL-NI",
             "facts": [{"concept": "us-gaap:NetIncomeLoss", "label": "annual_recent",
                        "value_scaled": 30_000_000_000}]},
        ]
        result = compute_metric("pe_ratio", evidence=evidence)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["value"], 100.0)
        self.assertEqual(result["data"]["formula"], "market_cap / net_income")

    def test_compute_price_change_from_history_rows(self):
        evidence = [
            {"kind": "market", "ticker": "NVDA", "company": "NVIDIA", "chunk_id": "NVDA-MKT-HIST",
             "data": {"rows": [
                 {"date": "2026-06-01", "close": 100.0},
                 {"date": "2026-06-15", "close": 105.0},
                 {"date": "2026-07-01", "close": 90.0},
             ]}},
        ]
        result = compute_metric("price_change", evidence=evidence)
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(result["data"]["value"], -10.0)
        self.assertEqual(result["data"]["inputs"]["first_close"], 100.0)
        self.assertEqual(result["data"]["inputs"]["last_close"], 90.0)

    def test_compute_ps_alias_matches_market_cap_to_revenue(self):
        evidence = [
            {"kind": "xbrl", "ticker": "AAPL", "company": "Apple", "chunk_id": "AAPL-XBRL-Revenue",
             "facts": [{"concept": "us-gaap:Revenues", "label": "annual_recent",
                        "value_scaled": 400_000_000_000}]},
            {"kind": "market", "chunk_id": "AAPL-MKT-TEST", "data": {"market_cap": 4_000_000_000_000}},
        ]
        result = compute_metric("ps_ratio", evidence=evidence)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["value"], 10)
        self.assertIn("-CALC-ps_ratio", result["evidence"][0]["chunk_id"])

    def test_compute_missing_input_statuses(self):
        self.assertEqual(compute_metric("pe_ratio", evidence=[])["status"], "missing_input")
        self.assertEqual(compute_metric("price_change", evidence=[])["status"], "missing_input")
        self.assertEqual(compute_metric("market_cap_to_revenue", evidence=[])["status"], "missing_input")
        self.assertEqual(compute_metric("price_change", evidence=[
            {"kind": "market", "chunk_id": "X-MKT-H", "data": {"rows": [{"date": "d", "close": 1.0}]}},
        ])["status"], "missing_input")

    def test_merge_evidence_keeps_tool_chunk_when_rag_fills_cap(self):
        # Mirrors the real executor flow: filing_rag/multi_company_compare puts its own chunks in
        # BOTH meta.context_chunks and the flat evidence list, so evidence contains 24 duplicates
        # of context_chunks PLUS the genuinely-new tool chunk appended after (screen_companies ran
        # after multi_company_compare). A naive "evidence-first" merge still truncates the new
        # chunk away because the 24 RAG dupes alone fill the cap before it's reached.
        rag_chunks = [{"chunk_id": f"RAG-{i}", "text": "x"} for i in range(24)]
        tool_chunk = {"chunk_id": "SCRN-operating_margin-TEST", "text": "screen"}
        evidence = rag_chunks + [tool_chunk]  # RAG dupes first, new tool chunk last
        meta = {"context_chunks": rag_chunks, "refused": False}
        merged = research._merge_evidence(meta, evidence)
        ids = [c["chunk_id"] for c in merged["context_chunks"]]
        self.assertIn("SCRN-operating_margin-TEST", ids)
        self.assertEqual(len(merged["context_chunks"]), 24)


if __name__ == "__main__":
    unittest.main()
