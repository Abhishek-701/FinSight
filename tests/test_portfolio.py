import tempfile
import unittest
from pathlib import Path

from app import config, portfolio


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

    def test_set_holding_overwrites_shares(self):
        portfolio.set_holding("client-a", "AAPL", 10)
        items = portfolio.set_holding("client-a", "AAPL", 25)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["shares"], 25)

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

    def test_unsupported_ticker_raises(self):
        with self.assertRaises(ValueError):
            portfolio.set_holding("client-a", "TSLA", 10)

    def test_invalid_shares_raise(self):
        for bad in (0, -5, float("nan"), float("inf"), 2e9):
            with self.assertRaises(ValueError):
                portfolio.set_holding("client-a", "AAPL", bad)

    def test_status(self):
        portfolio.set_holding("client-a", "AAPL", 10)
        status = portfolio.status()
        self.assertEqual(status["rows"], 1)


if __name__ == "__main__":
    unittest.main()
