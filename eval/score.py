"""Deterministic retrieve + answer scoring. Category does not select checks."""

from __future__ import annotations

import re

from eval.goldnum import answer_has_gold, evidence_covers, extract_numbers

_CITATION_RE = re.compile(r"\[([A-Z]{2,5}-[A-Za-z0-9_-]+)\]")


def _check(name: str, passed: bool, detail: str, layer: str) -> dict:
    return {"name": name, "passed": passed, "detail": detail, "layer": layer}


def id_hit(needle: str, haystack: list[str]) -> bool:
    """Exact id, or gold prefix of a grouped XBRL id (AAPL-XBRL-X matches AAPL-XBRL-X_Y)."""
    needle_u = needle.upper()
    for hid in haystack:
        hu = hid.upper()
        if hu == needle_u or hu.startswith(needle_u + "_") or hu.startswith(needle_u + "-"):
            return True
    return False


def score_retrieve(case: dict, retrieved_ids: list[str], forms: dict[str, str] | None = None) -> dict:
    gold = (case.get("gold") or {}).get("retrieve") or {}
    checks: list[dict] = []
    forms = forms or {}
    if not gold:
        return {"passed": True, "checks": [], "skipped": True}

    must = gold.get("must_include") or []
    missing = [cid for cid in must if not id_hit(cid, retrieved_ids)]
    checks.append(_check(
        "retrieve_hit_at_k",
        not missing,
        f"missing={missing} retrieved={retrieved_ids[:12]}",
        "retrieve",
    ))

    forbidden = gold.get("must_not_include") or []
    leaked = [cid for cid in forbidden if id_hit(cid, retrieved_ids)]
    if forbidden:
        checks.append(_check(
            "retrieve_must_not_include",
            not leaked,
            f"leaked={leaked}",
            "retrieve",
        ))

    want_form = gold.get("form")
    if want_form:
        targets = must or retrieved_ids

        def form_of(needle: str) -> str:
            for hid in retrieved_ids:
                if id_hit(needle, [hid]):
                    return forms.get(hid, "10-K")
            return "10-K"

        bad = [
            cid for cid in targets
            if id_hit(cid, retrieved_ids) and form_of(cid) != want_form
        ]
        checks.append(_check(
            "retrieve_form",
            not bad,
            f"want form={want_form} mismatched={bad}",
            "retrieve",
        ))

    want_ticker = gold.get("ticker")
    if want_ticker:
        on_ticker = [cid for cid in retrieved_ids if cid.upper().startswith(want_ticker.upper())]
        checks.append(_check(
            "retrieve_ticker",
            bool(on_ticker) or not retrieved_ids,
            f"want ticker={want_ticker} hits={on_ticker[:6]}",
            "retrieve",
        ))

    return {"passed": all(c["passed"] for c in checks), "checks": checks, "skipped": False}


def cited_ids(answer: str) -> list[str]:
    return _CITATION_RE.findall(answer or "")


def _evidence_blob(res: dict) -> str:
    parts: list[str] = []
    for det in res.get("citation_details") or []:
        parts.append(det.get("text") or "")
        for fact in det.get("facts") or []:
            parts.append(str(fact.get("value_display") or ""))
            parts.append(str(fact.get("value_scaled") or ""))
        parts.append(str(det.get("data") or ""))
    cited = set(res.get("citations") or [])
    for chunk in res.get("context_chunks") or []:
        if chunk.get("chunk_id") in cited:
            parts.append(chunk.get("text") or "")
    return "\n".join(parts)


def evidence_ids(res: dict) -> set[str]:
    ids: set[str] = set()
    for chunk in res.get("context_chunks") or []:
        cid = chunk.get("chunk_id")
        if cid:
            ids.add(cid)
    for det in res.get("citation_details") or []:
        cid = det.get("chunk_id")
        if cid:
            ids.add(cid)
    for t in res.get("tool_calls") or []:
        for cid in t.get("citations") or []:
            ids.add(cid)
    return ids


