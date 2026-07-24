"""Terminal report rendering (Rich).

Design goal: a first-time reader with no idea what "context rot" or a "reversal"
is should still understand every section. Each block leads with one plain-English
line that says *what it shows and why it matters*; the numbers stay exact.
"""

from __future__ import annotations

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from contextrot.analysis import AnalysisResult, RotCurve
from contextrot.report._hero import hero_stat

BAR_WIDTH = 40
_SPARK = "▁▂▃▄▅▆▇█"


def _bar(rate: float, max_rate: float, width: int = BAR_WIDTH) -> str:
    if max_rate <= 0:
        return ""
    filled = min(width, round(width * rate / max_rate))
    return "█" * filled


def _curve_max_rate(buckets: list) -> float:
    """Bar scale: ignore low-confidence buckets so a noisy 4-step bucket
    can't flatten the real bars (parity with the HTML chart). Works for any
    bucket kind with n/rate/low_confidence (fill and reversal curves)."""
    visible = [b for b in buckets if b.n]
    trusted = [b for b in visible if not b.low_confidence] or visible
    return max((b.rate for b in trusted), default=0.0)


def _sparkline(curve: RotCurve) -> str:
    max_rate = _curve_max_rate(curve.buckets)
    if max_rate <= 0:
        return ""
    out = []
    for b in curve.buckets:
        if b.n == 0:
            continue
        idx = min(int(min(b.rate, max_rate) / max_rate * (len(_SPARK) - 1)), len(_SPARK) - 1)
        out.append(_SPARK[idx])
    return "".join(out)


def _hint(text: str) -> Text:
    """One plain-language line under a section title (never competes with numbers)."""
    return Text(text, style="italic dim")


def render(result: AnalysisResult, console: Console | None = None) -> None:
    console = console or Console()
    curve = result.curve
    color = _VERDICT_COLOR[result.verdict_kind]

    console.print()
    console.print(_headline(result))
    console.print()

    if curve.total_steps:
        console.rule("[bold]Does your agent get worse as its context fills?[/bold]", style=color)
        console.print(
            _hint(
                "Each row: a slice of how full the context window was, and how often the "
                "agent slipped there.\nA slip = a failed edit, a repeated tool call, a "
                "re-read, an “actually, let me fix that,” or a tool error."
            )
        )
        console.print()
        console.print(_rot_curve_table(result))
        console.print()

        console.rule("[bold]Do mistakes snowball?[/bold]", style=color)
        console.print(
            _hint(
                "A “reversal” is the agent undoing or contradicting itself — a failed edit, "
                "a retry after an error,\nor an “actually, let me fix that.” This asks: once a "
                "session already has a few reversals,\ndoes the very next step fail more often?"
            )
        )
        console.print()
        console.print(_reversal_curve_table(result))
        console.print()

    comparisons: list[tuple[str, str, list]] = [
        ("By model", "which model holds up best on your work", list(result.models)),
        ("By project", "which repo degrades first", list(result.projects)),
        ("By coding agent", "which CLI holds up best", list(result.agents)),
    ]
    shown_any = False
    for title, why, rows in comparisons:
        if len([r for r in rows if not r.is_other]) >= 2:
            if not shown_any:
                console.rule("[bold]Side-by-side comparisons[/bold]", style=color)
                console.print(_hint(_COMPARISON_LEGEND))
                console.print()
                shown_any = True
            console.print(_comparison_table(title, why, rows))
            console.print()

    console.rule("[bold]Where your context goes[/bold]", style=color)
    console.print()
    console.print(_composition_panel(result))
    console.print()

    if result.prescriptions:
        console.rule("[bold]What to change[/bold]", style=color)
        console.print()
        console.print(_prescriptions_panel(result))
        console.print()

    console.print(
        f"[dim]{len(result.sessions)} sessions · {curve.total_steps} steps analyzed"
        + (f" · last {result.days} days" if result.days else "")
        + f" · {result.skipped_sessions} skipped (too short to read). "
        + "This spots patterns in your real sessions — it doesn’t prove cause. "
        + "See the methodology docs.[/dim]"
    )


_VERDICT_STYLE = {
    "rot": "bold red",
    "edge": "bold yellow",
    "clean": "bold green",
    "insufficient": "bold yellow",
}
_VERDICT_ICON = {"rot": "✗ ", "edge": "! ", "clean": "✓ ", "insufficient": "? "}
_VERDICT_COLOR = {"rot": "red", "edge": "yellow", "clean": "green", "insufficient": "yellow"}

_COMPARISON_LEGEND = (
    "Fresh fail = slip rate when the context is nearly empty · Deep fail = when it's nearly "
    "full\nRatio = Deep ÷ Fresh (1× = no rot, higher = worse) · Threshold = fill where slips "
    "start climbing"
)


