"""Schema-driven eval runner.

Usage:
  python eval/run_eval.py --tag smoke --layer retrieve
  python eval/run_eval.py --layer answer
  python eval/run_eval.py --layer judge
  python eval/run_eval.py --id aapl-opinc-fy2025

Layers: retrieve (no synthesis), answer (full pipeline + deterministic gold),
judge (answer + LLM judge). Judge never overrides a deterministic fail.
Suite PASS means every selected case passed — no 80% fudge.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, corpus, research  # noqa: E402
from eval.cases import load_cases  # noqa: E402
from eval.score import merge_scores, score_answer, score_retrieve  # noqa: E402

DEFAULT_OUT = Path(__file__).parent / "results.md"
DEFAULT_JSON = Path(__file__).parent / "results.json"
CACHE_DIR = Path(__file__).parent / ".cache"
LAYERS = ("retrieve", "answer", "judge")


def _cache_key(case: dict, layer: str) -> str:
    gold = json.dumps(case.get("gold") or {}, sort_keys=True, default=str)
    parts = [
        case["id"], layer, case["question"], gold,
        config.CHAT_MODEL, str(config.DENSE_SIM_THRESHOLD),
        corpus.version() or "", os.getenv("FINSIGHT_USE_RERANKER", ""),
        str(config.USE_LLM_ROUTER), config.ROUTER_MODEL,
    ]
    if layer == "judge":
        from eval.judge import JUDGE_MODEL
        parts.append(JUDGE_MODEL)
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


def _save_cache(key: str, payload: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(key).write_text(json.dumps(payload), encoding="utf-8")


def _apply_fixture(case: dict) -> str | None:
    fx = case.get("fixture") or {}
    holdings = fx.get("portfolio") or []
    if not holdings:
        return fx.get("client_id")
    from app import portfolio
    client_id = fx.get("client_id") or f"eval-{case['id']}"
    for h in holdings:
        portfolio.set_holding(client_id, h["ticker"], float(h["shares"]), h.get("cost_basis"))
    return client_id


def collect_retrieved(case: dict) -> tuple[list[str], dict[str, str]]:
    from app import retrieve, router
    from app.tools.filings import facts_lookup

    q = case["question"]
    route = router.route(q)
    gold = (case.get("gold") or {}).get("retrieve") or {}
    k = int(gold.get("k") or config.TOP_K_SINGLE)
    tickers = [gold["ticker"]] if gold.get("ticker") else (route.get("tickers") or None)
    ids: list[str] = []
    forms: dict[str, str] = {}

    fl = facts_lookup(q, route)
    for ev in fl.get("evidence") or []:
        cid = ev.get("chunk_id")
        if cid:
            ids.append(cid)
            forms[cid] = ev.get("form") or "10-K"

    from app.research import prefer_form
    res = retrieve.retrieve(q, tickers, k, prefer_form=prefer_form(q))
    for chunk in res.get("chunks") or []:
        cid = chunk.get("chunk_id")
        if cid:
            ids.append(cid)
            forms[cid] = chunk.get("form") or "10-K"
    return ids, forms


def _md_escape(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ").strip()


def _layer_rates(rows: list[dict]) -> dict[str, str]:
    def rate(layer: str) -> str:
        relevant = []
        for row in rows:
            checks = [c for c in row["score"]["checks"] if c.get("layer") == layer]
            if not checks:
                continue
            relevant.append(all(c["passed"] for c in checks))
        if not relevant:
            return "n/a"
        n = sum(relevant)
        return f"{n}/{len(relevant)} ({n / len(relevant):.0%})"

    return {
        "retrieve": rate("retrieve"),
        "answer": rate("answer"),
        "judge": rate("judge"),
    }


def run(
    layer: str,
    tags: set[str] | None,
    ids: set[str] | None,
    outpath: Path,
    jsonpath: Path,
    no_cache: bool,
) -> int:
    cases = load_cases(tags=tags, ids=ids)
    if not cases:
        raise SystemExit("No cases matched --tag/--id filters")

    rows: list[dict] = []
    n_cached = 0
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['id']}  {case['question'][:70]}")
        key = _cache_key(case, layer)
        cached = None if no_cache else _load_cached(key)
        retrieve_score: dict = {"passed": True, "checks": [], "skipped": True}
        answer_score: dict = {"passed": True, "checks": [], "skipped": True}
        judge_score: dict = {"passed": True, "checks": [], "skipped": True}
        res: dict = {}

        if cached is not None:
            n_cached += 1
            retrieve_score = cached.get("retrieve_score") or retrieve_score
            answer_score = cached.get("answer_score") or answer_score
            judge_score = cached.get("judge_score") or judge_score
            res = cached.get("res") or {}
        else:
            if layer in {"retrieve", "answer", "judge"} and (case.get("gold") or {}).get("retrieve"):
                ids_found, forms = collect_retrieved(case)
                retrieve_score = score_retrieve(case, ids_found, forms)
            if layer in {"answer", "judge"}:
                client_id = _apply_fixture(case)
                res = research.answer(case["question"], client_id=client_id)
                answer_score = score_answer(case, res)
            if layer == "judge" and (case.get("judge") or (case.get("gold") or {}).get("judge")):
                from eval.judge import judge_case
                judge_score = judge_case(case, res)
            _save_cache(key, {
                "retrieve_score": retrieve_score,
                "answer_score": answer_score,
                "judge_score": judge_score,
                "res": {
                    "answer": res.get("answer"),
                    "citations": res.get("citations"),
                    "citation_details": res.get("citation_details"),
                    "context_chunks": [
                        {"chunk_id": c.get("chunk_id"), "text": c.get("text"), "form": c.get("form")}
                        for c in (res.get("context_chunks") or [])
                    ],
                    "refused": res.get("refused"),
                    "refusal_reason": res.get("refusal_reason"),
                    "route": res.get("route"),
                    "plan": res.get("plan"),
                    "tool_calls": res.get("tool_calls"),
                } if res else {},
            })

        merged = merge_scores(retrieve_score, answer_score, judge_score)
        rows.append({
            "id": case["id"],
            "tags": case.get("tags") or [],
            "question": case["question"],
            "score": merged,
            "retrieve_score": retrieve_score,
            "answer_score": answer_score,
            "judge_score": judge_score,
            "answer": (res or cached or {}).get("answer") if isinstance(cached, dict) else res.get("answer"),
            "citations": res.get("citations") if res else (cached or {}).get("res", {}).get("citations"),
            "refused": res.get("refused") if res else (cached or {}).get("res", {}).get("refused"),
        })

    passed_count = sum(1 for r in rows if r["score"]["passed"])
    suite_passed = passed_count == len(rows)
    rates = _layer_rates(rows)

    header = (
        f"# Eval results\n\n"
        f"Generated {date.today().isoformat()} - synthesizer `{config.CHAT_MODEL}` - "
        f"layer `{layer}` - dense-similarity threshold {config.DENSE_SIM_THRESHOLD}\n\n"
        f"Suite: **{passed_count}/{len(rows)}** cases passed. "
        f"Status: **{'PASS' if suite_passed else 'FAIL'}**. "
        f"({n_cached}/{len(rows)} cached.)\n\n"
        f"Layer rates — retrieve: {rates['retrieve']}; "
        f"answer: {rates['answer']}; judge: {rates['judge']}.\n\n"
        f"Every declared check must pass. No 80% fudge.\n\n"
        f"| id | tags | passed | question |\n"
        f"|----|------|--------|----------|\n"
    )
    table = "\n".join(
        f"| {r['id']} | {', '.join(r['tags'])} | "
        f"{'yes' if r['score']['passed'] else 'no'} | {_md_escape(r['question'])} |"
        for r in rows
    )
    details = []
    for r in rows:
        checks = "\n".join(
            f"  - [{'x' if c['passed'] else ' '}] {c.get('layer')}/{c['name']}: {c['detail']}"
            for c in r["score"]["checks"]
        )
        details.append(
            f"### {r['id']}\n"
            f"- **passed:** {r['score']['passed']}  |  **tags:** {', '.join(r['tags'])}\n"
            f"- **question:** {r['question']}\n"
            + (f"- **checks:**\n{checks}\n" if checks else "")
            + (f"\n**Answer:**\n\n{r.get('answer') or ''}\n")
        )
    outpath.write_text(header + table + "\n\n## Cases\n\n" + "\n---\n\n".join(details), encoding="utf-8")
    jsonpath.write_text(json.dumps({
        "generated": date.today().isoformat(),
        "model": config.CHAT_MODEL,
        "layer": layer,
        "pass_rate": passed_count / len(rows),
        "passed": suite_passed,
        "layer_rates": rates,
        "results": rows,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {outpath} and {jsonpath} ({len(rows)} cases, {n_cached} cached). "
          f"{'PASS' if suite_passed else 'FAIL'}")
    return 0 if suite_passed else 1


def _parse_set(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    return {x.strip() for x in raw.split(",") if x.strip()}


def main() -> None:
    p = argparse.ArgumentParser(description="Schema-driven FinSight eval runner.")
    p.add_argument("--layer", choices=LAYERS, default="answer",
                   help="retrieve | answer | judge (judge includes answer + retrieve gold)")
    p.add_argument("--tag", help="Comma-separated tags; case must include ALL of them")
    p.add_argument("--id", dest="case_ids", help="Comma-separated case ids")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--json", dest="json_out", default=str(DEFAULT_JSON))
    p.add_argument("--no-cache", action="store_true")
    args = p.parse_args()
    raise SystemExit(run(
        layer=args.layer,
        tags=_parse_set(args.tag),
        ids=_parse_set(args.case_ids),
        outpath=Path(args.out),
        jsonpath=Path(args.json_out),
        no_cache=args.no_cache,
    ))


if __name__ == "__main__":
    main()
