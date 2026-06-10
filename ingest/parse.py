"""Phase 2 (part 1) — parse a 10-K HTML filing into ordered prose/table blocks.

Design (grounded in inspecting the real EDGAR files; see DECISIONS.md):
  - Real parser (BeautifulSoup + lxml). Drop <style>/<script>/<head> and iXBRL
    metadata nodes (ix:header/ix:hidden/ix:resources/ix:references) and display:none
    nodes. NEVER drop ix:nonFraction/ix:nonNumeric — those wrap the *visible numbers*;
    get_text() flows their content naturally.
  - Document walked as a stream of leaf <div> blocks + <table> blocks, in order. SEC
    filings wrap each line/paragraph in its own leaf div, so this keeps headings isolated.
  - Item-heading detection: a leaf div whose text starts with "Item N." and is NOT inside
    an <a> (kills the table-of-contents links and cross-references "refer to Item 1A").
    Each block is tagged with the nearest preceding such heading. Best-effort, not a tree.
  - Tables: colspan/rowspan expanded into a dense grid, then each data row serialized as a
    self-contained line carrying its compound column header, e.g.
        "Net sales: | Products | September 27, 2025 = 307,003"
    so a number can never drift from its year/segment. Accounting negatives (1,234) -> -1234.
    Layout tables (no numeric cells) are skipped. Units read from the table's own text.
  - Footnotes immediately following a table are co-located into that table's block.

Output: data/parsed/{TICKER}.json — a list of block dicts consumed by chunk.py.
No bare excepts (G8). No synthetic data (G3).
"""

import json
import re
import warnings
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

warnings.filterwarnings("ignore")  # silence XMLParsedAsHTMLWarning (iXBRL parsed as HTML, intentional)

RAW_DIR = Path("data/raw")
OUT_DIR = Path("data/parsed")
MANIFEST_PATH = Path("data/manifest.json")

# Nodes that carry no displayed prose/numbers and must be removed before text extraction.
DROP_TAGS = ["style", "script", "head", "ix:header", "ix:hidden", "ix:resources", "ix:references"]

HEADING_RE = re.compile(r"^Item\s+(\d+[A-Z]?)\.\s*(.*)", re.I)
# A number: optional $, digits with thousands separators, optional decimals, optional %.
NUMBER_RE = re.compile(r"-?\$?\d[\d,]*(?:\.\d+)?%?")
PAREN_NEG_RE = re.compile(r"^\((\$?[\d,]+(?:\.\d+)?)\)$")  # (1,234) -> negative
UNIT_RE = re.compile(r"in (thousands|millions|billions)", re.I)
FOOTNOTE_START_RE = re.compile(r"^\s*(\(\d+\)|\(\w\)|\*+|†|Note\b|\d+\s)")
YEAR_RE = re.compile(r"^(19|20)\d{2}$")
MONTH_RE = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", re.I)


def clean_text(s: str) -> str:
    """Normalize whitespace and nbsp; keep content intact."""
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def normalize_number(cell: str) -> str:
    """Accounting negative (1,234) -> -1234; otherwise return the cell unchanged."""
    m = PAREN_NEG_RE.match(cell.strip())
    if m:
        return "-" + m.group(1).replace(",", "").replace("$", "")
    return cell


def strip_noise(soup: BeautifulSoup) -> None:
    """Remove non-displayed nodes in place. Leaves ix:nonFraction/ix:nonNumeric intact."""
    for tag in soup(DROP_TAGS):
        tag.decompose()
    for node in soup.find_all(style=re.compile(r"display\s*:\s*none", re.I)):
        node.decompose()


def is_heading(div: Tag) -> re.Match | None:
    """Return the Item-heading match if this leaf div is a body heading, else None."""
    if div.find("a"):  # table-of-contents links wrap the item text in <a>
        return None
    text = clean_text(div.get_text(" "))
    if len(text) > 160:  # headings are short; long blocks are prose that merely starts with 'Item'
        return None
    return HEADING_RE.match(text)


