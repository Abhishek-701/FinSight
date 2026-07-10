import json
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
