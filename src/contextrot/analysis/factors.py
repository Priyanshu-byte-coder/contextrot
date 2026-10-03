"""What actually moves your failure rate.

The rot curve answers one question: does filling the context make your agent
worse? On a lot of real workloads the honest answer is no — and a tool that can
only say "not that" leaves you with nothing to act on. This module asks the
broader question with the same machinery: across every axis that can be read
cleanly from a transcript, **which one separates your good steps from your bad
ones?**

Each factor splits the same steps into groups and measures each group's slip
rate with a Wilson interval. How groups are compared depends on the axis:

* **Ordered axes** (context fill, mistakes so far, steps since you spoke) ask a
  directional question — *does it get worse as this grows?* — so they compare
  the **two ends**. Comparing the worst against the best group instead finds
  bumps: on real data it flagged "2 earlier mistakes" against "1" while "5+" sat
  right back at baseline, which is noise wearing a trend's clothes.
* **Categorical axes** (time of day, model, agent) ask *which one is best?*, so
  they compare the worst group against the best.

The bar for calling an effect is the one the verdict already uses — a ratio of
at least ``VERDICT_MIN_RATIO`` — plus non-overlapping 95% intervals for "clear".
Picking the best and worst of several categories flatters the gap, which is why
"clear" demands non-overlap rather than a p-value, and why "maybe" exists.

**Axes considered and rejected**, because shipping them would teach the wrong
lesson:

* *Session length.* Short sessions fail about twice as often on real data — but
  mostly because a session that goes badly gets abandoned early. The arrow points
  the other way, and "keep sessions long" would be exactly wrong advice.
* *Startup overhead* (system prompt, tool schemas, CLAUDE.md). The difference
  between light and heavy setups is dominated by *which agent* produced them, so
  the comparison measures agents, not setup weight. It stays in the composition
  panel as a description, not here as a cause.

Everything is association, not causation. Steps within a session are not
independent, so the intervals are narrower than they would be under a
session-level analysis; read them as descriptive.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from contextrot.analysis.rot import (
    REVERSAL_BUCKETS,
    VERDICT_MIN_N,
    VERDICT_MIN_RATIO,
    wilson_interval,
)
from contextrot.signals import StepSignals

# Minimum steps for a group to take part in a comparison. Matches the floor the
# verdict uses per zone, so a factor cannot be "clear" on less evidence than the
# headline needs.
FACTOR_MIN_N = VERDICT_MIN_N

# Strength labels, strongest first. The order is also the sort order.
STRENGTHS = ("clear", "maybe", "none", "insufficient")


@dataclass
class FactorGroup:
    """One slice of the steps — "at night", "on Opus 5", "after 2 mistakes"."""

    label: str
    phrase: str  # how the group reads mid-sentence: "at night (0–6h)"
    n: int = 0
    failures: int = 0

    @property
    def rate(self) -> float:
        return self.failures / self.n if self.n else 0.0

    @property
    def ci(self) -> tuple[float, float]:
        return wilson_interval(self.failures, self.n)

    @property
    def eligible(self) -> bool:
        return self.n >= FACTOR_MIN_N


@dataclass
class Factor:
    """One axis, its groups, and what the comparison found."""

    key: str
    name: str
    question: str
    ordinal: bool = False
    groups: list[FactorGroup] = field(default_factory=list)
    worst: FactorGroup | None = None
    best: FactorGroup | None = None
    ratio: float | None = None
    strength: str = "insufficient"
    finding: str = ""
    action: str = ""

    @property
    def rank(self) -> tuple[int, float]:
        """Sort key: strength first, then size of the gap."""
        return (STRENGTHS.index(self.strength), -(self.ratio or 0.0))


# --- the axes ----------------------------------------------------------------
#
# Each axis is (key, name, question, grouper, what-the-groups-compare). A grouper
# maps one step to a (label, phrase) pair, or None to leave the step out — a step
# with no timestamp has no hour, and a step that opens a turn is excluded from
# the autonomy axis for the reason given there.

Grouper = Callable[[StepSignals], "tuple[str, str] | None"]


def _fill(st: StepSignals) -> tuple[str, str] | None:
    for lo, hi in ((0, 20), (20, 40), (40, 60), (60, 80), (80, 101)):
        if lo <= st.fill_pct < hi:
            top = "100" if hi == 101 else str(hi)
            return f"{lo}–{top}%", f"at {lo}–{top}% context fill"
    return None


def _mistakes(st: StepSignals) -> tuple[str, str] | None:
    for lo, hi in REVERSAL_BUCKETS:
        if st.reversals_so_far >= lo and (hi is None or st.reversals_so_far <= hi):
            if hi is None:
                return f"{lo}+", f"after {lo}+ earlier mistakes"
            if lo == hi == 0:
                return "none yet", "with no mistakes yet in the session"
            if lo == hi:
                return str(lo), f"after {lo} earlier mistake{'' if lo == 1 else 's'}"
            return f"{lo}–{hi}", f"after {lo}–{hi} earlier mistakes"
    return None


_HOURS = (
    (0, 6, "night", "at night (0–6h)"),
    (6, 12, "morning", "in the morning (6–12h)"),
    (12, 18, "afternoon", "in the afternoon (12–18h)"),
    (18, 24, "evening", "in the evening (18–24h)"),
)


def _hour(st: StepSignals) -> tuple[str, str] | None:
    if st.timestamp is None:
        return None
    try:
        hour = st.timestamp.astimezone().hour  # your local clock, not UTC
    except (OverflowError, OSError, ValueError):
        return None
    for lo, hi, label, phrase in _HOURS:
        if lo <= hour < hi:
            return label, phrase
    return None


def _autonomy(st: StepSignals) -> tuple[str, str] | None:
    # Step 0 — the agent's first move after you speak — is left out on purpose.
    # It cannot be a retry (nothing has failed yet this turn) and rarely corrects
    # itself, so it slips at a fraction of the rate for mechanical reasons, and
    # including it would manufacture an "autonomy effect" out of the definition.
    depth = st.steps_since_prompt
    if depth is None or depth < 1:
        return None
    for lo, hi in ((1, 3), (4, 10), (11, 25), (26, None)):
        if depth >= lo and (hi is None or depth <= hi):
            label = f"{lo}+" if hi is None else f"{lo}–{hi}"
            return label, f"{label} steps after you last spoke"
    return None


def _model(st: StepSignals) -> tuple[str, str] | None:
    from contextrot.modelkey import model_family, model_label

    family = model_family(st.model)
    if family in ("unknown", "synthetic"):
        return None
    label = model_label(family)
    return label, f"on {label}"


def _agent(st: StepSignals) -> tuple[str, str] | None:
    if not st.source:
        return None
    return st.source, f"in {st.source}"


# (key, name, question, grouper, ordinal)
AXES: tuple[tuple[str, str, str, Grouper, bool], ...] = (
    (
        "mistakes",
        "Mistakes so far",
        "Once a session has gone wrong a few times, does it keep going wrong?",
        _mistakes,
        True,
    ),
    (
        "time_of_day",
        "Time of day",
        "Do sessions at some hours go worse than others?",
        _hour,
        False,
    ),
    (
        "autonomy",
        "Steps since you last spoke",
        "Does the agent slip more the longer it runs without you?",
        _autonomy,
        True,
    ),
    ("model", "Model", "Which model holds up best on your work?", _model, False),
    ("agent", "Coding agent", "Which agent CLI holds up best on your work?", _agent, False),
    (
        "context_fill",
        "Context fill",
        "Does a fuller context window make it slip more?",
        _fill,
        True,
    ),
)


def _group(steps: Iterable[StepSignals], grouper: Grouper) -> list[FactorGroup]:
    """Bucket steps by ``grouper``, keeping first-seen group order."""
    groups: dict[str, FactorGroup] = {}
    for st in steps:
        found = grouper(st)
        if found is None:
            continue
        label, phrase = found
        g = groups.get(label)
        if g is None:
            g = groups[label] = FactorGroup(label=label, phrase=phrase)
        g.n += 1
        if st.degraded:
            g.failures += 1
    return list(groups.values())


def _ordered(key: str, groups: list[FactorGroup]) -> list[FactorGroup]:
    """Natural order for display: the axis's own order, or biggest-first."""
    if key in ("model", "agent"):
        return sorted(groups, key=lambda g: g.n, reverse=True)
    order = {
        "time_of_day": [h[2] for h in _HOURS],
    }.get(key)
    if order is not None:
        return sorted(groups, key=lambda g: order.index(g.label) if g.label in order else 99)
    # Numeric axes are bucketed in ascending order already, but steps arrive in
    # session order, so the first-seen order is not reliably ascending.
    def lower_bound(g: FactorGroup) -> float:
        head = g.label.replace("none yet", "0").split("–")[0].rstrip("+%")
        try:
            return float(head)
        except ValueError:
            return 0.0

    return sorted(groups, key=lower_bound)


