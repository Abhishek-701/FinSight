import json
import tempfile
import unittest
from pathlib import Path

from app import config, facts, retrieve


class DynamicFactsMergeTests(unittest.TestCase):
    """facts.py merges data/facts.json (seed) with data/dynamic/facts/*.json (V4.1 ingest)."""

    def setUp(self):
        self._orig_dir = config.DYNAMIC_FACTS_DIR
        self._tmpdir = tempfile.TemporaryDirectory()
        config.DYNAMIC_FACTS_DIR = Path(self._tmpdir.name)
        facts.invalidate()

    def tearDown(self):
        config.DYNAMIC_FACTS_DIR = self._orig_dir
        facts.invalidate()
        self._tmpdir.cleanup()

    def test_no_dynamic_dir_falls_back_to_seed_only(self):
        # tmpdir exists but is empty -> no *.json files -> behaves like today.
        result = facts.query("revenue", "AAPL")
        self.assertIsNotNone(result)

    def test_dynamic_fact_file_is_queryable(self):
        dynamic_fact = {
            "ticker": "TSLA", "concept": "us-gaap:Revenues", "label": "annual_recent",
            "value_scaled": 96_000_000_000, "period_end": "2025-12-31", "filing_date": "2026-01-15",
        }
        (Path(config.DYNAMIC_FACTS_DIR) / "TSLA.json").write_text(
            json.dumps([dynamic_fact]), encoding="utf-8"
        )
        facts.invalidate()
        result = facts.query("revenue", "TSLA")
        self.assertIsNotNone(result)
        self.assertEqual(result["value_scaled"], 96_000_000_000)

    def test_invalidate_picks_up_a_file_added_after_first_load(self):
        self.assertIsNone(facts.query("revenue", "RIVN"))  # triggers + caches an empty load
        dynamic_fact = {
            "ticker": "RIVN", "concept": "us-gaap:Revenues", "label": "annual_recent",
            "value_scaled": 4_500_000_000, "period_end": "2025-12-31", "filing_date": "2026-02-01",
        }
        (Path(config.DYNAMIC_FACTS_DIR) / "RIVN.json").write_text(
            json.dumps([dynamic_fact]), encoding="utf-8"
        )
        self.assertIsNone(facts.query("revenue", "RIVN"))  # still cached, pre-invalidate
        facts.invalidate()
        self.assertIsNotNone(facts.query("revenue", "RIVN"))  # fresh load picks up the new file


class DynamicChunksLoaderTests(unittest.TestCase):
    """retrieve._load_dynamic_chunks() reads per-ticker chunk files (no Chroma needed)."""

    def setUp(self):
        self._orig_dir = config.DYNAMIC_CHUNKS_DIR
        self._tmpdir = tempfile.TemporaryDirectory()
        config.DYNAMIC_CHUNKS_DIR = Path(self._tmpdir.name)

    def tearDown(self):
        config.DYNAMIC_CHUNKS_DIR = self._orig_dir
        self._tmpdir.cleanup()

    def test_missing_dir_returns_empty(self):
        config.DYNAMIC_CHUNKS_DIR = Path(self._tmpdir.name) / "nope"
        self.assertEqual(retrieve._load_dynamic_chunks(), [])

    def test_reads_chunk_files_from_directory(self):
        chunk = {"chunk_id": "TSLA-0001", "ticker": "TSLA", "text": "Tesla makes electric vehicles."}
        (Path(config.DYNAMIC_CHUNKS_DIR) / "TSLA.json").write_text(
            json.dumps([chunk]), encoding="utf-8"
        )
        loaded = retrieve._load_dynamic_chunks()
        self.assertEqual(loaded, [chunk])

    def test_malformed_file_is_skipped_not_raised(self):
        (Path(config.DYNAMIC_CHUNKS_DIR) / "BAD.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(retrieve._load_dynamic_chunks(), [])


if __name__ == "__main__":
    unittest.main()
