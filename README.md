# Grounded Q&A over six SEC 10-K filings

A small, deterministic Q&A system over the most recent 10-K filings of **Apple, JPMorgan Chase,
Walmart, Coca-Cola, NVIDIA, and Caterpillar**. It answers questions with figures cited to the
exact passage they came from, and refuses (rather than guessing) when the answer isn't in the
six filings.

The design rationale, tradeoffs, and known weaknesses live in **[DECISIONS.md](DECISIONS.md)** —
read that for the "why". This file is the "how to run it".

## Pipeline (not an agent)

```
question
  → router          (regex/alias, no LLM)         single | decompose | out-of-corpus | clarify
  → xbrl_lookup     (fact store, no LLM)           XBRL fast path: returns answer if metric found
       ↓ miss only
  → [decompose]     (one temp-0 Claude call)       one self-contained sub-query per company
  → hybrid retrieve (BM25 + dense embeddings, RRF) + optional cross-encoder rerank
  → threshold gate  (dense cosine sim of top chunk)  refuse if out-of-corpus
  → synthesize      (temp-0 Claude, streamed)       grounded answer, inline [chunk_id] citations
```

**XBRL fast path:** before touching RAG, the system checks a structured fact store extracted
from the same 10-K HTML files (inline XBRL tags). If the question asks for a known numeric
metric (revenue, operating income, net income, EPS, R&D, provision for credit losses, operating
cash flow), the fact is returned directly — no retrieval, no decompose LLM call. RAG runs only
on a miss. Facts are formatted as synthetic chunks with the same schema as RAG chunks, so the
synthesis and citation logic is completely unchanged.

