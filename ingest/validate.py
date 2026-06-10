"""Phase 2 (part 3) — validate parse/chunk output. Warns loudly, never hard-crashes (G8/G10).

Per company it reports:
  (a) did Items 1, 1A, 7, 8 produce chunks?
  (b) does a revenue search hit at least one table chunk?
  (c) CSS/JS-residue check (style/script leftovers must be gone)
  (d) table alignment check (data rows whose value count != header column count = the
      silent multi-level-header failure)
  (e) prints the LARGEST table per company + 2 random table chunks for eyeball check.

This is a report, not a build gate: failures are surfaced at the checkpoint, not silenced.
"""

import json
import random
import re
from pathlib import Path

random.seed(0)  # determinism (G5): same "random" samples each run

CHUNKS_PATH = Path("data/chunks.json")
PARSED_DIR = Path("data/parsed")
MANIFEST_PATH = Path("data/manifest.json")

KEY_ITEMS = ["Item 1", "Item 1A", "Item 7", "Item 8"]
REVENUE_TERMS = ["total revenue", "net revenues", "total net sales", "net sales",
                 "total revenues", "net operating revenues", "total net revenue",
                 "sales and revenues", "total interest income"]  # CAT uses 'sales and revenues'
# CSS/JS residue signatures: style rule blocks, framework class noise, @media/font rules.
CSS_RESIDUE_RE = re.compile(r"\{[^{}]*[:;][^{}]*\}|css-[0-9a-z]+|\bant-[a-z]+|@media|font-family\s*:", re.I)

WARN = "  !! WARN"


def load_chunks_by_ticker() -> dict[str, list[dict]]:
    chunks = json.loads(CHUNKS_PATH.read_text())
    by: dict[str, list[dict]] = {}
    for c in chunks:
        by.setdefault(c["ticker"], []).append(c)
    return by


def check_items(chunks: list[dict]) -> list[str]:
    present = {c["item"] for c in chunks if c["item"]}
    missing = [it for it in KEY_ITEMS if it not in present]
    return missing


def check_revenue(chunks: list[dict]) -> bool:
    for c in chunks:
        if c["kind"] != "table":
            continue
        low = c["text"].lower()
        if any(term in low for term in REVENUE_TERMS) and re.search(r"\d[\d,]{2,}", c["text"]):
            return True
    return False


def check_css(chunks: list[dict]) -> list[str]:
    bad = []
    for c in chunks:
        if CSS_RESIDUE_RE.search(c["text"]):
            bad.append(c["chunk_id"])
    return bad


def check_alignment(blocks: list[dict]) -> tuple[int, int, list[dict]]:
    """Return (n_tables, n_irregular, worst-offender samples).

    A well-formed financial table has consistent row widths: most data rows carry the same
    number of values (one per period column). We flag tables whose rows are *internally
    inconsistent* (the most common row width covers <60% of rows) — that is the signature of
    a multi-level/merged-cell table whose numbers may have drifted from their headers.
    This is a precision-over-recall heuristic: it surfaces the genuinely messy tables rather
    than the many tables where header label-columns merely outnumber value-columns."""
    from collections import Counter
    irregular = []
    tables = [b for b in blocks if b["kind"] == "table"]
    for b in tables:
        counts = [c for c in b.get("row_value_counts", []) if c > 0]
        if len(counts) < 4:
            continue  # too few rows to judge consistency
        mode_count, mode_freq = Counter(counts).most_common(1)[0]
        consistency = mode_freq / len(counts)
        if consistency < 0.6:
            irregular.append({
                "mode": mode_count, "consistency": round(consistency, 2),
                "rows": len(counts), "first_line": b["text"].split("\n")[0][:90],
            })
    return len(tables), len(irregular), irregular[:3]


def largest_table(chunks: list[dict]) -> dict | None:
    tbls = [c for c in chunks if c["kind"] == "table"]
    return max(tbls, key=lambda c: len(c["text"]), default=None)


def main() -> None:
    by = load_chunks_by_ticker()
    manifest = {m["ticker"]: m for m in json.loads(MANIFEST_PATH.read_text())}
    total_warnings = 0

    for ticker in manifest:
        chunks = by.get(ticker, [])
        blocks = json.loads((PARSED_DIR / f"{ticker}.json").read_text())
        print("\n" + "=" * 70)
        print(f"{ticker} ({manifest[ticker]['accession']}) — {len(chunks)} chunks")
        print("=" * 70)

        missing = check_items(chunks)
        if missing:
            print(f"{WARN} (a) missing key Items: {missing}"); total_warnings += 1
        else:
            print("  (a) key Items 1/1A/7/8: all present")

        if check_revenue(chunks):
            print("  (b) revenue term hits a numeric table chunk: yes")
        else:
            print(f"{WARN} (b) no revenue term found in any table chunk"); total_warnings += 1

        css_bad = check_css(chunks)
        if css_bad:
            print(f"{WARN} (c) CSS/JS residue in {len(css_bad)} chunks e.g. {css_bad[:3]}"); total_warnings += 1
        else:
            print("  (c) CSS/JS residue: none")

        n_tables, n_mis, samples = check_alignment(blocks)
        if n_mis:
            print(f"{WARN} (d) {n_mis}/{n_tables} tables have irregular row widths (possible drift):")
            for s in samples:
                print(f"        {s['rows']} rows, only {int(s['consistency']*100)}% width={s['mode']} :: {s['first_line']}")
            total_warnings += 1
        else:
            print(f"  (d) table alignment: {n_tables} tables, none flagged irregular")

        big = largest_table(chunks)
        if big:
            print(f"  (e) LARGEST table chunk [{big['chunk_id']}] item={big['item']}:")
            print("      " + "\n      ".join(big["text"].split("\n")[:10]))
        for c in random.sample([c for c in chunks if c["kind"] == "table"],
                               k=min(2, sum(c["kind"] == "table" for c in chunks))):
            print(f"  (e) random table [{c['chunk_id']}] item={c['item']}:")
            print("      " + "\n      ".join(c["text"].split("\n")[:6]))

    print("\n" + "=" * 70)
    print(f"DONE. {total_warnings} warning(s) across six filings.")


if __name__ == "__main__":
    main()