def expand_grid(table: Tag) -> list[list[str]]:
    """Expand a <table> into a dense rectangular grid, honoring colspan/rowspan."""
    grid: list[list[str]] = []
    rowspan_carry: dict[int, tuple[int, str]] = {}  # col -> (remaining_rows, text)
    for tr in table.find_all("tr"):
        row: list[str] = []
        col = 0
        # First, place any cells carried down from a rowspan above.
        cells = tr.find_all(["td", "th"], recursive=False) or tr.find_all(["td", "th"])
        ci = 0
        while ci < len(cells) or col in rowspan_carry:
            if col in rowspan_carry:
                remaining, text = rowspan_carry[col]
                row.append(text)
                if remaining - 1 > 0:
                    rowspan_carry[col] = (remaining - 1, text)
                else:
                    del rowspan_carry[col]
                col += 1
                continue
            cell = cells[ci]
            ci += 1
            text = normalize_number(clean_text(cell.get_text(" ")))
            colspan = int(cell.get("colspan", 1) or 1)
            rowspan = int(cell.get("rowspan", 1) or 1)
            for k in range(colspan):
                row.append(text if k == 0 else "")  # colspan duplicates label only in first slot
                if rowspan > 1:
                    rowspan_carry[col] = (rowspan - 1, text if k == 0 else "")
                col += 1
        grid.append(row)
    return grid


def drop_empty_columns(grid: list[list[str]]) -> list[list[str]]:
    """Remove columns that are empty in every row (SEC spacer columns)."""
    if not grid:
        return grid
    width = max(len(r) for r in grid)
    grid = [r + [""] * (width - len(r)) for r in grid]
    keep = [c for c in range(width) if any(r[c].strip() for r in grid)]
    return [[r[c] for c in keep] for r in grid]


def blank_dollar_signs(grid: list[list[str]]) -> list[list[str]]:
    """Blank standalone '$'/'%' marker cells IN PLACE (SEC puts them in their own column).
    Blanking (not removing) keeps every row the same width so columns stay aligned; the
    now-empty marker columns are removed uniformly by drop_empty_columns afterwards."""
    return [["" if c.strip() in ("$", "%") else c for c in row] for row in grid]


def is_number(cell: str) -> bool:
    c = cell.strip()
    return bool(c) and bool(NUMBER_RE.fullmatch(c))


def is_period(cell: str) -> bool:
    """A period/date label that belongs in a column header, not a data value."""
    c = cell.strip()
    return bool(YEAR_RE.match(c) or MONTH_RE.search(c))


def is_magnitude(cell: str) -> bool:
    """A financial value (not a year/date). These are the numbers we align to headers."""
    return is_number(cell) and not is_period(cell)


def serialize_table(table: Tag) -> dict | None:
    """Turn a <table> into a serialized text block + alignment metadata.

    Returns None for layout tables (no numeric cells)."""
    grid = drop_empty_columns(blank_dollar_signs(expand_grid(table)))
    grid = [r for r in grid if any(c.strip() for c in r)]  # drop fully-empty rows
    if not grid:
        return None
    if not any(is_magnitude(c) for row in grid for c in row):
        return None  # layout table (no financial values) — skip so it doesn't pollute retrieval

    # Header zone = leading rows with no *magnitude* cell. Year/date rows (e.g. "2025",
    # "September 27, 2025") are periods, not values, so they stay in the header where they
    # belong — this is what keeps a number bound to its year.
    header_rows: list[list[str]] = []
    for row in grid:
        if any(is_magnitude(c) for c in row):
            break
        header_rows.append(row)
    body_rows = grid[len(header_rows):]

    width = max((len(r) for r in grid), default=0)
    col_header = []
    for c in range(1, width):  # column 0 is the row-label column
        parts = [hr[c] for hr in header_rows if c < len(hr) and hr[c].strip()]
        col_header.append(" ".join(parts))
    n_value_cols = sum(1 for h in col_header if h)

    lines: list[str] = []
    row_value_counts: list[int] = []
    section = ""  # running sub-header label (e.g. "Net sales:")
    for row in body_rows:
        label = row[0].strip() if row else ""
        values = [(i, row[i]) for i in range(1, len(row)) if is_magnitude(row[i])]
        if not values:  # a label-only row inside the body acts as a section header
            if label:
                section = label
            continue
        row_value_counts.append(len(values))
        prefix = f"{section} | " if section else ""
        for ci, val in values:
            col = col_header[ci - 1] if ci - 1 < len(col_header) else ""
            head = f" | {col}" if col else ""
            lines.append(f"{prefix}{label}{head} = {val}")

    return {
        "lines": lines,
        "n_value_cols": n_value_cols,
        "row_value_counts": row_value_counts,
        "raw_text": clean_text(table.get_text(" ")),
    }


