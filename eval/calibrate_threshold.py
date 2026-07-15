"""Threshold calibration for app.config.DENSE_SIM_THRESHOLD.

The refusal gate (app/research.py: prepare(), _run_summary()) refuses a question when the
dense cosine similarity of the top retrieved chunk falls below DENSE_SIM_THRESHOLD. That value
is currently "provisionally calibrated" (see the comment in app/config.py) from a handful of
Phase-3 probe scores. This script re-runs a small labeled probe set through retrieval ONLY
(no Anthropic/LLM call — just the OpenAI embedding + Chroma query retrieve() already makes),
prints the top_sim distribution grouped by label, and reports the gap the current threshold
sits in, so the value can be checked against current evidence rather than taken on faith.

This does NOT rewrite app/config.py — reading the gap and deciding whether/how to move the
threshold is a judgment call for a human, not something to auto-apply.

Usage: python eval/calibrate_threshold.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config, retrieve  # noqa: E402

# (query, tickers-or-None, label). "boundary" probes are real in-corpus questions phrased
# awkwardly enough to score low — the threshold must sit BELOW these, not above them, or
# genuine filing questions get wrongly refused.
_PROBES: list[tuple[str, list[str] | None, str]] = [
    ("Apple's business segments and main products", ["AAPL"], "in_corpus"),
    ("NVIDIA risk factors and competition", ["NVDA"], "in_corpus"),
    ("Walmart revenue and operating income", ["WMT"], "in_corpus"),
    ("JPMorgan Chase key risks", ["JPM"], "in_corpus"),
    ("Caterpillar segment revenue", ["CAT"], "in_corpus"),
    ("Coca-Cola's employee attrition rate", ["KO"], "boundary"),
    ("What was Tesla's revenue last year?", None, "out_of_corpus"),
    ("What is France's GDP?", None, "out_of_corpus"),
    ("What is the capital of Japan?", None, "out_of_corpus"),
    ("Best pizza toppings", None, "out_of_corpus"),
]


def main() -> None:
    print(f"Current DENSE_SIM_THRESHOLD = {config.DENSE_SIM_THRESHOLD}\n")
    print(f"{'label':<14} {'top_sim':>8}  query")
    print("-" * 70)

    by_label: dict[str, list[float]] = {}
    for query, tickers, label in _PROBES:
        res = retrieve.retrieve(query, tickers, config.TOP_K_SINGLE)
        top_sim = res["top_sim"]
        by_label.setdefault(label, []).append(top_sim)
        print(f"{label:<14} {top_sim:>8.3f}  {query}")

    print()
    for label in ("out_of_corpus", "boundary", "in_corpus"):
        sims = by_label.get(label, [])
        if sims:
            print(f"{label}: min={min(sims):.3f} max={max(sims):.3f} n={len(sims)}")

    out_of_corpus_max = max(by_label.get("out_of_corpus", [0.0]))
    boundary_min = min(by_label.get("boundary", [1.0]))
    in_corpus_min = min(by_label.get("in_corpus", [1.0]))
    floor = max(out_of_corpus_max, 0.0)  # threshold must clear every out-of-corpus probe
    ceiling = min(boundary_min, in_corpus_min)  # and stay below every real in-corpus probe

    print(f"\nSafe range for DENSE_SIM_THRESHOLD given these probes: "
          f"({floor:.3f}, {ceiling:.3f})")
    if floor >= ceiling:
        print("WARNING: no safe gap — an out-of-corpus probe scored at or above an in-corpus "
              "one. Add more probes or inspect these specific questions before touching the "
              "threshold.")
    elif floor <= config.DENSE_SIM_THRESHOLD <= ceiling:
        print(f"Current threshold {config.DENSE_SIM_THRESHOLD} sits inside the safe range — no "
              f"change indicated by this probe set.")
    else:
        print(f"Current threshold {config.DENSE_SIM_THRESHOLD} sits OUTSIDE the safe range. "
              f"Consider a value near the midpoint: {(floor + ceiling) / 2:.3f}")


if __name__ == "__main__":
    main()
