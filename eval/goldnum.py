"""Normalize and extract numeric claims for eval scoring.

Gold and answers both collapse to a canonical float so `$133,050 million`,
`133.05 billion`, and `1.3305e11` compare equal. Years, form names, and
citation ids are not claims.

Named goldnum (not numbers) so `python eval/run_eval.py` does not shadow
the stdlib `numbers` module that pydantic imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CITATION_RE = re.compile(r"\[([A-Z]{2,5}-[A-Za-z0-9_-]+)\]")
_FORM_RE = re.compile(r"\b10-[KQ]\b", re.I)

_UNIT_NUM_RE = re.compile(
    r"(?<![A-Za-z])(?P<sign>[-−])?\$?\s*(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
    r"\s*(?P<unit>billions?|bn\b|millions?|mn\b|thousand|percent|per\s*cent|%|"
    r"per\s+share|eps\b)?",
    re.I,
)

_UNIT_SCALE = {
    "billion": 1e9,
    "billions": 1e9,
    "bn": 1e9,
    "million": 1e6,
    "millions": 1e6,
    "mn": 1e6,
    "thousand": 1e3,
    "percent": 1.0,
    "per cent": 1.0,
    "%": 1.0,
    "per share": 1.0,
    "eps": 1.0,
}

_GOLD_UNIT_SCALE = {
    "billions": 1e9,
    "billion": 1e9,
    "millions": 1e6,
    "million": 1e6,
    "ones": 1.0,
    "per_share": 1.0,
    "percent": 1.0,
    "pct": 1.0,
}


@dataclass(frozen=True)
class CanonicalNumber:
    value: float
    unit: str
    raw: str


def gold_canonical(value: float, unit: str) -> float:
    """Turn a gold `{value, unit}` into a comparable float (USD, or % / per-share as-is)."""
    key = (unit or "ones").lower()
    scale = _GOLD_UNIT_SCALE.get(key)
    if scale is None:
        raise ValueError(f"unknown gold unit: {unit}")
    if key in {"millions", "million", "billions", "billion"}:
        return value * scale
    return value


def extract_numbers(text: str) -> list[CanonicalNumber]:
    """Numeric claims from an answer or evidence blob. Skips years and citation ids."""
    stripped = _CITATION_RE.sub(" ", text)
    stripped = _FORM_RE.sub(" ", stripped)
    out: list[CanonicalNumber] = []
    for m in _UNIT_NUM_RE.finditer(stripped):
        num_s = m.group("num")
        unit_s = (m.group("unit") or "").strip().lower()
        if not unit_s and re.fullmatch(r"(?:19|20)\d{2}", num_s.replace(",", "")):
            continue
        try:
            n = float(num_s.replace(",", ""))
        except ValueError:
            continue
        if m.group("sign"):
            n = -n
        if unit_s in {"percent", "per cent", "%"}:
            out.append(CanonicalNumber(n, "percent", m.group(0).strip()))
            continue
        if unit_s in {"per share", "eps"}:
            out.append(CanonicalNumber(n, "per_share", m.group(0).strip()))
            continue
        scale = _UNIT_SCALE.get(unit_s, 0.0)
        if scale:
            canonical = n * scale
            unit = "billions" if scale >= 1e9 else "millions" if scale >= 1e6 else "ones"
            out.append(CanonicalNumber(canonical, unit, m.group(0).strip()))
            continue
        if "," in num_s and abs(n) >= 100:
            out.append(CanonicalNumber(n * 1e6, "millions", m.group(0).strip()))
    return out


def numbers_close(got: float, expected: float, tolerance: float = 0.0) -> bool:
    if expected == 0:
        return abs(got) <= max(tolerance, 1e-6)
    rel = abs(got - expected) / abs(expected)
    abs_tol = max(tolerance, abs(expected) * 0.005, 1.0)
    return rel <= 0.005 or abs(got - expected) <= abs_tol


def answer_has_gold(answer: str, value: float, unit: str, tolerance: float = 0.0) -> bool:
    expected = gold_canonical(value, unit)
    unit_key = (unit or "ones").lower()
    for claim in extract_numbers(answer):
        if claim.unit == "percent" and unit_key in {"percent", "pct"}:
            if numbers_close(claim.value, expected, tolerance):
                return True
            continue
        if claim.unit == "per_share" and unit_key == "per_share":
            if numbers_close(claim.value, expected, tolerance):
                return True
            continue
        if unit_key in {"percent", "pct", "per_share"}:
            continue
        scaled_tol = tolerance * _GOLD_UNIT_SCALE.get(unit_key, 1.0)
        if numbers_close(claim.value, expected, scaled_tol):
            return True
    display = _display_forms(value, unit_key)
    compact = answer.replace(" ", "")
    return any(form.replace(" ", "") in compact or form in answer for form in display)


def _display_forms(value: float, unit: str) -> list[str]:
    if unit == "per_share":
        return [f"{value:.2f}", f"${value:.2f}", f"{value:g}"]
    if unit in {"percent", "pct"}:
        return [f"{value:g}%", f"{value:.1f}%"]
    ival = int(round(value))
    grouped = f"{ival:,}"
    forms = [grouped, str(ival), f"${grouped}", f"${ival}"]
    if unit in {"millions", "million"}:
        forms.extend([f"{grouped} million", f"${grouped} million"])
        as_b = value / 1000.0
        if as_b >= 0.1:
            forms.extend([
                f"{as_b:.2f} billion", f"${as_b:.2f} billion",
                f"{as_b:.1f} billion", f"${as_b:.1f} billion",
            ])
    return forms


def evidence_covers(claim: CanonicalNumber, evidence_text: str) -> bool:
    """True if the claim's magnitude appears in cited evidence (text or display numbers)."""
    for other in extract_numbers(evidence_text):
        if claim.unit == "percent" and other.unit == "percent":
            if numbers_close(claim.value, other.value):
                return True
            continue
        if claim.unit == "per_share" and other.unit == "per_share":
            if numbers_close(claim.value, other.value):
                return True
            continue
        if claim.unit in {"percent", "per_share"} or other.unit in {"percent", "per_share"}:
            continue
        if numbers_close(claim.value, other.value):
            return True
    if claim.unit == "millions":
        display = f"{int(round(claim.value / 1e6)):,}"
        if display in evidence_text:
            return True
    if claim.unit == "per_share":
        if f"{claim.value:.2f}" in evidence_text or f"{claim.value:g}" in evidence_text:
            return True
    if claim.unit == "percent":
        if f"{claim.value:g}%" in evidence_text or f"{claim.value:.1f}%" in evidence_text:
            return True
    return False
