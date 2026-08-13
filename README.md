# FinSight

FinSight is a grounded financial research assistant. It answers questions from SEC filings (10-K and, when ingested, the latest 10-Q), live delayed market data, and the user's own portfolio. Every filing figure is cited to a chunk or XBRL fact. If the corpus does not support the answer, it refuses rather than guessing.

Six companies ship pre-indexed: Apple, JPMorgan Chase, Walmart, Coca-Cola, NVIDIA, and Caterpillar. Any other US-listed name can be added from chat or the sidebar. FinSight fetches the filing from SEC EDGAR, parses and indexes it, then answers the original question. Market-only questions (price, market cap) work immediately without ingest.

Chat is a visible agent. The tool plan shows up before anything runs, each step reports running/done/error with latency, and the answer streams in after. Follow-up chips at the end of a reply are templated off the intent, not invented by the model.

Live demo: https://finsight-vh4y.onrender.com

The demo runs on Render's free tier. After about 15 minutes idle the service sleeps, so the first request can take 30 to 60 seconds. After that it is fast. Adding a company takes under a minute on top of a warm start. Companies added on the demo live on ephemeral disk and disappear on redeploy. The six seeds always come back with the image.

Sign in with Google is optional. Without it, portfolio, watchlist, and chat key off a browser `client_id`. With it, that anonymous data can be claimed onto a durable account (Postgres when `DATABASE_URL` is set).

## Decisions and tradeoffs

This section is for whoever is reading the repo as a take-home, not as an operator.

**Refuse instead of sounding helpful.** A finance chatbot that invents a number is worse than a 404. Retrieval has a dense-similarity gate. Synthesis is temp-0 and is told to say "not found" rather than substitute a nearby metric. A company that is not on EDGAR, or that has no 10-K, is refused. A real company that is not loaded yet is not refused. It gets an "Add TSLA" offer. Those are different failure modes and they are routed differently.

**Regex first, LLM second.** Plain lookups, screener superlatives, segments, portfolio questions, and cross-company valuation comparison never call a router model. Ambiguous mixed filing+market questions (valuation, "why did the stock move", insight-brief phrasing) get one structured JSON plan from Haiku. That plan is allowlisted and argument-checked before it runs. If the call fails or the plan is junk, a regex fallback for the same intents takes over. `FINSIGHT_USE_LLM_ROUTER=0` still answers those questions, just without the LLM planner.

**The model does not get to pick whose portfolio to read.** `portfolio_context`, `portfolio_whatif`, and `portfolio_filings` have no `client_id` in their schemas. The executor injects the authenticated identity from the request. A what-if trade is parsed from the question with a small regex, not by asking the model to author a trade. Cross-company P/E comparison is the same idea: `compute_metric` is scoped to one ticker at a time so you cannot get NVIDIA's ratio cited as Apple's.

**Citations are the product, not decoration.** Filing answers point at chunk ids or XBRL facts. Valuation ratios get a `-CALC-` chunk that shows the inputs. News is attributed to publisher and date and is never treated as the cause of a price move. "Why is NVIDIA down" states the move from market data, then lists disclosed risks and headlines as context. The synthesis prompt is explicit that a filing did not cause the move.

**Open universe, but one ingest at a time.** The six seeds are in git so the image boots without re-embedding. Everything else is add-only into the existing Chroma collection. Two concurrent embeds would blow the 512MB deploy ceiling, so ingest is capped at one job and the dynamic roster LRU-evicts at 12. Name resolution is three-tier (ticker, casual name with Inc./Corp stripped, then a subphrase in a sentence) against EDGAR's directory, not a hardcoded alias list.

**Eval scores the number, not the vibe.** Cases in `eval/cases/` declare gold figures, required chunk/fact ids, and optional judge rubrics. Layer 1 is retrieval hit@k with no synthesis. Layer 2 checks the gold number and that every number in the answer appears in the cited evidence. Layer 3 is a temp-0 Haiku judge that only sees cited evidence; a judge pass cannot rescue a wrong figure. There is no 80% suite fudge. Old `questions.yaml` files that scored "citation present" and "tool was selected" are gone.

**What I left out on purpose.** Alerts and email digests need a process that is awake. This service is not. Lot-level cost basis is a real schema change for P&L that barely moves a demo, so holdings keep one average cost per ticker. The cross-encoder reranker is on locally and off in the deploy image because torch does not fit in 512MB. The similarity threshold is 0.50 and the gap around it is thin. I left it there rather than pretend a 10-probe calibration was decisive.

**Stack choices.** FastAPI, Chroma, BM25, OpenAI embeddings, Claude for synthesis, yfinance for delayed quotes, EDGAR for filings. React + Vite on the front, SVG charts with no charting library. One Docker image. Sqlite locally, Postgres when `DATABASE_URL` is set. User data and the filing corpus are separate stores so a Render disk wipe does not require re-embedding Apple.

