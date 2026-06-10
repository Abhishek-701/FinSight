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
