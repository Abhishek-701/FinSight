import unittest
from unittest.mock import patch

from app import config, insight
from app.tools import market, registry


class InsightBriefDataTests(unittest.TestCase):
    def tearDown(self):
        market._QUOTE_CACHE.pop("AAPL", None)
        market._HISTORY_CACHE.pop(("AAPL", config.INSIGHT_HISTORY_PERIOD), None)

    def test_build_brief_data_offline_with_seeded_market_cache(self):
        market._QUOTE_CACHE["AAPL"] = {
            "ticker": "AAPL", "company": "Apple", "price": 200.0, "previous_close": 198.0,
            "change": 2.0, "change_percent": 1.01, "market_cap": 3_100_000_000_000.0,
            "currency": "USD", "source": "yfinance", "as_of": "2026-07-08T00:00:00+00:00",
            "disclaimer": config.MARKET_DISCLAIMER,
        }
        market._HISTORY_CACHE[("AAPL", config.INSIGHT_HISTORY_PERIOD)] = {
            "ticker": "AAPL", "company": "Apple", "period": config.INSIGHT_HISTORY_PERIOD,
            "rows": [
                {"date": "2026-04-08", "open": 190.0, "high": 192.0, "low": 189.0, "close": 190.0, "volume": 100},
                {"date": "2026-07-08", "open": 199.0, "high": 201.0, "low": 198.0, "close": 200.0, "volume": 100},
            ],
            "source": "yfinance", "as_of": "2026-07-08T00:00:00+00:00", "disclaimer": config.MARKET_DISCLAIMER,
        }

        data = insight.build_brief_data("AAPL")

        self.assertEqual(data["market_status"], "ok")
        self.assertIn("pe_ratio", data["valuation"])
        self.assertIn("ps_ratio", data["valuation"])
        self.assertIn("price_change", data["valuation"])
        self.assertAlmostEqual(data["valuation"]["price_change"]["value"], (200.0 - 190.0) / 190.0 * 100)

        ids = [c["chunk_id"] for c in data["evidence"]]
        self.assertTrue(any("-MKT-" in cid for cid in ids), ids)
        self.assertTrue(any("-XBRL-" in cid for cid in ids), ids)
        self.assertTrue(any("-CALC-" in cid for cid in ids), ids)
        self.assertIsNotNone(data["fundamentals"]["operating_margin"])
        self.assertIn("operating_margin", data["ranks"])

    def test_build_brief_data_degrades_without_market(self):
        with patch("app.tools.market.get_provider", side_effect=RuntimeError("no network")):
            data = insight.build_brief_data("AAPL")

        self.assertEqual(data["market_status"], "unavailable")
        self.assertEqual(data["valuation"], {})
        self.assertIsNone(data["quote"])
        self.assertIsNotNone(data["fundamentals"]["operating_margin"])
        self.assertIn("operating_margin", data["ranks"])


class InsightToolTests(unittest.TestCase):
    def tearDown(self):
        market._QUOTE_CACHE.pop("AAPL", None)
        market._HISTORY_CACHE.pop(("AAPL", config.INSIGHT_HISTORY_PERIOD), None)

    def test_company_insight_tool_registered(self):
        self.assertIn("company_insight", registry.TOOL_REGISTRY)
        self.assertEqual(registry.TOOL_REGISTRY["company_insight"].arg_spec["ticker"], list(config.COMPANIES))

    def test_company_insight_missing_ticker(self):
        result = insight.company_insight(ticker=None, route={"tickers": []})
        self.assertEqual(result["status"], "missing_ticker")

    def test_company_insight_returns_valuation_and_ranks(self):
        with patch("app.tools.market.get_provider", side_effect=RuntimeError("no network")):
            result = insight.company_insight(ticker="AAPL")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["market_status"], "unavailable")
        self.assertIn("ranks", result["data"])


if __name__ == "__main__":
    unittest.main()
