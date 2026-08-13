"""Layer 3: temp-0 structured LLM judge over cited evidence only.

A judge pass never overrides a deterministic fail (enforced by merge_scores in the runner).
Faithfulness does not see gold numbers. Correctness may see gold notes/period.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from app import config, obs

RUBRICS_PATH = Path(__file__).resolve().parent / "judge_rubrics.yaml"
JUDGE_MODEL = config.ROUTER_MODEL  # haiku; must differ from CHAT_MODEL (sonnet)

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["faithful", "correct", "unsupported_claims", "reason"],
    "properties": {
        "faithful": {"type": "boolean"},
        "correct": {"type": "boolean"},
        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
}


def _rubrics() -> dict[str, str]:
    return yaml.safe_load(RUBRICS_PATH.read_text(encoding="utf-8")) or {}


def _evidence_for_judge(res: dict) -> str:
    """Cited evidence only — never the full corpus, never uncited retrieval hits."""
    cited = set(res.get("citations") or [])
    blocks: list[str] = []
    by_id = {}
    for det in res.get("citation_details") or []:
        cid = det.get("chunk_id")
        if cid:
            by_id[cid] = det
    for cid in cited:
        det = by_id.get(cid) or {}
        text = det.get("text") or ""
        blocks.append(f"[{cid}]\n{text}")
    if not blocks:
        for chunk in res.get("context_chunks") or []:
            cid = chunk.get("chunk_id")
            if cid in cited:
                blocks.append(f"[{cid}]\n{chunk.get('text') or ''}")
    return "\n\n".join(blocks) if blocks else "(no cited evidence)"


def _system(rubric_names: list[str]) -> str:
    catalog = _rubrics()
    parts = [
        "You are a strict financial-RAG eval judge. Return JSON only.",
        "Score only the rubrics listed. Binary true/false — never a 1-5 scale.",
        "If a rubric is not listed, still fill the JSON fields (use true for unused axes).",
    ]
    for name in rubric_names:
        text = catalog.get(name)
        if not text:
            raise ValueError(f"unknown judge rubric: {name}")
        parts.append(f"## {name}\n{text.strip()}")
    return "\n\n".join(parts)


def _user_payload(case: dict, res: dict, rubric_names: list[str]) -> str:
    gold = (case.get("gold") or {}).get("answer") or {}
    judge_cfg = case.get("judge") or (case.get("gold") or {}).get("judge") or {}
    payload = {
        "question": case["question"],
        "answer": res.get("answer") or "",
        "cited_evidence": _evidence_for_judge(res),
        "rubrics": rubric_names,
    }
    # Correctness may see gold; faithfulness must not (rubber-stamp risk).
    if "correctness" in rubric_names:
        payload["gold_notes"] = judge_cfg.get("notes") or ""
        if gold.get("numbers"):
            payload["gold_numbers"] = gold["numbers"]
    return json.dumps(payload, ensure_ascii=False)


def judge_case(case: dict, res: dict) -> dict:
    """Run the judge. Invalid JSON / API failure = fail, not skip."""
    judge_cfg = case.get("judge") or (case.get("gold") or {}).get("judge") or {}
    rubric_names = list(judge_cfg.get("rubrics") or [])
    if not rubric_names:
        return {"passed": True, "checks": [], "skipped": True, "verdict": None}

    import anthropic

    client = anthropic.Anthropic()
    try:
        msg = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=512,
            temperature=0,
            system=_system(rubric_names),
            messages=[{"role": "user", "content": _user_payload(case, res, rubric_names)}],
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        )
        obs.add_llm_usage(JUDGE_MODEL, msg.usage.input_tokens, msg.usage.output_tokens)
        text = next(b.text for b in msg.content if b.type == "text")
        verdict = json.loads(text)
    except Exception as exc:  # noqa: BLE001 — any judge failure is a failed check
        return {
            "passed": False,
            "skipped": False,
            "verdict": None,
            "checks": [{
                "name": "judge_json",
                "passed": False,
                "detail": f"{type(exc).__name__}: {exc}",
                "layer": "judge",
            }],
        }

    checks = []
    if "faithfulness" in rubric_names:
        checks.append({
            "name": "judge_faithful",
            "passed": bool(verdict.get("faithful")),
            "detail": f"unsupported={verdict.get('unsupported_claims', [])} reason={verdict.get('reason', '')}",
            "layer": "judge",
        })
    if "correctness" in rubric_names:
        checks.append({
            "name": "judge_correct",
            "passed": bool(verdict.get("correct")),
            "detail": f"reason={verdict.get('reason', '')}",
            "layer": "judge",
        })
    extra = [r for r in rubric_names if r not in {"faithfulness", "correctness"}]
    if extra:
        # extras are folded into faithful+correct; require both true when declared
        checks.append({
            "name": "judge_extra",
            "passed": bool(verdict.get("faithful")) and bool(verdict.get("correct")),
            "detail": f"extras={extra} reason={verdict.get('reason', '')}",
            "layer": "judge",
        })
    return {
        "passed": all(c["passed"] for c in checks),
        "skipped": False,
        "verdict": verdict,
        "checks": checks,
    }