def _headline(result: AnalysisResult) -> Panel:
    curve = result.curve
    color = _VERDICT_COLOR[result.verdict_kind]
    hero = hero_stat(result)
    lines: list[Text] = []

    # Verdict word, color-blocked (reverse degrades gracefully under NO_COLOR).
    lines.append(
        Text(
            f" {_VERDICT_ICON[result.verdict_kind].strip()} {hero['headline_word']} ",
            style=f"bold {color} reverse",
        )
    )
    lines.append(Text())

    # The one number, on its own line so it reads big.
    t = Text()
    t.append(f"  {hero['value']}  ", style=f"bold {color}")
    t.append(hero["label"], style="dim")
    lines.append(t)

    spark = _sparkline(curve)
    if spark:
        t = Text()
        t.append("  slip rate ", style="dim")
        t.append(spark, style=color)
        t.append("  (as context fills, left→right)", style="dim")
        lines.append(t)
    lines.append(Text())

    lines.append(
        Text(
            _VERDICT_ICON[result.verdict_kind] + result.verdict_text,
            style=_VERDICT_STYLE[result.verdict_kind],
        )
    )
    lines.append(Text())

    if curve.degradation_ratio is not None and curve.low_fill_rate is not None:
        t = Text()
        t.append("How often it slips: ", style="bold")
        t.append(f"{curve.high_fill_rate:.1%}", style="bold red")
        t.append(" with a nearly-full context vs ")
        t.append(f"{curve.low_fill_rate:.1%}", style="bold green")
        t.append(" with a fresh one ")
        ratio = curve.degradation_ratio
        ratio_s = "∞" if ratio == float("inf") else f"{ratio:.1f}×"
        t.append(f"({ratio_s}", style="bold")
        t.append(
            ", real — clears statistical noise)"
            if curve.ratio_significant
            else ", within statistical noise)",
            style="dim",
        )
        lines.append(t)
        lines.append(
            Text(
                "  (“fresh” = context nearly empty, early in a session · "
                "“deep/full” = context nearly full)",
                style="dim",
            )
        )

    t = Text()
    t.append("Where it starts slipping: ", style="bold")
    if curve.knee_pct is not None:
        t.append(f"~{curve.knee_pct}% full", style="bold yellow")
        t.append(" — compact or start fresh before here", style="dim")
    else:
        t.append("nowhere in particular", style="green")
        t.append(" (slip rate stays flat as it fills)", style="dim")
    lines.append(t)

    t = Text()
    t.append("Wasted on slip-ups & their retries: ", style="bold")
    t.append(f"${result.rework_cost_usd:.2f}", style="bold red")
    t.append(f" of ${result.total_cost_usd:.2f} total token value")
    lines.append(t)
    lines.append(
        Text(
            "  (tokens priced at API list rates — a yardstick for waste, not your bill; "
            "subscriptions pay a flat fee)",
            style="dim",
        )
    )

    return Panel(
        Group(*lines),
        title="[bold]contextrot — your context rot report[/bold]",
        subtitle="[dim]does your coding agent get worse as its context fills up?[/dim]",
        border_style=color,
        padding=(1, 3),
    )


def _rot_curve_table(result: AnalysisResult) -> Table:
    curve = result.curve
    max_rate = _curve_max_rate(curve.buckets)

    table = Table(show_edge=False, pad_edge=False)
    table.add_column("Context fill", justify="right", style="cyan")
    table.add_column("Slip rate", justify="right")
    table.add_column("", min_width=BAR_WIDTH, max_width=BAR_WIDTH)
    table.add_column("steps", justify="right", style="dim")
    table.add_column("give-or-take", justify="right", style="dim")

    for b in curve.buckets:
        if b.n == 0:
            continue
        lo_ci, hi_ci = b.ci
        past_knee = curve.knee_pct is not None and b.lo >= curve.knee_pct
        bar_style = "red" if past_knee else "green"
        rate_txt = f"{b.rate:.0%}" + ("*" if b.low_confidence else "")
        table.add_row(
            f"{b.lo}–{b.hi}%",
            rate_txt,
            Text(_bar(b.rate, max_rate), style=bar_style),
            str(b.n),
            f"{lo_ci:.0%}–{hi_ci:.0%}",
        )

    caption = (
        "green = healthy zone · red = past your threshold · "
        "“give-or-take” = 95% confidence range"
    )
    if any(b.low_confidence for b in curve.buckets if b.n):
        caption += "\n* fewer than 15 steps here — read with caution"
    table.caption = caption
    return table


