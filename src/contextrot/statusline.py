"""One-line context-health segment, for any status bar.

Two ways in:

- **Claude Code** pipes session JSON to the configured statusline command on
  stdin (https://code.claude.com/docs/en/statusline) and displays what it
  prints — ``render_statusline(payload, cal)``.
- **Everything else** (tmux, Starship, a shell prompt, Waybar, any agent that
  offers no statusline hook) asks contextrot for the current fill instead of
  pushing it — ``render_fill(fill_pct, cal, palette)``, driven by
  ``contextrot.live.detect_live_session``.

Both render the same line::

    ctx 72% ███████░░░ · ▲ past your knee (~70%) · fail here 4.8% (1.5× fresh)

The coloring is the point: generic statuslines go yellow at a hardcoded 70%;
this one goes red where *your* measured failure curve says it should.
Uncalibrated (no report run yet, or too little data) falls back to generic
70/90 thresholds and says so.

Never raises: a statusline that crashes renders as an empty bar, so every path
degrades to printable text.
"""

from __future__ import annotations

from dataclasses import dataclass

from contextrot.calibration import Calibration

_BAR_CELLS = 10


@dataclass(frozen=True)
class Palette:
    """Color markup for one output target."""

    green: str
    yellow: str
    red: str
    dim: str
    reset: str


# ANSI escapes; Claude Code and shell prompts render these directly.
ANSI = Palette("\x1b[32m", "\x1b[33m", "\x1b[31m", "\x1b[2m", "\x1b[0m")
# No markup at all — for anything that would show the escapes literally.
PLAIN = Palette("", "", "", "", "")
# tmux status bars do NOT interpret ANSI; they use their own #[...] tags.
TMUX = Palette(
    "#[fg=green]", "#[fg=yellow]", "#[fg=red]", "#[fg=colour244]", "#[default]"
)

PALETTES = {"ansi": ANSI, "plain": PLAIN, "tmux": TMUX}


def _bar(pct: float) -> str:
    filled = int(round(pct / 100.0 * _BAR_CELLS))
    filled = max(0, min(_BAR_CELLS, filled))
    return "█" * filled + "░" * (_BAR_CELLS - filled)


def _zone(fill: float, knee: float | None, p: Palette) -> str:
    """green / yellow / red for the current fill against the knee."""
    if knee is not None:
        if fill >= knee:
            return p.red
        if fill >= knee - 10:
            return p.yellow
        return p.green
    # Uncalibrated: generic thresholds.
    if fill >= 90:
        return p.red
    if fill >= 70:
        return p.yellow
    return p.green


def render_fill(fill_pct: float, cal: Calibration | None, palette: Palette = ANSI) -> str:
    """The status line for a known context fill. Never raises."""
    try:
        return _render_fill(fill_pct, cal, palette)
    except Exception:  # noqa: BLE001 — a broken statusline helps nobody
        return "ctx —"


def _render_fill(fill_pct: float, cal: Calibration | None, p: Palette) -> str:
    calibrated = cal is not None and cal.calibrated
    knee = cal.knee_pct if calibrated and cal is not None else None

    fill = max(0.0, min(100.0, float(fill_pct)))
    color = _zone(fill, knee, p)
    parts = [f"ctx {color}{fill:.0f}% {_bar(fill)}{p.reset}"]

    if calibrated and cal is not None:
        if knee is not None:
            if fill >= knee:
                parts.append(f"{p.red}▲ past your knee (~{knee:.0f}%){p.reset}")
            else:
                parts.append(f"{p.dim}knee ~{knee:.0f}%{p.reset}")
        else:
            parts.append(f"{p.dim}no knee in your data{p.reset}")

        rate = cal.rate_at_fill(fill)
        if rate is not None and cal.low_fill_rate > 0:
            ratio = rate / cal.low_fill_rate
            note = f"fail here {rate * 100:.1f}%"
            if ratio >= 1.25:
                note += f" ({ratio:.1f}× fresh)"
            parts.append(note)
    else:
        parts.append(f"{p.dim}run contextrot to calibrate{p.reset}")

    return " · ".join(parts)


def render_statusline(payload: dict, cal: Calibration | None) -> str:
    """One printable line from Claude Code's statusline JSON + calibration."""
    try:
        return _render(payload, cal)
    except Exception:  # noqa: BLE001 — a broken statusline helps nobody
        return "ctx —"


def _render(payload: dict, cal: Calibration | None) -> str:
    ctx = payload.get("context_window") or {}
    used = ctx.get("used_percentage")

    calibrated = cal is not None and cal.calibrated
    knee = cal.knee_pct if calibrated and cal is not None else None

    if not isinstance(used, (int, float)):
        # Before the first API call (and right after /compact) Claude Code
        # sends null here — show the calibration context instead of a bar.
        if calibrated:
            if knee is not None:
                return f"ctx — {ANSI.dim}knee ~{knee:.0f}%{ANSI.reset}"
            return "ctx —"
        return f"ctx — {ANSI.dim}run contextrot to calibrate{ANSI.reset}"

    return _render_fill(float(used), cal, ANSI)
