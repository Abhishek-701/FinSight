import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config, universe


class UniverseSeedOnlyTests(unittest.TestCase):
    """No data/dynamic/registry.json present -> identical to config.COMPANIES/ALIASES."""

    def setUp(self):
        self._orig_path = config.DYNAMIC_REGISTRY_PATH
        self._tmpdir = tempfile.TemporaryDirectory()
        config.DYNAMIC_REGISTRY_PATH = Path(self._tmpdir.name) / "does_not_exist.json"

    def tearDown(self):
        config.DYNAMIC_REGISTRY_PATH = self._orig_path
        self._tmpdir.cleanup()

    def test_active_companies_matches_seeds(self):
        self.assertEqual(universe.active_companies(), config.COMPANIES)

    def test_active_tickers_matches_seeds(self):
        self.assertEqual(sorted(universe.active_tickers()), sorted(config.COMPANIES))

    def test_aliases_matches_seeds(self):
        self.assertEqual(universe.aliases(), config.ALIASES)

    def test_is_ingested_true_for_seed(self):
        self.assertTrue(universe.is_ingested("AAPL"))

    def test_is_ingested_false_for_unknown(self):
        self.assertFalse(universe.is_ingested("TSLA"))

    def test_company_name_known(self):
        self.assertEqual(universe.company_name("aapl"), "Apple")

    def test_company_name_unknown_falls_back_to_ticker(self):
        self.assertEqual(universe.company_name("tsla"), "TSLA")


class UniverseDynamicMergeTests(unittest.TestCase):
    """A populated data/dynamic/registry.json unions with the seeds."""

    def setUp(self):
        self._orig_path = config.DYNAMIC_REGISTRY_PATH
        self._tmpdir = tempfile.TemporaryDirectory()
        registry_path = Path(self._tmpdir.name) / "registry.json"
        registry_path.write_text(
            json.dumps({"TSLA": {"name": "Tesla", "cik": "0001318605"}}), encoding="utf-8"
        )
        config.DYNAMIC_REGISTRY_PATH = registry_path

    def tearDown(self):
        config.DYNAMIC_REGISTRY_PATH = self._orig_path
        self._tmpdir.cleanup()

    def test_active_companies_includes_dynamic(self):
        companies = universe.active_companies()
        self.assertEqual(companies["TSLA"], "Tesla")
        self.assertEqual(companies["AAPL"], "Apple")  # seeds still present

    def test_aliases_includes_dynamic_ticker_and_name(self):
        aliases = universe.aliases()
        self.assertEqual(aliases["tsla"], "TSLA")
        self.assertEqual(aliases["tesla"], "TSLA")

    def test_is_ingested_true_for_dynamic(self):
        self.assertTrue(universe.is_ingested("tsla"))

    def test_company_name_dynamic(self):
        self.assertEqual(universe.company_name("TSLA"), "Tesla")


