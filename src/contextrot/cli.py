"""contextrot command-line interface.

No `from __future__ import annotations` here: on Python 3.9 typer cannot
evaluate string annotations, which silently strips every typer.Option's
metadata. All annotations in this module must be valid at runtime.
"""

import contextlib
import json
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from contextrot import __version__
from contextrot.analysis import analyze, load_sessions
from contextrot.analysis.by_project import build_project_comparison, project_label
from contextrot.analysis.by_source import build_agent_comparison
from contextrot.analysis.fixes import (
    claude_md_report,
    disable_global_servers,
    unused_mcp_servers,
)

# Windows consoles often default to a legacy codepage that can't encode the
# box-drawing characters Rich uses; force UTF-8 where the stream supports it.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        with contextlib.suppress(ValueError, OSError):
            _stream.reconfigure(encoding="utf-8", errors="replace")

app = typer.Typer(
    name="contextrot",
    help=(
        "Find out where your coding agent starts degrading. "
        "Analyzes agent transcripts already on your disk — nothing is uploaded."
    ),
    no_args_is_help=False,
    add_completion=False,
)
console = Console()

# Optional[...] rather than `X | None`: these are evaluated at runtime (module
# level and again by typer's introspection), and pipe unions need Python 3.10.
DataDir = Annotated[
    Optional[Path],
    typer.Option(
        "--data-dir",
        help="Transcript directory override (default: every supported agent's own data dir).",
    ),
]
ProjectF = Annotated[
    Optional[str], typer.Option("--project", "-p", help="Only sessions whose project matches.")
]
Days = Annotated[int, typer.Option("--days", "-d", help="Only sessions from the last N days.")]
Window = Annotated[
    Optional[int], typer.Option("--window", help="Override the context-window size in tokens.")
]


def _project_basename(project: str) -> str:
    """Last path component of a project working directory.

    Single implementation lives in ``analysis.by_project.project_label`` so the
    ``sessions`` table and the per-project comparison agree on labels.
    """
    return project_label(project)


