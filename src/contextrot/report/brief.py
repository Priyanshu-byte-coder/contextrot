"""The short report — what you ran the tool to find out, and nothing else.

The full report (``terminal.render``) is an analysis: curves with confidence
intervals, a reversal table, three comparison tables, a context-composition
breakdown. That is the right output when you are investigating. It is the
wrong output when you just want to know whether you are fine, because the
answer is buried in the fourth panel.

This one answers three questions and stops:

1. Am I degrading?
2. If so, where — and what is it costing me?
3. What should I change?

The editorial rule, applied to every line: **if it would not change what you
do next, it belongs in ``--full``.** Confidence intervals, per-bucket counts,
the snowball table and the model comparison are all real and all useful, and
none of them survive that test for a first-time reader.

Prose rather than tables on purpose. A table invites you to read every cell; a
sentence tells you the answer.
"""

from __future__ import annotations

from rich.console import Console
from rich.padding import Padding
from rich.text import Text

from contextrot.analysis import AnalysisResult
from contextrot.analysis.rot import RotCurve
from contextrot.report._hero import HEADLINE_WORDS, VERDICT_COLOR, VERDICT_ICON

# Prescriptions worth interrupting someone for. The rest are in --full: a list
# of eight "things to try" is a backlog, not advice.
MAX_ACTIONS = 2

# A bucket needs at least this many steps before its depth counts as "measured".
# Matches the floor the calibration cache uses to quote a rate.
_MIN_BUCKET_N = 30


def _deepest_measured(curve: RotCurve) -> float | None:
    """Highest context fill the data actually reaches, ignoring thin buckets.

    A flat curve means one of two very different things — fill does not hurt
    you, or you never fill the window far enough to find out. On a 1M-token
    window most sessions never pass 80%, so "no rot" without this caveat
    overstates what was measured.
    """
    best: float | None = None
    for b in curve.buckets:
        if b.n >= _MIN_BUCKET_N and (best is None or b.hi > best):
            best = float(b.hi)
    return best


def _waste_share(result: AnalysisResult) -> float | None:
    """Share of token value spent on steps that slipped.

    Deliberately a percentage, not the dollar figure: costs are computed from
    API list prices, so on a subscription the absolute number is "what this
    would have cost on the API" and reads as a bill you never got. The share
    is the part that means the same thing either way.
    """
    if result.total_cost_usd <= 0:
        return None
    return result.rework_cost_usd / result.total_cost_usd


def _what_happened(result: AnalysisResult) -> Text:
    """One or two sentences: the finding, in plain words."""
    curve = result.curve
    kind = result.verdict_kind
    color = VERDICT_COLOR[kind]
    t = Text()

    if kind == "insufficient":
        t.append("There isn't enough data yet to say either way. ")
        t.append(
            f"You have {curve.low_fill_n:,} steps on a fresh context and "
            f"{curve.high_fill_n:,} on a full one; a verdict needs more of the thinner side."
        )
        return t

    if curve.high_fill_rate is None or curve.low_fill_rate is None:
        t.append(result.verdict_text)
        return t

    t.append("Your agent slips ")
    t.append(f"{curve.high_fill_rate:.1%}", style=f"bold {color}")
    t.append(" of the time when the context is nearly full, against ")
    t.append(f"{curve.low_fill_rate:.1%}", style="bold green")
    t.append(" when it's fresh")

    ratio = curve.degradation_ratio
    if kind in ("rot", "edge") and ratio is not None and ratio != float("inf"):
        t.append(" — ")
        t.append(f"{ratio:.1f}× worse", style=f"bold {color}")
        t.append(".")
    else:
        t.append(".")

    if curve.knee_pct is not None:
        t.append(" Quality drops past ")
        t.append(f"~{curve.knee_pct:.0f}% full", style=f"bold {color}")
        t.append(" and stays down.")
    elif kind == "clean":
        t.append(" Filling the window is not what's hurting your output.")
    return t


def _evidence(result: AnalysisResult) -> Text:
    """The scale behind the claim, and how deep it actually reaches."""
    curve = result.curve
    t = Text(style="dim")
    t.append(f"Measured on {curve.total_steps:,} steps")
    if result.days:
        t.append(f" from the last {result.days} days")
    deepest = _deepest_measured(curve)
    if deepest is not None and deepest < 100:
        t.append(f", up to {deepest:.0f}% full")
    t.append(".")
    return t


def _cost_line(result: AnalysisResult) -> Text | None:
    if result.verdict_kind == "insufficient":
        # Not enough data for a verdict is not enough data for a cost share
        # either; quoting one off a handful of steps is confident noise.
        return None
    share = _waste_share(result)
    if share is None or share <= 0:
        return None
    t = Text(style="dim")
    t.append(f"{share:.1%}")
    t.append(" of your token spend went to steps that slipped — retries, failed")
    t.append(" edits and re-reads that produced nothing.")
    return t


def _actions(result: AnalysisResult) -> list[Text]:
    """The top prescriptions, or an explicit all-clear."""
    lines: list[Text] = []
    if not result.prescriptions:
        t = Text("→ ", style="bold green")
        if result.verdict_kind == "clean":
            t.append("Nothing about context fill — your setup is holding up.")
        else:
            t.append("No specific fix reached its evidence threshold yet.")
        lines.append(t)
        return lines

    for p in sorted(result.prescriptions, key=lambda x: x.priority)[:MAX_ACTIONS]:
        head = Text("→ ", style="bold")
        head.append(p.title, style="bold")
        lines.append(head)
        if p.impact:
            lines.append(Text(f"   {p.impact}", style="dim"))
    return lines


def render(result: AnalysisResult, console: Console | None = None) -> None:
    """Print the short report."""
    console = console or Console()
    kind = result.verdict_kind
    color = VERDICT_COLOR[kind]

    def body(renderable) -> None:
        # Padding, not leading spaces: it indents wrapped continuation lines
        # too, and these sentences are long enough to wrap on a narrow terminal.
        console.print(Padding(renderable, (0, 0, 0, 2)))

    console.print()
    headline = Text(f" {VERDICT_ICON[kind].strip()} {HEADLINE_WORDS.get(kind, '')} ")
    headline.stylize(f"bold {color} reverse")
    console.print(headline)
    console.print()

    body(_what_happened(result))
    console.print()
    body(_evidence(result))
    cost = _cost_line(result)
    if cost is not None:
        body(cost)
    console.print()

    console.print(Text("  What to do", style="bold"))
    for line in _actions(result):
        body(line)
    console.print()

    hint = Text(style="dim")
    hint.append("Run ")
    hint.append("contextrot --full", style="cyan")
    hint.append(" for the curve behind this, the comparisons, and where your context goes.")
    body(hint)
    console.print()


__all__ = ["render"]
