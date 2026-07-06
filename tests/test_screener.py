import unittest
from unittest.mock import patch

from app import screener


class ScreenerTests(unittest.TestCase):
    def test_snapshot_offline_has_six_rows(self):
        snap = screener.snapshot(include_market=False)
        self.assertEqual(len(snap["rows"]), 6)
        self.assertIsNone(snap["disclaimer"])
        for row in snap["rows"]:
            self.assertEqual(row["market_status"], "skipped")
            self.assertIsNone(row["price"])

    def test_jpm_operating_margin_is_none(self):
        snap = screener.snapshot(include_market=False)
        jpm = next(r for r in snap["rows"] if r["ticker"] == "JPM")
        self.assertIsNone(jpm["operating_margin"])

    def test_all_companies_have_revenue_growth(self):
        snap = screener.snapshot(include_market=False)
        for row in snap["rows"]:
            self.assertIsNotNone(row["revenue_growth_yoy"], row["ticker"])

    def test_rank_puts_none_last_regardless_of_order(self):
        snap = screener.snapshot(include_market=False)
        for order in ("asc", "desc"):
            ranked = screener.rank("operating_margin", order=order, rows=snap["rows"])
            self.assertEqual(ranked[-1]["ticker"], "JPM")
            self.assertIsNone(ranked[-1]["operating_margin"])

    def test_rank_unknown_metric_raises(self):
        with self.assertRaises(ValueError):
            screener.rank("not_a_metric")

    def test_rank_sorts_descending_by_default(self):
        snap = screener.snapshot(include_market=False)
        ranked = screener.rank("net_margin", rows=snap["rows"])
        values = [r["net_margin"] for r in ranked if r["net_margin"] is not None]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_derived_metrics_exact_math(self):
        fake_facts = {
            ("revenue", "AAPL"): {"value_scaled": 1000.0, "concept": "us-gaap:Revenues", "period_end": "2025-01-01"},
            ("operating_income", "AAPL"): {"value_scaled": 300.0, "concept": "us-gaap:OperatingIncomeLoss", "period_end": "2025-01-01"},
            ("net_income", "AAPL"): {"value_scaled": 250.0, "concept": "us-gaap:NetIncomeLoss", "period_end": "2025-01-01"},
            ("equity", "AAPL"): {"value_scaled": 500.0, "concept": "us-gaap:StockholdersEquity", "period_end": "2025-01-01"},
        }

        def fake_query(metric, ticker, period="annual_recent"):
            return fake_facts.get((metric, ticker))

        def fake_query_yoy(metric, ticker):
            return fake_facts.get((metric, ticker)), {"value_scaled": 800.0}

        with patch("app.screener.facts.query", side_effect=fake_query), \
             patch("app.screener.facts.query_yoy", side_effect=fake_query_yoy):
            row = screener._row_for_ticker("AAPL", include_market=False)

        self.assertAlmostEqual(row["operating_margin"], 0.3)
        self.assertAlmostEqual(row["net_margin"], 0.25)
        self.assertAlmostEqual(row["roe"], 0.5)
        self.assertAlmostEqual(row["revenue_growth_yoy"], 0.25)


if __name__ == "__main__":
    unittest.main()
