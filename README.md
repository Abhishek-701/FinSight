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
  → [decompose]     (one temp-0 Claude call)       one self-contained sub-query per company
  → hybrid retrieve (BM25 + dense embeddings, RRF) + optional cross-encoder rerank
  → threshold gate  (dense cosine sim of top chunk)  refuse if out-of-corpus
  → synthesize      (temp-0 Claude, streamed)       grounded answer, inline [chunk_id] citations
```

Two refusal mechanisms: a **retrieval threshold** (out-of-corpus, e.g. "Tesla's revenue") and a
**synthesis/gaps gate** (in-corpus but undisclosed, e.g. "Coca-Cola's attrition rate").

## Decision log (one page)

*Filings used:* the six most recent 10-Ks from EDGAR; exact accession numbers + filing dates in
[`data/manifest.json`](data/manifest.json) and DECISIONS.md.

- **Chunking — why.** ~800-token prose windows (100 overlap), flushed at Item boundaries so a chunk
  never straddles Items. Tables are kept whole and serialized **row-wise**, where each value carries
  its compound column header, a `Consolidated` / `Segment-level` **scope tag**, and the table caption
  — so a number can't drift from its year/scope, and a table is retrievable by its description, not
  just its Item heading. (~2,440 chunks.)
- **Embeddings — why.** OpenAI `text-embedding-3-small`: Anthropic has no embeddings API; it's cheap
  and strong for dense retrieval.
- **Retrieval — why.** Hybrid **BM25 + dense, fused with RRF**, company-filtered. Lexical catches
  exact line-item terms, dense catches paraphrase, and RRF needs no cross-scorer calibration.
- **Reranker — why + toggle.** Optional cross-encoder (`ms-marco-MiniLM-L-6-v2`) over the top-30,
  `USE_RERANKER` in config. Surfaces a buried table row above prose; pulls `torch`, so it's toggleable.
- **Generation & honesty.** Temp-0 `claude-sonnet-4-6` (Opus 4.8 removed `temperature`). Every figure
  is cited to a chunk id; cross-company answers state each company's fiscal-year end. Two refusal
  gates as above — refuse rather than guess.
- **Routing — why.** Regex/alias map, no LLM, for determinism + explainability; the tradeoff is
  brittleness on unlisted aliases/phrasing.

**Where it breaks (honest).** Numeric fidelity inside complex tables is the weak spot. The eval's
multi-company comparison (**Q3 — the deliberate failure case**) still returns a wrong figure: a
*segment* "Total revenues" can be reported as the *consolidated* total — a concept-level (not
terminology) error the system cannot self-catch. The in/out-of-corpus threshold margin is thin
(~0.003 on one probe). Footnote linkage is local (adjacent notes only), not a global reference graph.

**With another week.** XBRL/companyfacts as the source of truth for numbers, with a reconciliation
cross-check against the scraped tables (closes the segment-vs-consolidated error at the root); a
temp-0 LLM router; per-query-type thresholds; a footnote reference graph. Full detail + the running
log in [DECISIONS.md](DECISIONS.md).

## Prerequisites

- **Python 3.11+** (developed on 3.13). Git.
- **Two API keys** (see why in DECISIONS.md):
  - `OPENAI_API_KEY` — embeddings only (`text-embedding-3-small`). Anthropic has no embeddings API.
  - `ANTHROPIC_API_KEY` — the chat model (`claude-sonnet-4-6`) for decomposition + synthesis.
- Ingest cost is tiny: embedding the whole corpus is well under $0.05; each question is a fraction
  of a cent of embeddings + one or two Claude calls.

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
python ingest/validate.py     # OPTIONAL report: section coverage, CSS residue, table alignment
```

`download.py` sends a real EDGAR `User-Agent`, rate-limits, and caches (it won't re-fetch files
already in `data/raw/`). `data/` is gitignored except `data/manifest.json` (provenance).

## Run the app

```bash
python -m uvicorn app.main:app --port 8000
# open http://127.0.0.1:8000  — ask a question, watch it stream, expand the cited sources
```

Or run the pipeline from the CLI (the four checkpoint questions):

```bash
python -m app.main
```

## Evaluate

The eval questions are hand-written (see `eval/questions.yaml`). The runner does **not** auto-grade.

```bash
# edit eval/questions.yaml with your questions, then:
python eval/run_eval.py        # -> eval/results.md (table + answers, with blank grade cells)
```

`results.md` records each question's route, refusal, top similarity, citations, and gaps; you fill
in correct / grounded / refusal-correct by hand.

## Configuration

All tunables are in **`app/config.py`** with inline rationale: chat model, retrieval `top_k`,
RRF constant, the refusal `DENSE_SIM_THRESHOLD` (0.50), context cap, and `USE_RERANKER`.

## Repo layout

```
ingest/   download.py  parse.py  chunk.py  embed.py  validate.py
app/      main.py (FastAPI + pipeline)  router.py  retrieve.py  decompose.py
          synthesize.py  rerank.py  config.py
eval/     questions.yaml  run_eval.py  results.md
static/   index.html
DECISIONS.md   running decision log + known weaknesses + next-week list
data/     raw/  parsed/  chunks.json  chroma/  manifest.json   (gitignored except manifest)
```
