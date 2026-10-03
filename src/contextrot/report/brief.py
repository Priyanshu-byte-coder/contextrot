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

from rich.console import Console, Group
from rich.padding import Padding
from rich.text import Text

from contextrot.analysis import AnalysisResult
from contextrot.analysis.rot import RotCurve
from contextrot.anim import Reveal, play
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


def _factor_line(result: AnalysisResult) -> Text | None:
    """The strongest *other* thing that moves the failure rate, if one is clear.

    Context fill is left out because the paragraph above already answered it.
    This line matters most on a clean verdict: "fill isn't hurting you" is a dead
    end on its own, and "but working at night is" is something you can act on.
    """
    if result.verdict_kind == "insufficient":
        return None
    from contextrot.analysis.factors import strongest

    top = strongest(result.factors, exclude=("context_fill",))
    if top is None:
        return None
    lead = "What does move it: " if result.verdict_kind == "clean" else "Also worth knowing: "
    t = Text()
    t.append(lead, style="bold")
    t.append(top.finding[:1].lower() + top.finding[1:])
    return t


def _live_suggestion(result: AnalysisResult) -> str:
    """The one live surface worth suggesting to *this* user.

    Claude Code users without the statusline get the statusline, because a report
    you run once is forgotten and a meter you see every turn is not. Users of other
    agents get `status`, which works in any terminal. Anyone already set up is
    pointed at `share` instead of being told to install what they have.
    """
    uses_claude = any(s.source == "claude-code" for s in result.sessions)
    if not uses_claude:
        return "contextrot status --setup tmux"
    try:
        from contextrot.install import claude_settings_path, is_contextrot_entry, read_settings

        installed = is_contextrot_entry(read_settings(claude_settings_path()).get("statusLine"))
    except Exception:  # noqa: BLE001 — a suggestion must never break the report
        installed = False
    return "contextrot share" if installed else "contextrot install statusline --apply"


def _actions(result: AnalysisResult) -> list:
    """The top prescriptions, or an explicit all-clear."""
    lines: list = []
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
            # Padding, not leading spaces, so a wrapped impact line stays under
            # the title instead of falling back to the margin.
            lines.append(Padding(Text(p.impact, style="dim"), (0, 0, 0, 3)))
    return lines


def render(
    result: AnalysisResult, console: Console | None = None, *, animate: bool = False
) -> None:
    """Print the short report.

    The verdict prints immediately and is never animated: it is the answer, and
    making someone wait for the answer is the one thing an animation must not do.
    What follows it — the explanation, the evidence, the action — arrives a line at
    a time, in the order you would read it anyway.

    No counting-up numbers here, deliberately. These are sentences with figures
    inside them, and a figure that changes width mid-count ("$9" to "$248.91")
    re-wraps the paragraph around it. Bars and standalone totals animate; prose
    does not.
    """
    console = console or Console()
    kind = result.verdict_kind
    color = VERDICT_COLOR[kind]

    def pad(renderable):
        # Padding, not leading spaces: it indents wrapped continuation lines
        # too, and these sentences are long enough to wrap on a narrow terminal.
        return Padding(renderable, (0, 0, 0, 2))

    console.print()
    headline = Text(f" {VERDICT_ICON[kind].strip()} {HEADLINE_WORDS.get(kind, '')} ")
    headline.stylize(f"bold {color} reverse")
    console.print(headline)
    console.print()

    blocks: list = [pad(_what_happened(result))]
    factor = _factor_line(result)
    if factor is not None:
        blocks.append(pad(factor))
    blocks.append(Text())
    blocks.append(pad(_evidence(result)))
    cost = _cost_line(result)
    if cost is not None:
        blocks.append(pad(cost))
    blocks.append(Text())
    blocks.append(Text("  What to do", style="bold"))
    blocks.extend(pad(line) for line in _actions(result))
    blocks.append(Text())

    # Three next steps, not a paragraph about each: the curve behind the verdict,
    # what else moves the rate, and the one live surface that fits this user.
    hint = Text(style="dim")
    hint.append("Next  ")
    for i, cmd in enumerate(("contextrot --full", "contextrot factors", _live_suggestion(result))):
        if i:
            hint.append("  ·  ")
        hint.append(cmd, style="cyan")
    blocks.append(pad(hint))

    def build(rv: Reveal):
        shown = list(rv.visible(blocks))
        # Hold the final height from the first frame so the block does not grow
        # downward under the cursor as lines arrive.
        return Group(*shown, *(Text() for _ in range(len(blocks) - len(shown))))

    play(console, build, animate=animate)
    console.print()


__all__ = ["render"]