## Try it

Ask things like:

- "What was Apple's revenue in fiscal 2024?" Structured XBRL fact, cited.
- "Compare NVIDIA and Caterpillar's operating margins." Per-company evidence, not one blended number.
- "Which company has the highest operating margin?" Screener ranking, not a RAG guess.
- "What are JPMorgan's key risks?" Item 1A retrieval, source chunks shown.
- "Tell me about Walmart." Four focused topic passes (business, financials, risks, outlook) instead of one 24-chunk dump.
- "Is NVIDIA expensive right now?" P/E and P/S from a live quote and filing fundamentals, compared to the other seeds. Snapshot, not advice.
- "Why is NVIDIA down this month?" Price move first, then risks and headlines as context.
- "Give me an insight brief on Apple." Quote, valuation, peer ranks, filing narrative.
- "Is Apple or NVIDIA more expensive?" Separate P/E and P/S per company, as a table, no LLM router.
- "What's the latest news on Apple?" Headlines with publisher and date.
- "How is my portfolio doing?" / "How concentrated am I?" Live value, P&L where you entered cost, HHI.
- "What if I bought 10 more shares of AAPL?" Simulation. Nothing is traded.
- "Has my portfolio beaten the market?" Current weights vs SPY over the period, only when asked.
- "Which of my holdings has the most rate exposure?" Filing RAG scoped to what you actually hold.

Follow-ups like "and its net income?" resolve to the last company. "What about AAPL?" keeps the prior intent (a valuation follow-up stays a valuation question).

A company that is not loaded yet: "What was Tesla's revenue last year?" Chat offers "+ Add TSLA". Progress is download, parse, index, done. Then the original question answers. "What's Rivian's stock price?" does not need the add step.

The sidebar also has Screener, Compare (overlaid price history), Portfolio (holdings, what-if, vs S&P 500), and Insight (one-page brief). Watchlist is the right-hand panel.

## How it works

```
question
  → company router     regex/alias, no LLM
                       single | decompose | needs_ingest | oos | clarify
  → offer ingest       real ticker, not loaded: "+ Add TSLA"
                       market-only questions skip this
  → XBRL lookup        structured facts for known metrics
  → tool router        regex, or one Haiku JSON plan for mixed questions
  → tools              filings, market, news, compute, screener, portfolio
  → threshold gate     refuse if top dense similarity is below 0.50
  → synthesize         temp-0 Claude, streamed, inline citations
```

Quarterly wording ("last quarter", "10-Q") prefers 10-Q facts and chunks. Fiscal-year wording stays on the 10-K. Mixing a FY number into a "last quarter" answer is an eval failure.

## Run locally

Python 3.11+ and Node.js 22+. You need `OPENAI_API_KEY` (embeddings, `text-embedding-3-small`) and `ANTHROPIC_API_KEY` (synthesis, `claude-sonnet-4-6`).

Optional:

- `FINSIGHT_API_KEY` requires `x-api-key` on API routes
- `FINSIGHT_RATE_LIMIT_PER_MINUTE` (default 60)
- `FINSIGHT_USE_RERANKER=0` skips the cross-encoder (default on locally, off in the deploy image)
- `FINSIGHT_USE_LLM_ROUTER=0` forces the regex-only tool router
- `FINSIGHT_ROUTER_MODEL` (default `claude-haiku-4-5`)
- `DATABASE_URL` a `postgresql://` URI. Unset keeps sqlite at `data/sessions.sqlite3`. Filing stores are unchanged.
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` for Sign in with Google. Without them, Sign-in is hidden.
- `FINSIGHT_BASE_URL` public origin for the OAuth redirect (default `http://localhost:8000`)
- `FINSIGHT_COOKIE_SECURE=1` on HTTPS
- `FINSIGHT_ADMIN_EMAILS` comma-separated, for the admin dashboard

Google Cloud: OAuth 2.0 Web client, redirect URIs `http://localhost:8000/api/auth/google/callback` locally and `{FINSIGHT_BASE_URL}/api/auth/google/callback` in production. No trailing slash on `FINSIGHT_BASE_URL`.

```bash
git clone https://github.com/Abhishek-701/FinSight.git
cd FinSight

python -m venv .venv
# Windows:       .venv\Scripts\activate
# macOS/Linux:   source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
```

The reranker downloads `sentence-transformers` and torch on first run. Set `FINSIGHT_USE_RERANKER=0` to skip that.

The repo ships with `data/chroma/`, `data/chunks.json`, and `data/facts.json`. Rebuild from EDGAR only if you need to:

```bash
python ingest/download.py
python ingest/parse.py
python ingest/chunk.py
python ingest/embed.py
python ingest/xbrl.py
```

