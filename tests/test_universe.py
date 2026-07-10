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
        self._orig_title_map = config.DYNAMIC_TITLE_MAP_PATH
        self._tmpdir = tempfile.TemporaryDirectory()
        config.DYNAMIC_REGISTRY_PATH = Path(self._tmpdir.name) / "registry_missing.json"
        config.DYNAMIC_CIK_MAP_PATH = Path(self._tmpdir.name) / "cik_map.json"
        config.DYNAMIC_TITLE_MAP_PATH = Path(self._tmpdir.name) / "title_map.json"
        universe._short_name_index_cache = None

    def tearDown(self):
        config.DYNAMIC_REGISTRY_PATH = self._orig_registry
        config.DYNAMIC_CIK_MAP_PATH = self._orig_cik_map
        config.DYNAMIC_TITLE_MAP_PATH = self._orig_title_map
        universe._short_name_index_cache = None
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

    @patch("ingest.download.load_ticker_titles")
    @patch("ingest.download.load_cik_map")
    def test_lowercase_common_word_does_not_false_positive_as_ticker(self, mock_load, mock_titles):
        # "IT" (Gartner) is a real ticker, but lowercase "it" in ordinary prose must not
        # match — the uppercase-token check is case-sensitive against the ORIGINAL text.
        # "Is" (sentence-capitalized) falls to the name-candidate tier but matches no title.
        mock_load.return_value = {"IT": "0000749251"}
        mock_titles.return_value = {"IT": "Gartner, Inc.", "TSLA": "Tesla, Inc."}
        result = universe.resolve_ticker("Is it a good time to invest?")
        self.assertIsNone(result)

    @patch("ingest.download.load_ticker_titles")
    @patch("ingest.download.load_cik_map")
    def test_unrecognized_text_returns_none(self, mock_load, mock_titles):
        mock_load.return_value = {"TSLA": "0001318605"}
        mock_titles.return_value = {"TSLA": "Tesla, Inc."}
        result = universe.resolve_ticker("What is the capital of France?")
        self.assertIsNone(result)

    @patch("ingest.download.load_ticker_titles")
    @patch("ingest.download.load_cik_map")
    def test_name_candidate_resolves_via_short_name_index(self, mock_load, mock_titles):
        # "Palantir" (a company NAME, not a ticker symbol) still resolves — this is the gap
        # that made chat only work for "PLTR" and not "Palantir" before this tier existed.
        mock_load.return_value = {"PLTR": "0001321655"}
        mock_titles.return_value = {"PLTR": "Palantir Technologies Inc."}
        result = universe.resolve_ticker("What was Palantir's revenue last year?")
        self.assertEqual(result, {"ticker": "PLTR", "cik": "0001321655", "ingested": False})

    @patch("ingest.download.load_ticker_titles")
    @patch("ingest.download.load_cik_map")
    def test_leading_capitalized_word_does_not_block_name_match(self, mock_load, mock_titles):
        # _NAME_CANDIDATE_RE greedily grabs adjacent capitalized words, so a sentence-initial
        # "Is" right before the company name becomes one candidate ("Is Rivian") that matches
        # nothing on its own — _sub_phrases must still try "Rivian" alone.
        mock_load.return_value = {"RIVN": "0001874178"}
        mock_titles.return_value = {"RIVN": "Rivian Automotive, Inc. / DE"}
        result = universe.resolve_ticker("Is Rivian a good investment?")
        self.assertEqual(result["ticker"], "RIVN")

    @patch("ingest.download.load_ticker_titles")
    @patch("ingest.download.load_cik_map")
    def test_edgar_failure_returns_none_instead_of_raising(self, mock_load, mock_titles):
        mock_load.side_effect = RuntimeError("EDGAR unreachable")
        mock_titles.side_effect = RuntimeError("EDGAR unreachable")
        result = universe.resolve_ticker("Is TSLA expensive right now?")
        self.assertIsNone(result)

    @patch("ingest.download.load_ticker_titles")
    def test_name_candidate_edgar_failure_returns_none(self, mock_titles):
        mock_titles.side_effect = RuntimeError("EDGAR unreachable")
        result = universe.resolve_ticker("What was Palantir's revenue last year?")
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


class SearchCompaniesTests(unittest.TestCase):
    """search_companies() — free-text name/ticker search, ranked, no live EDGAR calls."""

    def setUp(self):
        self._orig_title_map = config.DYNAMIC_TITLE_MAP_PATH
        self._tmpdir = tempfile.TemporaryDirectory()
        config.DYNAMIC_TITLE_MAP_PATH = Path(self._tmpdir.name) / "title_map.json"
        universe._title_map_cache = None
        self._patcher = patch(
            "ingest.download.load_ticker_titles",
            return_value={
                "TSLA": "Tesla, Inc.", "RIVN": "Rivian Automotive, Inc.",
                "AAPL": "Apple Inc.", "T": "AT&T Inc.",
            },
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        config.DYNAMIC_TITLE_MAP_PATH = self._orig_title_map
        universe._title_map_cache = None
        self._tmpdir.cleanup()

    def test_search_by_company_name(self):
        results = universe.search_companies("tesla")
        self.assertEqual(results[0]["ticker"], "TSLA")
        self.assertEqual(results[0]["name"], "Tesla, Inc.")

    def test_search_by_partial_ticker(self):
        results = universe.search_companies("riv")
        self.assertEqual(results[0]["ticker"], "RIVN")

    def test_exact_ticker_match_ranks_first(self):
        # "t" substring-matches AT&T's name/ticker AND Tesla's title ("Tesla, Inc." has no "t"
        # at start but contains one); exact ticker match "T" (AT&T) must still rank first.
        results = universe.search_companies("t")
        self.assertEqual(results[0]["ticker"], "T")

    def test_no_match_returns_empty_list(self):
        self.assertEqual(universe.search_companies("zzzzznomatch"), [])

    def test_empty_query_returns_empty_list_without_network_call(self):
        with patch("ingest.download.load_ticker_titles") as mock_load:
            self.assertEqual(universe.search_companies(""), [])
            mock_load.assert_not_called()

    def test_results_include_ingested_flag(self):
        results = universe.search_companies("apple")
        self.assertTrue(results[0]["ingested"])  # AAPL is a seed

    def test_edgar_failure_returns_empty_list_not_raise(self):
        self._patcher.stop()
        with patch("ingest.download.load_ticker_titles", side_effect=RuntimeError("down")):
            self.assertEqual(universe.search_companies("tesla"), [])
        self._patcher.start()  # tearDown expects the patcher to still be running


if __name__ == "__main__":
    unittest.main()