class RegistryMutationTests(unittest.TestCase):
    """register_ticker / touch_ticker / least_recently_used_dynamic_ticker / evict_ticker."""

    def setUp(self):
        self._orig_registry = config.DYNAMIC_REGISTRY_PATH
        self._orig_chunks_dir = config.DYNAMIC_CHUNKS_DIR
        self._orig_facts_dir = config.DYNAMIC_FACTS_DIR
        self._tmpdir = tempfile.TemporaryDirectory()
        base = Path(self._tmpdir.name)
        config.DYNAMIC_REGISTRY_PATH = base / "registry.json"
        config.DYNAMIC_CHUNKS_DIR = base / "chunks"
        config.DYNAMIC_FACTS_DIR = base / "facts"
        config.DYNAMIC_CHUNKS_DIR.mkdir()
        config.DYNAMIC_FACTS_DIR.mkdir()

    def tearDown(self):
        config.DYNAMIC_REGISTRY_PATH = self._orig_registry
        config.DYNAMIC_CHUNKS_DIR = self._orig_chunks_dir
        config.DYNAMIC_FACTS_DIR = self._orig_facts_dir
        self._tmpdir.cleanup()

    def test_register_ticker_writes_entry(self):
        universe.register_ticker("TSLA", {"name": "Tesla, Inc.", "last_used_at": "2026-01-01T00:00:00+00:00"})
        self.assertEqual(universe.active_companies()["TSLA"], "Tesla")

    def test_touch_ticker_bumps_last_used_at(self):
        universe.register_ticker("TSLA", {"name": "Tesla, Inc.", "last_used_at": "2026-01-01T00:00:00+00:00"})
        universe.touch_ticker("TSLA")
        registry = json.loads(config.DYNAMIC_REGISTRY_PATH.read_text(encoding="utf-8"))
        self.assertGreater(registry["TSLA"]["last_used_at"], "2026-01-01T00:00:00+00:00")

    def test_touch_ticker_is_noop_for_seed(self):
        universe.touch_ticker("AAPL")
        self.assertFalse(config.DYNAMIC_REGISTRY_PATH.exists())  # never wrote a registry file

    def test_touch_ticker_is_noop_for_unregistered_ticker(self):
        universe.touch_ticker("RIVN")
        self.assertFalse(config.DYNAMIC_REGISTRY_PATH.exists())

    def test_least_recently_used_picks_oldest(self):
        universe.register_ticker("TSLA", {"name": "Tesla", "last_used_at": "2026-01-01T00:00:00+00:00"})
        universe.register_ticker("RIVN", {"name": "Rivian", "last_used_at": "2026-03-01T00:00:00+00:00"})
        self.assertEqual(universe.least_recently_used_dynamic_ticker(), "TSLA")

    def test_least_recently_used_none_when_empty(self):
        self.assertIsNone(universe.least_recently_used_dynamic_ticker())

    @patch("app.retrieve.invalidate")
    @patch("app.facts.invalidate")
    def test_evict_ticker_removes_files_and_registry_entry(self, mock_facts_invalidate, mock_retrieve_invalidate):
        universe.register_ticker("TSLA", {"name": "Tesla", "last_used_at": "2026-01-01T00:00:00+00:00"})
        (config.DYNAMIC_CHUNKS_DIR / "TSLA.json").write_text("[]", encoding="utf-8")
        (config.DYNAMIC_FACTS_DIR / "TSLA.json").write_text("[]", encoding="utf-8")

        with patch("chromadb.PersistentClient") as mock_client_cls:
            mock_coll = mock_client_cls.return_value.get_collection.return_value
            universe.evict_ticker("TSLA")
            mock_coll.delete.assert_called_once_with(where={"ticker": "TSLA"})

        self.assertNotIn("TSLA", universe.active_companies())
        self.assertFalse((config.DYNAMIC_CHUNKS_DIR / "TSLA.json").exists())
        self.assertFalse((config.DYNAMIC_FACTS_DIR / "TSLA.json").exists())
        mock_retrieve_invalidate.assert_called_once()
        mock_facts_invalidate.assert_called_once()

    def test_evict_ticker_on_unregistered_ticker_is_a_noop(self):
        with patch("chromadb.PersistentClient") as mock_client_cls:
            universe.evict_ticker("NOPE")
            mock_client_cls.assert_not_called()


class UniverseMalformedRegistryTests(unittest.TestCase):
    """A corrupt registry file degrades to seed-only rather than raising."""

    def setUp(self):
        self._orig_path = config.DYNAMIC_REGISTRY_PATH
        self._tmpdir = tempfile.TemporaryDirectory()
        registry_path = Path(self._tmpdir.name) / "registry.json"
        registry_path.write_text("{not valid json", encoding="utf-8")
        config.DYNAMIC_REGISTRY_PATH = registry_path

    def tearDown(self):
        config.DYNAMIC_REGISTRY_PATH = self._orig_path
        self._tmpdir.cleanup()

    def test_active_companies_falls_back_to_seeds(self):
        self.assertEqual(universe.active_companies(), config.COMPANIES)


