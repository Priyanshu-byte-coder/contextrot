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

    # Refresh the calibration cache for live surfaces (statusline, hooks) —
    # only from a real run over the default data dirs, so pointing --data-dir
    # at a fixture or another machine's export can't poison your calibration.
    if data_dir is None:
        from contextrot.calibration import save_calibration

        save_calibration(result)

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

        # The most common false alarm: a short --days window hides enough
        # history for a verdict. If we came up short but there's likely more
        # on disk, point the way instead of just saying "keep using your agent".
        if result.verdict_kind == "insufficient" and days != 0:
            wider = "--days 90" if days < 90 else "--days 0"
            console.print(
                f"[dim]Tip: only the last {days} days were analyzed. "
                f"Try [/dim][cyan]contextrot {wider}[/cyan][dim] "
                "(0 = all history) to include more sessions.[/dim]"
            )

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
def badge(
    output: Annotated[
        Optional[Path],
        typer.Argument(help="Where to write the SVG (default: ./contextrot-badge.svg)."),
    ] = None,
    data_dir: DataDir = None,
    project: ProjectF = None,
    days: Days = 30,
    window: Window = None,
) -> None:
    """Write a shields-style SVG badge of your verdict — rendered locally.

    Embed your measured verdict ("context rot | clean ✓") in a README or
    blog post without any badge service seeing your data.
    """
    result = analyze(data_dir=data_dir, project_filter=project, days=days, window_override=window)
    if not result.sessions:
        console.print("[yellow]No sessions found.[/yellow]")
        raise typer.Exit(code=1)

    from contextrot.report.badge import render_badge

    out = output or Path("contextrot-badge.svg")
    if out.is_dir():
        out = out / "contextrot-badge.svg"
    try:
        out.write_text(render_badge(result), encoding="utf-8")
    except OSError as e:
        console.print(f"[red]Couldn't write badge to {out}:[/red] {e}")
        raise typer.Exit(code=1) from e
    console.print(f"[green]Badge written:[/green] {out}")
    console.print(f"  Embed: ![context rot]({out.name})", markup=False)


@app.command()
def trends(
    data_dir: DataDir = None,
    days: Days = 90,
    window: Window = None,
    weeks: Annotated[
        int, typer.Option("--weeks", "-w", help="How many recent weeks to show.")
    ] = 8,
) -> None:
    """Week-over-week trend — is your context hygiene improving?

    This is also the before/after check for `contextrot fix`: change your
    setup, keep working, re-run trends and watch whether failure rate and
    startup overhead actually moved.
    """
    from contextrot.analysis.trends import build_trend, trend_verdict

    result = analyze(data_dir=data_dir, project_filter=None, days=days, window_override=window)
    if not result.sessions:
        console.print("[yellow]No sessions found.[/yellow]")
        raise typer.Exit(code=1)

    trend = build_trend(result.steps, weeks=weeks)
    if not trend:
        console.print(
            "[yellow]No timestamped steps found[/yellow] — trends need transcripts "
            "that record per-step timestamps."
        )
        raise typer.Exit(code=1)

    kind, text = trend_verdict(trend)
    style = {"improving": "green", "worsening": "red", "flat": "cyan", "insufficient": "yellow"}[
        kind
    ]
    console.print(f"[{style} bold]{text}[/]")
    console.print()

    table = Table(title=f"Last {len(trend)} weeks")
    table.add_column("Week of", style="cyan")
    table.add_column("Steps", justify="right", style="dim")
    table.add_column("Failure", justify="right")
    table.add_column("95% CI", justify="right", style="dim")
    table.add_column("Avg fill", justify="right")
    table.add_column("Startup tokens", justify="right")

    for w in trend:
        ci = f"{w.ci[0]:.0%}–{w.ci[1]:.0%}"
        startup = f"{w.startup_tokens:,}" if w.startup_tokens is not None else "n/a"
        thin = " [dim]*[/dim]" if w.steps < 30 else ""
        table.add_row(
            w.label,
            f"{w.steps}{thin}",
            f"{w.rate:.1%}",
            ci,
            f"{w.avg_fill:.0f}%",
            startup,
        )
    console.print(table)
    console.print("[dim]* fewer than 30 steps — too thin to weigh in the trend.[/dim]")


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


