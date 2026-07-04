"""Terminal report rendering (Rich)."""

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


def _curve_max_rate(curve: RotCurve) -> float:
    """Bar scale: ignore low-confidence buckets so a noisy 4-step bucket
    can't flatten the real bars (parity with the HTML chart)."""
    visible = [b for b in curve.buckets if b.n]
    trusted = [b for b in visible if not b.low_confidence] or visible
    return max((b.rate for b in trusted), default=0.0)


def _sparkline(curve: RotCurve) -> str:
    max_rate = _curve_max_rate(curve)
    if max_rate <= 0:
        return ""
    out = []
    for b in curve.buckets:
        if b.n == 0:
            continue
        idx = min(int(min(b.rate, max_rate) / max_rate * (len(_SPARK) - 1)), len(_SPARK) - 1)
        out.append(_SPARK[idx])
    return "".join(out)


def render(result: AnalysisResult, console: Console | None = None) -> None:
    console = console or Console()
    curve = result.curve

    console.print()
    console.print(_headline(result))
    console.print()

    if curve.total_steps:
        console.print(_rot_curve_table(result))
        console.print()

    if len([m for m in result.models if not m.is_other]) >= 2:
        console.print(_models_table(result))
        console.print()

    console.print(_composition_panel(result))
    console.print()

    if result.prescriptions:
        console.print(_prescriptions_panel(result))
        console.print()

    console.print(
        f"[dim]{len(result.sessions)} sessions · {curve.total_steps} steps analyzed"
        + (f" · last {result.days} days" if result.days else "")
        + f" · {result.skipped_sessions} sessions skipped (too short/unreadable)."
        + " Observational diagnostic, not a controlled experiment —"
        + " see the methodology docs.[/dim]"
    )


_VERDICT_STYLE = {
    "rot": "bold red",
    "edge": "bold yellow",
    "clean": "bold green",
    "insufficient": "bold yellow",
}
_VERDICT_ICON = {"rot": "✗ ", "edge": "! ", "clean": "✓ ", "insufficient": "? "}


_VERDICT_COLOR = {"rot": "red", "edge": "yellow", "clean": "green", "insufficient": "yellow"}


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
        t.append("  rot curve ", style="dim")
        t.append(spark, style=color)
        t.append("  (fill 0→100%)", style="dim")
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
        t.append("Deep-context failure rate: ", style="bold")
        t.append(f"{curve.high_fill_rate:.1%}", style="bold red")
        t.append(" vs ")
        t.append(f"{curve.low_fill_rate:.1%}", style="bold green")
        t.append(" in fresh context ")
        ratio = curve.degradation_ratio
        ratio_s = "∞" if ratio == float("inf") else f"{ratio:.1f}×"
        t.append(f"({ratio_s}", style="bold")
        t.append(
            ", statistically significant)"
            if curve.ratio_significant
            else ", within statistical noise)",
            style="dim",
        )
        lines.append(t)

    t = Text()
    t.append("Your degradation threshold: ", style="bold")
    if curve.knee_pct is not None:
        t.append(f"~{curve.knee_pct}% context fill", style="bold yellow")
    else:
        t.append("none found", style="green")
        t.append(" (failure rate doesn't climb with fill)", style="dim")
    lines.append(t)

    t = Text()
    t.append("Token value burned in degraded steps: ", style="bold")
    t.append(f"${result.rework_cost_usd:.2f}", style="bold red")
    t.append(f" of ${result.total_cost_usd:.2f} total")
    lines.append(t)
    lines.append(
        Text(
            "  (tokens priced at API list rates — an efficiency yardstick, not your "
            "bill; subscriptions pay a flat fee)",
            style="dim",
        )
    )

    return Panel(
        Group(*lines),
        title="[bold]contextrot — your context rot report[/bold]",
        border_style=color,
        padding=(1, 3),
    )


def _rot_curve_table(result: AnalysisResult) -> Table:
    curve = result.curve
    max_rate = _curve_max_rate(curve)

    table = Table(
        title="Failure-signal rate by context fill",
        show_edge=False,
        pad_edge=False,
    )
    table.add_column("Fill", justify="right", style="cyan")
    table.add_column("Rate", justify="right")
    table.add_column("", min_width=BAR_WIDTH, max_width=BAR_WIDTH)
    table.add_column("n", justify="right", style="dim")
    table.add_column("95% CI", justify="right", style="dim")

    for b in curve.buckets:
        if b.n == 0:
            continue
        lo_ci, hi_ci = b.ci
        past_knee = curve.knee_pct is not None and b.lo >= curve.knee_pct
        bar_style = "red" if past_knee else "blue"
        rate_txt = f"{b.rate:.0%}" + ("*" if b.low_confidence else "")
        table.add_row(
            f"{b.lo}–{b.hi}%",
            rate_txt,
            Text(_bar(b.rate, max_rate), style=bar_style),
            str(b.n),
            f"{lo_ci:.0%}–{hi_ci:.0%}",
        )

    if any(b.low_confidence for b in curve.buckets if b.n):
        table.caption = "* fewer than 15 steps in bucket — low confidence"
    return table


def _models_table(result: AnalysisResult) -> Table:
    table = Table(title="By model", show_edge=False, pad_edge=False)
    table.add_column("Model", style="cyan")
    table.add_column("Steps", justify="right", style="dim")
    table.add_column("Fresh", justify="right")
    table.add_column("Deep", justify="right")
    table.add_column("Ratio", justify="right")
    table.add_column("Threshold", justify="right")
    table.add_column("Verdict")

    def fmt_rate(r: float | None) -> str:
        return f"{r:.1%}" if r is not None else "n/a"

    for m in result.models:
        c = m.curve
        ratio = c.degradation_ratio
        if ratio is None:
            ratio_s = "n/a"
        elif ratio == float("inf"):
            ratio_s = "∞"
        else:
            ratio_s = f"{ratio:.1f}×"
        knee_s = f"~{c.knee_pct}%" if c.knee_pct is not None else "none"
        if m.is_other:
            verdict_cell = Text("—", style="dim")
        else:
            verdict_cell = Text(
                _VERDICT_ICON[m.verdict_kind] + m.verdict_kind,
                style=_VERDICT_STYLE[m.verdict_kind],
            )
        row_style = "dim" if m.is_other else ""
        table.add_row(
            Text(m.label, style=row_style or "cyan"),
            str(m.steps),
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
        ("Startup overhead", comp.overhead_tokens, "before your first word"),
        ("Tool outputs", comp.tool_output_tokens, "results flowing into context"),
        ("Conversation", comp.conversation_tokens, "your messages + agent text"),
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
        f"Per-session averages (est., chars/4). Startup overhead is "
        f"{comp.overhead_pct_of_window:.0f}% of your {comp.context_window:,}-token "
        "window, every session.",
        style="bold" if comp.overhead_pct_of_window >= 15 else "",
    )
    return Panel(
        Group(table, Text(), sub),
        title="[bold]Where your context goes (estimated)[/bold]",
        padding=(1, 2),
    )


def _prescriptions_panel(result: AnalysisResult) -> Panel:
    lines: list[Text] = []
    for i, p in enumerate(result.prescriptions, 1):
        t = Text()
        t.append(f"{i}. {p.title}\n", style="bold yellow")
        t.append(f"   {p.detail}\n", style="")
        t.append(f"   Impact: {p.impact}\n", style="dim")
        lines.append(t)
    return Panel(Group(*lines), title="[bold]Prescriptions[/bold]", padding=(1, 2))
