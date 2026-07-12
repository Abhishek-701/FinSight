"""Eval runner for the research MVP.

Runs eval/questions.yaml through the pipeline and writes both:
  - a markdown report for review
  - a JSON report with deterministic regression checks

Usage:  python eval/run_eval.py [questions.yaml] [results.md] [results.json]
        python eval/run_eval.py --only 3,7,12
        python eval/run_eval.py --category valuation,news
        python eval/run_eval.py --no-cache          # force live calls, bypass the disk cache
        python eval/run_eval.py --model claude-haiku-4-5   # cheap iteration only, never for
                                                             # the acceptance run (see README)

Every live call is disk-cached in eval/.cache/ keyed on (question, category, model, threshold,
corpus version, reranker/router flags) — a rerun where nothing relevant changed costs nothing.
Use --no-cache for the one run that must reflect current reality (before a commit that touches
synthesis/routing/prompt code).
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config, corpus, main  # noqa: E402

DEFAULT_Q = Path(__file__).parent / "questions.yaml"
DEFAULT_OUT = Path(__file__).parent / "results.md"
DEFAULT_JSON = Path(__file__).parent / "results.json"
CACHE_DIR = Path(__file__).parent / ".cache"
PASS_THRESHOLD = 0.80

# Catches the clearest violations of "a filing or news headline is never a verified cause of a
# price move" (see synthesize.EXPLAIN_MOVE_GUIDANCE). Not exhaustive — subtler causal phrasing
# needs human review of the answer text, same caveat as the rest of this deterministic suite.
_CAUSATION_RE = re.compile(
    r"\b(caused (the|a) (drop|decline|rally|surge|jump|rise|fall)|"
    r"(because|due to) (the )?(filing|10-K|news|headline|report)|"
    r"(the )?(filing|10-K|news|headline) (caused|is why|led to))\b",
    re.I,
)


def _cache_key(question: str, category: str) -> str:
    """Everything that could change the correct answer for this question, right now."""
    parts = [
        question, category, config.CHAT_MODEL, str(config.DENSE_SIM_THRESHOLD),
        corpus.version() or "", os.getenv("FINSIGHT_USE_RERANKER", ""),
        str(config.USE_LLM_ROUTER), config.ROUTER_MODEL,
    ]
    raw = "\x1f".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def _load_cached(key: str) -> dict | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_cache(key: str, res: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(key).write_text(json.dumps(res), encoding="utf-8")


def _md_escape(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ").strip()


def _add_check(checks: list[dict], name: str, passed: bool, detail: str) -> None:
    checks.append({"name": name, "passed": passed, "detail": detail})


def _expected_refusal(item: dict) -> bool | None:
    category = item.get("category", "")
    if category in {"router_clarify", "refusal_oos", "refusal_needs_ingest", "refusal_no_portfolio"}:
        return True
    if category == "router_edge":
        return None
    return False


def _score(item: dict, res: dict) -> dict:
    """Deterministic checks that are stable enough for CI/regression use."""
    checks: list[dict] = []
    category = item.get("category", "")
    expected_refusal = _expected_refusal(item)
    refused = res.get("refused", False)
    citations = res.get("citations", [])
    reflection = res.get("reflection", {})
    tool_names = [t.get("tool") for t in res.get("tool_calls", [])]
    market_citations = [c for c in citations if "-MKT-" in c]

    if expected_refusal is not None:
        _add_check(
            checks,
            "refusal",
            refused == expected_refusal,
            f"expected refused={expected_refusal}, got refused={refused}",
        )

    if category == "router_clarify":
        _add_check(
            checks,
            "clarify_reason",
            res.get("refusal_reason") == "clarify",
            f"reason={res.get('refusal_reason', '')}",
        )

    if category == "refusal_oos":
        _add_check(
            checks,
            "oos_reason",
            res.get("refusal_reason") == "threshold",
            f"reason={res.get('refusal_reason', '')}",
        )

    if category == "refusal_needs_ingest":
        # V4.1: a real, resolvable-but-uningested company (e.g. Amazon) now gets an actionable
        # ingest offer instead of a flat oos refusal — action/ticker must be present too.
        _add_check(
            checks,
            "needs_ingest_reason",
            res.get("refusal_reason") == "needs_ingest",
            f"reason={res.get('refusal_reason', '')}",
        )
        _add_check(
            checks,
            "needs_ingest_action",
            res.get("action") == "offer_ingest" and bool(res.get("ticker")),
            f"action={res.get('action', '')} ticker={res.get('ticker', '')}",
        )

    if category == "refusal_no_portfolio":
        # V4.3: run_eval.py never supplies a client_id (no fixture-seeding harness for
        # portfolios), so a portfolio question here always hits the "no client_id" refusal —
        # a cheap regression guard for the router intent match without needing live holdings.
        _add_check(
            checks,
            "portfolio_refusal_reason",
            res.get("refusal_reason") in ("missing_client_id", "empty_portfolio"),
            f"reason={res.get('refusal_reason', '')}",
        )

    if category == "refusal_undisclosed":
        answer = res.get("answer", "").lower()
        _add_check(
            checks,
            "undisclosed_not_fabricated",
            "not found" in answer or bool(res.get("gaps")),
            "requires not-found language or a gap for undisclosed metrics",
        )

    if not refused and category not in {"router_edge"}:
        _add_check(
            checks,
            "citations_present",
            bool(citations),
            f"citation_count={len(citations)}",
        )

    if category in {"market", "hybrid"}:
        _add_check(
            checks,
            "market_tool_selected",
            "market_quote" in tool_names or "market_history" in tool_names,
            f"tools={tool_names}",
        )
        _add_check(
            checks,
            "market_citation_present",
            bool(market_citations),
            f"market_citations={market_citations}",
        )
        _add_check(
            checks,
            "market_as_of_present",
            "as of" in res.get("answer", "").lower(),
            "market answers should state quote freshness",
        )

    if category == "hybrid":
        _add_check(
            checks,
            "filing_and_market_citations",
            bool(market_citations) and any("-MKT-" not in c for c in citations),
            f"citations={citations}",
        )

    calc_citations = [c for c in citations if "-CALC-" in c]

    if category == "valuation":
        _add_check(
            checks,
            "market_tool_selected",
            "market_quote" in tool_names,
            f"tools={tool_names}",
        )
        _add_check(
            checks,
            "calc_citation_present",
            bool(calc_citations),
            f"calc_citations={calc_citations}",
        )
        _add_check(
            checks,
            "non_calc_citation_present",
            any("-CALC-" not in c for c in citations),
            f"citations={citations}; a valuation ratio needs an XBRL or SCRN source alongside the calc",
        )
        _add_check(
            checks,
            "market_as_of_present",
            "as of" in res.get("answer", "").lower(),
            "valuation answers should state quote freshness",
        )
        _add_check(
            checks,
            "not_advice_language",
            "advice" in res.get("answer", "").lower(),
            "valuation answers should disclaim investment advice",
        )

    if category == "explain_move":
        _add_check(
            checks,
            "history_tool_selected",
            "market_history" in tool_names,
            f"tools={tool_names}",
        )
        _add_check(
            checks,
            "market_and_calc_citations",
            bool(market_citations) and bool(calc_citations),
            f"market={market_citations}; calc={calc_citations}",
        )
        _add_check(
            checks,
            "filing_citation_present",
            any("-MKT-" not in c and "-CALC-" not in c and "-NEWS-" not in c for c in citations),
            f"citations={citations}",
        )
        _add_check(
            checks,
            "market_as_of_present",
            "as of" in res.get("answer", "").lower(),
            "explain-move answers should state quote freshness",
        )
        news_call = next((t for t in res.get("tool_calls", []) if t.get("tool") == "news_headlines"), None)
        _add_check(
            checks,
            "news_evidence_present",
            # V4.2: explain_move always plans news_headlines now; a "-NEWS-" citation or the
            # tool having run at all (it may legitimately find zero headlines) both count.
            any("-NEWS-" in c for c in citations) or news_call is not None,
            f"news_citations={[c for c in citations if '-NEWS-' in c]}; news_tool_called={news_call is not None}",
        )
        _add_check(
            checks,
            "no_causation_language",
            not _CAUSATION_RE.search(res.get("answer", "")),
            "explain-move answers must not claim a filing or news headline caused the price move",
        )
    if category == "news":
        news_citations = [c for c in citations if "-NEWS-" in c]
        _add_check(
            checks,
            "news_citation_present",
            bool(news_citations),
            f"citations={citations}",
        )
        # The model's exact attribution phrasing varies run to run ("reported by X", "X reports",
        # "— X, <date>", ...) — regexing one phrasing is fragile. Instead check that at least
        # one REAL publisher name from the news evidence itself (data.items[].publisher, e.g.
        # "Barchart", "Motley Fool") appears literally in the answer — phrasing-agnostic.
        news_detail = next((d for d in res.get("citation_details", []) if d.get("kind") == "news"), None)
        publishers = [
            it.get("publisher", "") for it in (news_detail or {}).get("data", {}).get("items", [])
            if it.get("publisher")
        ]
        answer_text = res.get("answer", "")
        _add_check(
            checks,
            "attribution_present",
            any(pub in answer_text for pub in publishers),
            f"publishers_in_evidence={publishers}",
        )
        _add_check(
            checks,
            "no_causation_language",
            not _CAUSATION_RE.search(res.get("answer", "")),
            "news answers must not claim a headline caused a price move",
        )

    if category == "insight":
        _add_check(
            checks,
            "company_insight_tool_selected",
            "company_insight" in tool_names,
            f"tools={tool_names}",
        )
        namespaces = {
            "rag" if "-XBRL-" not in c and "-MKT-" not in c and "-CALC-" not in c and "SCRN-" not in c else
            "xbrl" if "-XBRL-" in c else "market" if "-MKT-" in c else "calc" if "-CALC-" in c else "screen"
            for c in citations
        }
        _add_check(
            checks,
            "citations_span_multiple_sources",
            len(namespaces) >= 3,
            f"citation_namespaces={sorted(namespaces)}",
        )

    _add_check(
        checks,
        "agent_metadata",
        bool(res.get("plan")) and bool(res.get("tool_calls")),
        "plan and tool_calls should be present",
    )

    if reflection and not refused:
        # Gated on not-refused like citations_present above: a refusal/offer message can
        # incidentally contain a digit (e.g. "fetch its latest 10-K") without making a numeric
        # CLAIM that needs evidence — this check is about answers, not refusal text.
        _add_check(
            checks,
            "numeric_claim_cited",
            reflection.get("numeric_claim_has_citation", True),
            "numeric answers should include at least one citation",
        )

    expected_fail = "DELIBERATE FAILURE" in item.get("note", "")
    passed = all(c["passed"] for c in checks)
    return {
        "passed": passed or expected_fail,
        "raw_passed": passed,
        "expected_fail": expected_fail,
        "checks": checks,
    }


def run(
    qpath: Path, outpath: Path, jsonpath: Path,
    only: set[int] | None = None, categories: set[str] | None = None,
    no_cache: bool = False, model_override: str | None = None,
) -> None:
    all_items = yaml.safe_load(qpath.read_text(encoding="utf-8"))
    if not all_items:
        raise SystemExit(f"No questions found in {qpath}")

    # id = 1-based position in the YAML file, preserved even when filtering, so --only 7
    # unambiguously means "question 7 in questions.yaml" and reports stay cross-referenceable.
    numbered = list(enumerate(all_items, 1))
    if only:
        numbered = [(i, it) for i, it in numbered if i in only]
    if categories:
        numbered = [(i, it) for i, it in numbered if it.get("category", "") in categories]
    if not numbered:
        raise SystemExit("No questions matched --only/--category filters")

    orig_chat_model = config.CHAT_MODEL
    if model_override:
        config.CHAT_MODEL = model_override
        print(f"NOTE: using {model_override} instead of {orig_chat_model} — "
              f"structural-check iteration only, not a valid acceptance run.\n")

    rows, details, json_rows = [], [], []
    n_cached = 0
    try:
        for i, it in numbered:
            q = it["question"]
            cat = it.get("category", "")
            key = _cache_key(q, cat)
            cached = None if no_cache else _load_cached(key)
            if cached is not None:
                res = cached
                n_cached += 1
                print(f"[{i}/{len(all_items)}] (cached) {q[:70]}")
            else:
                print(f"[{i}/{len(all_items)}] {q[:70]}")
                res = main.answer(q)
                _save_cache(key, res)
            score = _score(it, res)
            top = max((r["top_sim"] for r in res.get("retrieval", [])), default=0.0)
            refused = res.get("refused", False)
            reason = res.get("refusal_reason", "") if refused else ""
            cites = ", ".join(res.get("citations", []))
            gaps = ", ".join(res.get("gaps", []))
            plan_actions = ", ".join(a["tool"] for a in res.get("plan", {}).get("actions", []))
            tool_status = ", ".join(f"{t['tool']}:{t['status']}" for t in res.get("tool_calls", []))

            rows.append(
                f"| {i} | {_md_escape(cat)} | {_md_escape(q)} | {res['route']['mode']} | "
                f"{'yes' if refused else 'no'} | {reason} | {top:.3f} | {_md_escape(cites)} | "
                f"{_md_escape(gaps)} | {'yes' if score['passed'] else 'no'} | "
                f"{'yes' if score['expected_fail'] else 'no'} | {_md_escape(plan_actions)} |"
            )

            sub = "\n".join(f"  - {r['ticker']}: sim={r['top_sim']:.3f}  q={r['query']!r}"
                            for r in res.get("retrieval", []))
            note = it.get("note", "")
            checks = "\n".join(
                f"  - [{'x' if c['passed'] else ' '}] {c['name']}: {c['detail']}"
                for c in score["checks"]
            )
            details.append(
                f"### {i}. {q}\n"
                f"- **category:** {cat}  |  **route:** {res['route']['mode']}  |  "
                f"**refused:** {refused} ({reason})  |  **top_sim:** {top:.3f}  |  "
                f"**passed:** {score['passed']}\n"
                + (f"- **your note:** {note}\n" if note else "")
                + (f"- **plan:** {plan_actions}\n" if plan_actions else "")
                + (f"- **tools:** {tool_status}\n" if tool_status else "")
                + (f"- **checks:**\n{checks}\n" if checks else "")
                + (f"- **sub-queries:**\n{sub}\n" if sub else "")
                + f"- **citations:** {cites or '(none)'}  |  **gaps:** {gaps or '(none)'}\n\n"
                f"**Answer:**\n\n{res['answer']}\n"
            )
            json_rows.append({
                "id": i,
                "category": cat,
                "question": q,
                "route": res["route"],
                "refused": refused,
                "refusal_reason": reason,
                "top_sim": top,
                "citations": res.get("citations", []),
                "gaps": res.get("gaps", []),
                "plan": res.get("plan", {}),
                "tool_calls": res.get("tool_calls", []),
                "reflection": res.get("reflection", {}),
                "score": score,
                "answer": res["answer"],
            })

        passed_count = sum(1 for row in json_rows if row["score"]["passed"])
        pass_rate = passed_count / len(json_rows)
        suite_passed = pass_rate >= PASS_THRESHOLD

        header = (
            f"# Eval results\n\n"
            f"Generated {date.today().isoformat()} - model `{config.CHAT_MODEL}` - "
            f"dense-similarity threshold {config.DENSE_SIM_THRESHOLD}\n\n"
            f"Automated pass rate: **{passed_count}/{len(json_rows)} ({pass_rate:.0%})**. "
            f"Suite threshold: **{PASS_THRESHOLD:.0%}**. "
            f"Suite status: **{'PASS' if suite_passed else 'FAIL'}**. "
            f"({n_cached}/{len(json_rows)} served from cache.)\n\n"
            f"Checks are deterministic regression signals; use the answers below for deeper human review.\n\n"
            f"| # | cat | question | route | refused | reason | top_sim | citations | gaps | "
            f"passed | expected_fail | plan |\n"
            f"|---|-----|----------|-------|---------|--------|---------|-----------|------|"
            f"-------|---------------|------|\n"
        )
        body = "\n".join(rows)
        detail = "\n\n## Answers (for grading)\n\n" + "\n---\n\n".join(details)
        outpath.write_text(header + body + "\n" + detail, encoding="utf-8")
        jsonpath.write_text(json.dumps({
            "generated": date.today().isoformat(),
            "model": config.CHAT_MODEL,
            "threshold": PASS_THRESHOLD,
            "pass_rate": pass_rate,
            "passed": suite_passed,
            "results": json_rows,
        }, indent=2), encoding="utf-8")
        print(f"\nWrote {outpath} and {jsonpath} ({len(numbered)} questions, "
              f"{n_cached} cached).")
    finally:
        config.CHAT_MODEL = orig_chat_model


def _parse_ids(raw: str) -> set[int]:
    return {int(x.strip()) for x in raw.split(",") if x.strip()}


def _parse_categories(raw: str) -> set[str]:
    return {x.strip() for x in raw.split(",") if x.strip()}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Eval runner for the research MVP.")
    p.add_argument("questions", nargs="?", default=str(DEFAULT_Q))
    p.add_argument("results_md", nargs="?", default=str(DEFAULT_OUT))
    p.add_argument("results_json", nargs="?", default=str(DEFAULT_JSON))
    p.add_argument("--only", help="Comma-separated 1-based question ids, e.g. --only 3,7,12")
    p.add_argument("--category", help="Comma-separated categories, e.g. --category valuation,news")
    p.add_argument("--no-cache", action="store_true", help="Force live calls, bypass the disk cache")
    p.add_argument(
        "--model",
        help="Override config.CHAT_MODEL for this run only — cheap structural-check iteration "
             "(tool selection, citation presence), NOT valid for the acceptance run.",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    qpath = Path(args.questions)
    outpath = Path(args.results_md)
    jsonpath = Path(args.results_json)
    run(
        qpath, outpath, jsonpath,
        only=_parse_ids(args.only) if args.only else None,
        categories=_parse_categories(args.category) if args.category else None,
        no_cache=args.no_cache,
        model_override=args.model,
    )