def _action(key: str, worst: FactorGroup, best: FactorGroup, groups: list[FactorGroup]) -> str:
    """One concrete thing to do about a factor that showed an effect."""
    ladder = [g.label for g in groups]
    rising = ladder.index(worst.label) > ladder.index(best.label)
    if key == "mistakes":
        if rising:
            return "When mistakes start piling up, start a fresh session instead of pushing on."
        return "Early mistakes don't snowball for you — pushing on through them is fine."
    if key == "time_of_day":
        return (
            f"Save risky changes for the {best.label}, when it holds up best — "
            f"and be wary of the {worst.label}."
        )
    if key == "autonomy":
        if rising:
            return f"Check in before the agent gets {worst.label} steps into a run on its own."
        return "Long unsupervised runs hold up fine — you don't need to hover."
    if key in ("model", "agent"):
        return f"For your work, {best.label} holds up better than {worst.label}."
    if key == "context_fill":
        if rising:
            return f"Compact or start fresh before the context reaches {worst.label}."
        return "A fuller context isn't what hurts you — don't clear just for the sake of it."
    return ""


def _assess(factor: Factor) -> Factor:
    """Fill in worst/best/ratio/strength/finding for one factor."""
    eligible = [g for g in factor.groups if g.eligible]
    if len(eligible) < 2:
        factor.strength = "insufficient"
        factor.finding = (
            f"Not enough data yet — needs at least two groups of {FACTOR_MIN_N}+ steps."
        )
        return factor

    if factor.ordinal:
        # Ends, not extremes: the axis asks a directional question.
        low_end, high_end = eligible[0], eligible[-1]
        worst, best = (
            (high_end, low_end) if high_end.rate >= low_end.rate else (low_end, high_end)
        )
    else:
        worst = max(eligible, key=lambda g: g.rate)
        best = min(eligible, key=lambda g: g.rate)
    factor.worst, factor.best = worst, best

    if best.rate > 0:
        factor.ratio = worst.rate / best.rate
    elif worst.rate > 0:
        factor.ratio = float("inf")
    else:
        factor.ratio = 1.0

    big_enough = factor.ratio >= VERDICT_MIN_RATIO
    separated = worst.ci[0] > best.ci[1]
    if big_enough and separated:
        factor.strength = "clear"
    elif big_enough:
        factor.strength = "maybe"
    else:
        factor.strength = "none"

    if factor.strength == "none":
        if factor.ordinal:
            lo, hi = eligible[0], eligible[-1]
            factor.finding = (
                f"No real difference from {lo.label} ({lo.rate:.1%}) "
                f"to {hi.label} ({hi.rate:.1%})."
            )
        else:
            factor.finding = (
                f"No real difference: {best.rate:.1%} at best, {worst.rate:.1%} at worst."
            )
        return factor

    ratio = "far more" if factor.ratio == float("inf") else f"{factor.ratio:.1f}× as"
    factor.finding = (
        f"It slips {ratio} often {worst.phrase} as {best.phrase} "
        f"({worst.rate:.1%} vs {best.rate:.1%})."
    )
    factor.action = _action(factor.key, worst, best, factor.groups)
    return factor


