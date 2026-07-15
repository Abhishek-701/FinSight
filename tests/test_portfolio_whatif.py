"""V5.2 tests for app.portfolio.whatif/parse_whatif_trades: hypothetical trade simulation,
never persisted. All offline (seeded quote cache, no live yfinance/LLM calls)."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config, portfolio
from app.tools import market


class PortfolioWhatifTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_whatif.sqlite3"

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        self._tmpdir.cleanup()
        market._QUOTE_CACHE.pop("AAPL", None)
        market._QUOTE_CACHE.pop("JPM", None)

    def _seed_quote(self, ticker, price):
        market._QUOTE_CACHE[ticker] = {
            "ticker": ticker, "company": ticker, "price": price, "previous_close": price,
            "change": 0.0, "change_percent": 0.0, "market_cap": price * 1e9,
            "currency": "USD", "source": "yfinance", "as_of": "2026-07-12T00:00:00+00:00",
            "disclaimer": config.MARKET_DISCLAIMER,
        }

    def test_adding_shares_to_existing_holding_increases_after_value(self):
        self._seed_quote("AAPL", 200.0)
        portfolio.set_holding("client-a", "AAPL", 10)  # $2000
        result = portfolio.whatif("client-a", [{"ticker": "AAPL", "delta_shares": 10}])
        self.assertEqual(result["before"]["total_value"], 2000.0)
        self.assertEqual(result["after"]["total_value"], 4000.0)

    def test_trimming_more_than_held_drops_the_holding_from_after(self):
        self._seed_quote("AAPL", 200.0)
        portfolio.set_holding("client-a", "AAPL", 10)
        result = portfolio.whatif("client-a", [{"ticker": "AAPL", "delta_shares": -20}])
        self.assertEqual(result["after"]["holdings"], [])
        self.assertEqual(result["after"]["total_value"], 0.0)

    def test_buying_a_ticker_not_currently_held_adds_it_to_after_only(self):
        self._seed_quote("AAPL", 200.0)
        self._seed_quote("JPM", 100.0)
        portfolio.set_holding("client-a", "AAPL", 10)
        result = portfolio.whatif("client-a", [{"ticker": "JPM", "delta_shares": 5}])
        before_tickers = {h["ticker"] for h in result["before"]["holdings"]}
        after_tickers = {h["ticker"] for h in result["after"]["holdings"]}
        self.assertNotIn("JPM", before_tickers)
        self.assertIn("JPM", after_tickers)

    def test_selling_a_ticker_not_currently_held_is_a_no_op(self):
        self._seed_quote("AAPL", 200.0)
        portfolio.set_holding("client-a", "AAPL", 10)
        result = portfolio.whatif("client-a", [{"ticker": "JPM", "delta_shares": -5}])
        after_tickers = {h["ticker"] for h in result["after"]["holdings"]}
        self.assertNotIn("JPM", after_tickers)

    def test_before_is_unaffected_by_the_hypothetical_trade(self):
        self._seed_quote("AAPL", 200.0)
        portfolio.set_holding("client-a", "AAPL", 10)
        portfolio.whatif("client-a", [{"ticker": "AAPL", "delta_shares": 100}])
        # Nothing persisted — a fresh analyze() still sees the original 10 shares.
        self.assertEqual(portfolio.analyze("client-a")["total_value"], 2000.0)

    def test_invalid_ticker_raises(self):
        self._seed_quote("AAPL", 200.0)
        portfolio.set_holding("client-a", "AAPL", 10)
        with self.assertRaises(ValueError):
            portfolio.whatif("client-a", [{"ticker": "BAD TICKER", "delta_shares": 1}])

    def test_invalid_delta_raises(self):
        self._seed_quote("AAPL", 200.0)
        portfolio.set_holding("client-a", "AAPL", 10)
        for bad in (0, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                portfolio.whatif("client-a", [{"ticker": "AAPL", "delta_shares": bad}])


class ParseWhatifTradesTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_parse_whatif.sqlite3"

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        self._tmpdir.cleanup()
        market._QUOTE_CACHE.pop("AAPL", None)
        market._QUOTE_CACHE.pop("JPM", None)

    def _seed_quote(self, ticker, price):
        market._QUOTE_CACHE[ticker] = {
            "ticker": ticker, "company": ticker, "price": price, "previous_close": price,
            "change": 0.0, "change_percent": 0.0, "market_cap": price * 1e9,
            "currency": "USD", "source": "yfinance", "as_of": "2026-07-12T00:00:00+00:00",
            "disclaimer": config.MARKET_DISCLAIMER,
        }

    def test_buy_shares_phrasing(self):
        trades = portfolio.parse_whatif_trades("what if I bought 10 shares of AAPL", "client-a")
        self.assertEqual(trades, [{"ticker": "AAPL", "delta_shares": 10.0}])

    def test_sell_shares_phrasing_is_negative(self):
        trades = portfolio.parse_whatif_trades("what if I sold 5 shares of JPM", "client-a")
        self.assertEqual(trades, [{"ticker": "JPM", "delta_shares": -5.0}])

    def test_top_holding_double_phrasing(self):
        self._seed_quote("AAPL", 200.0)
        self._seed_quote("JPM", 50.0)
        portfolio.set_holding("client-a", "AAPL", 10)  # $2000, the bigger holding
        portfolio.set_holding("client-a", "JPM", 5)     # $250
        trades = portfolio.parse_whatif_trades("what if I doubled my top holding", "client-a")
        self.assertEqual(trades, [{"ticker": "AAPL", "delta_shares": 10.0}])

    def test_top_holding_halve_phrasing(self):
        self._seed_quote("AAPL", 200.0)
        portfolio.set_holding("client-a", "AAPL", 10)
        trades = portfolio.parse_whatif_trades("what if I trimmed my top holding by half", "client-a")
        self.assertEqual(trades, [{"ticker": "AAPL", "delta_shares": -5.0}])

    def test_unrecognized_phrasing_returns_none(self):
        self.assertIsNone(portfolio.parse_whatif_trades("what if the market crashes", "client-a"))

    def test_top_holding_with_no_priced_holdings_returns_none(self):
        self.assertIsNone(portfolio.parse_whatif_trades("what if I doubled my top holding", "client-empty"))


if __name__ == "__main__":
    unittest.main()
