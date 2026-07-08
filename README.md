# FinSight

Financial research assistant over the most recent 10-K filings of **Apple, JPMorgan Chase, Walmart, Coca-Cola, NVIDIA, and Caterpillar** — grounded Q&A with inline citations, valuation-aware chat (P/E, P/S computed from live price × filing fundamentals), price-move explanations grounded in disclosed risk factors, one-click company insight briefs, a stock screener, side-by-side comparison, price charts, and a portfolio planner — all backed by the same filing corpus and live (delayed) market data.

**Live demo:** https://finsight-vh4y.onrender.com

> Runs on Render's free tier — after ~15 minutes idle the service spins down, so the **first request can take 30–60s** to cold-start. Subsequent requests are fast.

## Try it

Open the demo and ask things like:

- *"What was Apple's revenue in fiscal 2024?"* — answered from the structured XBRL fact store, cited to the filing.
- *"Compare NVIDIA and Caterpillar's operating margins"* — multi-company decomposition with per-company evidence.
- *"Which company has the highest operating margin?"* — ranked answer from the screener tool, not a guess.
- *"What are JPMorgan's key risks?"* — retrieval + synthesis over the risk-factor sections, with source chunks shown.
- *"Tell me about Walmart"* — broad question, routed to per-topic synthesis (business, risks, financials, outlook).
- *"Is NVIDIA expensive right now?"* — P/E and P/S computed from a live quote and XBRL fundamentals, compared against the other five companies; framed as a snapshot, never as buy/sell advice.
- *"Why is NVIDIA down this month?"* — states the price move factually from market data, then filing-disclosed risk factors as context investors may weigh — never claims a filing caused the move.
- *"Give me an insight brief on Apple"* — quote, valuation, peer ranks, and a two-section filing narrative in one answer.
- Follow-ups without a company name (*"and its net income?"*) resolve to the last company mentioned.

