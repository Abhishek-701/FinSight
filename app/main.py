"""FastAPI entrypoint for the financial research MVP.

Run the four checkpoint questions:  python -m app.main
(FastAPI/SSE endpoint is added to this file in Phase 4.)
"""

import json
import logging
import time
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime

from fastapi import Header, HTTPException, Request
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import audit, config, corpus, insight, portfolio, research, screener, watchlist
from app.agent import session
from app.agent.context import from_history
from app.tools import market

xbrl_lookup = research.xbrl_lookup
prepare = research.prepare
answer = research.answer


app = FastAPI()
log = logging.getLogger("fairway.api")

INDEX_HTML = config._ROOT / "static" / "index.html"
_RATE_BUCKETS: dict[str, deque[float]] = defaultdict(deque)

_WEB_ASSETS = config.WEB_DIST / "assets"
if _WEB_ASSETS.exists():
    app.mount("/assets", StaticFiles(directory=_WEB_ASSETS), name="web-assets")


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    stream: bool = False


class WatchlistRequest(BaseModel):
    client_id: str
    ticker: str


class PortfolioRequest(BaseModel):
    client_id: str
    ticker: str
    shares: float


def _guard(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    if config.API_KEY and x_api_key != config.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    ident = request.client.host if request.client else "unknown"
    now = time.time()
    bucket = _RATE_BUCKETS[ident]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= config.RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    bucket.append(now)


def _corpus_status() -> dict:
    return corpus.status()


def _startup_errors() -> list[str]:
    errors = []
    if not config.CHUNKS_PATH.exists():
        errors.append(f"Missing {config.CHUNKS_PATH}")
    if not config.FACTS_PATH.exists():
        errors.append(f"Missing {config.FACTS_PATH}")
    if not (config._ROOT / "data" / "chroma").exists():
        errors.append("Missing data/chroma")
    return errors


@app.on_event("startup")
def validate_startup() -> None:
    errors = _startup_errors()
    if errors:
        raise RuntimeError("; ".join(errors))


@app.middleware("http")
async def request_logging(request: Request, call_next):
    request_id = uuid.uuid4().hex[:12]
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    response.headers["x-request-id"] = request_id
    log.info(json.dumps({
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status_code": response.status_code,
        "elapsed_ms": elapsed_ms,
    }))
    return response


@app.get("/")
def index():
    dist_index = config.WEB_DIST / "index.html"
    return FileResponse(dist_index if dist_index.exists() else INDEX_HTML)


@app.get("/api/stream")
def stream(q: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    return StreamingResponse(research.stream_events(q), media_type="text/event-stream")


@app.get("/api/research")
def research_result(q: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    return research.run(q)


@app.post("/api/chat")
def chat(req: ChatRequest, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    sid = req.session_id or session.new_session_id()
    prior_history = session.history(sid)
    conversation_context = from_history(prior_history)
    session.append(sid, "user", req.message)
    if req.stream:
        def events():
            yield research.sse("session", {"session_id": sid})
            yield from research.stream_events(req.message, conversation_context)
        return StreamingResponse(events(), media_type="text/event-stream")

    result = research.run(req.message, conversation_context)
    result["session_id"] = sid
    session.append(sid, "assistant", result["answer"], {"tool_calls": result.get("tool_calls", [])})
    audit.record({
        "session_id": sid,
        "question": req.message,
        "contextualized_question": result.get("contextualized_question"),
        "citations": result.get("citations", []),
        "tool_calls": result.get("tool_calls", []),
        "refused": result.get("refused", False),
    })
    return result


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    return {"session_id": session_id, "messages": session.history(session_id)}


@app.get("/api/quote/{ticker}")
def quote(ticker: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    return market.market_quote(ticker)


@app.get("/api/companies")
def companies():
    return {"companies": config.COMPANIES}


@app.get("/api/watchlist")
def get_watchlist(client_id: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    return {"client_id": client_id, "items": watchlist.items(client_id)}


@app.post("/api/watchlist")
def add_watchlist(req: WatchlistRequest, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    try:
        items = watchlist.add(req.client_id, req.ticker)
    except ValueError:
        raise HTTPException(status_code=400, detail="unsupported_ticker")
    return {"ok": True, "items": items}


@app.delete("/api/watchlist/{ticker}")
def remove_watchlist(ticker: str, client_id: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    return {"ok": True, "items": watchlist.remove(client_id, ticker)}


@app.get("/api/quotes")
def quotes(tickers: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    symbols = [t.strip().upper() for t in tickers.split(",") if t.strip()][:10]
    return {"quotes": [market.market_quote(t) for t in symbols]}


@app.get("/api/history")
def history(tickers: str, request: Request, x_api_key: str | None = Header(default=None),
            period: str = "1mo"):
    _guard(request, x_api_key)
    if period not in config.MARKET_HISTORY_PERIODS:
        raise HTTPException(status_code=400, detail="unsupported_period")
    symbols = [t.strip().upper() for t in tickers.split(",") if t.strip()][:6]
    return {"histories": [market.market_history(t, period) for t in symbols]}


@app.get("/api/screener")
def screener_snapshot(request: Request, x_api_key: str | None = Header(default=None), live: int = 1):
    _guard(request, x_api_key)
    return screener.snapshot(include_market=bool(live))


def _portfolio_view(client_id: str) -> dict:
    holdings = []
    priced_value = 0.0
    for holding in portfolio.items(client_id):
        quote = market.market_quote(holding["ticker"])
        if quote["status"] == "ok":
            price = quote["data"]["price"]
            change_percent = quote["data"]["change_percent"]
            value = price * holding["shares"] if price is not None else None
            market_status = "ok"
        else:
            price = value = change_percent = None
            market_status = "unavailable"
        if value is not None:
            priced_value += value
        holdings.append({
            "ticker": holding["ticker"],
            "company": holding["company"],
            "shares": holding["shares"],
            "updated_at": holding["updated_at"],
            "price": price,
            "value": value,
            "weight": None,
            "change_percent": change_percent,
            "market_status": market_status,
        })
    for holding in holdings:
        if holding["value"] is not None and priced_value:
            holding["weight"] = holding["value"] / priced_value
    return {
        "client_id": client_id,
        "as_of": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "total_value": priced_value,
        "holdings": holdings,
        "disclaimer": config.MARKET_DISCLAIMER,
    }


@app.get("/api/portfolio")
def get_portfolio(client_id: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    return _portfolio_view(client_id)


@app.post("/api/portfolio")
def set_portfolio_holding(req: PortfolioRequest, request: Request,
                          x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    try:
        portfolio.set_holding(req.client_id, req.ticker, req.shares)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _portfolio_view(req.client_id)


@app.delete("/api/portfolio/{ticker}")
def remove_portfolio_holding(ticker: str, client_id: str, request: Request,
                             x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    portfolio.remove(client_id, ticker)
    return _portfolio_view(client_id)


@app.get("/api/insight/{ticker}")
def insight_brief(ticker: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    ticker = ticker.upper()
    if ticker not in config.COMPANIES:
        raise HTTPException(status_code=400, detail="unsupported_ticker")
    return insight.brief(ticker)


@app.get("/api/insight/{ticker}/stream")
def insight_brief_stream(ticker: str, request: Request, x_api_key: str | None = Header(default=None)):
    _guard(request, x_api_key)
    ticker = ticker.upper()
    if ticker not in config.COMPANIES:
        raise HTTPException(status_code=400, detail="unsupported_ticker")
    return StreamingResponse(insight.stream_brief(ticker), media_type="text/event-stream")


@app.get("/api/corpus/status")
def corpus_status():
    return _corpus_status()


@app.get("/health")
def health():
    errors = _startup_errors()
    return {
        "ok": not errors,
        "errors": errors,
        "market_provider": config.MARKET_PROVIDER,
        "openai_configured": bool(config.OPENAI_API_KEY) if hasattr(config, "OPENAI_API_KEY") else None,
        "anthropic_configured": bool(config.ANTHROPIC_API_KEY) if hasattr(config, "ANTHROPIC_API_KEY") else None,
        "session_store": session.status(),
        "watchlist_store": watchlist.status(),
        "portfolio_store": portfolio.status(),
        "audit_log": audit.status(),
        "corpus": _corpus_status(),
        "external_state": {
            "postgres_configured": bool(config.DATABASE_URL),
            "redis_configured": bool(config.REDIS_URL),
        },
    }


def _print(question: str, res: dict) -> None:
    print("\n" + "=" * 78)
    print("Q:", question)
    print("route:", res["route"])
    for r in res.get("retrieval", []):
        print(f"  sub[{r['ticker']}] top_sim={r['top_sim']}  q={r['query'][:60]!r}")
    if res.get("refused"):
        print(f"REFUSED ({res['refusal_reason']}): {res['answer']}")
        return
    print("\nANSWER:\n" + res["answer"])
    print("\ncitations:", res["citations"])
    print("gaps:", res["gaps"])


if __name__ == "__main__":
    questions = [
        "What was NVIDIA's total revenue?",
        "Which of these companies reported the highest R&D spend?",
        "What was Tesla's revenue?",
        "What is Coca-Cola's employee attrition rate?",
    ]
    for q in questions:
        _print(q, answer(q))
