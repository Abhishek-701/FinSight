"""V5.3 follow-up polish: 'What about AAPL?' should carry over the PRIOR question's intent
wording (e.g. 'expensive') instead of losing it, by rewriting the prior question with the new
company swapped in. All offline."""

import unittest

from app.agent.context import ConversationContext, contextualize_question


def _ctx(active_ticker, last_user_question, tickers=None):
    return ConversationContext(
        tickers=tickers or [active_ticker], active_ticker=active_ticker,
        last_user_question=last_user_question, last_assistant_summary=None,
    )


class ContextSwapTests(unittest.TestCase):
    def test_bare_swap_rewrites_prior_question_with_new_company(self):
        ctx = _ctx("NVDA", "Is NVDA expensive right now?")
        rewritten, _ = contextualize_question("What about AAPL?", ctx)
        self.assertIn("Apple", rewritten)
        self.assertIn("expensive", rewritten.lower())
        self.assertNotIn("NVDA", rewritten)

    def test_how_about_phrasing_also_triggers_swap(self):
        ctx = _ctx("NVDA", "Why is NVDA down this month?")
        rewritten, _ = contextualize_question("How about AAPL?", ctx)
        self.assertIn("Apple", rewritten)
        self.assertIn("down", rewritten.lower())

    def test_swap_to_the_same_company_is_a_no_op(self):
        ctx = _ctx("NVDA", "Is NVDA expensive right now?")
        rewritten, _ = contextualize_question("What about NVDA?", ctx)
        self.assertEqual(rewritten, "What about NVDA?")

    def test_non_bare_swap_question_is_not_rewritten(self):
        # Names AAPL explicitly with its own full question — not a bare "what about" swap,
        # so it should be used as-stated per the existing rule-1 behavior.
        ctx = _ctx("NVDA", "Is NVDA expensive right now?")
        rewritten, _ = contextualize_question("What is Apple's revenue?", ctx)
        self.assertEqual(rewritten, "What is Apple's revenue?")

    def test_no_active_ticker_falls_back_to_unchanged(self):
        ctx = ConversationContext(tickers=["AAPL"], active_ticker=None,
                                   last_user_question="Is AAPL expensive?", last_assistant_summary=None)
        rewritten, _ = contextualize_question("What about NVDA?", ctx)
        self.assertEqual(rewritten, "What about NVDA?")

    def test_no_context_returns_question_unchanged(self):
        rewritten, meta = contextualize_question("What about AAPL?", None)
        self.assertEqual(rewritten, "What about AAPL?")
        self.assertEqual(meta, {})


if __name__ == "__main__":
    unittest.main()
