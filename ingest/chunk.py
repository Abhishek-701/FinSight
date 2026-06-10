"""Phase 2 (part 2) — turn parsed blocks into retrieval chunks with metadata.

Rules (from PLAN_2.md):
  - Chunk within Item boundaries; never knowingly straddle Items.
  - Prose: ~800 tokens, 100 overlap.
  - Tables: kept whole where possible (already serialized self-contained in parse.py).
    If a table is too large, split by rows and REPEAT the header line on each piece so the
    company/section/units travel with every row group.
  - Metadata on every chunk: {company, item, section_title, accession, filing_date, chunk_id}.

Output: data/chunks.json — a flat list consumed by embed.py / retrieve.py.
"""

import json
from pathlib import Path

import tiktoken

PARSED_DIR = Path("data/parsed")
MANIFEST_PATH = Path("data/manifest.json")
OUT_PATH = Path("data/chunks.json")

PROSE_TOKENS = 800
PROSE_OVERLAP = 100
TABLE_MAX_TOKENS = 1000  # split larger tables by row groups

ENC = tiktoken.get_encoding("cl100k_base")
NAMES = {"AAPL": "Apple", "JPM": "JPMorgan Chase", "WMT": "Walmart",
         "KO": "Coca-Cola", "NVDA": "NVIDIA", "CAT": "Caterpillar"}


def n_tokens(text: str) -> int:
    return len(ENC.encode(text))


def token_windows(text: str, size: int, overlap: int) -> list[str]:
    """Sliding-window split by tokens."""
    toks = ENC.encode(text)
    if len(toks) <= size:
        return [text]
    out, start = [], 0
    while start < len(toks):
        out.append(ENC.decode(toks[start:start + size]))
        if start + size >= len(toks):
            break
        start += size - overlap
    return out


def split_table(text: str) -> list[str]:
    """Split an over-long table by rows, repeating the header (first line) on each piece."""
    lines = text.split("\n")
    header, rows = lines[0], lines[1:]
    if n_tokens(text) <= TABLE_MAX_TOKENS:
        return [text]
    pieces, cur = [], [header]
    for row in rows:
        cur.append(row)
        if n_tokens("\n".join(cur)) >= TABLE_MAX_TOKENS:
            pieces.append("\n".join(cur))
            cur = [header]  # repeat header on the next piece
    if len(cur) > 1:
        pieces.append("\n".join(cur))
    return pieces


def chunk_filing(ticker: str, blocks: list[dict], meta: dict) -> list[dict]:
    company = NAMES.get(ticker, ticker)
    chunks: list[dict] = []

    def add(text: str, item, section_title, kind):
        cid = f"{ticker}-{len(chunks):04d}"
        chunks.append({
            "chunk_id": cid, "ticker": ticker, "company": company,
            "item": item, "section_title": section_title,
            "accession": meta["accession"], "filing_date": meta["filing_date"],
            "kind": kind, "text": text,
        })

    prose_buf: list[str] = []
    buf_item = buf_title = None

    def flush_prose():
        nonlocal prose_buf, buf_item, buf_title
        if not prose_buf:
            return
        joined = " ".join(prose_buf)
        for w in token_windows(joined, PROSE_TOKENS, PROSE_OVERLAP):
            add(w, buf_item, buf_title, "prose")
        prose_buf = []

    for b in blocks:
        if b["kind"] == "heading":
            continue  # headings only set item context (already on following blocks)
        if b["kind"] == "table":
            flush_prose()
            for piece in split_table(b["text"]):
                add(piece, b.get("item"), b.get("section_title"), "table")
            continue
        # prose: flush when the Item changes so chunks never straddle Items
        if b.get("item") != buf_item and prose_buf:
            flush_prose()
        buf_item, buf_title = b.get("item"), b.get("section_title")
        prose_buf.append(b["text"])
    flush_prose()
    return chunks


def main() -> None:
    manifest = {m["ticker"]: m for m in json.loads(MANIFEST_PATH.read_text())}
    all_chunks: list[dict] = []
    for ticker, meta in manifest.items():
        blocks = json.loads((PARSED_DIR / f"{ticker}.json").read_text())
        cs = chunk_filing(ticker, blocks, meta)
        n_table = sum(c["kind"] == "table" for c in cs)
        print(f"{ticker}: {len(cs)} chunks ({n_table} table, {len(cs) - n_table} prose)")
        all_chunks.extend(cs)
    OUT_PATH.write_text(json.dumps(all_chunks, indent=2))
    print(f"\nWrote {len(all_chunks)} chunks -> {OUT_PATH}")


if __name__ == "__main__":
    main()
