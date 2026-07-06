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
