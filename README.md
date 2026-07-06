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
- `FINSIGHT_USE_RERANKER` — set to `0` to skip the cross-encoder reranker (default `1` locally, `0` in the deploy image; see [Deploy](#deploy))

For the frontend: Node.js 22+.

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

The reranker downloads `sentence-transformers` + `torch` on first run. Set `FINSIGHT_USE_RERANKER=0` to skip it.

## Ingest

Run once. Outputs are cached — re-running only fetches what's missing.

```bash
python ingest/download.py   # fetch 10-Ks from SEC EDGAR → data/raw/
python ingest/parse.py      # HTML → prose/table blocks → data/parsed/
python ingest/chunk.py      # blocks → retrieval chunks → data/chunks.json
python ingest/embed.py      # embed chunks → Chroma at data/chroma/
python ingest/xbrl.py       # inline XBRL tags → data/facts.json
```

## Run (backend only, legacy UI)

```bash
python -m uvicorn app.main:app --port 8000
# open http://127.0.0.1:8000
```

## Run (with the React frontend)

```bash
# terminal 1 — backend
python -m uvicorn app.main:app --port 8000

# terminal 2 — frontend (proxies /api to :8000)
cd web
npm install
npm run dev
# open http://127.0.0.1:5173
```

`npm run build` (from `web/`) compiles the SPA into `static/dist/`; FastAPI serves it at `/` automatically when present, falling back to the legacy `static/index.html` otherwise.

## API

| Endpoint | Method | Description |
|---|---|---|
| `/api/chat` | POST | `{ "message", "session_id", "stream" }` — main endpoint, handles session context |
| `/api/stream` | GET | `?q=` — SSE stream of tokens then done event with citations and tool trace |
| `/api/research` | GET | `?q=` — full result in one JSON response |
| `/api/sessions/{id}` | GET | Stored messages for a session |
| `/api/quote/{ticker}` | GET | Live quote from yfinance |
| `/api/quotes` | GET | `?tickers=AAPL,JPM` — batch quotes (used by the watchlist panel) |
| `/api/watchlist` | GET | `?client_id=` — list a client's watchlist |
| `/api/watchlist` | POST | `{ "client_id", "ticker" }` — add a ticker |
| `/api/watchlist/{ticker}` | DELETE | `?client_id=` — remove a ticker |
| `/api/companies` | GET | Supported tickers |
| `/health` | GET | Health check |

The watchlist is keyed by an anonymous `client_id` (a UUID the frontend generates and stores in `localStorage`) — no accounts required. See `app/watchlist.py`.

## Evaluate

```bash
python eval/run_eval.py                          # filing regression suite
python -m unittest discover -s tests             # offline unit tests (no LLM calls)
```

The regression suite passes at the same threshold with the reranker on or off (`FINSIGHT_USE_RERANKER=0`); deploy runs with it off to fit the free-tier RAM ceiling.

## Deploy

The app is one Docker service: a multi-stage build compiles the React SPA (Node stage) and copies it into the FastAPI image (Python stage), which serves both the API and the static frontend.

Deployed on [Render](https://render.com)'s free tier via `render.yaml`:

1. Connect the GitHub repo in the Render dashboard → New → Blueprint.
2. Set `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` as secrets when prompted (they're marked `sync: false` in `render.yaml`, so Render asks for them rather than reading them from the repo).
3. Push to `main` — Render builds the Dockerfile and deploys automatically on every push.

The reranker is off in deploy (`FINSIGHT_USE_RERANKER=0`, baked into the Dockerfile) since `sentence-transformers`/`torch` would exceed the free tier's 512MB RAM. The vector store and chunk/fact stores are committed to the repo (`data/chroma/`, `data/chunks.json`, `data/facts.json`) so the image builds directly from git with no re-ingest or re-embedding step. The watchlist/session SQLite database lives on ephemeral disk and resets on redeploy; the frontend mirrors watchlist tickers in `localStorage` and re-syncs them on load, so a user's watchlist survives a redeploy even though the server-side row does not.

Free-tier services spin down after ~15 minutes idle; the first request after that takes 30-60s to cold-start.

## Repo layout

```
ingest/     download  parse  chunk  embed  xbrl  validate
app/        main  research  config  audit  corpus  synthesize  retrieve  router  decompose  facts  rerank  watchlist
app/agent/  executor  router_llm  context  session
app/tools/  filings  market  compute  registry
web/        Vite + React + TS frontend (src/components, src/hooks, src/lib)
eval/       questions.yaml  run_eval.py
static/     index.html (legacy fallback)  dist/ (built SPA, gitignored)
tests/
data/       raw/  parsed/  chunks.json  facts.json  chroma/  manifest.json
```

All tunables are in `app/config.py`.
