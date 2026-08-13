"""Offline tests for the schema-driven eval scorer (no LLM, no embeddings)."""

import unittest

from eval.cases import load_cases
from eval.numbers import answer_has_gold, extract_numbers
from eval.score import merge_scores, score_answer, score_retrieve


class NumberExtractionTests(unittest.TestCase):
    def test_millions_and_billions_match_same_gold(self):
        self.assertTrue(answer_has_gold(
            "Apple's operating income was **$133,050 million** [AAPL-XBRL-OperatingIncomeLoss].",
            133050, "millions",
        ))
        self.assertTrue(answer_has_gold(
            "Operating income was $133.05 billion for fiscal 2025.",
            133050, "millions",
        ))

    def test_eps_is_per_share_not_millions(self):
        self.assertTrue(answer_has_gold("Basic EPS was **$4.93** per share.", 4.93, "per_share"))
        self.assertFalse(answer_has_gold("Basic EPS was **$4.93** per share.", 4930000, "millions"))

    def test_percent_margin(self):
        self.assertTrue(answer_has_gold("Gross margin was **61.6%**.", 61.6, "percent"))

    def test_year_is_not_a_claim(self):
        claims = extract_numbers("For fiscal year 2025, revenue was $416,161 million.")
        years = [c for c in claims if abs(c.value - 2025) < 0.1]
        self.assertEqual(years, [])
        self.assertTrue(any(abs(c.value - 416161e6) < 1e9 for c in claims))

    def test_wrong_number_does_not_match_gold(self):
        self.assertFalse(answer_has_gold(
            "Net income was $99,280 million [AAPL-XBRL-NetIncome].",
            133050, "millions",
        ))


class RetrieveScoreTests(unittest.TestCase):
    def test_hit_at_k_accepts_grouped_xbrl_id(self):
        case = {"gold": {"retrieve": {
            "must_include": ["AAPL-XBRL-OperatingIncomeLoss"],
            "form": "10-K",
            "ticker": "AAPL",
        }}}
        got = score_retrieve(
            case,
            ["AAPL-XBRL-OperatingIncomeLoss_ProfitLoss"],
            {"AAPL-XBRL-OperatingIncomeLoss_ProfitLoss": "10-K"},
        )
        self.assertTrue(got["passed"], got["checks"])

    def test_must_not_include_catches_fy_on_quarterly(self):
        case = {"gold": {"retrieve": {
            "must_include": ["AAPL-10Q-XBRL-Revenue"],
            "must_not_include": ["AAPL-XBRL-RevenueFromContractWithCustomerExcludingAssessedTax"],
            "form": "10-Q",
        }}}
        got = score_retrieve(
            case,
            ["AAPL-XBRL-RevenueFromContractWithCustomerExcludingAssessedTax"],
            {"AAPL-XBRL-RevenueFromContractWithCustomerExcludingAssessedTax": "10-K"},
        )
        self.assertFalse(got["passed"])
        names = {c["name"] for c in got["checks"] if not c["passed"]}
        self.assertIn("retrieve_must_not_include", names)

    def test_skip_when_no_retrieve_gold(self):
        got = score_retrieve({"gold": {}}, ["AAPL-0001"])
        self.assertTrue(got["skipped"])
        self.assertTrue(got["passed"])


