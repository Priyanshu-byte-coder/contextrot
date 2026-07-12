"""Claude Code statusline segment.

Claude Code pipes session JSON to the configured statusline command on
stdin (see https://code.claude.com/docs/en/statusline) and displays
whatever the command prints. This renderer turns that JSON plus the
user's calibration snapshot into a one-line context-health segment:

    ctx 72% ███████░░░ ▲ past your knee (~70%) · fail here 4.8% (1.5× fresh)

The coloring is the point: generic statuslines go yellow at a hardcoded
70%; this one goes red where *your* measured failure curve says it
should. Uncalibrated (no report run yet, or too little data) falls back
to generic 70/90 thresholds and says so.

Never raises: a statusline that crashes renders as an empty bar, so every
path degrades to printable text.
"""

from __future__ import annotations

from contextrot.calibration import Calibration

# ANSI codes; Claude Code renders these in the statusline row.
_GREEN = "\x1b[32m"
_YELLOW = "\x1b[33m"
_RED = "\x1b[31m"
_DIM = "\x1b[2m"
_RESET = "\x1b[0m"

_BAR_CELLS = 10


def _bar(pct: float) -> str:
    filled = int(round(pct / 100.0 * _BAR_CELLS))
    filled = max(0, min(_BAR_CELLS, filled))
    return "█" * filled + "░" * (_BAR_CELLS - filled)


def _zone(fill: float, knee: float | None) -> str:
    """green / yellow / red for the current fill against the knee."""
    if knee is not None:
        if fill >= knee:
            return _RED
        if fill >= knee - 10:
            return _YELLOW
        return _GREEN
    # Uncalibrated: generic thresholds.
    if fill >= 90:
        return _RED
    if fill >= 70:
        return _YELLOW
    return _GREEN


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
                return f"ctx — {_DIM}knee ~{knee:.0f}%{_RESET}"
            return "ctx —"
        return f"ctx — {_DIM}run contextrot to calibrate{_RESET}"

    fill = max(0.0, min(100.0, float(used)))
    color = _zone(fill, knee)
    parts = [f"ctx {color}{fill:.0f}% {_bar(fill)}{_RESET}"]

    if calibrated and cal is not None:
        if knee is not None:
            if fill >= knee:
                marker = f"{_RED}▲ past your knee (~{knee:.0f}%){_RESET}"
            else:
                marker = f"{_DIM}knee ~{knee:.0f}%{_RESET}"
            parts.append(marker)
        else:
            parts.append(f"{_DIM}no knee in your data{_RESET}")

        rate = cal.rate_at_fill(fill)
        if rate is not None and cal.low_fill_rate > 0:
            ratio = rate / cal.low_fill_rate
            note = f"fail here {rate * 100:.1f}%"
            if ratio >= 1.25:
                note += f" ({ratio:.1f}× fresh)"
            parts.append(note)
    else:
        parts.append(f"{_DIM}run contextrot to calibrate{_RESET}")

    return " · ".join(parts)
