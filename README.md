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
