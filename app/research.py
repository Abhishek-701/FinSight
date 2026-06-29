"""MVP research orchestration.

This module wraps the existing deterministic RAG/XBRL pipeline in a small
plan -> act -> reflect flow. The tools are plain Python functions so the
behavior remains easy to inspect and compare in evals.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterable

from app import config, decompose, facts as facts_mod, retrieve, router, synthesize
from app.agent.context import ConversationContext, contextualize_question
from app.agent import executor
from app.agent.router_llm import route_tools

# Matches both RAG chunk IDs (e.g. AAPL-0044) and XBRL chunk IDs (e.g. AAPL-XBRL-OperatingIncomeLoss).
CITATION_RE = re.compile(r"\[([A-Z]{2,4}-[A-Za-z0-9_-]+)\]")

CLARIFY_MSG = ("I can only answer about Apple, JPMorgan Chase, Walmart, Coca-Cola, NVIDIA, and "
               "Caterpillar. Which company do you mean?")

_SEGMENT_BAIL_RE = re.compile(
    r"\b(sam'?s?\s*club|data\s+center|datacenter|financial\s+products?\s+(segment|revenues?)|"
    r"me&t\b|wholesale\s+club)\b",
    re.I,
)
_YOY_RE = re.compile(
    r"\b(change|increase|decrease|from\s+\d{4}\s+to|year.over.year|yoy|prior\s+year"
    r"|compar.{0,10}year|both\s+year|each\s+year)\b",
    re.I,
)

_SUMMARY_INTENT_RE = re.compile(
    r"\b(tell\s+me\s+(more|about|everything)|what\s+(else|can\s+you|do\s+you\s+know)|"
    r"overview|summarize?|summary|describe|profile|all\s+about|general(ly)?)\b",
    re.I,
)

# When any of these topic words appear alongside a summary-intent phrase, the question
# is about ONE specific aspect of the company, not the company broadly. These questions
# belong in focused RAG, not the 4-topic full-company summary path.
# Patterns ending in \w* absorb plurals and derivations (risk→risks, strateg→strategy/strategies,
# competit→competition/competitive, operat→operations/operational, regulat→regulation/regulatory).
_SPECIFIC_TOPIC_RE = re.compile(
    r"\b(risks?\b|strateg\w+|income|profit|segment\w*|products?|services?|"
    r"competit\w+|debt|equity|employ\w+|headcount|guidance|"
    r"cash\s+flow|earnings|growth|forecast|valuation|"
    r"balance\s+sheet|operat\w+|market\s+share|dividend\w*|capex|margin|"
    r"eps|litigation|regulat\w+|compliance|supply\s+chain|workforce)",
    re.I,
)

# Fixed (suffix, title) pairs for per-topic synthesis on broad summary questions.
# Each topic gets its own retrieval call and its own 600-token synthesis call.
# The model never sees more than one topic's chunks at once, preventing the
# multi-section skeleton it generates when all 24 chunks arrive together.
_SUMMARY_TOPICS: list[tuple[str, str]] = [
    ("business overview main products services operating segments", "Business Overview"),
    ("revenue operating income net income financial performance results", "Financial Performance"),
    ("key risk factors business operational and regulatory risks", "Key Risks"),
    ("strategy competitive position growth initiatives outlook", "Strategy & Outlook"),
]


def _refusal(reason: str, msg: str, meta: dict) -> dict:
    return {"answer": msg, "citations": [], "gaps": [], "refused": True,
            "refusal_reason": reason, **meta}


def _elapsed(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


def _rag_tool_name(route: dict) -> str:
    if route["mode"] == "clarify":
        return "refuse_or_clarify"
    if route["mode"] == "decompose":
        return "multi_company_compare"
    return "filing_rag"


def _company_name(ticker: str | None) -> str:
    return config.COMPANIES.get(ticker or "", "")


def _is_segment_question(question: str) -> bool:
    return bool(re.search(config.SEGMENT_INTENT_RE, question, re.I))


def _compound_parts(question: str) -> list[str]:
    if not re.search(config.COMPOUND_INTENT_RE, question, re.I):
        return []
    parts = [p.strip(" ?,") for p in re.split(r"\b(?:and|also|as well as)\b", question, flags=re.I)]
    return [p for p in parts if len(p.split()) >= 3]


def _is_summary_question(question: str, route: dict) -> bool:
    """True when the question asks for a broad overview of a single company as a whole.

    The 4-topic summary path (Business Overview / Financial Performance / Key Risks /
    Strategy & Outlook) is only correct when the user wants everything about a company,
    not when they ask about one specific aspect. _SPECIFIC_TOPIC_RE guards against
    "tell me about key risks" or "describe the strategy" triggering the full summary.
    """
    return (
        bool(_SUMMARY_INTENT_RE.search(question))
        and not bool(_SPECIFIC_TOPIC_RE.search(question))
        and route.get("mode") == "single"
        and not re.search(config.COMPUTE_INTENT_RE, question, re.I)
        and not detect_xbrl_metrics(question)
        and bool(route.get("tickers"))
    )


def _single_company_subs(question: str, ticker: str) -> list[dict]:
    # Broad summary questions are handled by _run_summary before this is called.
    # This function only needs to handle compound questions and single-query cases.
    parts = _compound_parts(question)
    if len(parts) <= 1:
        return [{"ticker": ticker, "query": question}]
    company = _company_name(ticker)
    subs = []
    for part in parts[: config.FANOUT_CAP]:
        query = part if company.lower() in part.lower() else f"{company} {part}"
        subs.append({"ticker": ticker, "query": query})
    return subs


def detect_xbrl_metrics(question: str) -> list[str]:
    """Return every configured XBRL metric mentioned in the question."""
    matched: list[str] = []
    for pattern, metric in config.XBRL_KEYWORD_MAP:
        if re.search(pattern, question, re.I) and metric not in matched:
            matched.append(metric)
    return matched


def plan(question: str, route: dict | None = None) -> dict:
    """Build the bounded MVP research plan for a question."""
    route = route or router.route(question)
    metrics = detect_xbrl_metrics(question)
    return route_tools(question, route, metrics)


def xbrl_lookup(question: str, route: dict) -> dict | None:
    """Check the XBRL fact store for a numeric answer. Returns XBRL meta dict or None."""
    mode = route["mode"]
    tickers = route["tickers"]

    if _SEGMENT_BAIL_RE.search(question) or _is_segment_question(question):
        return None

    matched_metrics = detect_xbrl_metrics(question)
    if not matched_metrics:
        return None

    is_yoy = bool(_YOY_RE.search(question))
    fact_list: list[dict] = []

    for metric in matched_metrics:
        if mode == "decompose":
            for ticker in tickers:
                if is_yoy:
                    rec, pri = facts_mod.query_yoy(metric, ticker)
                    if rec:
                        fact_list.append(rec)
                    if pri:
                        fact_list.append(pri)
                else:
                    f = facts_mod.query(metric, ticker)
                    if f:
                        fact_list.append(f)
        else:
            ticker = tickers[0] if tickers else None
            if not ticker:
                return None
            if is_yoy:
                rec, pri = facts_mod.query_yoy(metric, ticker)
                if rec:
                    fact_list.append(rec)
                if pri:
                    fact_list.append(pri)
            else:
                f = facts_mod.query(metric, ticker)
                if f:
                    fact_list.append(f)

    seen: set[tuple] = set()
    unique_facts: list[dict] = []
    for f in fact_list:
        key = (f["ticker"], f["concept"], f["label"])
        if key not in seen:
            seen.add(key)
            unique_facts.append(f)

    if not unique_facts:
        return None

    _, synthetic_chunks = synthesize.build_xbrl_context(unique_facts)
    return {
        "route": route,
        "sub_queries": [],
        "retrieval": [],
        "context_chunks": synthetic_chunks,
        "refused": False,
        "xbrl_hit": True,
        "xbrl_metrics": matched_metrics,
        "xbrl_metric": matched_metrics[-1],
    }


def prepare(question: str, route: dict | None = None) -> dict:
    """Route, retrieve, and apply the threshold gate. Returns everything except synthesis."""
    route = route or router.route(question)
    mode, tickers = route["mode"], route["tickers"]
    meta = {"route": route, "sub_queries": [], "retrieval": [], "xbrl_hit": False}

    if mode == "clarify":
        return _refusal("clarify", CLARIFY_MSG, meta)

    if mode == "decompose":
        subs = decompose.decompose(question, tickers)
    elif mode == "single":
        subs = _single_company_subs(question, tickers[0])
    else:
        subs = [{"ticker": None, "query": question}]
    meta["sub_queries"] = subs

    k = config.TOP_K_SINGLE if mode in ("single", "oos") else config.TOP_K_SUB
    all_chunks: dict[str, dict] = {}
    top_sims = []
    for sub in subs:
        res = retrieve.retrieve(sub["query"], [sub["ticker"]] if sub["ticker"] else None, k)
        top_sims.append(res["top_sim"])
        meta["retrieval"].append({"ticker": sub["ticker"], "query": sub["query"],
                                  "top_sim": round(res["top_sim"], 3),
                                  "chunk_ids": [c["chunk_id"] for c in res["chunks"]]})
        for chunk in res["chunks"]:
            if chunk["chunk_id"] not in all_chunks or chunk["fused_score"] > all_chunks[chunk["chunk_id"]]["fused_score"]:
                all_chunks[chunk["chunk_id"]] = chunk

    if top_sims and max(top_sims) < config.DENSE_SIM_THRESHOLD:
        return _refusal(
            "threshold",
            "I couldn't find this in the six filings I cover (Apple, JPMorgan Chase, Walmart, "
            "Coca-Cola, NVIDIA, Caterpillar), so I can't answer it.",
            meta,
        )

    chunks = sorted(all_chunks.values(), key=lambda c: c["fused_score"], reverse=True)
    meta["context_chunks"] = chunks[: config.MAX_CONTEXT_CHUNKS]
    meta["refused"] = False
    return meta


def reflect(meta: dict, answer_text: str) -> dict:
    """Record lightweight validation signals for the generated report."""
    cited = set(CITATION_RE.findall(answer_text))
    cited_tickers = {cid.split("-")[0] for cid in cited}
    requested_tickers = meta.get("route", {}).get("tickers", [])
    gaps = [config.COMPANIES[t] for t in requested_tickers if t not in cited_tickers]
    numeric_claim = bool(re.search(r"\d", answer_text))
    not_found = "not found" in answer_text.lower() or "cannot answer" in answer_text.lower()
    return {
        "citations_present": bool(cited),
        "numeric_claim_has_citation": not numeric_claim or bool(cited),
        "requested_tickers": requested_tickers,
        "cited_tickers": sorted(cited_tickers),
        "gaps": gaps,
        "not_found_detected": not_found,
    }


def _citation_payload(cited: Iterable[str], context_chunks: list[dict]) -> list[dict]:
    ctx = {c["chunk_id"]: c for c in context_chunks}
    return [{
        "chunk_id": cid,
        "company": ctx[cid]["company"],
        "section": ctx[cid].get("section_title") or ctx[cid].get("item") or "",
        "text": ctx[cid]["text"],
        "kind": ctx[cid].get("kind"),
        "data": ctx[cid].get("data", {}),
        "facts": ctx[cid].get("facts", []),
    } for cid in cited if cid in ctx]


def _merge_evidence(meta: dict, evidence: list[dict]) -> dict:
    """Attach tool evidence to the synthesis context without duplicating chunks."""
    if meta.get("refused"):
        return meta
    by_id: dict[str, dict] = {}
    for chunk in meta.get("context_chunks", []) + evidence:
        by_id[chunk["chunk_id"]] = chunk
    meta["context_chunks"] = list(by_id.values())[: config.MAX_CONTEXT_CHUNKS]
    return meta


def _prepare_with_tools(question: str, route: dict, research_plan: dict) -> tuple[dict, list[dict]]:
    context = {"question": question, "route": route}
    tool_calls, evidence = executor.execute(research_plan["actions"], context)
    meta = context.get("meta")
    if not meta and evidence:
        meta = {"route": route, "sub_queries": [], "retrieval": [], "context_chunks": evidence,
                "refused": False, "xbrl_hit": False}
    if not meta:
        tool_start = time.perf_counter()
        meta = prepare(question, route)
        tool_calls.append({
            "tool": _rag_tool_name(route),
            "status": "refused" if meta.get("refused") else "ok",
            "retrieval": meta.get("retrieval", []),
            "elapsed_ms": _elapsed(tool_start),
        })
    return _merge_evidence(meta, evidence), tool_calls


def _run_summary(question: str, ticker: str, route: dict, started: float) -> dict:
    """Per-topic retrieve-and-synthesize for broad summary questions.

    Iterates _SUMMARY_TOPICS. For each topic:
      1. Retrieve TOP_K_SUB chunks scoped to this ticker.
      2. If the top chunk scores below the threshold, skip the topic.
      3. Call synthesize_section (600 tokens max) — the model only sees one
         topic's chunks, so it writes prose, not a section skeleton.
      4. Prefix the paragraph with a ### heading and accumulate.

    The structure (headings, order) is fixed here in code. The model is only
    ever asked to write prose; it never sees the full 24-chunk context at once.
    """
    company = _company_name(ticker)
    all_chunks: dict[str, dict] = {}
    all_cited: set[str] = set()
    retrieval_log: list[dict] = []
    tool_calls: list[dict] = []
    sections: list[str] = []

    for suffix, title in _SUMMARY_TOPICS:
        query = f"{company} {suffix}"
        res = retrieve.retrieve(query, [ticker], config.TOP_K_SUB)
        retrieval_log.append({
            "ticker": ticker, "query": query,
            "top_sim": round(res["top_sim"], 3),
            "chunk_ids": [c["chunk_id"] for c in res["chunks"]],
        })
        if res["top_sim"] < config.DENSE_SIM_THRESHOLD:
            continue
        chunks = res["chunks"]
        for chunk in chunks:
            all_chunks[chunk["chunk_id"]] = chunk

        synth_t0 = time.perf_counter()
        paragraph = synthesize.synthesize_section(query, chunks)
        elapsed_synth = _elapsed(synth_t0)

        if paragraph.strip():
            cited_here = set(CITATION_RE.findall(paragraph))
            all_cited.update(cited_here)
            sections.append(f"### {title}\n{paragraph}")
            tool_calls.append({
                "tool": "synthesize_section", "topic": title, "status": "ok",
                "citations": sorted(cited_here), "elapsed_ms": elapsed_synth,
            })

    if not sections:
        meta = {"route": route, "sub_queries": [], "retrieval": retrieval_log, "xbrl_hit": False}
        return {
            **_refusal("threshold",
                       "I couldn't find enough information in the filings to summarize.",
                       meta),
            "plan": {}, "tool_calls": tool_calls, "elapsed_ms": _elapsed(started),
        }

    answer = f"## {company}\n\n" + "\n\n".join(sections)
    cited = sorted(all_cited)
    context_chunks = list(all_chunks.values())
    sub_queries = [{"ticker": ticker, "query": f"{company} {s}"} for s, _ in _SUMMARY_TOPICS]
    reflection = reflect({"route": route}, answer)

    return {
        "route": route,
        "sub_queries": sub_queries,
        "retrieval": retrieval_log,
        "context_chunks": context_chunks,
        "refused": False,
        "xbrl_hit": False,
        "answer": answer,
        "citations": cited,
        "citation_details": _citation_payload(cited, context_chunks),
        "gaps": reflection["gaps"],
        "reflection": reflection,
        "plan": {"strategy": "per_topic_summary", "topics": [t for _, t in _SUMMARY_TOPICS]},
        "tool_calls": tool_calls,
        "elapsed_ms": _elapsed(started),
    }


def finalize(question: str, meta: dict) -> dict:
    """Shared tail: synthesize, extract citations, and attach reflection metadata."""
    text = "".join(synthesize.stream_answer(question, meta["context_chunks"]))
    cited = sorted(set(CITATION_RE.findall(text)))
    reflection = reflect(meta, text)
    return {
        **meta,
        "answer": text,
        "citations": cited,
        "citation_details": _citation_payload(cited, meta["context_chunks"]),
        "gaps": reflection["gaps"],
        "refused": False,
        "reflection": reflection,
    }


def run(question: str, conversation_context: ConversationContext | None = None) -> dict:
    """Full non-streaming research run with plan, tool trace, and answer."""
    started = time.perf_counter()
    working_question, context_meta = contextualize_question(question, conversation_context)
    route = router.route(working_question)

    if _is_summary_question(working_question, route):
        result = _run_summary(working_question, route["tickers"][0], route, started)
        return {**result, "question": question,
                "contextualized_question": working_question,
                "conversation_context": context_meta}

    research_plan = plan(working_question, route)
    meta, tool_calls = _prepare_with_tools(working_question, route, research_plan)

    if meta.get("refused"):
        reflection = reflect(meta, meta["answer"])
        return {**meta, "plan": research_plan, "tool_calls": tool_calls,
                "reflection": reflection, "question": question,
                "contextualized_question": working_question,
                "conversation_context": context_meta,
                "elapsed_ms": _elapsed(started)}

    tool_start = time.perf_counter()
    result = finalize(working_question, meta)
    tool_calls.append({
        "tool": "synthesize_report",
        "status": "ok",
        "citations": result["citations"],
        "elapsed_ms": _elapsed(tool_start),
    })
    return {**result, "plan": research_plan, "tool_calls": tool_calls,
            "question": question, "contextualized_question": working_question,
            "conversation_context": context_meta,
            "elapsed_ms": _elapsed(started)}


def answer(question: str) -> dict:
    """Compatibility wrapper for CLI/eval callers."""
    return run(question)


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def stream_events(question: str, conversation_context: ConversationContext | None = None):
    """SSE generator: stream answer tokens, then a done event with metadata."""
    started = time.perf_counter()
    working_question, context_meta = contextualize_question(question, conversation_context)
    route = router.route(working_question)

    if _is_summary_question(working_question, route):
        ticker = route["tickers"][0]
        company = _company_name(ticker)
        all_chunks: dict[str, dict] = {}
        all_cited: set[str] = set()
        retrieval_log: list[dict] = []
        tool_calls: list[dict] = []
        acc: list[str] = []

        header = f"## {company}\n\n"
        yield sse("token", {"text": header})
        acc.append(header)

        for suffix, title in _SUMMARY_TOPICS:
            query = f"{company} {suffix}"
            res = retrieve.retrieve(query, [ticker], config.TOP_K_SUB)
            retrieval_log.append({
                "ticker": ticker, "query": query,
                "top_sim": round(res["top_sim"], 3),
                "chunk_ids": [c["chunk_id"] for c in res["chunks"]],
            })
            if res["top_sim"] < config.DENSE_SIM_THRESHOLD:
                continue
            chunks = res["chunks"]
            for chunk in chunks:
                all_chunks[chunk["chunk_id"]] = chunk

            section_header = f"### {title}\n"
            yield sse("token", {"text": section_header})
            acc.append(section_header)

            synth_t0 = time.perf_counter()
            para_acc: list[str] = []
            for token in synthesize.stream_section(query, chunks):
                acc.append(token)
                para_acc.append(token)
                yield sse("token", {"text": token})

            para_text = "".join(para_acc)
            cited_here = set(CITATION_RE.findall(para_text))
            all_cited.update(cited_here)
            tool_calls.append({
                "tool": "synthesize_section", "topic": title, "status": "ok",
                "citations": sorted(cited_here), "elapsed_ms": _elapsed(synth_t0),
            })

            sep = "\n\n"
            yield sse("token", {"text": sep})
            acc.append(sep)

        text = "".join(acc)
        cited = sorted(all_cited)
        context_chunks = list(all_chunks.values())
        reflection = reflect({"route": route}, text)
        citations_payload = _citation_payload(cited, context_chunks)
        yield sse("done", {
            "citations": citations_payload,
            "gaps": reflection["gaps"],
            "refused": False,
            "plan": {"strategy": "per_topic_summary", "topics": [t for _, t in _SUMMARY_TOPICS]},
            "tool_calls": tool_calls,
            "reflection": reflection,
            "question": question,
            "contextualized_question": working_question,
            "conversation_context": context_meta,
            "elapsed_ms": _elapsed(started),
        })
        return

    research_plan = plan(working_question, route)
    meta, tool_calls = _prepare_with_tools(working_question, route, research_plan)

    if meta.get("refused"):
        reflection = reflect(meta, meta["answer"])
        yield sse("token", {"text": meta["answer"]})
        yield sse("done", {"citations": [], "gaps": [], "refused": True,
                           "refusal_reason": meta["refusal_reason"],
                           "plan": research_plan, "tool_calls": tool_calls,
                           "reflection": reflection, "question": question,
                           "contextualized_question": working_question,
                           "conversation_context": context_meta,
                           "elapsed_ms": _elapsed(started)})
        return

    ctx = {c["chunk_id"]: c for c in meta["context_chunks"]}
    acc = []
    tool_start = time.perf_counter()
    for token in synthesize.stream_answer(working_question, meta["context_chunks"]):
        acc.append(token)
        yield sse("token", {"text": token})

    text = "".join(acc)
    cited = sorted(set(CITATION_RE.findall(text)))
    reflection = reflect(meta, text)
    tool_calls.append({
        "tool": "synthesize_report",
        "status": "ok",
        "citations": cited,
        "elapsed_ms": _elapsed(tool_start),
    })
    citations = [{
        "chunk_id": cid,
        "company": ctx[cid]["company"],
        "section": ctx[cid].get("section_title") or ctx[cid].get("item") or "",
        "text": ctx[cid]["text"],
        "kind": ctx[cid].get("kind"),
        "data": ctx[cid].get("data", {}),
        "facts": ctx[cid].get("facts", []),
    } for cid in cited if cid in ctx]
    yield sse("done", {"citations": citations, "gaps": reflection["gaps"], "refused": False,
                       "plan": research_plan, "tool_calls": tool_calls,
                       "reflection": reflection, "question": question,
                       "contextualized_question": working_question,
                       "conversation_context": context_meta,
                       "elapsed_ms": _elapsed(started)})