@app.command()
def statusline() -> None:
    """Render a Claude Code statusline segment (reads session JSON from stdin).

    Wire it up with `contextrot install statusline` — Claude Code pipes live
    session JSON to this command and displays what it prints: current context
    fill, colored against YOUR measured degradation curve, not a generic
    threshold. Run a plain `contextrot` report now and then to recalibrate.
    """
    from contextrot.calibration import load_calibration
    from contextrot.statusline import render_statusline

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    # Plain print, not rich: Claude Code displays the raw bytes, and rich
    # soft-wrapping or highlighting would mangle the ANSI segment.
    print(render_statusline(payload, load_calibration()))


@app.command()
def hook() -> None:
    """Claude Code PostToolUse hook: warn once when a session crosses your knee.

    Wire it up with `contextrot install hook`. Reads hook JSON from stdin,
    checks the live transcript's context fill against your measured
    degradation threshold, and emits a systemMessage the first time a
    session crosses it. Silent when uncalibrated or your curve has no knee.
    """
    from contextrot.calibration import load_calibration
    from contextrot.hook import evaluate

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
        msg = evaluate(payload, load_calibration())
    except Exception:  # noqa: BLE001 — a crashing hook disrupts the session
        msg = None
    if msg:
        print(json.dumps({"systemMessage": msg}))


@app.command()
def mcp() -> None:
    """Serve contextrot as an MCP stdio server for any MCP-capable agent.

    Tools: rot_report, agents_ranking, prescriptions. Register with e.g.
    `claude mcp add contextrot -- contextrot mcp`. Local files only —
    stdio is a pipe to the parent process, and contextrot makes zero
    network calls.
    """
    from contextrot.mcp import serve

    serve()


InstallSettings = Annotated[
    Optional[Path],
    typer.Option(
        "--settings",
        help="Path to Claude Code settings.json (default: ~/.claude/settings.json).",
    ),
]


@app.command()
def install(
    target: Annotated[
        str, typer.Argument(help="What to install: 'statusline'.")
    ],
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help="Actually write settings.json (backs it up first). "
            "Without this, install is a dry run and writes nothing.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Replace an existing non-contextrot statusLine (still backed up).",
        ),
    ] = False,
    settings: InstallSettings = None,
) -> None:
    """Install a contextrot live surface into Claude Code. Dry-run by default."""
    from contextrot.install import (
        add_hook,
        claude_settings_path,
        has_hook,
        hook_entry,
        is_contextrot_entry,
        read_settings,
        statusline_entry,
        write_settings_with_backup,
    )

    if target not in ("statusline", "hook"):
        console.print(
            f"[red]Unknown install target:[/red] {target} (expected 'statusline' or 'hook')"
        )
        raise typer.Exit(code=2)

    path = settings or claude_settings_path()
    try:
        current = read_settings(path)
    except (ValueError, OSError) as e:
        console.print(f"[red]Couldn't read {path}:[/red] {e}")
        raise typer.Exit(code=1) from e

    if target == "statusline":
        entry = statusline_entry()
        existing = current.get("statusLine")
        if existing == entry:
            console.print(f"[green]Already installed[/green] in {path} — nothing to do.")
            raise typer.Exit(code=0)
        if existing is not None and not is_contextrot_entry(existing) and not force:
            console.print(
                f"[yellow]A statusLine is already configured[/yellow] in {path}:\n"
                f"  {json.dumps(existing)}\n"
                "It isn't contextrot's, so it won't be replaced without [bold]--force[/bold] "
                "(the previous file is backed up either way)."
            )
            raise typer.Exit(code=1)
        preview = {"statusLine": entry}
    else:
        if has_hook(current):
            console.print(f"[green]Already installed[/green] in {path} — nothing to do.")
            raise typer.Exit(code=0)
        preview = {"hooks": {"PostToolUse": ["…existing entries…", hook_entry()]}}

    console.print(f"[bold]Would set in {path}:[/bold]")
    console.print(json.dumps(preview, indent=2))
    if not apply:
        console.print(
            "  [dim]Dry run.[/dim] Re-run with [bold]--apply[/bold] to write "
            "(the previous settings.json is backed up first). Nothing was written."
        )
        raise typer.Exit(code=0)

    if not typer.confirm(f"Write {target} config to {path}?", default=False):
        console.print("Nothing written.")
        raise typer.Exit(code=0)

    if target == "statusline":
        current["statusLine"] = statusline_entry()
        done = "[green]Statusline installed.[/green] It appears on your next interaction."
    else:
        add_hook(current)
        done = (
            "[green]Hook installed.[/green] You'll get a one-time warning whenever a "
            "session crosses your measured degradation threshold."
        )
    backup = write_settings_with_backup(path, current)
    console.print(done)
    if backup is not None:
        console.print(f"  Backup written: {backup}")
    console.print(f"  Undo: `contextrot uninstall {target} --apply`, or restore the backup.")


