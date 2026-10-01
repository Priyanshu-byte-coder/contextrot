"""Capture the showcase media that can be captured reproducibly.

Most of `assets/showcase/` is hand-taken terminal PNGs. The water assets are not:
they are rendered here straight from the synthetic corpus that
`make_showcase_data.py` writes, so they can be regenerated and diffed rather than
re-photographed, and so nothing from a real machine can leak into them.

    python scripts/make_showcase_data.py --out .showcase-data
    python scripts/capture_showcase.py --data-dir .showcase-data

SVG rather than PNG because rich can export it directly — no browser, no headless
renderer, no extra dependency — and GitHub renders it inline.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from rich.console import Console
from rich.text import Text

ASSETS = Path("assets/showcase")


def _console(width: int = 96) -> Console:
    """A recording console wide enough for the tank plus its margins."""
    return Console(width=width, record=True, force_terminal=True, legacy_windows=False)


def capture_water(data_dir: Path, out: Path) -> None:
    """The `contextrot water` output: filled tank, breakdown, provenance."""
    from contextrot import cli
    from contextrot.analysis import load_sessions
    from contextrot.water import totals_for_sessions

    sessions, _ = load_sessions(data_dir=data_dir, days=None)
    totals = totals_for_sessions(sessions)

    console = _console()
    previous, cli.console = cli.console, console
    try:
        # animate=False prints the still, fully-filled frame, which is what a
        # static asset should show.
        cli._render_water(totals, seconds=0.0, animate=False)
    finally:
        cli.console = previous
    console.save_svg(str(out), title="contextrot water")
    print(f"wrote {out}")


def capture_statusline(data_dir: Path, out: Path) -> None:
    """The statusline with the water segment on, from a synthetic transcript."""
    from contextrot.statusline import parse_segments, render_statusline

    transcripts = sorted(data_dir.glob("*/*.jsonl"))
    if not transcripts:
        raise SystemExit(f"no synthetic transcripts under {data_dir}")
    # The deepest one, so the line shows a meaningful running total.
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
    line = render_statusline(
        payload, None, segments=parse_segments("ctx,tokens,health,plan,water")
    )

    console = _console(width=104)
    # Text.from_ansi, not print(): the statusline emits real ANSI escapes, and
    # printing them as literal text embeds control characters that make the
    # exported SVG malformed XML. from_ansi turns them into rich styles.
    console.print(Text.from_ansi(line), soft_wrap=True)
    console.save_svg(str(out), title="contextrot statusline — water segment")
    print(f"wrote {out}")
    print("  " + json.dumps(line))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, required=True, help="The synthetic corpus.")
    ap.add_argument("--assets", type=Path, default=ASSETS, help="Where to write the SVGs.")
    args = ap.parse_args()
    args.assets.mkdir(parents=True, exist_ok=True)
    capture_water(args.data_dir, args.assets / "water.svg")
    capture_statusline(args.data_dir, args.assets / "statusline-water.svg")


if __name__ == "__main__":
    main()
