# FinSight

Financial research assistant over SEC 10-K filings — seeded with **Apple, JPMorgan Chase, Walmart, Coca-Cola, NVIDIA, and Caterpillar**, and open to **any US-listed company on demand**: ask about a ticker or company name that isn't loaded yet and FinSight fetches its latest 10-K from SEC EDGAR live. Grounded Q&A with inline citations, valuation-aware chat (P/E, P/S computed from live price × filing fundamentals), price-move explanations grounded in disclosed risk factors and reported news headlines, cross-company valuation comparison, one-click company insight briefs, a stock screener, side-by-side comparison, price charts, and portfolio intelligence (live P&L, concentration, hypothetical what-if trades, and a vs-S&P-500 benchmark) — all backed by the same filing corpus and live (delayed) market data. Chat runs as a visible agent: the tool plan and each step's progress stream live as they execute, and every answer ends with clickable follow-up questions.

**Live demo:** https://finsight-vh4y.onrender.com

> Runs on Render's free tier — after ~15 minutes idle the service spins down, so the **first request can take 30–60s** to cold-start. Subsequent requests are fast. Adding a new company (see below) takes under a minute on top of that. Companies added on demand live on the server's disk, which is **ephemeral on Render** — they don't survive a redeploy, so the demo's roster occasionally resets back to the six seeds; adding them back is quick.

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
- *"Is Apple or NVIDIA more expensive?"* — P/E and P/S computed and cited **separately per company**, presented as a table, resolved deterministically (no LLM router involved).
- *"What's the latest news on Apple?"* — recent third-party headlines, always attributed to publisher/date and framed as reported context, never a verified cause of anything.
- *"How is my portfolio doing?"* / *"How concentrated am I?"* — live valuation, day change, P&L (only where you've entered a cost basis), and concentration (HHI) for your own saved holdings.
- *"What if I bought 10 more shares of AAPL?"* / *"What if I doubled my top holding?"* — simulates the trade and reports before/after value and concentration; nothing is bought or sold.
- *"Has my portfolio beaten the market?"* — your holdings' value applied backward over the period vs. SPY, folded into the same portfolio answer only when asked.
- *"Which of my holdings has the most rate exposure?"* — joins your holdings with filing evidence scoped to the companies you actually hold.
- Follow-ups without a company name (*"and its net income?"*) resolve to the last company mentioned; a bare swap (*"What about AAPL?"*) carries over the prior question's intent (e.g. a valuation follow-up stays a valuation question) instead of losing it.

**Ask about a company that isn't loaded yet** — *"What was Tesla's revenue last year?"*, *"Is Palantir expensive right now?"*, *"What's Rivian's stock price?"* — chat resolves the ticker or company name against the full SEC EDGAR universe and, for a filing question, offers a **"+ Add TSLA"** button right in the reply; click it, watch a short progress bar (download → parse → index → done, under a minute), and the original question answers itself once it's ready. Market-only questions ("what's the stock price") work immediately, no add needed. You can also search any ticker or company name directly from the **"Add a Company"** box in the sidebar. Once added, a company is a full citizen of the corpus — same grounded Q&A, valuation, and insight briefs as the six seeds.

The tool plan appears **as soon as it's decided** — before any tool has even run — and each step lights up live (running → done/error, with its latency) as the agent executes it; the answer streams in after. Every answer shows its **citations and tool trace**, including which router strategy answered it (`llm_router` for the valuation/explain-move/insight questions above, `deterministic` for everything else, including the newer portfolio/comparison intents — see [How it works](#how-it-works)), and ends with a row of clickable follow-up questions templated off the answer's intent. A company FinSight can't find on SEC EDGAR at all (or that has no 10-K on file) is refused rather than hallucinated.

Beyond chat, the sidebar has four more views:

- **Screener** — derived XBRL metrics (margins, ROE, revenue growth, P/S) across the six seed companies, sortable, with live-price sparklines; each row has a one-click **Insight** action.
- **Compare** — overlaid price history chart (hover crosshair) for any subset of the six seed tickers.
- **Portfolio** — enter share counts (and an optional cost basis) per ticker (any ticker, not just the seeds); live valuation, weights, day change, unrealized P&L, and HHI concentration. A **What If** panel simulates a hypothetical trade (buy/sell/double/halve a holding) and shows before/after value and concentration without touching your real holdings, and a **vs S&P 500** chart compares your current holdings/weights against SPY over a chosen period. Stored per anonymous `client_id` in `localStorage` — no account needed. Same for the **watchlist** panel.
- **Insight** — pick a company for a one-page brief: live quote + sparkline, P/E/P/S/price-change tiles, a fundamentals row with peer-rank badges, and a streaming two-section filing narrative (business & outlook, key risks), all with sources. Works for any added company, not just the seeds.

## How it works

```
question
  → router          regex/alias, no LLM          single | decompose | needs_ingest | oos | clarify
       ↓ needs_ingest (real ticker/company, not loaded yet)
  → offer_ingest    chat: "+ Add TSLA" chip       market-only questions answer immediately —
                     (or search the sidebar)       only filing questions need the add step
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

**Open universe, ingested on demand.** A ticker symbol, `$cashtag`, or company name that resolves against the full SEC EDGAR directory but isn't in the corpus yet routes to `needs_ingest` instead of a flat refusal. `ingest/pipeline.py` reuses the exact same download → parse → chunk → XBRL-extract logic as the six seed companies, add-only into the existing Chroma collection (never touching the seeds), orchestrated by `app/ingest_jobs.py` with a hard one-at-a-time cap (the free-tier RAM ceiling doesn't survive two filings embedding concurrently) and LRU eviction once the dynamic roster hits `UNIVERSE_MAX_DYNAMIC` (12 by default). Company-name resolution (`app/universe.py`) matches EDGAR's company-title directory, not just tickers, with three tiers — exact ticker/cashtag, exact casual name ("Palantir" → PLTR, stripped of legal suffixes like "Inc."), then word-subphrase fallback for names embedded in a sentence.

**Tool routing is hybrid.** Unambiguous questions (plain lookups, screener superlatives, segment questions, portfolio questions, cross-company valuation comparison) are routed by regex alone — zero LLM cost, fully deterministic. Ambiguous or mixed filing+market questions (valuation, "why did the stock move", insight-brief phrasing) get one temp-0 structured-JSON call to a small model (`claude-haiku-4-5`) that plans which tools to call and in what order. That plan is never trusted directly — every tool name and argument is validated against an allowlist before execution, and any invalid or missing plan falls back to a regex-only version of the same three intents, so the feature still works with the router disabled (`FINSIGHT_USE_LLM_ROUTER=0`) or no LLM available. New computed ratios (P/E, P/S, price-change) reuse the same `-CALC-` citation scheme as the original market-cap-to-revenue calculator, and `compute_metric` accepts an optional `ticker` to scope a multi-company evidence pool to one company at a time — the piece that makes cross-company comparison return two distinct ratios instead of the same one twice. Valuation, explain-move, portfolio, what-if, comparison, and holdings-aware answers each get an extra grounding instruction appended to the synthesis prompt — valuation ratios are point-in-time and not advice, a filing may never be cited as the *cause* of a price move, a what-if trade is a simulation that was never executed, and nothing ever recommends what the user should buy/sell/trim.

**Portfolio questions never touch the LLM router.** `portfolio_context`, `portfolio_whatif`, and `portfolio_filings` read/simulate the requesting user's own holdings, so *whose* portfolio a plan reads is injected by the executor from the authenticated request — never chosen by an LLM-produced or regex-produced plan, and none of the three tools even has a `client_id` argument in their schema. What-if trades ("what if I bought 10 shares of AAPL", "what if I doubled my top holding") are parsed from the question by the tool itself with a narrow, deterministic parser — not by asking a model to author a trade.

**The agent's plan and progress stream live.** `/api/chat` (SSE mode) emits a `plan` event the instant a plan is chosen — before any tool runs — followed by a `tool_start`/`tool_result` pair per step as the executor works through it, then the answer tokens, then a `done` event with citations, the tool trace, and a handful of deterministic follow-up `suggestions` templated off the answer's intent. The executor itself is unchanged either way: `execute()` (used by non-streaming callers/evals) is a thin wrapper over the same `execute_events()` generator that powers the live stream.

Refusals happen at three points: the retrieval threshold, the synthesis grounding rules, and the system prompt (which is built fresh per request from the live company roster — seeds plus whatever's been added — rather than a fixed list).

**Stack:** FastAPI + ChromaDB + BM25 (`rank_bm25`) backend, OpenAI embeddings, Claude for synthesis and routing, yfinance for market data, SEC EDGAR for on-demand filing ingest; React 19 + TypeScript + Vite frontend with zero-dependency SVG charts; one Docker image deployed on Render.

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
- `DATABASE_URL` — a `postgresql://` URL switches sessions/portfolio/watchlist (`app/storage.py`) from the sqlite default to Postgres; unset (the default) keeps everything on sqlite exactly as before. The filing corpus (chunks/facts/Chroma) is unaffected either way. Verified live against a throwaway Postgres container (session ordering, watchlist dedupe, portfolio upsert + the `cost_basis` migration, and `whatif()`) via a one-off manual script, not the pytest suite — the existing tests isolate each test with a fresh sqlite file per test (`setUp`), which doesn't carry over to a shared Postgres instance without added per-test cleanup this phase didn't build. The sqlite path is what the automated suite (`tests/`) actually exercises.

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

Any other company doesn't need a script — ask about it in the running app (or use the sidebar search) and `ingest/pipeline.py` runs the same steps for that one ticker into `data/dynamic/`, add-only into the existing Chroma collection.

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
| `/api/chat` | POST | `{ "message", "session_id", "stream", "client_id" }` — main endpoint, handles session context. Streaming mode emits `session` → `plan` → (`tool_start`/`tool_result`)* → `token`* → `done` (citations, tool trace, `suggestions`) |
| `/api/stream` | GET | `?q=` — same SSE event sequence as `/api/chat` streaming, without session/client context |
| `/api/research` | GET | `?q=` — full result in one JSON response |
| `/api/sessions/{id}` | GET | Stored messages for a session |
| `/api/quote/{ticker}` | GET | Live quote from yfinance |
| `/api/quotes` | GET | `?tickers=AAPL,JPM` — batch quotes (watchlist panel) |
| `/api/news/{ticker}` | GET | Recent third-party headlines (yfinance, RSS fallback) |
| `/api/history` | GET | `?tickers=&period=1mo` — batch price history (charts) |
| `/api/screener` | GET | Derived-metric snapshot for all six companies (`?live=0` to skip quotes) |
| `/api/watchlist` | GET/POST | `?client_id=` list / `{ "client_id", "ticker" }` add |
| `/api/watchlist/{ticker}` | DELETE | `?client_id=` — remove a ticker |
| `/api/portfolio` | GET/POST | `?client_id=` plain holdings list / `{ "client_id", "ticker", "shares", "cost_basis" }` set |
| `/api/portfolio/{ticker}` | DELETE | `?client_id=` — remove a holding |
| `/api/portfolio/analysis` | GET | `?client_id=` — live valuation, P&L, and HHI concentration (the computed view) |
| `/api/portfolio/whatif` | POST | `{ "client_id", "trades": [{ "ticker", "delta_shares" }] }` — simulate a hypothetical trade; never persisted |
| `/api/portfolio/benchmark` | GET | `?client_id=&period=3mo` — current holdings/weights vs. SPY over a period, as two chartable OHLCV-shaped series |
| `/api/insight/{ticker}` | GET | Full insight brief: quote, valuation, peer ranks, filing narrative |
| `/api/insight/{ticker}/stream` | GET | SSE — `card` event (deterministic data) immediately, then narrative tokens, then `done` |
| `/api/companies` | GET | Currently-loaded companies (seeds + anything added on demand) |
| `/api/universe/search` | GET | `?q=` — ranked ticker/company-name search over the full SEC EDGAR directory |
| `/api/universe/resolve` | GET | `?q=` — resolve an exact ticker/cashtag against EDGAR (chat's own resolution path) |
| `/api/companies/{ticker}/ingest` | POST | Start (or dedupe into) an on-demand ingest job; `202`-style job snapshot |
| `/api/companies/{ticker}/ingest/status` | GET | Poll an ingest job's status/stage/progress |
| `/api/companies/{ticker}/ingest/stream` | GET | SSE — staged `progress` events (download/parse/chunk/embed) then `done` |
| `/api/corpus/status` | GET | Corpus/store health |
| `/health` | GET | Health check |

Watchlist and portfolio are keyed by an anonymous `client_id` (a UUID the frontend generates and stores in `localStorage`) — no accounts required.

## Evaluate

```bash
python eval/run_eval.py                                                   # filing regression suite
python eval/run_eval.py eval/questions_v3.yaml eval/results_v3.md eval/results_v3.json   # valuation/explain-move/insight/news suite
python eval/run_eval.py eval/questions_v5.yaml eval/results_v5.md eval/results_v5.json   # cross-company valuation comparison suite
python -m unittest discover -s tests             # offline unit tests (no LLM calls)
```

The regression suite passes at the same threshold with the reranker on or off (`FINSIGHT_USE_RERANKER=0`); deploy runs with it off to fit the free-tier RAM ceiling. The V3 suite (`questions_v3.yaml`) runs with the hybrid LLM router on by default and checks tool selection, citation namespaces, and grounding language (freshness, advice disclaimers) for those intents. The V5 suite (`questions_v5.yaml`) checks that cross-company comparison cites **both** companies' own calculation evidence (not the same ticker's chunk twice); every suite also carries an unconditional `suggestions_field_present` regression guard now that every answer path attaches a `suggestions` list. Portfolio/what-if/holdings-aware questions aren't in any YAML suite — `run_eval.py` has no fixture-seeding hook for a `client_id`'s holdings — so those are covered by `tests/test_portfolio_whatif.py`, `tests/test_portfolio_benchmark.py`, and `tests/test_portfolio_agent.py` instead.

**Threshold calibration:** `python eval/calibrate_threshold.py` runs a small labeled probe set (real in-corpus hits, a boundary case, and known out-of-corpus questions) through retrieval only — no LLM cost — and prints the top-similarity distribution and the gap `DENSE_SIM_THRESHOLD` sits in, so the "provisionally calibrated" value in `app/config.py` can be checked against current evidence rather than taken on faith.

## Deploy

One Docker service: a multi-stage build compiles the React SPA (Node stage) and copies it into the FastAPI image (Python stage), which serves both the API and the static frontend.

Deployed on [Render](https://render.com)'s free tier via `render.yaml`:

1. Connect the GitHub repo in the Render dashboard → New → Blueprint.
2. Set `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` as secrets when prompted (they're marked `sync: false` in `render.yaml`, so Render asks for them rather than reading them from the repo).
3. Push to `master` — Render builds the Dockerfile and deploys automatically on every push.

The reranker is off in deploy (`FINSIGHT_USE_RERANKER=0`, baked into the Dockerfile) since `sentence-transformers`/`torch` would exceed the free tier's 512MB RAM. The vector store and chunk/fact stores for the six seed companies are committed to the repo so the image builds directly from git with no re-ingest or re-embedding step. The watchlist/portfolio/session SQLite database and any on-demand-added companies (`data/dynamic/`, gitignored) live on ephemeral disk and reset on redeploy; the frontend mirrors tickers and share counts in `localStorage` and re-syncs them on load, so a user's watchlist/portfolio *selections* survive a redeploy even though the server-side rows — and any added companies' filing data — do not. Re-adding a company after a redeploy is the same ~1-minute flow as adding it the first time.

**Optional Postgres.** Setting `DATABASE_URL` (e.g. to Render's own free Postgres add-on — note its 90-day expiry on the free tier) moves sessions/portfolio/watchlist off the ephemeral disk so they survive a redeploy; the filing corpus still ships in the image either way. This isn't wired into `render.yaml` by default — it's opt-in, not required for the demo to work.

## Repo layout

```
ingest/     download  parse  chunk  embed  xbrl  validate  pipeline (on-demand per-ticker ingest)
app/        main  research  config  audit  corpus  synthesize  retrieve  router  decompose  facts
            rerank  screener  watchlist  portfolio  insight  universe (open-universe registry
            + ticker/name resolution)  ingest_jobs (async ingest orchestration + LRU eviction)
            suggest (deterministic follow-up chips)  storage (sqlite/Postgres backend selection)
app/agent/  executor  router_llm  router_plan  context  session
app/tools/  filings  market  news  compute  screen  portfolio_ctx  registry
web/        Vite + React + TS frontend (src/components, src/hooks, src/lib)
eval/       questions.yaml  questions_market.yaml  questions_hybrid.yaml  questions_v3.yaml
            questions_v5.yaml  questions_smoke.yaml  run_eval.py  calibrate_threshold.py
static/     index.html (legacy fallback)  dist/ (built SPA, gitignored)
tests/
data/       raw/  parsed/  chunks.json  facts.json  chroma/  manifest.json  dynamic/ (on-demand
            ingested companies, gitignored — see Deploy)
```

All tunables are in `app/config.py`.

## Future work

- **Alerts/digest on portfolio moves or news** — deliberately out of scope: Render's free tier spins the service down after ~15 minutes idle, so there's no scheduler or push channel to fire an alert while nothing is running. A "digest" would only ever fire when someone's already looking at the app, which the existing portfolio/news chat answers already cover.
- **Lot-level cost basis** — `app/portfolio.py` intentionally tracks one average `cost_basis` per ticker, overwritten on each update, not individual purchase lots. Real lot tracking is a meaningful schema change for numbers that barely move the demo; the current model is documented as an explicit non-goal at the top of that file.
