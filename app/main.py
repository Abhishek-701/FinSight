"""FastAPI entrypoint for the financial research MVP.

Run the four checkpoint questions:  python -m app.main
(FastAPI/SSE endpoint is added to this file in Phase 4.)
"""

import json
import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app import config, research
from app.agent import session
from app.tools import market

xbrl_lookup = research.xbrl_lookup
prepare = research.prepare
answer = research.answer


app = FastAPI()
log = logging.getLogger("fairway.api")

INDEX_HTML = config._ROOT / "static" / "index.html"
_RATE_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    stream: bool = False


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
    manifest_path = config._ROOT / "data" / "manifest.json"
    chunks_path = config.CHUNKS_PATH
    facts_path = config.FACTS_PATH
    manifest = []
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunk_count = 0
    if chunks_path.exists():
        chunk_count = len(json.loads(chunks_path.read_text(encoding="utf-8")))
    return {
        "companies": config.COMPANIES,
        "manifest_count": len(manifest),
        "chunk_count": chunk_count,
        "facts_present": facts_path.exists(),
        "chroma_present": (config._ROOT / "data" / "chroma").exists(),
        "filings": manifest,
    }


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
    return FileResponse(INDEX_HTML)


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
    session.append(sid, "user", req.message)
    if req.stream:
        def events():
            yield research.sse("session", {"session_id": sid})
            yield from research.stream_events(req.message)
        return StreamingResponse(events(), media_type="text/event-stream")

    result = research.run(req.message)
    result["session_id"] = sid
    session.append(sid, "assistant", result["answer"], {"tool_calls": result.get("tool_calls", [])})
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
        "session_store": session.status(),
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
