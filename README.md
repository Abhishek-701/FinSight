# Financial Analysis Agent over SEC filings and market data

A production-oriented financial analysis agent over the most recent 10-K filings of **Apple,
JPMorgan Chase, Walmart, Coca-Cola, NVIDIA, and Caterpillar**. It answers filing questions with
cited passages, can mix in yfinance-backed market data, and returns an inspectable tool trace.

## Pipeline

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

The FastAPI app now wraps this deterministic core in a lightweight research orchestration layer:
`plan → act → reflect`. The plan selects bounded tool actions such as `facts_lookup`,
`filing_rag`, `multi_company_compare`, `market_quote`, and `synthesize_report`; the tool trace
and reflection checks are returned with each response for debugging and evals.

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

## Prerequisites

- **Python 3.11+** (developed on 3.13). Git.
- **Two API keys**:
  - `OPENAI_API_KEY` — embeddings only (`text-embedding-3-small`). Anthropic has no embeddings API.
  - `ANTHROPIC_API_KEY` — the chat model (`claude-sonnet-4-6`) for decomposition + synthesis.
- **Optional production controls**:
  - `FAIRWAY_API_KEY` — require `x-api-key` on expensive endpoints when set.
  - `FAIRWAY_RATE_LIMIT_PER_MINUTE` — simple per-IP request limit.
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
> `USE_RERANKER = False` in `app/config.py` to skip the model load.

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

API shapes:

- `GET /api/stream?q=...` streams answer tokens and finishes with citations, gaps, plan, and tool trace metadata.
- `GET /api/research?q=...` returns the full structured result in one JSON response.
- `POST /api/chat` accepts `{ "message": "...", "session_id": null, "stream": false }`.
- `GET /api/sessions/{session_id}` returns stored chat messages.
- `GET /api/quote/{ticker}` returns direct yfinance quote data.
- `GET /api/companies`, `GET /api/corpus/status`, and `GET /health` support UI and deployment checks.

Or run the pipeline from the CLI (four checkpoint questions):

```bash
python -m app.main
```

## Evaluate

The eval questions are hand-written (see `eval/questions.yaml`). The runner emits deterministic
regression checks plus a markdown report for human review.

```bash
# filing regression suite:
python eval/run_eval.py

# market / hybrid suites:
python eval/run_eval.py eval/questions_market.yaml eval/results_market.md eval/results_market.json
python eval/run_eval.py eval/questions_hybrid.yaml eval/results_hybrid.md eval/results_hybrid.json
```

The market and hybrid suites check tool selection, market citations, and as-of timestamp language.
Use mocked market responses for deterministic CI if yfinance variability becomes noisy.

## Configuration

All tunables are in **`app/config.py`** with inline rationale: chat model, retrieval `top_k`,
RRF constant, refusal threshold, context cap, reranker toggle, XBRL maps, market cache TTLs,
agent step cap, API key, and rate-limit settings.

## Repo layout

```
ingest/   download.py  parse.py  chunk.py  embed.py  xbrl.py  validate.py
app/      main.py (FastAPI endpoints, health, chat/session APIs)
          research.py (plan/act/reflect orchestration)
          agent/ (bounded executor, router, session store)
          tools/ (filings, market, compute, registry)
          router.py  retrieve.py  decompose.py  facts.py (XBRL fact store)
          synthesize.py (build_xbrl_context)  rerank.py  config.py  __init__.py
eval/     questions.yaml  run_eval.py  results.md
static/   index.html
data/     raw/  parsed/  chunks.json  facts.json  chroma/  manifest.json
          (all gitignored except manifest.json; facts.json regenerated by ingest/xbrl.py)
```