class AnswerScoreTests(unittest.TestCase):
    def test_gold_number_and_citation(self):
        case = {
            "gold": {
                "answer": {
                    "refuse": False,
                    "numbers": [{"value": 133050, "unit": "millions", "period": "FY2025"}],
                    "must_cite": ["AAPL-XBRL-OperatingIncomeLoss"],
                    "must_not_match": ["net income of"],
                },
                "faithfulness": "numbers_in_evidence",
            }
        }
        res = {
            "refused": False,
            "answer": (
                "Apple's total operating income for fiscal year 2025 was "
                "**$133,050 million** [AAPL-XBRL-OperatingIncomeLoss]."
            ),
            "citations": ["AAPL-XBRL-OperatingIncomeLoss"],
            "context_chunks": [{
                "chunk_id": "AAPL-XBRL-OperatingIncomeLoss",
                "text": "Consolidated | OperatingIncomeLoss | 2025-09-27 = 133,050",
            }],
            "citation_details": [{
                "chunk_id": "AAPL-XBRL-OperatingIncomeLoss",
                "text": "Consolidated | OperatingIncomeLoss | 2025-09-27 = 133,050",
                "facts": [{"value_display": "133,050", "value_scaled": 133050000000.0}],
            }],
        }
        got = score_answer(case, res)
        self.assertTrue(got["passed"], got["checks"])

    def test_unsupported_number_fails_faithfulness(self):
        case = {"gold": {"faithfulness": "numbers_in_evidence", "answer": {"refuse": False}}}
        res = {
            "refused": False,
            "answer": "Revenue was **$999,999 million** [AAPL-XBRL-Revenue].",
            "citations": ["AAPL-XBRL-Revenue"],
            "context_chunks": [{
                "chunk_id": "AAPL-XBRL-Revenue",
                "text": "Consolidated | Revenue | 2025-09-27 = 416,161",
            }],
            "citation_details": [{
                "chunk_id": "AAPL-XBRL-Revenue",
                "text": "Consolidated | Revenue | 2025-09-27 = 416,161",
            }],
        }
        got = score_answer(case, res)
        self.assertFalse(got["passed"])
        names = {c["name"] for c in got["checks"] if not c["passed"]}
        self.assertIn("numbers_in_evidence", names)

    def test_hallucinated_citation_fails(self):
        case = {"gold": {"faithfulness": "numbers_in_evidence", "answer": {"refuse": False}}}
        res = {
            "refused": False,
            "answer": "Revenue was **$416,161 million** [AAPL-9999].",
            "citations": ["AAPL-9999"],
            "context_chunks": [{
                "chunk_id": "AAPL-XBRL-Revenue",
                "text": "Consolidated | Revenue | 2025-09-27 = 416,161",
            }],
            "citation_details": [{
                "chunk_id": "AAPL-XBRL-Revenue",
                "text": "Consolidated | Revenue | 2025-09-27 = 416,161",
            }],
        }
        got = score_answer(case, res)
        self.assertFalse(got["passed"])
        names = {c["name"] for c in got["checks"] if not c["passed"]}
        self.assertIn("citation_in_evidence", names)

    def test_refuse_reason(self):
        case = {"gold": {"answer": {"refuse": True, "refuse_reason": "clarify"}}}
        res = {"refused": True, "refusal_reason": "clarify", "answer": "Which company?"}
        self.assertTrue(score_answer(case, res)["passed"])
        res["refusal_reason"] = "threshold"
        self.assertFalse(score_answer(case, res)["passed"])

    def test_judge_cannot_rescue_deterministic_fail(self):
        det = {"passed": False, "checks": [{"name": "gold_number", "passed": False, "layer": "answer"}]}
        judge = {"passed": True, "checks": [{"name": "judge_faithful", "passed": True, "layer": "judge"}]}
        merged = merge_scores(det, judge)
        self.assertFalse(merged["passed"])


class CaseLoaderTests(unittest.TestCase):
    def test_cases_have_unique_ids_and_smoke_tag(self):
        all_cases = load_cases()
        ids = [c["id"] for c in all_cases]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreater(len(all_cases), 20)
        smoke = load_cases(tags={"smoke"})
        self.assertGreater(len(smoke), 5)
        self.assertTrue(all("smoke" in (c.get("tags") or []) for c in smoke))
        one = load_cases(ids={"aapl-opinc-fy2025"})
        self.assertEqual(len(one), 1)
        self.assertEqual(one[0]["gold"]["answer"]["numbers"][0]["value"], 133050)


if __name__ == "__main__":
    unittest.main()
