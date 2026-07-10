"""Corpus manifest helpers for freshness and data lineage."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from app import config, universe


def manifest() -> list[dict]:
    path = config._ROOT / "data" / "manifest.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def version() -> str | None:
    items = manifest()
    if not items:
        return None
    payload = json.dumps(items, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def status() -> dict:
    items = manifest()
    return {
        "corpus_version": version(),
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "companies": universe.active_companies(),
        "manifest_count": len(items),
        "chunk_count": _json_count(config.CHUNKS_PATH),
        "facts_count": _json_count(config.FACTS_PATH),
        "facts_present": config.FACTS_PATH.exists(),
        "chroma_present": (config._ROOT / "data" / "chroma").exists(),
        "filings": items,
    }


def _json_count(path) -> int:
    if not path.exists():
        return 0
    return len(json.loads(path.read_text(encoding="utf-8")))
