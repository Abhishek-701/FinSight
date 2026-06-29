# FinSight

Financial Q&A over the most recent 10-K filings of **Apple, JPMorgan Chase, Walmart, Coca-Cola, NVIDIA, and Caterpillar**. Answers are cited to source chunks, live market data is mixed in where relevant, and every response includes a tool trace.

## How it works

```
question
  → router          regex/alias, no LLM          single | decompose | oos | clarify
  → xbrl_lookup     structured fact store         fast path for known numeric metrics
       ↓ miss
  → retrieve        BM25 + dense embeddings, RRF  optional cross-encoder rerank
  → threshold gate  cosine sim of top chunk       refuse if out-of-corpus
  → synthesize      temp-0 Claude, streamed       grounded answer with inline citations
```

Broad questions ("tell me about Apple") route to per-topic synthesis — four focused retrieval+synthesis calls in sequence rather than one large context dump. Specific topic questions ("tell me about key risks") go through focused RAG. Follow-up questions without a company name resolve to the most recently mentioned company.

Refusals happen at three points: the retrieval threshold, the synthesis grounding rules, and the system prompt (which explicitly declines for any company outside the six).

## Prerequisites

- Python 3.11+
- `OPENAI_API_KEY` — embeddings only (`text-embedding-3-small`)
- `ANTHROPIC_API_KEY` — decomposition and synthesis (`claude-sonnet-4-6`)

Optional:
- `FINSIGHT_API_KEY` — require `x-api-key` header on API endpoints
- `FINSIGHT_RATE_LIMIT_PER_MINUTE` — per-IP rate limit (default: 60)

## Setup

```bash
git clone https://github.com/Abhishek-701/FinSight.git
cd FinSight

python -m venv .venv
# Windows:       .venv\Scripts\activate
# macOS/Linux:   source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # add OPENAI_API_KEY and ANTHROPIC_API_KEY
```

The reranker downloads `sentence-transformers` + `torch` on first run. Set `USE_RERANKER = False` in `app/config.py` to skip it.

## Ingest

Run once. Outputs are cached — re-running only fetches what's missing.

```bash
python ingest/download.py   # fetch 10-Ks from SEC EDGAR → data/raw/
python ingest/parse.py      # HTML → prose/table blocks → data/parsed/
python ingest/chunk.py      # blocks → retrieval chunks → data/chunks.json
python ingest/embed.py      # embed chunks → Chroma at data/chroma/
python ingest/xbrl.py       # inline XBRL tags → data/facts.json
```

## Run

```bash
python -m uvicorn app.main:app --port 8000
# open http://127.0.0.1:8000
```

## API

| Endpoint | Method | Description |
|---|---|---|
| `/api/chat` | POST | `{ "message", "session_id", "stream" }` — main endpoint, handles session context |
| `/api/stream` | GET | `?q=` — SSE stream of tokens then done event with citations and tool trace |
| `/api/research` | GET | `?q=` — full result in one JSON response |
| `/api/sessions/{id}` | GET | Stored messages for a session |
| `/api/quote/{ticker}` | GET | Live quote from yfinance |
| `/api/companies` | GET | Supported tickers |
| `/health` | GET | Health check |

## Evaluate

```bash
python eval/run_eval.py                          # filing regression suite
python -m unittest discover -s tests             # offline unit tests (no LLM calls)
```

## Repo layout

```
ingest/     download  parse  chunk  embed  xbrl  validate
app/        main  research  config  audit  corpus  synthesize  retrieve  router  decompose  facts  rerank
app/agent/  executor  router_llm  context  session
app/tools/  filings  market  compute  registry
eval/       questions.yaml  run_eval.py
static/     index.html
tests/
data/       raw/  parsed/  chunks.json  facts.json  chroma/  manifest.json
```

All tunables are in `app/config.py`.