def _finite_or_none(value: Optional[float]) -> Optional[float]:
    if value is None or value == float("inf"):
        return None
    return round(value, 3)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"contextrot {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    data_dir: DataDir = None,
    project: ProjectF = None,
    days: Days = 30,
    window: Window = None,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
    html: Annotated[
        Optional[Path], typer.Option("--html", help="Also write a shareable HTML report.")
    ] = None,
    version: Annotated[
        Optional[bool],
        typer.Option("--version", callback=_version_callback, is_eager=True),
    ] = None,
) -> None:
    """Analyze your sessions and print the rot report."""
    if ctx.invoked_subcommand is not None:
        return

    result = analyze(data_dir=data_dir, project_filter=project, days=days, window_override=window)

    if not result.sessions:
        console.print(
            "[yellow]No agent sessions found.[/yellow] "
            "contextrot reads local transcripts from Claude Code, Codex CLI, Gemini CLI, "
            "Qwen Code, OpenCode, and Cline/Roo/Kilo Code. "
            "Point elsewhere with --data-dir, or widen the range with --days."
        )
        raise typer.Exit(code=1)

    if as_json:
        payload = {
            "version": __version__,
            "verdict": {"kind": result.verdict_kind, "text": result.verdict_text},
            "sessions": len(result.sessions),
            "steps": [s.as_dict() for s in result.steps],
            "curve": {
                "buckets": [
                    {
                        "range": [b.lo, b.hi],
                        "n": b.n,
                        "degraded": b.degraded,
                        "rate": round(b.rate, 4),
                        "ci": [round(x, 4) for x in b.ci],
                        "by_signal": b.by_signal,
                    }
                    for b in result.curve.buckets
                    if b.n
                ],
                "low_fill_rate": result.curve.low_fill_rate,
                "high_fill_rate": result.curve.high_fill_rate,
                "degradation_ratio": _finite_or_none(result.curve.degradation_ratio),
                "ratio_significant": result.curve.ratio_significant,
                "knee_pct": result.curve.knee_pct,
            },
            "reversal_curve": {
                "buckets": [
                    {
                        "range": [b.lo, b.hi],
                        "label": b.label,
                        "n": b.n,
                        "degraded": b.degraded,
                        "rate": round(b.rate, 4),
                        "ci": [round(x, 4) for x in b.ci],
                    }
                    for b in result.reversal_curve.buckets
                    if b.n
                ],
                "total_reversal_events": result.reversal_curve.total_reversal_events,
            },
            "models": [
                {
                    "family": m.family,
                    "label": m.label,
                    "steps": m.steps,
                    "fresh_rate": m.curve.low_fill_rate,
                    "deep_rate": m.curve.high_fill_rate,
                    "ratio": _finite_or_none(m.curve.degradation_ratio),
                    "ratio_significant": m.curve.ratio_significant,
                    "knee_pct": m.curve.knee_pct,
                    "verdict": m.verdict_kind,
                    "other": m.is_other,
                }
                for m in result.models
            ],
            "projects": [
                {
                    "key": p.key,
                    "label": p.label,
                    "steps": p.steps,
                    "fresh_rate": p.curve.low_fill_rate,
                    "deep_rate": p.curve.high_fill_rate,
                    "ratio": _finite_or_none(p.curve.degradation_ratio),
                    "ratio_significant": p.curve.ratio_significant,
                    "knee_pct": p.curve.knee_pct,
                    "verdict": p.verdict_kind,
                    "other": p.is_other,
                }
                for p in result.projects
            ],
            "agents": [
                {
                    "key": a.key,
                    "label": a.label,
                    "steps": a.steps,
                    "fresh_rate": a.curve.low_fill_rate,
                    "deep_rate": a.curve.high_fill_rate,
                    "ratio": _finite_or_none(a.curve.degradation_ratio),
                    "ratio_significant": a.curve.ratio_significant,
                    "knee_pct": a.curve.knee_pct,
                    "verdict": a.verdict_kind,
                    "other": a.is_other,
                }
                for a in result.agents
            ],
            "composition": vars(result.composition),
            "cost": {
                "total_usd": round(result.total_cost_usd, 2),
                "rework_usd": round(result.rework_cost_usd, 2),
                "pricing_basis": "api_list_prices",
            },
            "prescriptions": [vars(p) for p in result.prescriptions],
        }
        print(json.dumps(payload, indent=2))
    else:
        from contextrot.report import render

        render(result, console)

    if html is not None:
        from contextrot.report import render_html

        try:
            out = render_html(result, html)
        except OSError as e:
            console.print(f"[red]Couldn't write HTML report to {html}:[/red] {e}")
            raise typer.Exit(code=1) from e
        console.print(f"[green]HTML report written:[/green] {out}")


@app.command()
def sessions(
    data_dir: DataDir = None,
    project: ProjectF = None,
    days: Days = 30,
) -> None:
    """List parsed sessions with their peak context fill."""
    found, skipped = load_sessions(data_dir, project, days)
    if not found:
        console.print("[yellow]No sessions found.[/yellow]")
        raise typer.Exit(code=1)

    # Only spend a column on the agent when sessions actually span several.
    multi_agent = len({s.source for s in found}) > 1

    table = Table(title=f"{len(found)} sessions ({skipped} skipped)")
    table.add_column("Started", style="dim")
    table.add_column("Project")
    if multi_agent:
        table.add_column("Agent", style="dim")
    table.add_column("Steps", justify="right")
    table.add_column("Peak prompt", justify="right")
    table.add_column("Model", style="dim")

    for s in found:
        started = s.started_at.strftime("%Y-%m-%d %H:%M") if s.started_at else "?"
        model = s.steps[0].model if s.steps else "?"
        project_name = _project_basename(s.project) if s.project else "?"
        cells = [started, project_name]
        if multi_agent:
            cells.append(s.source)
        cells += [str(len(s.steps)), f"{s.peak_prompt_tokens:,}", model]
        table.add_row(*cells)
    console.print(table)


