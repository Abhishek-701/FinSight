"""Phase 2 (part 3) — extract XBRL numeric facts from Inline XBRL 10-K filings.

Reads data/raw/{TICKER}.html (already downloaded — no new fetch), parses
ix:nonFraction tags, and writes data/facts.json — a list of typed facts for
consolidated annual periods only.

Design (see DECISIONS.md):
- Uses BeautifulSoup/lxml (existing dependency). No new XBRL library.
- Consolidated = xbrli:context has NO xbrli:segment child (segments carry
  xbrldi:explicitMember inside xbrli:segment).
- Annual period = consolidated duration context, endDate - startDate >= 350 days.
  The two most-recent such contexts per ticker become "annual_recent" / "annual_prior".
  Algorithm is robust to arbitrary context numbering (doesn't assume c-1 = annual).
- value_display: the number as printed in the filing (e.g. "133,050") — already in
  the table's stated unit (millions USD for most line items, dollars/share for EPS).
- value_scaled: float = raw_digits * 10^scale — the absolute value; useful for
  comparisons and reconciliation without needing to know the unit.
- Self-validating reconciliation: warns if a fact's display value cannot be located
  in any chunk for that ticker (signals a parse/chunk alignment gap — not a blocker).

Output: data/facts.json
No bare excepts (G8). No synthetic data (G3).
"""

import json
import re
import warnings
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")  # silence XMLParsedAsHTMLWarning (intentional — same as parse.py)

RAW_DIR = Path("data/raw")
MANIFEST_PATH = Path("data/manifest.json")
CHUNKS_PATH = Path("data/chunks.json")
OUT_PATH = Path("data/facts.json")

_MIN_ANNUAL_DAYS = 350  # distinguish annual (365 days) from quarterly (~90 days)


def _parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        return None


def _build_context_map(soup: BeautifulSoup) -> dict[str, dict]:
    """Parse all xbrli:context elements into a lookup dict keyed by context id.

    Each entry: {type, start, end, instant, consolidated}
    consolidated=True when the context has no xbrli:segment child (company-wide total).
    """
    result: dict[str, dict] = {}
    for ctx in soup.find_all(lambda t: "context" in t.name.lower()):
        ctx_id = ctx.get("id")
        if not ctx_id:
            continue

        # Consolidated = no xbrli:segment (which houses xbrldi:explicitMember for segments)
        consolidated = not bool(ctx.find(lambda t: "segment" in t.name.lower()))

        info: dict = {"consolidated": consolidated}
        start_el = ctx.find(lambda t: t.name.lower().endswith("startdate"))
        end_el = ctx.find(lambda t: t.name.lower().endswith("enddate"))
        instant_el = ctx.find(lambda t: t.name.lower().endswith("instant"))

        if start_el and end_el:
            info["type"] = "duration"
            info["start"] = _parse_date(start_el.get_text())
            info["end"] = _parse_date(end_el.get_text())
        elif instant_el:
            info["type"] = "instant"
            info["instant"] = _parse_date(instant_el.get_text())
        else:
            info["type"] = "unknown"

        result[ctx_id] = info
    return result


def _annual_context_ids(ctx_map: dict[str, dict]) -> tuple[list[str], list[str]]:
    """Return (duration_ids, instant_ids) for consolidated annual periods, most-recent first.

    duration_ids — income statement / CFS facts (duration >= 350 days).
    instant_ids  — balance-sheet facts (instant contexts whose date matches a FY-end date
                   from the duration set, e.g. us-gaap:Assets, us-gaap:StockholdersEquity).
    The two lists are parallel: instant_ids[i] corresponds to the same FY as duration_ids[i].
    """
    dur_candidates = [
        (cid, info) for cid, info in ctx_map.items()
        if info.get("consolidated") and info.get("type") == "duration"
        and info.get("start") and info.get("end")
        and (info["end"] - info["start"]).days >= _MIN_ANNUAL_DAYS
    ]
    dur_candidates.sort(key=lambda x: x[1]["end"], reverse=True)
    dur_ids = [cid for cid, _ in dur_candidates[:3]]

    # FY-end dates from the duration contexts (order preserved for label alignment).
    fy_ends = [ctx_map[cid]["end"] for cid in dur_ids]

    # Consolidated instant contexts keyed by their date.
    inst_by_date: dict = {}
    for cid, info in ctx_map.items():
        if info.get("consolidated") and info.get("type") == "instant" and info.get("instant") in fy_ends:
            inst_by_date[info["instant"]] = cid  # last writer wins; one per date in practice

    # Align to the same FY order as dur_ids so period labels match.
    inst_ids = [inst_by_date[d] for d in fy_ends if d in inst_by_date]
    return dur_ids, inst_ids