Any other ticker is ingested from the running app via `ingest/pipeline.py` into `data/dynamic/`.

```bash
python -m uvicorn app.main:app --port 8000

cd web
npm install
npm run dev
# http://127.0.0.1:5173  (proxies /api to :8000)
```

`npm run build` from `web/` writes the SPA into `static/dist/`. FastAPI serves it at `/` when that folder exists. Without it, http://127.0.0.1:8000 is the legacy page.

## API

| Endpoint | Method | Description |
|---|---|---|
| `/api/chat` | POST | `{ "message", "session_id", "stream", "client_id" }`. SSE: `session` then `plan` then `tool_start`/`tool_result` then `token` then `done` |
| `/api/stream` | GET | `?q=` same SSE sequence, no session |
| `/api/research` | GET | `?q=` one JSON result |
| `/api/sessions/{id}` | GET | stored messages |
| `/api/quote/{ticker}` | GET | live quote |
| `/api/quotes` | GET | `?tickers=AAPL,JPM` |
| `/api/news/{ticker}` | GET | headlines |
| `/api/history` | GET | `?tickers=&period=1mo` |
| `/api/screener` | GET | derived metrics (`?live=0` skips quotes) |
| `/api/watchlist` | GET/POST | `?client_id=` |
| `/api/watchlist/{ticker}` | DELETE | `?client_id=` |
| `/api/portfolio` | GET/POST | holdings; POST sets shares and optional cost basis |
| `/api/portfolio/{ticker}` | DELETE | |
| `/api/portfolio/analysis` | GET | live P&L and HHI |
| `/api/portfolio/whatif` | POST | `{ "client_id", "trades": [{ "ticker", "delta_shares" }] }` not persisted |
| `/api/portfolio/benchmark` | GET | holdings vs SPY |
| `/api/insight/{ticker}` | GET | full brief |
| `/api/insight/{ticker}/stream` | GET | SSE: `card` then narrative tokens then `done` |
| `/api/companies` | GET | seeds plus anything added |
| `/api/universe/search` | GET | `?q=` EDGAR name/ticker search |
| `/api/universe/resolve` | GET | `?q=` exact ticker/cashtag |
| `/api/companies/{ticker}/ingest` | POST | start or join an ingest job |
| `/api/companies/{ticker}/ingest/status` | GET | |
| `/api/companies/{ticker}/ingest/stream` | GET | SSE progress |
| `/api/corpus/status` | GET | |
| `/health` | GET | |

Auth: `GET /api/auth/google/login`, `GET /api/auth/google/callback`, `GET /api/auth/me`, `POST /api/auth/logout`, `POST /api/auth/claim`. Watchlist and portfolio use the anonymous `client_id` or the signed-in user id.

## Evaluate

```bash
python eval/run_eval.py --tag smoke --layer retrieve
python eval/run_eval.py --tag smoke --layer answer
python eval/run_eval.py --layer judge
python eval/run_eval.py --tag quarterly
python eval/run_eval.py --id aapl-opinc-fy2025
python -m unittest discover -s tests
```

`--layer retrieve` is the cheap loop while changing ingest or chunking. `--layer answer` is gold numbers plus faithfulness. `--layer judge` is the acceptance run. `eval/calibrate_threshold.py` probes retrieval similarity only (no LLM) so you can see where 0.50 sits against current evidence.

## Deploy

One Docker image: Node stage builds the SPA, Python stage serves API and static files. `render.yaml` is the blueprint.

1. Connect the GitHub repo in Render, New, Blueprint.
2. Set secrets (`sync: false` in the blueprint): `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and for durable login `DATABASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `FINSIGHT_BASE_URL`, optionally `FINSIGHT_ADMIN_EMAILS`. `FINSIGHT_COOKIE_SECURE` is already `1`.
3. Push to `master`.

The reranker is off in the image. Seed chroma/chunks/facts are in git, so the build does not re-embed. Dynamic companies reset on redeploy. Set `DATABASE_URL` if you want users, sessions, portfolio, watchlist, audit, and metrics to survive that.

## Repo layout

```
ingest/     download  parse  chunk  embed  xbrl  validate  pipeline
app/        main  research  config  retrieve  synthesize  router  facts
            screener  watchlist  portfolio  insight  universe  ingest_jobs
            suggest  storage  auth  audit  metrics  admin
app/agent/  executor  router_llm  router_plan  context  session
app/tools/  filings  market  news  compute  screen  portfolio_ctx  registry
web/        Vite + React + TS
eval/       cases/  run_eval.py  judge.py  calibrate_threshold.py
tests/
data/       raw/  parsed/  chunks.json  facts.json  chroma/  dynamic/
```

Tunables are in `app/config.py`.
