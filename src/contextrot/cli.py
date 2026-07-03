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
    typer.Option("--data-dir", help="Transcript directory (default: ~/.claude/projects)."),
]
ProjectF = Annotated[
    Optional[str], typer.Option("--project", "-p", help="Only sessions whose project matches.")
]
Days = Annotated[int, typer.Option("--days", "-d", help="Only sessions from the last N days.")]
Window = Annotated[
    Optional[int], typer.Option("--window", help="Override the context-window size in tokens.")
]


def _project_basename(project: str) -> str:
    """Last path component, tolerant of both separators.

    Transcripts record the project as the agent's working directory, which
    may be a Windows path even when contextrot runs elsewhere (shared
    fixtures, copied transcript dirs) — so os.path can't be trusted here.
    """
    return project.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] or project


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
            "contextrot currently reads Claude Code transcripts from ~/.claude/projects. "
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

        out = render_html(result, html)
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

    table = Table(title=f"{len(found)} sessions ({skipped} skipped)")
    table.add_column("Started", style="dim")
    table.add_column("Project")
    table.add_column("Steps", justify="right")
    table.add_column("Peak prompt", justify="right")
    table.add_column("Model", style="dim")

    for s in found:
        started = s.started_at.strftime("%Y-%m-%d %H:%M") if s.started_at else "?"
        model = s.steps[0].model if s.steps else "?"
        project_name = _project_basename(s.project) if s.project else "?"
        table.add_row(
            started, project_name, str(len(s.steps)), f"{s.peak_prompt_tokens:,}", model
        )
    console.print(table)


if __name__ == "__main__":
    app()
