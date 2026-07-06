import tempfile
import unittest
from pathlib import Path

from app import config, watchlist


class WatchlistTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config.SESSION_DB_PATH
        config.SESSION_DB_PATH = Path(self._tmpdir.name) / "test_watchlist.sqlite3"

    def tearDown(self):
        config.SESSION_DB_PATH = self._orig_path
        self._tmpdir.cleanup()

    def test_add_and_list(self):
        items = watchlist.add("client-a", "aapl")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["ticker"], "AAPL")
        self.assertEqual(items[0]["company"], "Apple")

    def test_duplicate_add_is_idempotent(self):
        watchlist.add("client-a", "AAPL")
        items = watchlist.add("client-a", "AAPL")
        self.assertEqual(len(items), 1)

    def test_remove(self):
        watchlist.add("client-a", "AAPL")
        watchlist.add("client-a", "JPM")
        items = watchlist.remove("client-a", "AAPL")
        self.assertEqual([i["ticker"] for i in items], ["JPM"])

    def test_client_isolation(self):
        watchlist.add("client-a", "AAPL")
        watchlist.add("client-b", "JPM")
        self.assertEqual([i["ticker"] for i in watchlist.items("client-a")], ["AAPL"])
        self.assertEqual([i["ticker"] for i in watchlist.items("client-b")], ["JPM"])

    def test_unsupported_ticker_raises(self):
        with self.assertRaises(ValueError):
            watchlist.add("client-a", "TSLA")

    def test_status(self):
        watchlist.add("client-a", "AAPL")
        status = watchlist.status()
        self.assertEqual(status["rows"], 1)


if __name__ == "__main__":
    unittest.main()
