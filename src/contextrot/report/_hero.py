"""The ONE number that leads every report.

Both renderers (terminal and HTML, including the share card) consume this so
the headline can never drift between outputs.
"""

from __future__ import annotations

from contextrot.analysis import AnalysisResult
from contextrot.analysis.rot import VERDICT_MIN_N

HEADLINE_WORDS = {
    "rot": "CONTEXT ROT DETECTED",
    "edge": "EDGE ROT",
    "clean": "NO MEASURABLE ROT",
    "insufficient": "NOT ENOUGH DATA YET",
}


def hero_stat(result: AnalysisResult) -> dict:
    """Returns {kind, headline_word, value, label, secondary: [str, ...]}."""
    curve = result.curve
    kind = result.verdict_kind
    ratio = curve.degradation_ratio

    rates = None
    if curve.high_fill_rate is not None and curve.low_fill_rate is not None:
        rates = f"{curve.high_fill_rate:.1%} deep vs {curve.low_fill_rate:.1%} fresh"
    burned = f"${result.rework_cost_usd:.2f} burned in degraded steps"

    secondary: list[str] = []
    if kind == "rot":
        value = "∞" if ratio == float("inf") else f"{ratio:.1f}×"
        label = "more failures in deep context than fresh"
        if rates:
            secondary.append(rates)
        secondary.append(burned)
        if curve.knee_pct is not None:
            secondary.append(f"degrades past ~{curve.knee_pct}% fill")
    elif kind == "edge":
        # verdict() only returns "edge" when knee_pct is set.
        value = f"~{curve.knee_pct}%"
        label = "context fill where your agent starts failing"
        if rates:
            secondary.append(rates)
        secondary.append(burned)
    elif kind == "clean":
        value = f"{curve.total_steps:,}"
        label = "steps analyzed — failure rate stays flat"
        if rates:
            secondary.append(rates)
        secondary.append(f"${result.total_cost_usd:.2f} total token value")
    else:  # insufficient
        have = min(curve.low_fill_n, curve.high_fill_n)
        needed = max(VERDICT_MIN_N - have, 0)
        value = f"~{needed}"
        label = "more steps needed for a verdict"
        secondary.append(
            f"{curve.low_fill_n} fresh-context / {curve.high_fill_n} deep-context steps so far"
        )

    return {
        "kind": kind,
        "headline_word": HEADLINE_WORDS.get(kind, ""),
        "value": value,
        "label": label,
        "secondary": secondary,
    }
