"""Week-over-week trend: is your context hygiene getting better or worse?

The report answers "where do I degrade"; this answers "is it improving" —
which is also the before/after measurement for `contextrot fix`: change your
setup, keep working, and watch whether failure rate and startup overhead
actually move.

Same statistical honesty as everywhere else: the improving/worsening verdict
only fires when the pooled Wilson intervals of the earlier and later halves
don't overlap. One good week proves nothing, and the trend says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from contextrot.analysis.rot import wilson_interval
from contextrot.signals import StepSignals

# A week this thin can't say anything about failure rates.
MIN_WEEK_STEPS = 30


@dataclass
class WeekStats:
    week_start: date  # Monday
    steps: int
    degraded: int
    rate: float
    ci: tuple[float, float]
    avg_fill: float
    startup_tokens: int | None  # avg first-step prompt ≈ session startup overhead

    @property
    def label(self) -> str:
        return self.week_start.strftime("%b %d")


def build_trend(steps: list[StepSignals], weeks: int = 8) -> list[WeekStats]:
    """Per-ISO-week stats over the most recent `weeks` weeks with data."""
    by_week: dict[date, list[StepSignals]] = {}
    for s in steps:
        if s.timestamp is None:
            continue
        d = s.timestamp.date()
        monday = d - timedelta(days=d.weekday())
        by_week.setdefault(monday, []).append(s)

    out: list[WeekStats] = []
    for monday in sorted(by_week)[-weeks:]:
        group = by_week[monday]
        n = len(group)
        degraded = sum(1 for s in group if s.degraded)
        firsts = [s.prompt_tokens for s in group if s.step_index == 0]
        out.append(
            WeekStats(
                week_start=monday,
                steps=n,
                degraded=degraded,
                rate=degraded / n if n else 0.0,
                ci=wilson_interval(degraded, n),
                avg_fill=sum(s.fill_pct for s in group) / n if n else 0.0,
                startup_tokens=round(sum(firsts) / len(firsts)) if firsts else None,
            )
        )
    return out


def trend_verdict(trend: list[WeekStats]) -> tuple[str, str]:
    """(kind, text) where kind is improving / worsening / flat / insufficient.

    Pools the earlier half against the later half; a direction is only
    declared when the two pooled Wilson intervals don't overlap.
    """
    solid = [w for w in trend if w.steps >= MIN_WEEK_STEPS]
    if len(solid) < 2:
        return (
            "insufficient",
            "Not enough weekly data for a trend yet — keep using your agent and re-run.",
        )

    half = len(solid) // 2
    early, late = solid[:half], solid[half:]
    e_deg, e_n = sum(w.degraded for w in early), sum(w.steps for w in early)
    l_deg, l_n = sum(w.degraded for w in late), sum(w.steps for w in late)
    e_rate = e_deg / e_n if e_n else 0.0
    l_rate = l_deg / l_n if l_n else 0.0
    e_ci = wilson_interval(e_deg, e_n)
    l_ci = wilson_interval(l_deg, l_n)

    detail = f"failure rate {e_rate:.1%} → {l_rate:.1%}"
    if l_ci[1] < e_ci[0]:
        return ("improving", f"Improving: {detail} — the drop clears statistical noise.")
    if l_ci[0] > e_ci[1]:
        return ("worsening", f"Worsening: {detail} — the rise clears statistical noise.")
    return ("flat", f"No significant trend: {detail} (within statistical noise).")
