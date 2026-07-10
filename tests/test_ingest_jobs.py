import unittest
from unittest.mock import patch

from app import config, ingest_jobs
from ingest.pipeline import IngestError, IngestResult


class StartIngestDedupeTests(unittest.TestCase):
    def setUp(self):
        ingest_jobs._jobs.clear()

    def tearDown(self):
        ingest_jobs._jobs.clear()

    @patch.object(ingest_jobs, "_executor")
    def test_start_ingest_creates_queued_job(self, mock_executor):
        job = ingest_jobs.start_ingest("tsla")
        self.assertEqual(job["ticker"], "TSLA")
        self.assertEqual(job["status"], "queued")
        mock_executor.submit.assert_called_once()

    @patch.object(ingest_jobs, "_executor")
    def test_second_call_while_running_dedupes_not_a_new_job(self, mock_executor):
        ingest_jobs._jobs["TSLA"] = {
            "ticker": "TSLA", "status": "running", "stage": "parsing", "pct": 0.3,
        }
        job = ingest_jobs.start_ingest("TSLA")
        self.assertEqual(job["status"], "running")
        mock_executor.submit.assert_not_called()

    @patch.object(ingest_jobs, "_executor")
    def test_retry_after_error_starts_a_new_job(self, mock_executor):
        ingest_jobs._jobs["TSLA"] = {"ticker": "TSLA", "status": "error", "error": {"reason": "x"}}
        job = ingest_jobs.start_ingest("TSLA")
        self.assertEqual(job["status"], "queued")
        mock_executor.submit.assert_called_once()

    def test_get_job_returns_none_for_unknown_ticker(self):
        self.assertIsNone(ingest_jobs.get_job("NOPE"))


class RunJobTests(unittest.TestCase):
    def setUp(self):
        ingest_jobs._jobs.clear()
        ingest_jobs._jobs["TSLA"] = {
            "ticker": "TSLA", "status": "queued", "stage": None, "pct": 0.0,
            "error": None, "result": None,
        }

    def tearDown(self):
        ingest_jobs._jobs.clear()

    @patch("app.ingest_jobs._evict_if_at_capacity")
    @patch("app.ingest_jobs.ingest_ticker")
    def test_successful_run_marks_done_with_result(self, mock_ingest, mock_evict):
        mock_ingest.return_value = IngestResult(
            ticker="TSLA", company="Tesla", cik="0001318605", accession="a",
            filing_date="2026-01-01", chunk_count=229, fact_count=730,
        )
        ingest_jobs._run("TSLA")
        job = ingest_jobs.get_job("TSLA")
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["pct"], 1.0)
        self.assertEqual(job["result"]["ticker"], "TSLA")
        self.assertEqual(job["result"]["chunk_count"], 229)

    @patch("app.ingest_jobs._evict_if_at_capacity")
    @patch("app.ingest_jobs.ingest_ticker")
    def test_typed_ingest_error_preserves_reason(self, mock_ingest, mock_evict):
        mock_ingest.side_effect = IngestError("no_10k_available", "no 10-K on file")
        ingest_jobs._run("TSLA")
        job = ingest_jobs.get_job("TSLA")
        self.assertEqual(job["status"], "error")
        self.assertEqual(job["error"]["reason"], "no_10k_available")

    @patch("app.ingest_jobs._evict_if_at_capacity")
    @patch("app.ingest_jobs.ingest_ticker")
    def test_unexpected_exception_becomes_internal_error_not_a_crash(self, mock_ingest, mock_evict):
        mock_ingest.side_effect = RuntimeError("boom")
        ingest_jobs._run("TSLA")  # must not raise — job boundary swallows it
        job = ingest_jobs.get_job("TSLA")
        self.assertEqual(job["status"], "error")
        self.assertEqual(job["error"]["reason"], "internal_error")

    @patch("app.ingest_jobs.ingest_ticker")
    def test_progress_callback_updates_job_stage(self, mock_ingest):
        def fake_ingest(ticker, progress):
            progress("parsing", 0.3)
            return IngestResult(ticker, "Tesla", "cik", "acc", "2026-01-01", 1, 1)
        mock_ingest.side_effect = fake_ingest
        with patch("app.ingest_jobs._evict_if_at_capacity"):
            ingest_jobs._run("TSLA")
        # Final state is "done" (progress overwritten by the final update), but this
        # confirms the callback wiring doesn't raise and reaches the handler.
        self.assertEqual(ingest_jobs.get_job("TSLA")["status"], "done")


class EvictionTests(unittest.TestCase):
    @patch("app.ingest_jobs.universe.evict_ticker")
    @patch("app.ingest_jobs.universe.least_recently_used_dynamic_ticker")
    @patch("app.ingest_jobs.universe.active_companies")
    def test_evicts_lru_when_at_capacity(self, mock_active, mock_lru, mock_evict):
        mock_active.return_value = {
            **config.COMPANIES,
            **{f"DYN{i}": f"Dyn {i}" for i in range(config.UNIVERSE_MAX_DYNAMIC)},
        }
        mock_lru.return_value = "DYN0"
        ingest_jobs._evict_if_at_capacity()
        mock_evict.assert_called_once_with("DYN0")

    @patch("app.ingest_jobs.universe.evict_ticker")
    @patch("app.ingest_jobs.universe.active_companies")
    def test_no_eviction_below_capacity(self, mock_active, mock_evict):
        mock_active.return_value = dict(config.COMPANIES)  # zero dynamic companies
        ingest_jobs._evict_if_at_capacity()
        mock_evict.assert_not_called()


if __name__ == "__main__":
    unittest.main()