@app.command()
def projects(
    data_dir: DataDir = None,
    days: Days = 30,
    window: Window = None,
) -> None:
    """Compare context rot across your projects — which repo degrades first."""
    result = analyze(data_dir=data_dir, project_filter=None, days=days, window_override=window)
    if not result.sessions:
        console.print("[yellow]No sessions found.[/yellow]")
        raise typer.Exit(code=1)

    # require_two=False so a single-project user still sees that project's curve.
    stats = build_project_comparison(result.steps, require_two=False)
    if not stats:
        console.print(
            "[yellow]Not enough steps in any project yet[/yellow] "
            "(need ~150 steps per project). Keep using your agent and re-run."
        )
        raise typer.Exit(code=1)

    _icon = {"rot": "✗", "edge": "!", "clean": "✓", "insufficient": "?"}
    _style = {"rot": "red", "edge": "yellow", "clean": "green", "insufficient": "yellow"}

    table = Table(title="Context rot by project")
    table.add_column("Project", style="cyan")
    table.add_column("Steps", justify="right", style="dim")
    table.add_column("Fresh", justify="right")
    table.add_column("Deep", justify="right")
    table.add_column("Ratio", justify="right")
    table.add_column("Threshold", justify="right")
    table.add_column("Verdict")

    for p in stats:
        c = p.curve
        fresh = f"{c.low_fill_rate:.1%}" if c.low_fill_rate is not None else "n/a"
        deep = f"{c.high_fill_rate:.1%}" if c.high_fill_rate is not None else "n/a"
        ratio = c.degradation_ratio
        if ratio is None:
            ratio_s = "n/a"
        elif ratio == float("inf"):
            ratio_s = "∞"
        else:
            ratio_s = f"{ratio:.1f}×"
        knee_s = f"~{c.knee_pct}%" if c.knee_pct is not None else "none"
        if p.is_other:
            verdict_cell = "[dim]—[/dim]"
        else:
            verdict_cell = f"[{_style[p.verdict_kind]}]{_icon[p.verdict_kind]} {p.verdict_kind}[/]"
        table.add_row(p.label, str(p.steps), fresh, deep, ratio_s, knee_s, verdict_cell)
    console.print(table)


@app.command()
def agents(
    data_dir: DataDir = None,
    days: Days = 30,
    window: Window = None,
) -> None:
    """Compare context rot across your coding agents — which CLI degrades first."""
    result = analyze(data_dir=data_dir, project_filter=None, days=days, window_override=window)
    if not result.sessions:
        console.print("[yellow]No sessions found.[/yellow]")
        raise typer.Exit(code=1)

    # require_two=False so a single-agent user still sees that agent's curve.
    stats = build_agent_comparison(result.steps, require_two=False)
    if not stats:
        console.print(
            "[yellow]Not enough steps from any agent yet[/yellow] "
            "(need ~150 steps per agent). Keep using your agent and re-run."
        )
        raise typer.Exit(code=1)

    _icon = {"rot": "✗", "edge": "!", "clean": "✓", "insufficient": "?"}
    _style = {"rot": "red", "edge": "yellow", "clean": "green", "insufficient": "yellow"}

    table = Table(title="Context rot by agent")
    table.add_column("Agent", style="cyan")
    table.add_column("Steps", justify="right", style="dim")
    table.add_column("Fresh", justify="right")
    table.add_column("Deep", justify="right")
    table.add_column("Ratio", justify="right")
    table.add_column("Threshold", justify="right")
    table.add_column("Verdict")

    for a in stats:
        c = a.curve
        fresh = f"{c.low_fill_rate:.1%}" if c.low_fill_rate is not None else "n/a"
        deep = f"{c.high_fill_rate:.1%}" if c.high_fill_rate is not None else "n/a"
        ratio = c.degradation_ratio
        if ratio is None:
            ratio_s = "n/a"
        elif ratio == float("inf"):
            ratio_s = "∞"
        else:
            ratio_s = f"{ratio:.1f}×"
        knee_s = f"~{c.knee_pct}%" if c.knee_pct is not None else "none"
        if a.is_other:
            verdict_cell = "[dim]—[/dim]"
        else:
            verdict_cell = f"[{_style[a.verdict_kind]}]{_icon[a.verdict_kind]} {a.verdict_kind}[/]"
        table.add_row(a.label, str(a.steps), fresh, deep, ratio_s, knee_s, verdict_cell)
    console.print(table)


