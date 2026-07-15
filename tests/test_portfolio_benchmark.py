"""V5.2 tests for app.portfolio.benchmark: weighted portfolio-vs-SPY series, all offline via
a mocked app.tools.market.market_history (no live yfinance calls)."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config, portfolio
from app.tools import market


def _history(rows: list[tuple]) -> dict:
    return {
        "status": "ok",
        "data": {"rows": [
            {"date": d, "open": c, "high": c, "low": c, "close": c, "volume": 0} for d, c in rows
        ]},
    }


class PortfolioBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_benchmark.sqlite3"

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        self._tmpdir.cleanup()

    def test_empty_portfolio_returns_no_series(self):
        result = portfolio.benchmark("client-empty", "3mo")
        self.assertIsNone(result["portfolio"])
        self.assertIsNone(result["spy"])

    def test_weighted_series_uses_current_shares_across_common_dates(self):
        portfolio.set_holding("client-a", "AAPL", 10)
        portfolio.set_holding("client-a", "JPM", 5)

        def fake_history(ticker, period="3mo", **_):
            if ticker == "AAPL":
                return _history([("2026-01-01", 100.0), ("2026-01-02", 110.0)])
            if ticker == "JPM":
                return _history([("2026-01-01", 50.0), ("2026-01-02", 40.0)])
            if ticker == "SPY":
                return _history([("2026-01-01", 400.0), ("2026-01-02", 404.0)])
            raise AssertionError(f"unexpected ticker {ticker}")

        with patch("app.portfolio.market.market_quote") as mock_quote, \
             patch("app.portfolio.market.market_history", side_effect=fake_history):
            mock_quote.side_effect = lambda t, **_: {
                "status": "ok",
                "data": {"price": 110.0 if t == "AAPL" else 40.0, "previous_close": 100.0,
                          "change": 0.0, "change_percent": 0.0, "market_cap": 1e9,
                          "currency": "USD", "source": "yfinance",
                          "as_of": "2026-01-02T00:00:00+00:00", "disclaimer": ""},
            }
            result = portfolio.benchmark("client-a", "3mo")

        self.assertEqual(result["holdings_used"], ["AAPL", "JPM"])
        rows = result["portfolio"]
        self.assertEqual(len(rows), 2)
        # day 1: 10*100 + 5*50 = 1250; day 2: 10*110 + 5*40 = 1300
        self.assertAlmostEqual(rows[0]["close"], 1250.0)
        self.assertAlmostEqual(rows[1]["close"], 1300.0)
        self.assertEqual([r["close"] for r in result["spy"]], [400.0, 404.0])

    def test_holding_missing_history_is_excluded_not_fatal(self):
        portfolio.set_holding("client-a", "AAPL", 10)
        portfolio.set_holding("client-a", "ZZZZ", 5)

        def fake_history(ticker, period="3mo", **_):
            if ticker == "AAPL":
                return _history([("2026-01-01", 100.0)])
            if ticker == "SPY":
                return _history([("2026-01-01", 400.0)])
            return {"status": "error", "error": "no_data", "evidence": []}

        with patch("app.portfolio.market.market_quote") as mock_quote, \
             patch("app.portfolio.market.market_history", side_effect=fake_history):
            mock_quote.side_effect = lambda t, **_: (
                {"status": "ok", "data": {"price": 100.0, "previous_close": 100.0, "change": 0.0,
                                          "change_percent": 0.0, "market_cap": 1e9, "currency": "USD",
                                          "source": "yfinance", "as_of": "2026-01-01T00:00:00+00:00",
                                          "disclaimer": ""}}
                if t == "AAPL" else {"status": "error", "error": "no_data", "evidence": []}
            )
            result = portfolio.benchmark("client-a", "3mo")

        self.assertEqual(result["holdings_used"], ["AAPL"])

    def test_period_is_passed_through(self):
        portfolio.set_holding("client-a", "AAPL", 10)
        seen_periods = []

        def fake_history(ticker, period="3mo", **_):
            seen_periods.append(period)
            return _history([("2026-01-01", 100.0)])

        with patch("app.portfolio.market.market_quote") as mock_quote, \
             patch("app.portfolio.market.market_history", side_effect=fake_history):
            mock_quote.return_value = {
                "status": "ok",
                "data": {"price": 100.0, "previous_close": 100.0, "change": 0.0,
                          "change_percent": 0.0, "market_cap": 1e9, "currency": "USD",
                          "source": "yfinance", "as_of": "2026-01-01T00:00:00+00:00", "disclaimer": ""},
            }
            portfolio.benchmark("client-a", "1y")

        self.assertTrue(all(p == "1y" for p in seen_periods))


if __name__ == "__main__":
    unittest.main()
