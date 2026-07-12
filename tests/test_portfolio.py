import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config, portfolio
from app.tools import market


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_portfolio.sqlite3"

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        self._tmpdir.cleanup()

    def test_set_and_list(self):
        items = portfolio.set_holding("client-a", "aapl", 10.5)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["ticker"], "AAPL")
        self.assertEqual(items[0]["company"], "Apple")
        self.assertEqual(items[0]["shares"], 10.5)
        self.assertIsNone(items[0]["cost_basis"])

    def test_set_holding_overwrites_shares(self):
        portfolio.set_holding("client-a", "AAPL", 10)
        items = portfolio.set_holding("client-a", "AAPL", 25)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["shares"], 25)

    def test_set_holding_with_cost_basis(self):
        items = portfolio.set_holding("client-a", "AAPL", 10, cost_basis=150.0)
        self.assertEqual(items[0]["cost_basis"], 150.0)

    def test_cost_basis_overwritten_on_update_like_shares(self):
        portfolio.set_holding("client-a", "AAPL", 10, cost_basis=150.0)
        items = portfolio.set_holding("client-a", "AAPL", 15, cost_basis=160.0)
        self.assertEqual(items[0]["shares"], 15)
        self.assertEqual(items[0]["cost_basis"], 160.0)

    def test_remove(self):
        portfolio.set_holding("client-a", "AAPL", 10)
        portfolio.set_holding("client-a", "JPM", 5)
        items = portfolio.remove("client-a", "AAPL")
        self.assertEqual([i["ticker"] for i in items], ["JPM"])

    def test_client_isolation(self):
        portfolio.set_holding("client-a", "AAPL", 10)
        portfolio.set_holding("client-b", "JPM", 5)
        self.assertEqual([i["ticker"] for i in portfolio.items("client-a")], ["AAPL"])
        self.assertEqual([i["ticker"] for i in portfolio.items("client-b")], ["JPM"])

    def test_malformed_ticker_raises(self):
        for bad in ("", "TOO LONG SPACES", "AAPL;DROP", "12345678901"):
            with self.assertRaises(ValueError):
                portfolio.set_holding("client-a", bad, 10)

    def test_any_real_ticker_accepted_not_just_seeds(self):
        # V4.3: a portfolio can hold any well-formed ticker, not just the six seed/ingested
        # companies — quotes work regardless of filing coverage.
        items = portfolio.set_holding("client-a", "TSLA", 5)
        self.assertEqual(items[0]["ticker"], "TSLA")

    def test_invalid_shares_raise(self):
        for bad in (0, -5, float("nan"), float("inf"), 2e9):
            with self.assertRaises(ValueError):
                portfolio.set_holding("client-a", "AAPL", bad)

    def test_invalid_cost_basis_raises(self):
        for bad in (0, -5, float("nan"), float("inf"), 2e9):
            with self.assertRaises(ValueError):
                portfolio.set_holding("client-a", "AAPL", 10, cost_basis=bad)

    def test_status(self):
        portfolio.set_holding("client-a", "AAPL", 10)
        status = portfolio.status()
        self.assertEqual(status["rows"], 1)

    def test_migration_is_idempotent_across_repeated_connects(self):
        portfolio.set_holding("client-a", "AAPL", 10)
        portfolio.set_holding("client-a", "JPM", 5, cost_basis=100)  # second _connect() call
        items = portfolio.items("client-a")
        self.assertEqual(len(items), 2)


class PortfolioAnalyzeTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_portfolio_analyze.sqlite3"

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        self._tmpdir.cleanup()
        market._QUOTE_CACHE.pop("AAPL", None)
        market._QUOTE_CACHE.pop("JPM", None)
        market._QUOTE_CACHE.pop("KO", None)

    def _seed_quote(self, ticker, price, change, change_percent):
        market._QUOTE_CACHE[ticker] = {
            "ticker": ticker, "company": ticker, "price": price, "previous_close": price - change,
            "change": change, "change_percent": change_percent, "market_cap": price * 1e9,
            "currency": "USD", "source": "yfinance", "as_of": "2026-07-12T00:00:00+00:00",
            "disclaimer": config.MARKET_DISCLAIMER,
        }

    def test_empty_portfolio_returns_zero_value_no_concentration(self):
        result = portfolio.analyze("client-empty")
        self.assertEqual(result["holdings"], [])
        self.assertEqual(result["total_value"], 0.0)
        self.assertIsNone(result["concentration"])

    def test_value_and_weight_computed_from_live_quote(self):
        self._seed_quote("AAPL", 200.0, 2.0, 1.0)
        self._seed_quote("JPM", 100.0, -1.0, -1.0)
        portfolio.set_holding("client-a", "AAPL", 10)   # $2000
        portfolio.set_holding("client-a", "JPM", 10)     # $1000
        result = portfolio.analyze("client-a")
        self.assertEqual(result["total_value"], 3000.0)
        by_ticker = {h["ticker"]: h for h in result["holdings"]}
        self.assertAlmostEqual(by_ticker["AAPL"]["weight"], 2000 / 3000)
        self.assertAlmostEqual(by_ticker["JPM"]["weight"], 1000 / 3000)

    def test_unrealized_pl_only_when_cost_basis_known(self):
        self._seed_quote("AAPL", 200.0, 0.0, 0.0)
        self._seed_quote("JPM", 100.0, 0.0, 0.0)
        portfolio.set_holding("client-a", "AAPL", 10, cost_basis=150.0)  # +500
        portfolio.set_holding("client-a", "JPM", 10)  # no cost basis
        result = portfolio.analyze("client-a")
        by_ticker = {h["ticker"]: h for h in result["holdings"]}
        self.assertEqual(by_ticker["AAPL"]["unrealized_pl"], 500.0)
        self.assertIsNone(by_ticker["JPM"]["unrealized_pl"])
        # Total only sums the known ones — never silently treats missing basis as zero P&L.
        self.assertEqual(result["total_unrealized_pl"], 500.0)

    def test_total_unrealized_pl_none_when_no_holding_has_cost_basis(self):
        self._seed_quote("AAPL", 200.0, 0.0, 0.0)
        portfolio.set_holding("client-a", "AAPL", 10)
        result = portfolio.analyze("client-a")
        self.assertIsNone(result["total_unrealized_pl"])

    def test_day_change_aggregates_dollar_change(self):
        self._seed_quote("AAPL", 200.0, 2.0, 1.0)  # +$2/share * 10 shares = +$20
        portfolio.set_holding("client-a", "AAPL", 10)
        result = portfolio.analyze("client-a")
        self.assertAlmostEqual(result["total_day_change"], 20.0)

    def test_day_change_pct_is_a_fraction_not_a_percentage(self):
        # market.py's change_percent is percentage-scaled (1.0 means "+1.0%"); every other
        # *_pct/weight field on a holding is a 0-1 fraction — analyze() must normalize at the
        # boundary so a formatter doing value*100 doesn't turn +1.0% into +100%.
        self._seed_quote("AAPL", 200.0, 2.0, 1.0)  # yfinance-style: change_percent=1.0 means +1.0%
        portfolio.set_holding("client-a", "AAPL", 10)
        result = portfolio.analyze("client-a")
        self.assertAlmostEqual(result["holdings"][0]["day_change_pct"], 0.01)

    def test_concentration_single_holding_is_100pct_weight_max_hhi(self):
        self._seed_quote("AAPL", 200.0, 0.0, 0.0)
        portfolio.set_holding("client-a", "AAPL", 10)
        result = portfolio.analyze("client-a")
        conc = result["concentration"]
        self.assertEqual(conc["top_ticker"], "AAPL")
        self.assertAlmostEqual(conc["top_weight"], 1.0)
        self.assertAlmostEqual(conc["hhi"], 10000.0)
        self.assertEqual(conc["band"], "concentrated")

    def test_concentration_three_equal_holdings_is_concentrated_band(self):
        self._seed_quote("AAPL", 100.0, 0.0, 0.0)
        self._seed_quote("JPM", 100.0, 0.0, 0.0)
        self._seed_quote("KO", 100.0, 0.0, 0.0)
        portfolio.set_holding("client-a", "AAPL", 10)
        portfolio.set_holding("client-a", "JPM", 10)
        portfolio.set_holding("client-a", "KO", 10)
        result = portfolio.analyze("client-a")
        conc = result["concentration"]
        # Three equal-weight (33.3%) holdings -> HHI = 3 * 33.33^2 ≈ 3333 -> still "concentrated"
        # (>2500) — three holdings alone isn't enough to diversify away the band.
        self.assertAlmostEqual(conc["hhi"], 3333.3, delta=1)
        self.assertEqual(conc["band"], "concentrated")

    def test_concentration_many_equal_holdings_is_diversified_band(self):
        tickers = [f"T{i}" for i in range(8)]  # 8 equal 12.5% holdings -> HHI = 8*12.5^2 = 1250
        for t in tickers:
            self._seed_quote(t, 100.0, 0.0, 0.0)
            portfolio.set_holding("client-a", t, 10)
        result = portfolio.analyze("client-a")
        conc = result["concentration"]
        self.assertAlmostEqual(conc["hhi"], 1250.0, delta=1)
        self.assertEqual(conc["band"], "diversified")
        for t in tickers:
            market._QUOTE_CACHE.pop(t, None)

    def test_holding_with_failed_quote_degrades_gracefully(self):
        # AAPL has a seeded (cache-hit) quote; ZZZZ's market_quote() is mocked to fail the way
        # a genuinely unknown ticker would — analyze() must not raise, just mark it unavailable.
        self._seed_quote("AAPL", 200.0, 0.0, 0.0)
        portfolio.set_holding("client-a", "AAPL", 10)
        portfolio.set_holding("client-a", "ZZZZ", 5)

        real_market_quote = market.market_quote

        def fake_market_quote(ticker, **kwargs):
            if ticker == "ZZZZ":
                return {"status": "error", "error": "market_provider_error:no data", "evidence": []}
            return real_market_quote(ticker, **kwargs)

        with patch("app.portfolio.market.market_quote", side_effect=fake_market_quote):
            result = portfolio.analyze("client-a")

        statuses = {h["ticker"]: h["market_status"] for h in result["holdings"]}
        self.assertEqual(statuses["AAPL"], "ok")
        self.assertEqual(statuses["ZZZZ"], "unavailable")
        # total_value should reflect only the priced holding
        self.assertEqual(result["total_value"], 2000.0)


if __name__ == "__main__":
    unittest.main()
