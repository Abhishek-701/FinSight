import unittest
from unittest.mock import patch

from app import research, router
from app.agent.router_llm import route_tools


class RouterNeedsIngestTests(unittest.TestCase):
    """router.route() offers ingestion for a real-but-uningested ticker instead of a flat oos."""

    @patch("app.router.universe.resolve_ticker")
    def test_unresolved_real_ticker_routes_to_needs_ingest(self, mock_resolve):
        mock_resolve.return_value = {"ticker": "TSLA", "cik": "0001318605", "ingested": False}
        result = router.route("What was TSLA's revenue last year?")
        self.assertEqual(result, {"mode": "needs_ingest", "tickers": [], "ticker": "TSLA"})

    @patch("app.router.universe.resolve_ticker")
    def test_no_resolution_falls_back_to_oos(self, mock_resolve):
        mock_resolve.return_value = None
        result = router.route("What was Amazon's revenue last year?")
        self.assertEqual(result["mode"], "oos")

    @patch("app.router.universe.resolve_ticker")
    def test_resolved_ticker_that_is_already_ingested_does_not_offer(self, mock_resolve):
        # Shouldn't happen in practice (detect_companies would have caught it first), but
        # route() must not offer to "ingest" something already in the corpus.
        mock_resolve.return_value = {"ticker": "AAPL", "cik": "0000320193", "ingested": True}
        result = router.route("Tell me about Fakecorp")
        self.assertEqual(result["mode"], "oos")


class RouteToolsNeedsIngestTests(unittest.TestCase):
    """route_tools() short-circuits needs_ingest for filing questions, but lets market
    questions (any ticker, no ingest required) answer directly."""

    def _needs_ingest_route(self, ticker="TSLA"):
        return {"mode": "needs_ingest", "tickers": [], "ticker": ticker}

    def test_filing_question_offers_ingest_without_running_rag(self):
        plan = route_tools("What was TSLA's revenue last year?", self._needs_ingest_route())
        self.assertEqual(plan["strategy"], "deterministic")
        self.assertEqual(plan["actions"], [{"tool": "refuse_or_clarify", "reason": "needs_ingest"}])

    def test_market_question_plans_market_quote_not_ingest_offer(self):
        plan = route_tools("What is TSLA's current stock price?", self._needs_ingest_route())
        tools = [a["tool"] for a in plan["actions"]]
        self.assertIn("market_quote", tools)
        self.assertNotIn("refuse_or_clarify", tools)
        quote_action = next(a for a in plan["actions"] if a["tool"] == "market_quote")
        self.assertEqual(quote_action["args"]["ticker"], "TSLA")


class ResearchOfferIngestTests(unittest.TestCase):
    """research.prepare() turns needs_ingest into a structured, actionable offer."""

    def test_prepare_returns_offer_ingest_payload(self):
        route = {"mode": "needs_ingest", "tickers": [], "ticker": "TSLA"}
        meta = research.prepare("What was TSLA's revenue last year?", route)
        self.assertTrue(meta["refused"])
        self.assertEqual(meta["refusal_reason"], "needs_ingest")
        self.assertEqual(meta["action"], "offer_ingest")
        self.assertEqual(meta["ticker"], "TSLA")


class StreamEventsOfferIngestTests(unittest.TestCase):
    """The frontend uses the STREAMING chat endpoint exclusively (useChat.ts -> streamChat),
    so the offer_ingest action/ticker must survive stream_events()'s own "done" event
    construction, not just the non-streaming run()/answer() path."""

    @patch("app.router.universe.resolve_ticker")
    def test_done_event_carries_action_and_ticker(self, mock_resolve):
        mock_resolve.return_value = {"ticker": "TSLA", "cik": "0001318605", "ingested": False}
        events = list(research.stream_events("What was TSLA's revenue last year?"))
        done_events = [e for e in events if e.startswith("event: done")]
        self.assertEqual(len(done_events), 1)
        payload = done_events[0]
        self.assertIn('"action": "offer_ingest"', payload)
        self.assertIn('"ticker": "TSLA"', payload)
        self.assertIn('"refusal_reason": "needs_ingest"', payload)


if __name__ == "__main__":
    unittest.main()
