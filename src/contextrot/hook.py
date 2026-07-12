"""Knee-crossing warning hook for Claude Code (PostToolUse).

Claude Code pipes hook JSON (session_id, transcript_path, …) on stdin after
every tool call. This module reads the *tail* of the live transcript to get
the current context fill — cheap even on multi-megabyte session files — and
compares it against the user's measured degradation threshold from the
calibration cache. The first time a session crosses its knee, the hook emits
a ``systemMessage`` warning; a marker file keeps it from nagging on every
subsequent tool call, and the warning re-arms once fill drops back below the
knee (e.g. after /compact).

Silent by design when there's nothing honest to say: no calibration, no
knee in the user's data, or an unreadable transcript all produce no output.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path

from contextrot.calibration import Calibration

# Fill must drop this many points below the knee before the warning re-arms.
REARM_MARGIN = 5.0

# How much of the transcript tail to scan for the latest usage entry.
_TAIL_BYTES = 262_144


def state_dir() -> Path:
    """Where warn-once markers live. Overridable for tests."""
    env = os.environ.get("CONTEXTROT_HOOK_STATE")
    if env:
        return Path(env)
    return Path(tempfile.gettempdir()) / "contextrot-hook"


def tail_fill_pct(transcript_path: Path, max_bytes: int = _TAIL_BYTES) -> float | None:
    """Context fill %% from the last assistant usage entry in a live transcript."""
    from contextrot.pricing import context_window_for

    try:
        size = transcript_path.stat().st_size
        with transcript_path.open("rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()  # drop the partial first line
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None

    for line in reversed(tail.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        prompt = (
            int(usage.get("input_tokens") or 0)
            + int(usage.get("cache_creation_input_tokens") or 0)
            + int(usage.get("cache_read_input_tokens") or 0)
        )
        if prompt <= 0:
            continue
        window = context_window_for(str(message.get("model") or ""), None)
        return min(100.0, 100.0 * prompt / max(window, 1))
    return None


def evaluate(payload: dict, cal: Calibration | None) -> str | None:
    """The warning to show, or None. Handles the warn-once marker lifecycle."""
    if cal is None or not cal.calibrated or cal.knee_pct is None:
        return None
    transcript = payload.get("transcript_path")
    if not transcript:
        return None
    fill = tail_fill_pct(Path(str(transcript)))
    if fill is None:
        return None

    knee = float(cal.knee_pct)
    session = str(payload.get("session_id") or "unknown")
    marker = state_dir() / f"warned-{session}"

    if fill >= knee:
        if marker.exists():
            return None
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(f"{fill:.1f}", encoding="utf-8")
        except OSError:
            pass  # still warn — worst case it warns again
        msg = (
            f"contextrot: context {fill:.0f}% — past your measured degradation "
            f"threshold (~{knee:.0f}%)."
        )
        rate = cal.rate_at_fill(fill)
        if rate is not None and cal.low_fill_rate > 0:
            ratio = rate / cal.low_fill_rate
            if ratio >= 1.25:
                msg += f" Your failure rate here is {ratio:.1f}× fresh-context."
        msg += " Consider /compact or a fresh session."
        return msg

    if fill <= knee - REARM_MARGIN and marker.exists():
        with contextlib.suppress(OSError):
            marker.unlink()
    return None