Every answer shows its **citations and tool trace** — including which router strategy answered it (`llm_router` for the valuation/explain-move/insight questions above, `deterministic` for everything else — see [How it works](#how-it-works)). Questions outside the six companies (or outside the filings) are refused rather than hallucinated.

Beyond chat, the sidebar has four more views:

- **Screener** — derived XBRL metrics (margins, ROE, revenue growth, P/S) across all six companies, sortable, with live-price sparklines; each row has a one-click **Insight** action.
- **Compare** — overlaid price history chart (hover crosshair) for any subset of the six tickers.
- **Portfolio** — enter share counts per ticker; live valuation, weights, and day change. Stored per anonymous `client_id` in `localStorage` — no account needed. Same for the **watchlist** panel.
- **Insight** — pick a company for a one-page brief: live quote + sparkline, P/E/P/S/price-change tiles, a fundamentals row with peer-rank badges, and a streaming two-section filing narrative (business & outlook, key risks), all with sources.

## How it works

```
question
  → router          regex/alias, no LLM          single | decompose | oos | clarify
  → xbrl_lookup     structured fact store         fast path for known numeric metrics
       ↓ miss
  → tool router     regex fast paths, or one      bounded plan: which tools to call
                     structured LLM call for       and in what order
                     valuation/explain-move/
                     insight-brief questions
  → tools           facts/RAG/market/compute/      evidence chunks, uniform schema,
                     screener/insight              citable [chunk_id]s
  → threshold gate  cosine sim of top chunk        refuse if out-of-corpus
  → synthesize      temp-0 Claude, streamed        grounded answer with inline citations
```

Broad questions ("tell me about Apple") route to per-topic synthesis — four focused retrieval+synthesis calls in sequence rather than one large context dump. Derived-metric superlatives ("highest operating margin") route to a `screen_companies` tool that ranks from computed XBRL metrics, so the answer is citable numbers rather than weak RAG.

**Tool routing is hybrid.** Unambiguous questions (plain lookups, screener superlatives, segment questions) are routed by regex alone — zero LLM cost, fully deterministic. Ambiguous or mixed filing+market questions (valuation, "why did the stock move", insight-brief phrasing) get one temp-0 structured-JSON call to a small model (`claude-haiku-4-5`) that plans which tools to call and in what order. That plan is never trusted directly — every tool name and argument is validated against an allowlist before execution, and any invalid or missing plan falls back to a regex-only version of the same three intents, so the feature still works with the router disabled (`FINSIGHT_USE_LLM_ROUTER=0`) or no LLM available. New computed ratios (P/E, P/S, price-change) reuse the same `-CALC-` citation scheme as the original market-cap-to-revenue calculator; valuation and explain-move answers each get an extra grounding instruction appended to the synthesis prompt — valuation ratios are point-in-time and not advice, and a filing may never be cited as the *cause* of a price move, only as disclosed context.

Refusals happen at three points: the retrieval threshold, the synthesis grounding rules, and the system prompt (which explicitly declines for any company outside the six).

**Stack:** FastAPI + ChromaDB + BM25 (`rank_bm25`) backend, OpenAI embeddings, Claude for synthesis and routing, yfinance for market data; React 19 + TypeScript + Vite frontend with zero-dependency SVG charts; one Docker image deployed on Render.

## Run locally

### Prerequisites

- Python 3.11+ and Node.js 22+
- `OPENAI_API_KEY` — embeddings only (`text-embedding-3-small`)
- `ANTHROPIC_API_KEY` — decomposition and synthesis (`claude-sonnet-4-6`)

Optional:
- `FINSIGHT_API_KEY` — require `x-api-key` header on API endpoints
- `FINSIGHT_RATE_LIMIT_PER_MINUTE` — per-IP rate limit (default: 60)
- `FINSIGHT_USE_RERANKER` — set to `0` to skip the cross-encoder reranker (default `1` locally, `0` in the deploy image; see [Deploy](#deploy))
- `FINSIGHT_USE_LLM_ROUTER` — set to `0` to force the deterministic-only tool router (default `1`)
- `FINSIGHT_ROUTER_MODEL` — model for the hybrid tool router (default `claude-haiku-4-5`)

### Setup

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

### Ingest

The repo ships with pre-built stores (`data/chroma/`, `data/chunks.json`, `data/facts.json`), so this is only needed to rebuild from scratch. Outputs are cached — re-running only fetches what's missing.

```bash
python ingest/download.py   # fetch 10-Ks from SEC EDGAR → data/raw/
python ingest/parse.py      # HTML → prose/table blocks → data/parsed/
python ingest/chunk.py      # blocks → retrieval chunks → data/chunks.json
python ingest/embed.py      # embed chunks → Chroma at data/chroma/
python ingest/xbrl.py       # inline XBRL tags → data/facts.json
```

### Run

```bash
# terminal 1 — backend
python -m uvicorn app.main:app --port 8000

# terminal 2 — frontend (proxies /api to :8000)
cd web
npm install
npm run dev
# open http://127.0.0.1:5173
```

Backend alone at http://127.0.0.1:8000 serves the legacy UI. `npm run build` (from `web/`) compiles the SPA into `static/dist/`; FastAPI serves it at `/` automatically when present.

## API

| Endpoint | Method | Description |
|---|---|---|
| `/api/chat` | POST | `{ "message", "session_id", "stream" }` — main endpoint, handles session context |
| `/api/stream` | GET | `?q=` — SSE stream of tokens then done event with citations and tool trace |
| `/api/research` | GET | `?q=` — full result in one JSON response |
| `/api/sessions/{id}` | GET | Stored messages for a session |
| `/api/quote/{ticker}` | GET | Live quote from yfinance |
| `/api/quotes` | GET | `?tickers=AAPL,JPM` — batch quotes (watchlist panel) |
| `/api/history` | GET | `?tickers=&period=1mo` — batch price history (charts) |
| `/api/screener` | GET | Derived-metric snapshot for all six companies (`?live=0` to skip quotes) |
| `/api/watchlist` | GET/POST | `?client_id=` list / `{ "client_id", "ticker" }` add |
| `/api/watchlist/{ticker}` | DELETE | `?client_id=` — remove a ticker |
| `/api/portfolio` | GET/POST | `?client_id=` valued holdings / `{ "client_id", "ticker", "shares" }` set |
| `/api/portfolio/{ticker}` | DELETE | `?client_id=` — remove a holding |
| `/api/insight/{ticker}` | GET | Full insight brief: quote, valuation, peer ranks, filing narrative |
| `/api/insight/{ticker}/stream` | GET | SSE — `card` event (deterministic data) immediately, then narrative tokens, then `done` |
| `/api/companies` | GET | Supported tickers |
| `/api/corpus/status` | GET | Corpus/store health |
| `/health` | GET | Health check |

Watchlist and portfolio are keyed by an anonymous `client_id` (a UUID the frontend generates and stores in `localStorage`) — no accounts required.

## Evaluate

```bash
python eval/run_eval.py                                                   # filing regression suite
python eval/run_eval.py eval/questions_v3.yaml eval/results_v3.md eval/results_v3.json   # valuation/explain-move/insight suite
python -m unittest discover -s tests             # offline unit tests (no LLM calls)
```

The regression suite passes at the same threshold with the reranker on or off (`FINSIGHT_USE_RERANKER=0`); deploy runs with it off to fit the free-tier RAM ceiling. The V3 suite (`questions_v3.yaml`) runs with the hybrid LLM router on by default and checks tool selection, citation namespaces, and grounding language (freshness, advice disclaimers) for the three new intents.

## Deploy

One Docker service: a multi-stage build compiles the React SPA (Node stage) and copies it into the FastAPI image (Python stage), which serves both the API and the static frontend.

Deployed on [Render](https://render.com)'s free tier via `render.yaml`:

1. Connect the GitHub repo in the Render dashboard → New → Blueprint.
2. Set `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` as secrets when prompted (they're marked `sync: false` in `render.yaml`, so Render asks for them rather than reading them from the repo).
3. Push to `main` — Render builds the Dockerfile and deploys automatically on every push.

The reranker is off in deploy (`FINSIGHT_USE_RERANKER=0`, baked into the Dockerfile) since `sentence-transformers`/`torch` would exceed the free tier's 512MB RAM. The vector store and chunk/fact stores are committed to the repo so the image builds directly from git with no re-ingest or re-embedding step. The watchlist/portfolio/session SQLite database lives on ephemeral disk and resets on redeploy; the frontend mirrors tickers and share counts in `localStorage` and re-syncs them on load, so a user's data survives a redeploy even though the server-side rows do not.

## Repo layout

```
ingest/     download  parse  chunk  embed  xbrl  validate
app/        main  research  config  audit  corpus  synthesize  retrieve  router  decompose  facts  rerank  screener  watchlist  portfolio  insight
app/agent/  executor  router_llm  router_plan  context  session
app/tools/  filings  market  compute  screen  registry
web/        Vite + React + TS frontend (src/components, src/hooks, src/lib)
eval/       questions.yaml  questions_market.yaml  questions_hybrid.yaml  questions_v3.yaml  run_eval.py
static/     index.html (legacy fallback)  dist/ (built SPA, gitignored)
tests/
data/       raw/  parsed/  chunks.json  facts.json  chroma/  manifest.json
```

All tunables are in `app/config.py`.
