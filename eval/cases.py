"""Load schema-driven eval cases from eval/cases/*.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml

CASES_DIR = Path(__file__).resolve().parent / "cases"


def load_cases(
    tags: set[str] | None = None,
    ids: set[str] | None = None,
    cases_dir: Path | None = None,
) -> list[dict]:
    directory = cases_dir or CASES_DIR
    if not directory.exists():
        return []
    cases: list[dict] = []
    seen: set[str] = set()
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not raw:
            continue
        items = raw["cases"] if isinstance(raw, dict) and "cases" in raw else raw
        for item in items:
            cid = item.get("id")
            if not cid:
                raise ValueError(f"{path.name}: case missing id")
            if cid in seen:
                raise ValueError(f"duplicate case id: {cid}")
            seen.add(cid)
            item["_source"] = path.name
            cases.append(item)
    if ids:
        cases = [c for c in cases if c["id"] in ids]
    if tags:
        cases = [c for c in cases if tags.issubset(set(c.get("tags") or []))]
    return cases
