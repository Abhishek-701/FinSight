"""Offline tests for the V4.1b ingest/resolve endpoints — ingest_jobs and universe are mocked
so this suite never touches the network, Chroma, or a real EDGAR ticker map. Live end-to-end
behavior (real ingest through these same endpoints) was verified manually; see commit history.
"""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class StartIngestEndpointTests(unittest.TestCase):
    @patch("app.main.universe.is_ingested", return_value=True)
    def test_already_ingested_short_circuits_without_starting_job(self, mock_ingested):
        with patch("app.main.ingest_jobs.start_ingest") as mock_start:
            resp = client.post("/api/companies/AAPL/ingest")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "already_ingested", "job": None})
        mock_start.assert_not_called()

    @patch("app.main.universe.is_ingested", return_value=False)
    @patch("app.main.ingest_jobs.start_ingest")
    def test_new_ticker_starts_job(self, mock_start, mock_ingested):
        mock_start.return_value = {
            "ticker": "TSLA", "status": "queued", "stage": None, "pct": 0.0,
            "error": None, "result": None,
        }
        resp = client.post("/api/companies/tsla/ingest")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "queued")
        mock_start.assert_called_once_with("TSLA")


class IngestStatusEndpointTests(unittest.TestCase):
    @patch("app.main.ingest_jobs.get_job")
    def test_running_job_returns_snapshot(self, mock_get_job):
        mock_get_job.return_value = {
            "ticker": "TSLA", "status": "running", "stage": "parsing", "pct": 0.3,
            "error": None, "result": None,
        }
        resp = client.get("/api/companies/TSLA/ingest/status")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "running")

    @patch("app.main.universe.is_ingested", return_value=True)
    @patch("app.main.ingest_jobs.get_job", return_value=None)
    def test_no_job_but_already_ingested(self, mock_get_job, mock_ingested):
        resp = client.get("/api/companies/AAPL/ingest/status")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "already_ingested", "job": None})

    @patch("app.main.universe.is_ingested", return_value=False)
    @patch("app.main.ingest_jobs.get_job", return_value=None)
    def test_no_job_and_never_ingested_returns_404(self, mock_get_job, mock_ingested):
        resp = client.get("/api/companies/ZZZZZ/ingest/status")
        self.assertEqual(resp.status_code, 404)


class UniverseResolveEndpointTests(unittest.TestCase):
    @patch("app.main.universe.resolve_ticker")
    def test_resolvable_ticker_returns_200(self, mock_resolve):
        mock_resolve.return_value = {"ticker": "TSLA", "cik": "0001318605", "ingested": False}
        resp = client.get("/api/universe/resolve?q=TSLA")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["ticker"], "TSLA")
        self.assertEqual(body["ingested"], False)

    @patch("app.main.universe.resolve_ticker", return_value=None)
    def test_unresolvable_returns_404(self, mock_resolve):
        resp = client.get("/api/universe/resolve?q=NOTATICKER")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