class ResolveTickerTests(unittest.TestCase):
    """resolve_ticker() against a mocked EDGAR cik map — no live network calls."""

    def setUp(self):
        self._orig_registry = config.DYNAMIC_REGISTRY_PATH
        self._orig_cik_map = config.DYNAMIC_CIK_MAP_PATH
        self._tmpdir = tempfile.TemporaryDirectory()
        config.DYNAMIC_REGISTRY_PATH = Path(self._tmpdir.name) / "registry_missing.json"
        config.DYNAMIC_CIK_MAP_PATH = Path(self._tmpdir.name) / "cik_map.json"

    def tearDown(self):
        config.DYNAMIC_REGISTRY_PATH = self._orig_registry
        config.DYNAMIC_CIK_MAP_PATH = self._orig_cik_map
        self._tmpdir.cleanup()

    def test_already_known_alias_resolves_without_network(self):
        with patch("ingest.download.load_cik_map") as mock_load:
            result = universe.resolve_ticker("What was Apple's revenue?")
            mock_load.assert_not_called()
        self.assertEqual(result, {"ticker": "AAPL", "cik": None, "ingested": True})

    @patch("ingest.download.load_cik_map")
    def test_uppercase_ticker_token_resolves_via_edgar_map(self, mock_load):
        mock_load.return_value = {"TSLA": "0001318605"}
        result = universe.resolve_ticker("Is TSLA expensive right now?")
        self.assertEqual(result, {"ticker": "TSLA", "cik": "0001318605", "ingested": False})

    @patch("ingest.download.load_cik_map")
    def test_cashtag_resolves(self, mock_load):
        mock_load.return_value = {"TSLA": "0001318605"}
        result = universe.resolve_ticker("What's happening with $TSLA?")
        self.assertEqual(result["ticker"], "TSLA")

    @patch("ingest.download.load_cik_map")
    def test_lowercase_common_word_does_not_false_positive_as_ticker(self, mock_load):
        # "IT" (Gartner) is a real ticker, but lowercase "it" in ordinary prose must not
        # match — the uppercase-token check is case-sensitive against the ORIGINAL text.
        mock_load.return_value = {"IT": "0000749251"}
        result = universe.resolve_ticker("Is it a good time to invest?")
        self.assertIsNone(result)

    @patch("ingest.download.load_cik_map")
    def test_unrecognized_text_returns_none(self, mock_load):
        mock_load.return_value = {"TSLA": "0001318605"}
        result = universe.resolve_ticker("What is the capital of France?")
        self.assertIsNone(result)

    @patch("ingest.download.load_cik_map")
    def test_edgar_failure_returns_none_instead_of_raising(self, mock_load):
        mock_load.side_effect = RuntimeError("EDGAR unreachable")
        result = universe.resolve_ticker("Is TSLA expensive right now?")
        self.assertIsNone(result)


class CikMapMemoryCacheTests(unittest.TestCase):
    """load_cik_map() only hits disk once per process while the file is unchanged/fresh —
    resolve_ticker() runs on the router's hot path, so re-parsing the ~13k-entry EDGAR map
    from disk on every request would be wasteful."""

    def setUp(self):
        self._orig_cik_map = config.DYNAMIC_CIK_MAP_PATH
        self._tmpdir = tempfile.TemporaryDirectory()
        config.DYNAMIC_CIK_MAP_PATH = Path(self._tmpdir.name) / "cik_map.json"
        universe._cik_map_cache = None

    def tearDown(self):
        config.DYNAMIC_CIK_MAP_PATH = self._orig_cik_map
        universe._cik_map_cache = None
        self._tmpdir.cleanup()

    @patch("ingest.download.load_cik_map")
    def test_repeated_calls_read_disk_once(self, mock_load):
        mock_load.return_value = {"TSLA": "0001318605"}
        universe.load_cik_map()  # first call: network fetch + disk write + memory cache
        with patch("pathlib.Path.read_text") as mock_read_text:
            universe.load_cik_map()
            universe.load_cik_map()
            mock_read_text.assert_not_called()  # served from memory, not disk


if __name__ == "__main__":
    unittest.main()
