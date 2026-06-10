# DECISIONS.md — running log

Updated as choices are made (guardrail G7), not batched at the end.

## Architecture (locked, from PLAN_2.md)
- Stack: Python 3.11+, FastAPI, single static HTML/JS page (no React, no build step).
- Vector store: Chroma (local, persisted). BM25: `rank_bm25`.
- Embeddings: OpenAI `text-embedding-3-small` (Anthropic has no embeddings API).
- Chat LLM: Anthropic (Claude) for decomposition + synthesis, temperature 0.
- Pipeline, not agent: question -> router -> [decompose] -> hybrid retrieval -> threshold gate -> synthesis.
- Routing: regex/alias map (no LLM) for explainability + determinism.
- Refusal: two distinct gates (out-of-corpus threshold on normalized dense similarity; in-corpus-undisclosed via synthesis/gaps).

## Dependencies (G2 — one line each)
See requirements.txt; each line carries its justification.

## Decision log
- 2026-06-10: Fetch ALL SIX filings from EDGAR through one clean path (incl. Apple), rather
  than using a viewer-saved Apple file. Reason: provided file was unavailable; uniform path
  is simpler and the CSS-residue stripping in parse.py is built defensively regardless.
- 2026-06-10: Chat LLM = Anthropic (Claude); embeddings = OpenAI. Two keys: Claude has no
  embeddings API, so dense retrieval needs OpenAI text-embedding-3-small.
- 2026-06-10: EDGAR User-Agent = "Abhishek <walvekarabhishek701@gmail.com>" per SEC fair-access policy.
- 2026-06-10: BLOCKER (Phase 3): chromadb pulls native chroma-hnswlib, which has no prebuilt
  wheel for Python 3.13 on Windows -> source build fails (needs MSVC C++ build tools). Phase 2
  needs no vector store, so deferred. RESOLVED: chromadb 1.5.9 ships prebuilt cp313 Windows
  wheels (no C++ build needed); repinned 0.5.23 -> 1.5.9. Verified `import chromadb` works.
- 2026-06-10: EDGAR-fetched files are CLEAN (0 <style>/<script>, minimal css- noise) — unlike
  the viewer-saved Apple copy the plan referenced. CSS-residue stripping kept defensively.
  Files ARE Inline XBRL: ix:nonFraction tags present (NVDA ~1127) carrying value/scale/unit/
  period — available for the optional headline-figure cross-check.

### Phase 2 — parse/chunk/validate (2026-06-10)
- Walk the doc as ordered leaf-<div> + <table> blocks (SEC wraps each line in its own div).
- Item headings: regex `^Item N.` at position 0, NOT inside <a> (kills TOC links + "refer to
  Item 1A" cross-refs), short block. Detected on any div (not just leaf — WMT nests its
  headings) and deduped by item number so an outer wrapper + inner copy don't double-emit.
- Tables: expand colspan/rowspan into a dense grid; BLANK `$`/`%` marker cells in place (then
  drop all-empty columns) so every row keeps the same width and values stay aligned to headers
  — removing `$` per-row was the bug that drifted numbers off their year. Header zone = leading
  rows with no *magnitude* cell; years/dates are periods (kept as headers), not values. Each
  data row serialized self-contained: "section | label | <col header> = <value>". Accounting
  negatives (1,234) -> -1234. Layout tables (no magnitude cells) skipped. Units read from the
  table text + the caption line just above (SEC puts "(In millions)" there).
- Footnotes immediately following a table are appended to that table's block as "[footnote] ...".
- Chunking: prose ~800 tokens / 100 overlap (tiktoken cl100k_base), flushed at Item boundaries
  so chunks never straddle Items. Tables kept whole; tables >1000 tokens split by rows with the
  header line repeated on each piece. chunk_id = "{TICKER}-{NNNN}". 2419 chunks total.
- validate.py is a REPORT (warns, never blocks): (a) Items 1/1A/7/8 present, (b) revenue term in
  a numeric table, (c) CSS/JS residue, (d) irregular-row-width tables (precision heuristic:
  flag when the modal row width covers <60% of rows = likely multi-level drift), (e) prints the
  largest table per company + 2 seeded-random table chunks. Spot-checked headline figures by
  hand: AAPL total net sales 416,161; WMT total revenues 713,163; NVDA revenue 215,938 — all
  correct and bound to the right fiscal year.

## Filings used (Phase 1, fetched 2026-06-10 from EDGAR)
| Ticker | Company | Form | Accession | Filed | Fiscal period end (from doc name) |
|--------|---------|------|-----------|-------|-----------------------------------|
| AAPL | Apple | 10-K | 0000320193-25-000079 | 2025-10-31 | 2025-09-27 |
| JPM  | JPMorgan Chase | 10-K | 0001628280-26-008131 | 2026-02-13 | 2025-12-31 |
| WMT  | Walmart | 10-K | 0000104169-26-000055 | 2026-03-13 | 2026-01-31 |
| KO   | Coca-Cola | 10-K | 0001628280-26-010047 | 2026-02-20 | 2025-12-31 |
| NVDA | NVIDIA | 10-K | 0001045810-26-000021 | 2026-02-25 | 2026-01-25 |
| CAT  | Caterpillar | 10-K | 0000018230-26-000008 | 2026-02-13 | 2025-12-31 |

All exact form "10-K" (no 10-K/A amendments). Note the differing fiscal year ends (Apple
Sep, NVDA/WMT Jan, others Dec) — this matters for cross-company comparisons (Phase 6 eval).

## Known weaknesses
(filled at Phase 7 — see PLAN_2.md "Known weaknesses")

## Next week
(filled at Phase 7)
