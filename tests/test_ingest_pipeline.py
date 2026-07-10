import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config
from ingest import pipeline


class CikResolutionTests(unittest.TestCase):
    """resolve_cik() / the on-disk cik_map cache — no live EDGAR calls (mocked)."""

    def setUp(self):
        self._orig_path = config.DYNAMIC_CIK_MAP_PATH
        self._tmpdir = tempfile.TemporaryDirectory()
        config.DYNAMIC_CIK_MAP_PATH = Path(self._tmpdir.name) / "cik_map.json"

    def tearDown(self):
        config.DYNAMIC_CIK_MAP_PATH = self._orig_path
        self._tmpdir.cleanup()

    @patch("ingest.pipeline.download.load_cik_map")
    def test_unknown_ticker_raises_ticker_not_found(self, mock_load):
        mock_load.return_value = {"AAPL": "0000320193"}
        with self.assertRaises(pipeline.IngestError) as ctx:
            pipeline.resolve_cik("NOTAREALTICKER")
        self.assertEqual(ctx.exception.reason, "ticker_not_found")
        # Cache miss -> forced refresh -> still missing -> only 2 calls, not infinite retry.
        self.assertEqual(mock_load.call_count, 2)

    @patch("ingest.pipeline.download.load_cik_map")
    def test_known_ticker_resolves(self, mock_load):
        mock_load.return_value = {"TSLA": "0001318605"}
        self.assertEqual(pipeline.resolve_cik("tsla"), "0001318605")
        self.assertEqual(mock_load.call_count, 1)

    @patch("ingest.pipeline.download.load_cik_map")
    def test_second_call_uses_disk_cache_not_network(self, mock_load):
        mock_load.return_value = {"TSLA": "0001318605"}
        pipeline.resolve_cik("TSLA")
        pipeline.resolve_cik("TSLA")
        self.assertEqual(mock_load.call_count, 1)  # second call hit the fresh on-disk cache


class IngestTickerErrorPathTests(unittest.TestCase):
    """ingest_ticker() surfaces typed errors instead of raw exceptions, before any
    network-heavy embedding/writing happens."""

    def setUp(self):
        self._orig_path = config.DYNAMIC_CIK_MAP_PATH
        self._tmpdir = tempfile.TemporaryDirectory()
        config.DYNAMIC_CIK_MAP_PATH = Path(self._tmpdir.name) / "cik_map.json"

    def tearDown(self):
        config.DYNAMIC_CIK_MAP_PATH = self._orig_path
        self._tmpdir.cleanup()

    @patch("ingest.pipeline.download.load_cik_map")
    def test_unknown_ticker_short_circuits_before_any_fetch(self, mock_load):
        mock_load.return_value = {}
        with self.assertRaises(pipeline.IngestError) as ctx:
            pipeline.ingest_ticker("ZZZZZ")
        self.assertEqual(ctx.exception.reason, "ticker_not_found")

    @patch("ingest.pipeline.download.latest_10k")
    @patch("ingest.pipeline.resolve_cik")
    def test_no_10k_on_file_raises_typed_error(self, mock_resolve, mock_latest):
        mock_resolve.return_value = "0000000001"
        mock_latest.side_effect = RuntimeError("No 10-K found in recent filings for CIK 1")
        with self.assertRaises(pipeline.IngestError) as ctx:
            pipeline.ingest_ticker("FOREIGN20F")
        self.assertEqual(ctx.exception.reason, "no_10k_available")

    @patch("ingest.pipeline.download._get")
    @patch("ingest.pipeline.download.latest_10k")
    @patch("ingest.pipeline.resolve_cik")
    def test_oversized_filing_raises_typed_error(self, mock_resolve, mock_latest, mock_get):
        mock_resolve.return_value = "0000000001"
        mock_latest.return_value = {
            "form": "10-K", "accession": "0000000001-26-000001",
            "accession_nodash": "000000000126000001", "filing_date": "2026-01-01",
            "primary_doc": "doc.htm", "company_name": "Huge Corp",
        }
        mock_get.return_value = b"x" * (config.INGEST_MAX_RAW_MB * 1024 * 1024 + 1)
        with self.assertRaises(pipeline.IngestError) as ctx:
            pipeline.ingest_ticker("HUGE")
        self.assertEqual(ctx.exception.reason, "filing_too_large")


if __name__ == "__main__":
    unittest.main()
