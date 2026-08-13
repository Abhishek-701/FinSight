"""Period routing: quarter vs YTD vs FY. No network, no LLM."""

import unittest
from datetime import date
from unittest.mock import patch

from app import research
from ingest import download
from ingest.chunk import chunk_filing
from ingest.xbrl import _quarter_context_ids, _ytd_context_ids


class FilingPeriodTests(unittest.TestCase):
    def test_last_quarter_is_quarter_recent(self):
        self.assertEqual(
            research.filing_period("What was Apple's revenue last quarter?"),
            "quarter_recent",
        )
        self.assertEqual(research.prefer_form("What was Apple's revenue last quarter?"), "10-Q")

    def test_fiscal_year_stays_annual(self):
        self.assertEqual(
            research.filing_period("What was Apple's total operating income for fiscal year 2025?"),
            "annual_recent",
        )
        self.assertIsNone(research.prefer_form(
            "What was Apple's total operating income for fiscal year 2025?",
        ))

    def test_ytd_intent(self):
        self.assertEqual(
            research.filing_period("What was NVIDIA's revenue year to date?"),
            "ytd_recent",
        )

    def test_10q_token(self):
        self.assertEqual(research.filing_period("Summarize Apple's latest 10-Q"), "quarter_recent")


class XbrlPeriodBucketTests(unittest.TestCase):
    def test_quarter_vs_ytd_vs_annual_split(self):
        ctx = {
            "q": {"consolidated": True, "type": "duration",
                  "start": date(2025, 10, 1), "end": date(2025, 12, 31)},  # 91 days
            "ytd": {"consolidated": True, "type": "duration",
                    "start": date(2025, 1, 1), "end": date(2025, 12, 31)},  # 364 days? 364 >= 350 annual
            "ytd6": {"consolidated": True, "type": "duration",
                     "start": date(2025, 1, 1), "end": date(2025, 6, 30)},  # ~180 days
            "fy": {"consolidated": True, "type": "duration",
                   "start": date(2025, 1, 1), "end": date(2025, 12, 31)},
            "seg": {"consolidated": False, "type": "duration",
                    "start": date(2025, 10, 1), "end": date(2025, 12, 31)},
        }
        q_dur, _ = _quarter_context_ids(ctx)
        self.assertEqual(q_dur, ["q"])
        y_dur, _ = _ytd_context_ids(ctx)
        self.assertEqual(y_dur, ["ytd6"])


class ChunkFormTests(unittest.TestCase):
    def test_10q_chunk_ids_are_namespaced(self):
        blocks = [{"kind": "prose", "item": "Item 1", "section_title": "Financials",
                   "text": "Revenue was 100."}]
        meta = {"form": "10-Q", "accession": "000-1", "filing_date": "2026-02-01"}
        chunks = chunk_filing("AAPL", blocks, meta)
        self.assertTrue(chunks)
        self.assertTrue(chunks[0]["chunk_id"].startswith("AAPL-10Q-"))
        self.assertEqual(chunks[0]["form"], "10-Q")

    def test_10k_chunk_ids_unchanged(self):
        blocks = [{"kind": "prose", "item": "Item 8", "section_title": "Financials",
                   "text": "Revenue was 100."}]
        meta = {"form": "10-K", "accession": "000-1", "filing_date": "2025-10-31"}
        chunks = chunk_filing("AAPL", blocks, meta)
        self.assertTrue(chunks[0]["chunk_id"].startswith("AAPL-0"))
        self.assertEqual(chunks[0]["form"], "10-K")


class LatestFormTests(unittest.TestCase):
    @patch("ingest.download._get")
    def test_exact_form_skips_amendments(self, mock_get):
        mock_get.return_value = b"""{
            "name": "Apple Inc.",
            "filings": {"recent": {
                "form": ["10-K/A", "10-Q", "10-K"],
                "accessionNumber": ["a", "b", "c"],
                "filingDate": ["2026-01-01", "2026-05-02", "2025-10-31"],
                "primaryDocument": ["amd.htm", "q.htm", "k.htm"]
            }}
        }"""
        q = download.latest_form("0000320193", "10-Q")
        self.assertEqual(q["form"], "10-Q")
        self.assertEqual(q["accession"], "b")
        k = download.latest_form("0000320193", "10-K")
        self.assertEqual(k["form"], "10-K")
        self.assertEqual(k["accession"], "c")


class FilingStemTests(unittest.TestCase):
    def test_10k_keeps_ticker_name(self):
        self.assertEqual(download.filing_stem("AAPL", "10-K"), "AAPL")

    def test_10q_is_namespaced(self):
        self.assertEqual(download.filing_stem("AAPL", "10-Q"), "AAPL-10Q")


if __name__ == "__main__":
    unittest.main()