@app.command()
def fix(
    data_dir: DataDir = None,
    days: Days = 30,
    window: Window = None,
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help="Actually disable unused global MCP servers (backs up the config first). "
            "Without this, fix is a dry run and writes nothing.",
        ),
    ] = False,
    config: Annotated[
        Optional[Path],
        typer.Option("--config", help="Path to Claude Code config (default: ~/.claude.json)."),
    ] = None,
) -> None:
    """Turn the report's prescriptions into concrete, checkable actions.

    Dry-run by default: it inspects your config and prints what it would change,
    writing nothing. Pass --apply to disable unused *global* MCP servers (moved
    to a reversible stash after a full backup, with a y/N prompt per server).
    Per-project servers and CLAUDE.md are reported only, never auto-edited.
    """
    claude_json = config or (Path.home() / ".claude.json")
    claude_md = Path.home() / ".claude" / "CLAUDE.md"

    result = analyze(data_dir=data_dir, project_filter=None, days=days, window_override=window)
    if not result.sessions:
        console.print("[yellow]No sessions found.[/yellow] Nothing to prescribe.")
        raise typer.Exit(code=1)

    # 1. The existing prescriptions, as-is.
    if result.prescriptions:
        console.print("[bold]Prescriptions from your data[/bold]")
        for i, p in enumerate(result.prescriptions, 1):
            console.print(f"  [yellow]{i}. {p.title}[/yellow]")
            console.print(f"     {p.detail}")
        console.print()

    # 2. CLAUDE.md size (report only — never auto-edited).
    md = claude_md_report(claude_md)
    if md is not None:
        console.print(
            f"[bold]Global CLAUDE.md[/bold]: ~{md.token_estimate:,} tokens "
            f"({md.chars:,} chars) loaded before your first word, every session — "
            f"{md.path}"
        )
        console.print("  Trim stale sections by hand; contextrot never rewrites your prose.")
        console.print()

    # 3. Unused MCP servers.
    unused = unused_mcp_servers(result.sessions, claude_json)
    if not unused.any:
        console.print(
            "[green]No unused MCP servers found[/green] "
            "(every configured server had at least one tool call in this window)."
        )
        raise typer.Exit(code=0)

    if unused.project_unused:
        console.print(
            "[bold]Project-scoped MCP servers unused this window[/bold] "
            "(reported only — remove with the Claude CLI if you agree):"
        )
        for srv in unused.project_unused:
            console.print(
                f"  [cyan]{srv.name}[/cyan]  in {project_label(srv.source)}  →  "
                f"[dim]claude mcp remove {srv.name}[/dim]"
            )
        console.print()

    if not unused.global_unused:
        raise typer.Exit(code=0)

    names = [s.name for s in unused.global_unused]
    console.print(
        f"[bold]Global MCP servers unused this window[/bold]: {', '.join(names)}"
    )
    if not apply:
        console.print(
            "  [dim]Dry run.[/dim] Re-run with [bold]--apply[/bold] to disable these "
            "(moved to a reversible stash after a full backup). Nothing was written."
        )
        raise typer.Exit(code=0)

    to_disable = []
    for name in names:
        if typer.confirm(f"Disable global MCP server '{name}'?", default=False):
            to_disable.append(name)
    if not to_disable:
        console.print("Nothing disabled.")
        raise typer.Exit(code=0)

    backup, moved = disable_global_servers(claude_json, to_disable)
    console.print(f"[green]Disabled:[/green] {', '.join(moved)}")
    console.print(f"  Backup written: {backup}")
    console.print(
        "  Undo: restore the backup, or move the entries back from "
        "'contextrotDisabledMcpServers' to 'mcpServers'."
    )


if __name__ == "__main__":
    app()
