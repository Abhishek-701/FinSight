"""Async orchestration for on-demand ingest jobs (V4.1b).

One ingest at a time — INGEST_MAX_CONCURRENT=1 is non-negotiable at the 512MB deploy RAM
ceiling — run on a background thread so FastAPI's event loop stays free to serve chat/quote
requests while a filing parses/embeds. Job state is in-process (matches the rest of the app's
free-tier-friendly in-memory caches, e.g. app.tools.market's TTL caches): a redeploy loses
in-flight job state, which is fine since ingestion is idempotent and re-startable.

Eviction: before starting a new ingest, if the dynamic universe is at capacity
(config.UNIVERSE_MAX_DYNAMIC), the least-recently-used dynamic company (app.universe.
least_recently_used_dynamic_ticker, tracked via router.route()'s touch_ticker calls) is evicted
to make room. Seeds are never evicted — eviction only ever touches the dynamic registry.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Any

from app import config, universe
from ingest.pipeline import IngestError, ingest_ticker

_executor = ThreadPoolExecutor(max_workers=1)
_semaphore = threading.Semaphore(config.INGEST_MAX_CONCURRENT)
_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}  # ticker -> job state, in-process only


def get_job(ticker: str) -> dict | None:
    with _lock:
        job = _jobs.get(ticker.upper())
        return dict(job) if job is not None else None


def start_ingest(ticker: str) -> dict:
    """Idempotent: a double-click or two concurrent requests for the same ticker dedupe into
    the one in-flight job instead of starting a second ingest."""
    ticker = ticker.upper()
    with _lock:
        existing = _jobs.get(ticker)
        if existing and existing["status"] in ("queued", "running"):
            return dict(existing)
        job = {
            "ticker": ticker, "status": "queued", "stage": None, "pct": 0.0,
            "error": None, "result": None, "started_at": time.time(),
        }
        _jobs[ticker] = job
    _executor.submit(_run, ticker)
    return dict(job)


def _make_progress(ticker: str):
    def progress(stage: str, pct: float) -> None:
        with _lock:
            job = _jobs.get(ticker)
            if job is not None:
                job["stage"], job["pct"] = stage, pct
    return progress


def _evict_if_at_capacity() -> None:
    dynamic_count = len(universe.active_companies()) - len(config.COMPANIES)
    if dynamic_count < config.UNIVERSE_MAX_DYNAMIC:
        return
    lru = universe.least_recently_used_dynamic_ticker()
    if lru is not None:
        universe.evict_ticker(lru)


def _run(ticker: str) -> None:
    with _semaphore:
        with _lock:
            _jobs[ticker]["status"] = "running"
        try:
            _evict_if_at_capacity()
            result = ingest_ticker(ticker, progress=_make_progress(ticker))
            with _lock:
                _jobs[ticker].update(
                    status="done", stage="done", pct=1.0, result=asdict(result)
                )
        except IngestError as exc:
            with _lock:
                _jobs[ticker].update(
                    status="error", error={"reason": exc.reason, "message": str(exc)}
                )
        except Exception as exc:  # noqa: BLE001 - job boundary must not crash the executor thread
            with _lock:
                _jobs[ticker].update(
                    status="error", error={"reason": "internal_error", "message": str(exc)}
                )
