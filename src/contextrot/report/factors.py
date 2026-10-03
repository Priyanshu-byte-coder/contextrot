"""The factors report: what actually moves your failure rate.

Two parts, in the order you need them. First a ranked table — one row per axis,
strongest effect first — so the shape of the answer is visible at a glance.
Then, only for effects that cleared the bar, the plain-language finding and the
one thing to do about it. Axes with no effect stay in the table on purpose:
"time of day doesn't matter for you" is an answer too, and leaving it out would
make a clean result look like a missing one.

The gap bar is log-scaled. Ratios multiply — 2× and 4× are the same step apart
as 1× and 2× — and a linear bar would let one 9× outlier flatten every other row
to a sliver.
"""

from __future__ import annotations

import math

from rich.console import Console, Group
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from contextrot import anim
from contextrot.analysis import AnalysisResult
from contextrot.analysis.factors import FACTOR_MIN_N, Factor

# A 10× gap fills the bar; anything bigger is clamped. 10× is already "this one
# thing dominates", and a longer scale would make ordinary 1.5× effects invisible.
_GAP_CEILING = 10.0
_GAP_CELLS = 10

# How many findings to spell out below the table. The table shows every axis;
# prose is for the ones worth acting on, and three is already a to-do list.
MAX_FINDINGS = 3

_MARK = {"clear": "●", "maybe": "◐", "none": "○", "insufficient": "·"}
_STYLE = {"clear": "bold red", "maybe": "yellow", "none": "dim", "insufficient": "dim"}
_WORD = {
    "clear": "clear",
    "maybe": "maybe",
    "none": "no effect",
    "insufficient": "too little data",
}


def _gap(ratio: float | None) -> float:
    """0..1 position of a ratio on the log-scaled gap bar."""
    if ratio is None or ratio <= 1.0:
        return 0.0
    if ratio == float("inf"):
        return 1.0
    return min(1.0, math.log(ratio) / math.log(_GAP_CEILING))


def _contrast(f: Factor) -> Text:
    """``night 5.3%  vs  morning 3.2%`` — or why there is no contrast."""
    if f.strength == "insufficient":
        return Text(f"needs two groups of {FACTOR_MIN_N}+ steps", style="dim")
    if f.strength == "none" or f.worst is None or f.best is None:
        return Text("no real difference", style="dim")
    t = Text()
    t.append(f.worst.label, style="bold")
    t.append(f" {f.worst.rate:.1%}", style="red")
    t.append("  vs  ", style="dim")
    t.append(f.best.label, style="bold")
    t.append(f" {f.best.rate:.1%}", style="green")
    return t


def _table(factors: list[Factor], rv: anim.Reveal) -> Table:
    table = Table(box=None, pad_edge=False, padding=(0, 2, 0, 0), show_header=True)
    table.add_column("", no_wrap=True)
    table.add_column("Factor", style="cyan", no_wrap=True)
    table.add_column("Worst vs best")
    table.add_column("Gap", justify="right", no_wrap=True)
    table.add_column("", min_width=_GAP_CELLS, max_width=_GAP_CELLS)
    table.add_column("", no_wrap=True)

    for i, f in enumerate(factors):
        local = rv.stagger(i, len(factors))
        style = _STYLE[f.strength]
        if f.ratio is None or f.strength == "insufficient":
            gap = ""
        elif f.ratio == float("inf"):
            gap = "∞"
        else:
            gap = f"{f.ratio:.1f}×"
        table.add_row(
            Text(_MARK[f.strength], style=style),
            f.name,
            _contrast(f),
            Text(gap, style=style),
            # No bar for "no effect": a 1.1× sliver is noise drawn as if it meant
            # something, and the word beside it already says it doesn't.
            Text(
                anim.bar(_gap(f.ratio), 1.0, _GAP_CELLS, local)
                if f.strength in ("clear", "maybe")
                else "",
                style=style,
            ),
            Text(_WORD[f.strength], style=style),
        )
    return table


def _findings(factors: list[Factor]) -> list:
    """The prose: what was found and what to do, for effects worth acting on."""
    worth = [f for f in factors if f.strength in ("clear", "maybe")][:MAX_FINDINGS]
    if not worth:
        return [
            Text(
                "Nothing here separates your good steps from your bad ones. Whatever is "
                "causing your slips, it isn't any of these.",
                style="dim",
            )
        ]
    out: list = []
    for f in worth:
        head = Text()
        head.append(f"{_MARK[f.strength]} {f.name}", style=_STYLE[f.strength])
        if f.strength == "maybe":
            head.append("  (suggestive — the ranges overlap)", style="dim")
        out.append(head)
        out.append(Padding(Text(f.finding), (0, 0, 0, 2)))
        if f.action:
            act = Text("→ ", style="bold")
            act.append(f.action)
            out.append(Padding(act, (0, 0, 0, 2)))
        out.append(Text())
    return out


def render(
    result: AnalysisResult, console: Console | None = None, *, animate: bool = False
) -> None:
    """Print the factors report."""
    console = console or Console()
    factors = list(result.factors)

    console.print()
    console.print(Text("  What actually moves your failure rate", style="bold"))
    scope = f"  Measured on {len(result.steps):,} steps"
    if result.days:
        scope += f" from the last {result.days} days"
    console.print(Text(scope + ".", style="dim"))
    console.print()

    anim.play(console, lambda rv: Padding(_table(factors, rv), (0, 0, 0, 2)), animate=animate)
    console.print()

    console.print(Padding(Group(*_findings(factors)), (0, 0, 0, 2)))
    console.print(
        Padding(
            Text(
                "Association, not causation. Ordered factors compare their two ends; "
                "categories compare the best against the worst. ● clear = ranges don't "
                "overlap, ◐ maybe = they do.",
                style="dim",
            ),
            (0, 0, 0, 2),
        )
    )
    console.print()


__all__ = ["MAX_FINDINGS", "render"]