@app.command()
def uninstall(
    target: Annotated[
        str, typer.Argument(help="What to uninstall: 'statusline'.")
    ],
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help="Actually write settings.json (backs it up first). "
            "Without this, uninstall is a dry run and writes nothing.",
        ),
    ] = False,
    settings: InstallSettings = None,
) -> None:
    """Remove a contextrot live surface from Claude Code. Dry-run by default."""
    from contextrot.install import (
        claude_settings_path,
        has_hook,
        is_contextrot_entry,
        read_settings,
        remove_hook,
        write_settings_with_backup,
    )

    if target not in ("statusline", "hook"):
        console.print(
            f"[red]Unknown uninstall target:[/red] {target} (expected 'statusline' or 'hook')"
        )
        raise typer.Exit(code=2)

    path = settings or claude_settings_path()
    try:
        current = read_settings(path)
    except (ValueError, OSError) as e:
        console.print(f"[red]Couldn't read {path}:[/red] {e}")
        raise typer.Exit(code=1) from e

    if target == "statusline":
        existing = current.get("statusLine")
        if existing is None:
            console.print("[green]No statusLine configured[/green] — nothing to remove.")
            raise typer.Exit(code=0)
        if not is_contextrot_entry(existing):
            console.print(
                "[yellow]The configured statusLine isn't contextrot's[/yellow] — "
                "not touching it:\n"
                f"  {json.dumps(existing)}"
            )
            raise typer.Exit(code=1)
        what = "'statusLine'"
    else:
        if not has_hook(current):
            console.print("[green]No contextrot hook configured[/green] — nothing to remove.")
            raise typer.Exit(code=0)
        what = "the contextrot PostToolUse hook"

    console.print(f"[bold]Would remove {what} from {path}.[/bold]")
    if not apply:
        console.print(
            "  [dim]Dry run.[/dim] Re-run with [bold]--apply[/bold] to write. "
            "Nothing was written."
        )
        raise typer.Exit(code=0)

    if not typer.confirm(f"Remove {what} from {path}?", default=False):
        console.print("Nothing written.")
        raise typer.Exit(code=0)

    if target == "statusline":
        del current["statusLine"]
        done = "[green]Statusline removed.[/green]"
    else:
        remove_hook(current)
        done = "[green]Hook removed.[/green]"
    backup = write_settings_with_backup(path, current)
    console.print(done)
    if backup is not None:
        console.print(f"  Backup written: {backup}")


if __name__ == "__main__":
    app()