def _extract_facts(
    soup: BeautifulSoup,
    ticker: str,
    ctx_map: dict[str, dict],
    dur_ids: list[str],
    inst_ids: list[str],
    filing_date: str,
) -> list[dict]:
    """Extract ix:nonFraction facts for consolidated annual periods.

    Covers both duration contexts (income statement / CFS) and instant contexts
    (balance sheet — Assets, Liabilities, StockholdersEquity, etc.).
    """
    if not dur_ids and not inst_ids:
        return []

    period_labels = ["annual_recent", "annual_prior", "annual_2prior"]
    period_label: dict[str, str] = {}
    for i, cid in enumerate(dur_ids):
        period_label[cid] = period_labels[i]
    for i, cid in enumerate(inst_ids):
        period_label[cid] = period_labels[i]

    facts: list[dict] = []
    for tag in soup.find_all(re.compile(r"nonfraction", re.I)):
        ctx_ref = tag.get("contextref", "")
        if ctx_ref not in period_label:
            continue

        concept = tag.get("name", "")
        if not concept:
            continue

        try:
            scale = int(tag.get("scale", "0"))
        except ValueError:
            scale = 0

        # Get the display text exactly as printed in the filing.
        value_display = tag.get_text().strip().replace("\xa0", " ")
        # Digits-only string for numeric operations and reconciliation search.
        digits_only = re.sub(r"[^\d.]", "", value_display)
        if not digits_only or not re.search(r"\d", digits_only):
            continue  # empty or non-numeric (e.g. replacement chars from encoding errors)

        try:
            value_scaled = float(digits_only) * (10 ** scale)
        except ValueError:
            continue

        ctx_info = ctx_map[ctx_ref]
        if ctx_info.get("type") == "duration":
            period_end = str(ctx_info["end"])
        elif ctx_info.get("type") == "instant":
            period_end = str(ctx_info["instant"])
        else:
            period_end = ""

        facts.append({
            "ticker": ticker,
            "concept": concept,
            "label": period_label[ctx_ref],      # "annual_recent" | "annual_prior" | "annual_2prior"
            "period_end": period_end,             # ISO date string, e.g. "2025-09-27"
            "value_display": value_display,       # as printed in filing, e.g. "133,050" (millions)
            "value_scaled": value_scaled,         # absolute: 133050 * 10^6 = 133,050,000,000
            "unit": tag.get("unitref", ""),       # e.g. "usd", "shares", "usd/shares"
            "scale": scale,                       # from the iXBRL tag
            "context_id": ctx_ref,
            "filing_date": filing_date,
        })

    return facts


def extract_facts_from_html(html: str, ticker: str, filing_date: str) -> list[dict]:
    """Public per-ticker entrypoint: consolidated annual XBRL facts from one filing's HTML.

    Reused by main() (six seed companies) and ingest/pipeline.py (on-demand tickers).
    """
    soup = BeautifulSoup(html, "lxml")
    ctx_map = _build_context_map(soup)
    dur_ids, inst_ids = _annual_context_ids(ctx_map)
    return _extract_facts(soup, ticker, ctx_map, dur_ids, inst_ids, filing_date)


def _reconcile(all_facts: list[dict], chunks: list[dict]) -> None:
    """Cross-check every extracted fact against the RAG chunk corpus.

    For each fact, search all chunks of the same ticker for the display value.
    A miss means the number is in XBRL but not in any chunk — typically a
    table-splitting artifact or a value that only appears in XBRL metadata.
    Misses are printed as WARNINGs (not fatal — XBRL is the authoritative source).
    """
    # Group chunk text by ticker for fast lookup.
    by_ticker: dict[str, list[str]] = {}
    for c in chunks:
        by_ticker.setdefault(c["ticker"], []).append(c["text"])

    misses: list[str] = []
    for f in all_facts:
        ticker_texts = by_ticker.get(f["ticker"], [])
        # Search for both the comma-formatted display (e.g. "133,050") and
        # the stripped form (e.g. "133050") to handle chunk formatting variation.
        stripped = re.sub(r"[,\s]", "", f["value_display"])
        found = any(
            f["value_display"] in t or stripped in t
            for t in ticker_texts
        )
        if not found:
            misses.append(
                f"  {f['ticker']} {f['concept']} ({f['label']}) = {f['value_display']}"
            )

    if misses:
        print(f"\nWARNING: {len(misses)} fact(s) not matched in chunks (possible parse gap):")
        for m in misses[:20]:  # cap output — JPM has many facts
            print(m)
        if len(misses) > 20:
            print(f"  ... and {len(misses) - 20} more")
    else:
        print("\nReconciliation OK — all extracted facts matched in at least one chunk. ✓")


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())
    chunks = json.loads(CHUNKS_PATH.read_text()) if CHUNKS_PATH.exists() else []

    all_facts: list[dict] = []

    for entry in manifest:
        ticker = entry["ticker"]
        filing_date = entry["filing_date"]
        html_path = Path(entry["raw_path"])
        print(f"\n{ticker}: {html_path.name}")

        html = html_path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html, "lxml")

        ctx_map = _build_context_map(soup)
        dur_ids, inst_ids = _annual_context_ids(ctx_map)

        print(f"  Duration contexts ({len(dur_ids)}):")
        for cid in dur_ids:
            info = ctx_map[cid]
            print(f"    {cid}: {info.get('start')} to {info.get('end')} "
                  f"({(info['end'] - info['start']).days} days)")
        print(f"  Balance-sheet instant contexts ({len(inst_ids)}): {inst_ids}")

        facts = _extract_facts(soup, ticker, ctx_map, dur_ids, inst_ids, filing_date)
        print(f"  Extracted {len(facts)} consolidated annual facts")
        all_facts.extend(facts)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(all_facts, indent=2))
    print(f"\nWrote {len(all_facts)} total facts -> {OUT_PATH}")

    if chunks:
        _reconcile(all_facts, chunks)
    else:
        print("(chunks.json not found — skipping reconciliation)")


if __name__ == "__main__":
    main()