def score_answer(case: dict, res: dict) -> dict:
    gold = (case.get("gold") or {}).get("answer") or {}
    checks: list[dict] = []
    answer = res.get("answer") or ""
    refused = bool(res.get("refused"))

    if "refuse" in gold:
        expected = bool(gold["refuse"])
        checks.append(_check(
            "refuse",
            refused == expected,
            f"expected refused={expected}, got={refused} reason={res.get('refusal_reason', '')}",
            "answer",
        ))
        want_reason = gold.get("refuse_reason")
        if want_reason:
            got_reason = res.get("refusal_reason") or ""
            checks.append(_check(
                "refuse_reason",
                got_reason == want_reason,
                f"expected={want_reason} got={got_reason}",
                "answer",
            ))

    if gold.get("refuse"):
        return {"passed": all(c["passed"] for c in checks), "checks": checks}

    citations = list(res.get("citations") or []) or cited_ids(answer)

    for spec in gold.get("numbers") or []:
        value = spec["value"]
        unit = spec.get("unit") or "ones"
        tol = float(spec.get("tolerance") or 0)
        ok = answer_has_gold(answer, value, unit, tol)
        label = spec.get("id") or f"{value} {unit}"
        checks.append(_check("gold_number", ok, f"{label} found={ok}", "answer"))
        period = spec.get("period")
        if period:
            period_ok = str(period).lower() in answer.lower()
            iso = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(period))
            if iso and not period_ok:
                months = (
                    "January February March April May June "
                    "July August September October November December"
                ).split()
                y, m, d = iso.group(1), int(iso.group(2)), int(iso.group(3))
                human = f"{months[m - 1]} {d}, {y}"
                period_ok = human.lower() in answer.lower()
            elif not period_ok:
                year_m = re.search(r"(19|20)\d{2}", str(period))
                period_ok = bool(year_m) and year_m.group(0) in answer
            checks.append(_check(
                "gold_period",
                period_ok,
                f"period={period} in_answer={period_ok}",
                "answer",
            ))

    for cid in gold.get("must_cite") or []:
        checks.append(_check(
            "must_cite",
            id_hit(cid, citations),
            f"want {cid} citations={citations}",
            "answer",
        ))

    want_form = gold.get("must_cite_form")
    if want_form == "10-Q":
        form_ok = any("10Q" in c.upper() for c in citations)
        checks.append(_check("must_cite_form", form_ok, f"want 10-Q citations={citations}", "answer"))
    elif want_form == "10-K":
        form_ok = bool(citations) and not all("10Q" in c.upper() for c in citations)
        checks.append(_check("must_cite_form", form_ok, f"want 10-K citations={citations}", "answer"))

    for pat in gold.get("must_include") or []:
        checks.append(_check(
            "must_include",
            bool(re.search(pat, answer, re.I)),
            f"pattern={pat!r}",
            "answer",
        ))
    for pat in gold.get("must_not_match") or []:
        checks.append(_check(
            "must_not_match",
            not re.search(pat, answer, re.I),
            f"pattern={pat!r}",
            "answer",
        ))

    faith = (case.get("gold") or {}).get("faithfulness")
    if faith == "numbers_in_evidence" and not refused:
        blob = _evidence_blob(res)
        pool = evidence_ids(res)
        cited = cited_ids(answer)
        hallucinated = [cid for cid in cited if pool and cid not in pool]
        checks.append(_check(
            "citation_in_evidence",
            not hallucinated,
            f"hallucinated={hallucinated}",
            "answer",
        ))
        unsupported = [
            claim.raw for claim in extract_numbers(answer)
            if not evidence_covers(claim, blob)
        ]
        checks.append(_check(
            "numbers_in_evidence",
            not unsupported,
            f"unsupported={unsupported}",
            "answer",
        ))

    return {"passed": all(c["passed"] for c in checks) if checks else True, "checks": checks}


def merge_scores(*scores: dict) -> dict:
    checks: list[dict] = []
    passed = True
    for s in scores:
        if not s:
            continue
        checks.extend(s.get("checks") or [])
        if s.get("skipped"):
            continue
        passed = passed and bool(s.get("passed", True))
    return {"passed": passed, "checks": checks}
