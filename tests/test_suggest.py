"""V5.1 tests for app.suggest: deterministic follow-up chips, no LLM involved."""

import unittest

from app import suggest


class SuggestTests(unittest.TestCase):
    def test_valuation_intent_formats_company_name(self):
        out = suggest.suggest("valuation", "AAPL", refused=False, refusal_reason=None)
        self.assertTrue(out)
        self.assertTrue(all("Apple" in q for q in out))

    def test_unknown_intent_falls_back_to_generic(self):
        out = suggest.suggest("filings_only", "KO", refused=False, refusal_reason=None)
        self.assertTrue(out)
        self.assertTrue(all("Coca-Cola" in q for q in out))

    def test_no_ticker_no_portfolio_intent_returns_empty(self):
        self.assertEqual(suggest.suggest("valuation", None, refused=False, refusal_reason=None), [])

    def test_portfolio_intent_ignores_missing_ticker(self):
        out = suggest.suggest("portfolio", None, refused=False, refusal_reason=None)
        self.assertEqual(out, suggest._TEMPLATES["portfolio"])

    def test_plain_refusal_returns_empty(self):
        out = suggest.suggest("filings_only", "AAPL", refused=True, refusal_reason="threshold")
        self.assertEqual(out, [])
        out = suggest.suggest(None, None, refused=True, refusal_reason="clarify")
        self.assertEqual(out, [])

    def test_needs_ingest_overrides_refused_with_ticker_specific_prompts(self):
        out = suggest.suggest(None, "TSLA", refused=True, refusal_reason="needs_ingest")
        self.assertTrue(out)
        self.assertTrue(all("TSLA" in q or "Once added" in q for q in out))

    def test_needs_ingest_without_ticker_returns_empty(self):
        out = suggest.suggest(None, None, refused=True, refusal_reason="needs_ingest")
        self.assertEqual(out, [])

    def test_at_most_three_suggestions(self):
        for intent in [*suggest._TEMPLATES, "filings_only", None]:
            out = suggest.suggest(intent, "AAPL", refused=False, refusal_reason=None)
            self.assertLessEqual(len(out), 3)


if __name__ == "__main__":
    unittest.main()