def build_factors(steps: list[StepSignals]) -> list[Factor]:
    """Every axis, assessed and ranked strongest-first."""
    out: list[Factor] = []
    for key, name, question, grouper, ordinal in AXES:
        groups = _ordered(key, _group(steps, grouper))
        factor = Factor(key=key, name=name, question=question, ordinal=ordinal, groups=groups)
        out.append(_assess(factor))
    return sorted(out, key=lambda f: f.rank)


def strongest(factors: list[Factor], *, exclude: tuple[str, ...] = ()) -> Factor | None:
    """The single most important clear effect, or None if nothing cleared the bar."""
    for f in factors:
        if f.strength == "clear" and f.key not in exclude:
            return f
    return None


def factor_dict(f: Factor) -> dict:
    """A factor as plain data, for --json and for ``contextrot share``.

    Group labels are agent names, model families, hours and buckets — never
    project names or paths — so this is safe to include in an anonymized share.
    """

    def group(g: FactorGroup | None) -> dict | None:
        if g is None:
            return None
        return {"label": g.label, "n": g.n, "failures": g.failures, "rate": round(g.rate, 4)}

    ratio = f.ratio
    return {
        "factor": f.key,
        "name": f.name,
        "strength": f.strength,
        "ordinal": f.ordinal,
        "ratio": None if ratio is None or ratio == float("inf") else round(ratio, 3),
        "worst": group(f.worst),
        "best": group(f.best),
        "groups": [group(g) for g in f.groups],
        "finding": f.finding,
        "action": f.action,
    }


__all__ = [
    "AXES",
    "FACTOR_MIN_N",
    "STRENGTHS",
    "Factor",
    "FactorGroup",
    "build_factors",
    "factor_dict",
    "strongest",
]