def _reversal_curve_table(result: AnalysisResult) -> Table:
    curve = result.reversal_curve
    visible = [b for b in curve.buckets if b.n]
    max_rate = _curve_max_rate(curve.buckets)

    table = Table(show_edge=False, pad_edge=False)
    table.add_column("Reversals so far", justify="right", style="cyan")
    table.add_column("Next-step slip rate", justify="right")
    table.add_column("", min_width=BAR_WIDTH, max_width=BAR_WIDTH)
    table.add_column("steps", justify="right", style="dim")
    table.add_column("give-or-take", justify="right", style="dim")

    for b in visible:
        lo_ci, hi_ci = b.ci
        rate_txt = f"{b.rate:.0%}" + ("*" if b.low_confidence else "")
        table.add_row(
            b.label,
            rate_txt,
            Text(_bar(b.rate, max_rate), style="magenta"),
            str(b.n),
            f"{lo_ci:.0%}–{hi_ci:.0%}",
        )

    table.caption = _snowball_takeaway(visible)
    return table


def _snowball_takeaway(visible: list) -> str:
    """A plain, data-driven conclusion for the reversal table."""
    trusted = [b for b in visible if not b.low_confidence]
    base = next((b.rate for b in visible if b.label.startswith("0")), None)
    if base is None and visible:
        base = visible[0].rate
    later_max = max((b.rate for b in trusted[1:]), default=0.0)
    if base and later_max >= 1.5 * base:
        return (
            "→ Yes, mistakes snowball: after a few reversals the next step fails far more "
            "often.\n  Starting a fresh session breaks the spiral."
        )
    return "→ No snowball here: past reversals don't raise the next step's slip rate."


def _comparison_table(title: str, why: str, rows: list) -> Table:
    table = Table(title=f"{title} — [dim]{why}[/dim]", show_edge=False, pad_edge=False)
    table.add_column(title.replace("By ", "").replace("coding ", "").capitalize(), style="cyan")
    table.add_column("Steps", justify="right", style="dim")
    table.add_column("Fresh fail", justify="right")
    table.add_column("Deep fail", justify="right")
    table.add_column("Ratio", justify="right")
    table.add_column("Threshold", justify="right")
    table.add_column("Verdict")

    def fmt_rate(r: float | None) -> str:
        return f"{r:.1%}" if r is not None else "n/a"

    for item in rows:
        c = item.curve
        ratio = c.degradation_ratio
        if ratio is None:
            ratio_s = "n/a"
        elif ratio == float("inf"):
            ratio_s = "∞"
        else:
            ratio_s = f"{ratio:.1f}×"
        knee_s = f"~{c.knee_pct}%" if c.knee_pct is not None else "none"
        if item.is_other:
            verdict_cell = Text("—", style="dim")
        else:
            verdict_cell = Text(
                _VERDICT_ICON[item.verdict_kind] + item.verdict_kind,
                style=_VERDICT_STYLE[item.verdict_kind],
            )
        row_style = "dim" if item.is_other else ""
        table.add_row(
            Text(item.label, style=row_style or "cyan"),
            str(item.steps),
            fmt_rate(c.low_fill_rate),
            fmt_rate(c.high_fill_rate),
            ratio_s,
            knee_s,
            verdict_cell,
            style=row_style or None,
        )
    return table


def _composition_panel(result: AnalysisResult) -> Panel:
    comp = result.composition
    rows = [
        ("Startup overhead", comp.overhead_tokens,
         "loaded before you type — system prompt, tool schemas, CLAUDE.md"),
        ("Tool outputs", comp.tool_output_tokens,
         "results flowing back in — reads, command output"),
        ("Conversation", comp.conversation_tokens, "your messages + the agent's replies"),
        ("Other growth", comp.other_growth_tokens, "thinking, bookkeeping"),
    ]
    rows = [r for r in rows if r[1] > 0]
    biggest = max((r[1] for r in rows), default=1)
    table = Table(show_edge=False, show_header=False, pad_edge=False)
    table.add_column(min_width=17)
    table.add_column(justify="right")
    table.add_column(min_width=16, max_width=16)
    table.add_column(style="dim")
    for label, tokens, note in rows:
        share = tokens / biggest
        bar = Text("█" * max(1, round(16 * share)), style="blue")
        table.add_row(label, f"{tokens:,}", bar, note)
    sub = Text(
        f"Averages per session (estimated). Startup overhead alone is "
        f"{comp.overhead_pct_of_window:.0f}% of your {comp.context_window:,}-token window — "
        "spent before you say a word, every time.",
        style="bold" if comp.overhead_pct_of_window >= 15 else "dim",
    )
    return Panel(
        Group(_hint("Where an average session's context window gets spent:"), Text(), table,
              Text(), sub),
        title="[bold]Where your context goes (estimated)[/bold]",
        padding=(1, 2),
    )


def _prescriptions_panel(result: AnalysisResult) -> Panel:
    lines: list[Text] = [_hint("Concrete things to try, ranked by impact on your data:"), Text()]
    for i, p in enumerate(result.prescriptions, 1):
        t = Text()
        t.append(f"{i}. {p.title}\n", style="bold yellow")
        t.append(f"   {p.detail}\n", style="")
        t.append(f"   Impact: {p.impact}\n", style="dim")
        lines.append(t)
    return Panel(Group(*lines), title="[bold]What to change[/bold]", padding=(1, 2))
