"""Eval runner for the research MVP.

Runs eval/questions.yaml through the pipeline and writes both:
  - a markdown report for review
  - a JSON report with deterministic regression checks

Usage:  python eval/run_eval.py [questions.yaml] [results.md] [results.json]
"""

import json
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config, main  # noqa: E402

DEFAULT_Q = Path(__file__).parent / "questions.yaml"
DEFAULT_OUT = Path(__file__).parent / "results.md"
DEFAULT_JSON = Path(__file__).parent / "results.json"
PASS_THRESHOLD = 0.80


def _md_escape(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ").strip()


def _add_check(checks: list[dict], name: str, passed: bool, detail: str) -> None:
    checks.append({"name": name, "passed": passed, "detail": detail})


def _expected_refusal(item: dict) -> bool | None:
    category = item.get("category", "")
    if category in {"router_clarify", "refusal_oos"}:
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
            any("-MKT-" not in c and "-CALC-" not in c for c in citations),
            f"citations={citations}",
        )
        _add_check(
            checks,
            "market_as_of_present",
            "as of" in res.get("answer", "").lower(),
            "explain-move answers should state quote freshness",
        )
        # Causal-language leakage ("caused", "because of", "due to" tying a filing risk to the
        # price move) is not reliably checkable with a deterministic string match — graded by
        # human review of the answer in results_v3.md, per the guidance in synthesize.py.

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

    if reflection:
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


def run(qpath: Path, outpath: Path, jsonpath: Path) -> None:
    items = yaml.safe_load(qpath.read_text(encoding="utf-8"))
    if not items:
        raise SystemExit(f"No questions found in {qpath}")

    rows, details, json_rows = [], [], []
    for i, it in enumerate(items, 1):
        q = it["question"]
        cat = it.get("category", "")
        print(f"[{i}/{len(items)}] {q[:70]}")
        res = main.answer(q)
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
        f"Suite status: **{'PASS' if suite_passed else 'FAIL'}**.\n\n"
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
    print(f"\nWrote {outpath} and {jsonpath} ({len(items)} questions).")


if __name__ == "__main__":
    qpath = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_Q
    outpath = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT
    jsonpath = Path(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_JSON
    run(qpath, outpath, jsonpath)
