"""Regenerate the showcase media from the synthetic corpus.

Every terminal screen in README.md and SHOWCASE.md is rendered here, straight
from the corpus ``make_showcase_data.py`` writes, so the images can be
regenerated after any output change and diffed in review rather than
re-photographed — and so nothing from a real machine can end up in them.

    python scripts/make_showcase_data.py --out .showcase-data
    python scripts/capture_showcase.py --data-dir .showcase-data

Run it from the repository root with a **relative** ``--data-dir``: a few screens
print where transcripts were found, and an absolute path would put your home
directory in a committed image.

SVG rather than PNG because rich exports it directly — no browser, no headless
renderer, no extra dependency — and both GitHub and PyPI render it inline.

Two screens stay hand-captured and are not touched here: the HTML report (it
needs a browser) and the in-session hook warning (it is Claude Code's own UI).
"""

from __future__ import annotations

import argparse
import io
import os
import time
from pathlib import Path

from rich.console import Console
from rich.text import Text

ASSETS = Path("assets/showcase")

# (file stem, argv after `contextrot`, terminal width). Widths are set per screen
# so wide tables don't wrap and narrow ones don't float in empty space.
SCREENS: tuple[tuple[str, list[str], int], ...] = (
    ("hero", [], 100),
    ("report-full", ["--full"], 112),
    ("factors", ["factors"], 104),
    ("waste", ["waste"], 96),
    ("projects", ["projects"], 100),
    ("agents", ["agents"], 100),
    ("trends", ["trends"], 100),
    ("fix", ["fix"], 100),
    # One project only, so the table is a screenful rather than seventy rows.
    ("sessions", ["sessions", "--project", "cli-tools"], 100),
    # Last: it tables the calibration the report runs above wrote into the sandbox
    # home, so it shows the synthetic curves rather than anybody's real ones.
    ("doctor", ["doctor"], 104),
)


def _sandbox_home(root: Path) -> Path:
    """A fake home directory, so no screen reads anything of yours.

    Several commands look in your home directory regardless of ``--data-dir``:
    ``fix`` reads ``~/.claude.json`` (your MCP servers, keyed by your project
    paths) and ``~/.claude/CLAUDE.md``; the report reads your calibration and
    whether your status line is installed. Captured from a real home, those end up
    in a committed image — an early version of this script leaked a username and
    three real MCP server names exactly that way. So every capture runs with
    HOME and USERPROFILE pointed here, at a config that is synthetic too.
    """
    home = root / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (home / ".claude.json").write_text(
        """{
  "mcpServers": {"github": {"command": "gh-mcp"}, "browser": {"command": "browser-mcp"}},
  "projects": {"/home/dev/auth-service": {"mcpServers": {"postgres": {"command": "pg-mcp"}}}}
}
""",
        encoding="utf-8",
    )
    (home / ".claude" / "CLAUDE.md").write_text(
        "# House rules\n\n" + "- Prefer small, reviewed changes.\n" * 120,
        encoding="utf-8",
    )
    return home


def _recorder(width: int) -> Console:
    """A recording console that writes nowhere but keeps everything for export."""
    return Console(
        width=width,
        record=True,
        force_terminal=True,
        legacy_windows=False,
        file=io.StringIO(),
    )


def capture_command(stem: str, argv: list[str], width: int, data_dir: Path, out: Path) -> None:
    """Run one command against the corpus and export what it printed."""
    import typer

    from contextrot import cli

    console = _recorder(width)
    previous, cli.console = cli.console, console
    try:
        cli.app([*argv, "--data-dir", str(data_dir), "--days", "0"], standalone_mode=False)
    except (SystemExit, typer.Exit):
        pass
    finally:
        cli.console = previous
    console.save_svg(str(out / f"{stem}.svg"), title=f"contextrot {' '.join(argv)}".strip())
    print(f"wrote {out / f'{stem}.svg'}")


def capture_water(data_dir: Path, out: Path) -> None:
    """``contextrot water``: the filled tank, the breakdown, the provenance."""
    from contextrot import cli
    from contextrot.analysis import load_sessions
    from contextrot.water import totals_for_sessions

    sessions, _ = load_sessions(data_dir=data_dir, days=None)
    totals = totals_for_sessions(sessions)
    console = _recorder(96)
    previous, cli.console = cli.console, console
    try:
        # animate=False prints the still, fully-filled frame — what an asset shows.
        cli._render_water(totals, seconds=0.0, animate=False)
    finally:
        cli.console = previous
    console.save_svg(str(out / "water.svg"), title="contextrot water")
    print(f"wrote {out / 'water.svg'}")


def capture_statuslines(data_dir: Path, out: Path) -> None:
    """The Claude Code status line, default segments and with water on."""
    from contextrot.statusline import parse_segments, render_statusline

    transcripts = sorted(data_dir.glob("*/*.jsonl"))
    if not transcripts:
        raise SystemExit(f"no synthetic transcripts under {data_dir}")
    transcript = max(transcripts, key=lambda p: p.stat().st_size)

    payload = {
        "transcript_path": str(transcript),
        "model": {"id": "claude-opus-5", "display_name": "Opus 5"},
        "context_window": {
            "total_input_tokens": 342_000,
            "context_window_size": 1_000_000,
            "used_percentage": 34.2,
        },
        "rate_limits": {
            "five_hour": {"used_percentage": 24.0, "resets_at": time.time() + 4_200},
            "seven_day": {"used_percentage": 41.0, "resets_at": time.time() + 300_000},
        },
    }
    for stem, segments in (
        ("statusline", "ctx,tokens,health,plan"),
        ("statusline-water", "ctx,tokens,health,plan,water"),
    ):
        line = render_statusline(payload, None, segments=parse_segments(segments))
        console = _recorder(104)
        # from_ansi, not a plain print: printing the escapes as literal text
        # embeds control characters and the exported SVG is malformed XML.
        console.print(Text.from_ansi(line), soft_wrap=True)
        console.save_svg(str(out / f"{stem}.svg"), title="contextrot statusline")
        print(f"wrote {out / f'{stem}.svg'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, required=True, help="The synthetic corpus.")
    ap.add_argument("--assets", type=Path, default=ASSETS, help="Where to write the SVGs.")
    args = ap.parse_args()
    if args.data_dir.is_absolute():
        raise SystemExit(
            "--data-dir must be relative (run from the repo root): screens that print "
            "where transcripts were found would otherwise embed your home directory."
        )
    # Animation must be off: a recording console keeps every frame, and a still
    # image of an animation is the finished frame, not all of them stacked.
    os.environ["CONTEXTROT_NO_ANIM"] = "1"
    home = _sandbox_home(args.data_dir)
    # Relative on purpose, like --data-dir: `fix` prints the config paths it read,
    # and an absolute sandbox path would put the repo's location in the image.
    os.environ["HOME"] = os.environ["USERPROFILE"] = str(home)
    args.assets.mkdir(parents=True, exist_ok=True)

    # A real `contextrot` run writes a calibration that `doctor` and the status line
    # read — but only from your default data dirs, never from --data-dir, so that a
    # fixture can't poison it. Write one into the sandbox home explicitly, so the
    # doctor screen shows the curves a user would actually see after a first run.
    from contextrot.analysis import analyze
    from contextrot.calibration import save_calibration

    save_calibration(analyze(data_dir=args.data_dir, days=None))

    for stem, argv, width in SCREENS:
        capture_command(stem, argv, width, args.data_dir, args.assets)
    capture_water(args.data_dir, args.assets)
    capture_statuslines(args.data_dir, args.assets)


if __name__ == "__main__":
    main()