Three refusal mechanisms: a **retrieval threshold** (out-of-corpus, e.g. "Tesla's revenue"), a
**synthesis/gaps gate** (in-corpus but undisclosed, e.g. "Coca-Cola's attrition rate"), and a
**synthesis-level OOS guard** (the system prompt explicitly declines for any company not among the
six — a safety net for edge cases where the cosine similarity lands exactly at the threshold and
the gate doesn't fire, as in Q17/Amazon at 0.500).

## Decision log (one page)

*Filings used:* the six most recent 10-Ks from EDGAR; exact accession numbers + filing dates in
[`data/manifest.json`](data/manifest.json) and DECISIONS.md.

- **Chunking — why.** ~800-token prose windows (100 overlap), flushed at Item boundaries so a
  chunk never straddles Items. Tables are kept whole and serialized **row-wise**, where each value
  carries its compound column header, a `Consolidated` / `Segment-level` **scope tag**, and the
  table caption — so a number can't drift from its year/scope, and a table is retrievable by its
  description, not just its Item heading. (~2,440 chunks.)
- **Embeddings — why.** OpenAI `text-embedding-3-small`: Anthropic has no embeddings API; it's
  cheap and strong for dense retrieval.
- **Retrieval — why.** Hybrid **BM25 + dense, fused with RRF**, company-filtered. Lexical catches
  exact line-item terms, dense catches paraphrase, and RRF needs no cross-scorer calibration.
- **Reranker — why + toggle.** Optional cross-encoder (`ms-marco-MiniLM-L-6-v2`) over the top-30,
  `USE_RERANKER` in config. Surfaces a buried table row above prose; pulls `torch`, so it's
  toggleable.
- **XBRL fast path — why.** Inline XBRL tags in the 10-K HTML are the authoritative numeric
  source — tagged by the company itself, machine-readable, unambiguous about period and
  consolidation scope. Parsing them with BeautifulSoup (an existing dependency) costs nothing
  at query time and eliminates retrieval misses for the most common numeric questions. Per-ticker
  concept overrides handle terminology differences (Apple uses
  `RevenueFromContractWithCustomerExcludingAssessedTax`; JPMorgan uses
  `RevenuesNetOfInterestExpense`; Caterpillar's net income lives in `ProfitLoss`). The lookup
  also supports **multi-metric questions** (e.g. "R&D vs operating cash flow") by collecting
  every matching keyword rather than stopping at the first, and **year-over-year deltas** by
  fetching both the current and prior-year tagged facts when the question contains change/YoY
  language.
- **Generation & honesty.** Temp-0 `claude-sonnet-4-6` (Opus 4.8 removed `temperature`). Every
  figure is cited to a chunk id; cross-company answers state each company's fiscal-year end.
  Three refusal gates as above — refuse rather than guess. The synthesis prompt also suppresses
  describing which in-corpus companies appeared in the context when the question asks about an
  out-of-corpus entity, preventing confusing responses like "Walmart and NVIDIA are in the
  context but Amazon is not."
- **Routing — why.** Regex/alias map, no LLM, for determinism + explainability; the tradeoff is
  brittleness on unlisted aliases/phrasing. The superlative regex uses a negative lookahead
  (`most(?!\s+recent)`) so "most recent fiscal year" doesn't spuriously fan-out to all six
  companies instead of routing to the correct single-company or OOS path.

**Where it breaks (honest).** Q24 in the eval is the deliberate failure: asking for NVIDIA's
*Data Center segment* revenue causes the XBRL fast path to intercept (keyword `revenue` matches)
and return a synthetic chunk with the *consolidated* total ($215,938M). The segment bail-out is
a hardcoded allowlist (`Sam's Club`, `Financial Products`, `ME&T`) that doesn't know "Data
Center." Claude correctly says "segment not found," but the actual figure — which IS in Item 8's
segment notes — is never retrieved because RAG was bypassed. The in/out-of-corpus threshold
margin is thin (~0.003 on one probe); Q17/Amazon lands at exactly 0.500 — the strict `<`
comparison means the threshold gate doesn't fire, but the synthesis-level OOS guard handles
it cleanly (Claude declines rather than leaking context from unrelated Walmart/NVIDIA chunks).
Footnote linkage is local, not a global reference graph. Multi-statement questions that mix
balance-sheet and cash-flow line items not in XBRL (e.g. Q21: Apple capex + total assets)
rely on RAG alone and may retrieve the right chunk without extracting both figures cleanly.

**Next steps.** Two approaches to fix the segment bypass: (1) a compound-noun heuristic that
detects a Title-Cased phrase between the company name and the metric keyword, indicating a
division name; (2) a temp-0 Haiku classifier (`CONSOLIDATED` vs `SEGMENT`, ~$0.0001/call).
The heuristic covers ~80% of cases for free; the classifier is general but adds latency + API
dependency. Full detail in [DECISIONS.md](DECISIONS.md).

## Prerequisites

- **Python 3.11+** (developed on 3.13). Git.
- **Two API keys** (see why in DECISIONS.md):
  - `OPENAI_API_KEY` — embeddings only (`text-embedding-3-small`). Anthropic has no embeddings API.
  - `ANTHROPIC_API_KEY` — the chat model (`claude-sonnet-4-6`) for decomposition + synthesis.
- Ingest cost is tiny: embedding the whole corpus is well under $0.05; each question is a
  fraction of a cent of embeddings + one or two Claude calls. XBRL extraction is local only
  (no API calls).

## Setup

```bash
git clone https://github.com/Abhishek-701/fairway_take_home.git
cd fairway_take_home

python -m venv .venv
# Windows:        .venv\Scripts\activate
# macOS / Linux:  source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # then edit .env and fill in both keys
```

> The reranker pulls `sentence-transformers` + `torch` (a large download). It's optional — set
> `USE_RERANKER = False` in `app/config.py` to skip the model load. See DECISIONS.md.

## Ingest (run once; outputs are cached and reproducible)

```bash
python ingest/download.py     # fetch the 6 latest 10-Ks from SEC EDGAR -> data/raw/, data/manifest.json
python ingest/parse.py        # HTML -> ordered prose/table blocks -> data/parsed/
python ingest/chunk.py        # blocks -> retrieval chunks -> data/chunks.json
python ingest/embed.py        # embed chunks -> Chroma (persisted) at data/chroma/
python ingest/xbrl.py         # parse inline XBRL tags -> data/facts.json  (fast, no API calls)
python ingest/validate.py     # OPTIONAL report: section coverage, CSS residue, table alignment
```

`download.py` sends a real EDGAR `User-Agent`, rate-limits, and caches (it won't re-fetch files
already in `data/raw/`). `ingest/xbrl.py` runs a self-validating reconciliation check that warns
if any extracted value is absent from the chunk corpus. `data/` is gitignored except
`data/manifest.json` (provenance); `data/facts.json` is regenerated from the raw HTML.

## Run the app

```bash
python -m uvicorn app.main:app --port 8000
# open http://127.0.0.1:8000  — ask a question, watch it stream, expand the cited sources
```

Or run the pipeline from the CLI (four checkpoint questions):

```bash
python -m app.main
```

## Evaluate

The eval questions are hand-written (see `eval/questions.yaml`). The runner does **not** auto-grade.

```bash
# edit eval/questions.yaml with your questions, then:
python eval/run_eval.py        # -> eval/results.md (table + answers, with blank grade cells)
```

`results.md` records each question's route, refusal, top similarity, citations, and gaps; you
fill in correct / grounded / refusal-correct by hand. Q24 is the deliberate failure probe — it
is expected to produce `correct=no`.

## Configuration

All tunables are in **`app/config.py`** with inline rationale: chat model, retrieval `top_k`,
RRF constant, the refusal `DENSE_SIM_THRESHOLD` (0.50), context cap, `USE_RERANKER`,
`XBRL_CONCEPT_MAP` (per-ticker concept overrides), and `XBRL_KEYWORD_MAP` (regex patterns that
map question fragments to canonical metric names).

## Repo layout

```
ingest/   download.py  parse.py  chunk.py  embed.py  xbrl.py  validate.py
app/      main.py (FastAPI + pipeline, xbrl_lookup fast path)
          router.py  retrieve.py  decompose.py  facts.py (XBRL fact store)
          synthesize.py (build_xbrl_context)  rerank.py  config.py  __init__.py
eval/     questions.yaml  run_eval.py  results.md
static/   index.html
DECISIONS.md   running decision log + known weaknesses + next-step list
data/     raw/  parsed/  chunks.json  facts.json  chroma/  manifest.json
          (all gitignored except manifest.json; facts.json regenerated by ingest/xbrl.py)
```