def find_units(table: Tag, caption: str = "") -> str:
    """Read units from the table's own text and the caption line just above it
    (e.g. 'in millions', 'except per share'). SEC often puts '(In millions)' in a div
    directly above the table rather than inside it."""
    text = clean_text(table.get_text(" ")) + " " + caption
    bits = []
    m = UNIT_RE.search(text)
    if m:
        bits.append("in " + m.group(1).lower())
    if re.search(r"except per share", text, re.I):
        bits.append("except per share")
    return ", ".join(bits)


def parse_filing(html: str, company: str, meta: dict) -> list[dict]:
    """Walk the document and return ordered prose/table blocks tagged with Item headings."""
    soup = BeautifulSoup(html, "lxml")
    strip_noise(soup)

    cur_item = None
    cur_title = None
    caption = ""  # most recent prose line, used as a units caption for the next table
    blocks: list[dict] = []

    # find_all preserves document order. Skip anything inside a table (the table emits it).
    for el in soup.find_all(["div", "table"]):
        if el.find_parent("table") is not None:
            continue
        if el.name == "table":
            if el.find("table"):  # nested table wrapper: let the inner one be emitted
                continue
            ser = serialize_table(el)
            if ser is None:
                continue
            units = find_units(el, caption)
            header = f"[{company}] {cur_title or ''} (units: {units or 'n/a'})".strip()
            text = header + "\n" + "\n".join(ser["lines"])
            blocks.append({
                "kind": "table", "item": cur_item, "section_title": cur_title,
                "units": units, "text": text,
                "n_value_cols": ser["n_value_cols"],
                "row_value_counts": ser["row_value_counts"],
            })
            continue

        # div. Heading check first (works for nested heading divs too); dedup by item so an
        # outer wrapper div and its inner copy don't both emit (WMT nests its headings).
        match = is_heading(el)
        if match:
            item = "Item " + match.group(1).upper()
            if item != cur_item:
                cur_item = item
                cur_title = clean_text(match.group(2)) or item
                blocks.append({
                    "kind": "heading", "item": cur_item, "section_title": cur_title,
                    "text": f"{cur_item}. {cur_title}",
                })
            continue

        # Prose: leaf divs only (no nested div/table) for line-level granularity.
        if el.find("div") or el.find("table"):
            continue
        text = clean_text(el.get_text(" "))
        if not text:
            continue
        # Co-locate a footnote that immediately follows a table into that table's block.
        if blocks and blocks[-1]["kind"] == "table" and FOOTNOTE_START_RE.match(text) and len(text) < 600:
            blocks[-1]["text"] += "\n[footnote] " + text
            continue
        caption = text
        blocks.append({
            "kind": "prose", "item": cur_item, "section_title": cur_title, "text": text,
        })

    return blocks


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST_PATH.read_text())
    company_of = {m["ticker"]: m for m in manifest}
    names = {"AAPL": "Apple", "JPM": "JPMorgan Chase", "WMT": "Walmart",
             "KO": "Coca-Cola", "NVDA": "NVIDIA", "CAT": "Caterpillar"}

    for ticker, meta in company_of.items():
        html = (RAW_DIR / f"{ticker}.html").read_text(encoding="utf-8", errors="replace")
        blocks = parse_filing(html, names.get(ticker, ticker), meta)
        n_prose = sum(b["kind"] == "prose" for b in blocks)
        n_table = sum(b["kind"] == "table" for b in blocks)
        n_head = sum(b["kind"] == "heading" for b in blocks)
        (OUT_DIR / f"{ticker}.json").write_text(json.dumps(blocks, indent=2))
        print(f"{ticker}: {len(blocks)} blocks  ({n_head} headings, {n_prose} prose, {n_table} tables)")


if __name__ == "__main__":
    main()
