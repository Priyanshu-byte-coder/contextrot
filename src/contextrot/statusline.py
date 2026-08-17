"""One-line context-health segment, for any status bar.

Two ways in:

- **Claude Code** pipes session JSON to the configured statusline command on
  stdin (https://code.claude.com/docs/en/statusline) and displays what it
  prints — ``render_statusline(payload, cal)``.
- **Everything else** (tmux, Starship, a shell prompt, Waybar, any agent that
  offers no statusline hook) asks contextrot for the current fill instead of
  pushing it — ``render_fill(fill_pct, cal, palette)``, driven by
  ``contextrot.live.detect_live_session``.

Both render the same line, assembled from named segments::

    ctx 34% ███░░░░░░░ · 68k/200k · 132k left · knee ~70% · slip 4.7% (fresh 5.1%)

Segments, in fixed order (pick with ``segments=``):

``ctx``
    Fill percentage plus the bar, colored against *your* curve.
``tokens``
    Absolute context tokens: used, window size, and how many are left.
``health``
    What your measured curve says about this fill level — see below.
``plan``
    Claude.ai subscription rate limits (5-hour and weekly). Claude Code only,
    Pro/Max only, and absent until the session's first API response.
``cost``
    Session cost in USD, as Claude Code estimates it. Off by default.

The coloring is the point: generic statuslines go yellow at a hardcoded 70%;
this one goes red where *your* measured failure curve says it should.
Uncalibrated (no report run yet, or too little data) falls back to generic
70/90 thresholds and says so.

The health segment distinguishes three genuinely different states, because
conflating them is how a working tool looks broken:

- *no report yet* → "run contextrot to calibrate"
- *measured, threshold found* → "knee ~70%" / "▲ past knee ~70%"
- *measured, no threshold exists* → **nothing**

That last case is good news, not missing data: a flat or falling failure curve
means context fill is not what's hurting this user. It earns no words at all —
the bar's color already carries it, and a segment that restates "you're fine"
on every render is one you stop reading. (An earlier iteration spelled it out
as "no rot found in 20.1k steps (flat to 80%)", which was accurate and still
too loud for the widest part of the line; ``contextrot doctor`` carries that
detail now.) Words appear only when they would change what you do.

Never raises: a statusline that crashes renders as an empty bar, so every path
degrades to printable text.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from contextrot.calibration import Calibration

_BAR_CELLS = 10

# Width of the 5-hour / weekly quota meters. Narrower than the context bar:
# they are context for the main number, not the main number.
_PLAN_CELLS = 5

# Partial-cell fills, 1/8 through 7/8. Index 0 is unused (a cell with no fill
# renders as the empty character instead).
_EIGHTHS = " ▏▎▍▌▋▊▉"

# Every segment this module can render, in the order they appear in the line.
SEGMENT_NAMES = ("ctx", "tokens", "health", "plan", "cost")

# Cost is opt-in: it answers a different question than context health, and it
# is the one number Claude Code already shows elsewhere.
DEFAULT_SEGMENTS = ("ctx", "tokens", "health", "plan")

# Rate-limit coloring. Unlike the context curve these are hard quotas, so
# generic thresholds are the honest choice — there is nothing to calibrate.
PLAN_WARN_PCT = 70.0
PLAN_CRIT_PCT = 90.0

LEGEND = """\
contextrot statusline segments

  ctx 34% ███░░░░░░░   How full the context window is right now. The color is
                       calibrated to YOUR history, not a generic 70/90 rule:
                       green = below your threshold, yellow = within 10 points
                       of it, red = past it.

                       When your curve has NO threshold, the bar falls back to
                       70/90 — not as a rot warning, but because running out of
                       window is a separate problem from quality degradation.
                       So a yellow bar with no warning text beside it is not a
                       contradiction: the window is filling, and filling it
                       still isn't measurably hurting your output.

                       Bars fill in eighth-cells, so they glide as the number
                       climbs instead of jumping a whole cell at a time.

  68k/200k · 132k left Absolute tokens in the context window, the window size,
                       and what remains. Input tokens only (fresh + cache
                       creation + cache reads), matching how fill % is computed.

  knee ~70%            Your measured degradation threshold: the fill level
                       where your failure rate rises and stays risen. Shown as
                       "nearing knee" ten points out, "▲ past knee" once you
                       cross it.

  (nothing here)       Silence is the good case. When your curve is clean the
                       health segment says nothing at all — the green bar is
                       the message, and a bar that repeats good news every
                       render is a bar you stop reading. Run `contextrot
                       doctor` for the full evidence, including how deep your
                       data actually reaches.

                       When something IS off but no single threshold exists,
                       you get "deep runs hotter" (elevated at depth),
                       "rot measured" (real degradation, no crisp line), or
                       "need deeper sessions" (not enough deep steps to rule).

  slip 4.7%            Of your past steps at this same fill level, 4.7% hit at
                       least one failure signal: a tool error, a failed edit, a
                       retry of the same call, a re-read of a file already in
                       context, or a self-correction. It is a historical base
                       rate, NOT a prediction about your next message.

  (fresh 5.1%)         The same rate at low fill, for comparison. Shown as
                       "1.9× fresh" instead when this level is meaningfully
                       worse. Only appears alongside a warning — on its own it
                       is a number without a question.

  5h █▎░░░ 24%         Claude.ai subscription rate limits consumed: the 5-hour
  wk ██░░░ 41%         rolling window and the weekly one, each with its own
                       meter, green through red. Time until reset is appended
                       once a window passes 70%. Claude Code + Pro/Max only,
                       and only after the session's first API response; the
                       meters simply disappear otherwise.

  $0.12                Session cost so far, as Claude Code estimates it.
                       Opt in with --segments ctx,tokens,health,plan,cost.

Recalibrate by running a plain `contextrot` report now and then."""


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


def parse_segments(spec: str | None) -> tuple[str, ...]:
    """A comma-separated segment list, order-normalized. Tolerant of junk.

    Unknown names are dropped rather than raising: a statusline is not the
    place to fail a whole session over a typo in a config string.
    """
    if not spec:
        return DEFAULT_SEGMENTS
    wanted = {w.strip().lower() for w in spec.split(",") if w.strip()}
    if not wanted:
        return DEFAULT_SEGMENTS
    if "all" in wanted:
        return SEGMENT_NAMES
    picked = tuple(name for name in SEGMENT_NAMES if name in wanted)
    return picked or DEFAULT_SEGMENTS


def _fmt_tokens(n: int) -> str:
    """Compact token count: 950, 68k, 1.2M."""
    n = max(0, int(n))
    if n >= 1_000_000:
        millions = n / 1_000_000
        return f"{millions:.0f}M" if millions >= 10 else f"{millions:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n / 1000:.0f}k"
    return str(n)


def _fmt_count(n: int) -> str:
    """Compact step count for the evidence note: 812, 20.1k."""
    n = max(0, int(n))
    if n >= 10_000:
        return f"{n / 1000:.0f}k"
    if n >= 1_000:
        return f"{n / 1000:.1f}k"
    return str(n)


def _fmt_eta(seconds: float) -> str | None:
    """Time until a reset, coarse on purpose: 1h12m, 23m, <1m.

    None for a reset already in the past. That means the timestamp is stale or
    bogus, and rendering it as "<1m" would invent urgency out of bad data.
    """
    if seconds <= 0:
        return None
    if seconds < 60:
        return "<1m"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h{minutes % 60:02d}m"


def _bar(pct: float, cells: int = _BAR_CELLS) -> str:
    """A smooth progress bar: partial eighth-blocks, not whole cells.

    A 10-cell bar that only fills in whole cells jumps in 10% steps, so it sits
    still while the number beside it climbs and then lurches. Eighth-blocks give
    the same width 8× the resolution, so the bar moves every ~1.25%.
    """
    pct = max(0.0, min(100.0, pct))
    exact = pct / 100.0 * cells
    full = int(exact)
    if full >= cells:
        return "█" * cells
    out = "█" * full
    eighths = int((exact - full) * 8)
    out += _EIGHTHS[eighths] if eighths else "░"
    return out + "░" * (cells - full - 1)


def _zone(fill: float, knee: float | None, p: Palette) -> str:
    """green / yellow / red for the current fill against the knee."""
    if knee is not None:
        if fill >= knee:
            return p.red
        if fill >= knee - 10:
            return p.yellow
        return p.green
    # Uncalibrated, or calibrated with no threshold: generic thresholds. A
    # window can still fill up even when filling it does you no measured harm.
    if fill >= 90:
        return p.red
    if fill >= 70:
        return p.yellow
    return p.green


def _tokens_segment(tokens: int | None, window: int | None, p: Palette) -> str | None:
    """``68k/200k · 132k left`` when both numbers are known."""
    if not tokens or not window or window <= 0:
        return None
    left = max(0, int(window) - int(tokens))
    return (
        f"{_fmt_tokens(tokens)}/{_fmt_tokens(window)} · "
        f"{p.dim}{_fmt_tokens(left)} left{p.reset}"
    )


def _slip_note(fill: float, cal: Calibration, p: Palette) -> str | None:
    """``slip 4.7% (fresh 5.1%)`` — a historical base rate, labeled as one."""
    rate = cal.rate_at_fill(fill)
    if rate is None:
        return None
    note = f"slip {rate * 100:.1f}%"
    baseline = cal.low_fill_rate
    if baseline > 0:
        ratio = rate / baseline
        if ratio >= 1.25:
            return f"{note} — {p.red}{ratio:.1f}× fresh{p.reset}"
        return f"{note} {p.dim}(fresh {baseline * 100:.1f}%){p.reset}"
    return note


def _no_knee_note(cal: Calibration, p: Palette) -> str | None:
    """What to say when the curve has no declared threshold — often nothing.

    "No knee" is not one state. A knee is only declared when a bucket's
    confidence-interval floor clears the baseline, so a curve can be measurably
    *worse* deep down and still have no single crossing point. The verdict says
    which case this is:

    - ``clean``       measured, and fill genuinely doesn't hurt you → **silent**
    - ``edge``        deep context runs hotter, but no clean line to draw
    - ``rot``         degradation is real, the threshold just isn't crisp
    - anything else   not enough deep-context steps to rule either way

    ``clean`` returns None on purpose. Spelling out "no rot found in 20k steps"
    on every render spends the widest part of the line restating that nothing is
    wrong; the green bar already says so. The full evidence — including how deep
    the data actually reaches — lives in ``contextrot doctor``, where there is
    room for it.
    """
    verdict = cal.verdict_kind
    if verdict == "clean":
        return None
    if verdict == "edge":
        return f"{p.yellow}deep runs hotter{p.reset}"
    if verdict == "rot":
        return f"{p.red}rot measured{p.reset}"
    return f"{p.dim}need deeper sessions{p.reset}"


def _health_segments(fill: float, cal: Calibration | None, p: Palette) -> list[str]:
    """What the user's own curve says about this fill level.

    Speaks only when there is something to say. A calibrated, clean curve adds
    nothing — the bar's color carries "you're fine", and a status bar that
    repeats good news every render trains you to stop reading it.
    """
    if cal is None or not cal.calibrated:
        return [f"{p.dim}run contextrot to calibrate{p.reset}"]

    out: list[str] = []
    knee = cal.knee_pct
    if knee is not None:
        if fill >= knee:
            out.append(f"{p.red}▲ past knee ~{knee:.0f}%{p.reset}")
        elif fill >= knee - 10:
            out.append(f"{p.yellow}nearing knee ~{knee:.0f}%{p.reset}")
        else:
            out.append(f"{p.dim}knee ~{knee:.0f}%{p.reset}")
    else:
        note = _no_knee_note(cal, p)
        if note:
            out.append(note)

    # The slip rate is context for a warning, not a standalone reading: quote it
    # only when something above it needed explaining.
    if out:
        slip = _slip_note(fill, cal, p)
        if slip:
            out.append(slip)
    return out


def _plan_segment(limits: dict, p: Palette) -> str | None:
    """``plan 5h 24% wk 41%`` from Claude Code's ``rate_limits`` object.

    Absent for API-key users and until the session's first API response, so
    every field is treated as optional.
    """
    if not isinstance(limits, dict):
        return None
    shown: list[str] = []
    for key, label in (("five_hour", "5h"), ("seven_day", "wk")):
        window = limits.get(key)
        if not isinstance(window, dict):
            continue
        pct = window.get("used_percentage")
        if not isinstance(pct, (int, float)) or isinstance(pct, bool):
            continue
        pct = max(0.0, min(100.0, float(pct)))
        if pct >= PLAN_CRIT_PCT:
            color = p.red
        elif pct >= PLAN_WARN_PCT:
            color = p.yellow
        else:
            color = p.green
        text = f"{p.dim}{label}{p.reset} {color}{_bar(pct, _PLAN_CELLS)} {pct:.0f}%{p.reset}"
        resets_at = window.get("resets_at")
        if pct >= PLAN_WARN_PCT and isinstance(resets_at, (int, float)):
            eta = _fmt_eta(float(resets_at) - time.time())
            if eta:
                text += f" {p.dim}{eta}{p.reset}"
        shown.append(text)
    if not shown:
        return None
    # Each window is its own segment so the separators stay uniform across the
    # whole line — the bars already read as a group without a "plan" label.
    return " · ".join(shown)


def _cost_segment(cost: object, p: Palette) -> str | None:
    if not isinstance(cost, (int, float)) or isinstance(cost, bool):
        return None
    return f"{p.dim}${float(cost):.2f}{p.reset}"


def render_fill(
    fill_pct: float,
    cal: Calibration | None,
    palette: Palette = ANSI,
    *,
    tokens: int | None = None,
    window: int | None = None,
    segments: tuple[str, ...] = DEFAULT_SEGMENTS,
) -> str:
    """The status line for a known context fill. Never raises."""
    try:
        return _compose(
            fill_pct=fill_pct,
            cal=cal,
            p=palette,
            segments=segments,
            tokens=tokens,
            window=window,
            limits=None,
            cost=None,
        )
    except Exception:  # noqa: BLE001 — a broken statusline helps nobody
        return "ctx —"


def _compose(
    *,
    fill_pct: float | None,
    cal: Calibration | None,
    p: Palette,
    segments: tuple[str, ...],
    tokens: int | None,
    window: int | None,
    limits: dict | None,
    cost: object,
) -> str:
    """Assemble the selected segments into one line."""
    calibrated = cal is not None and cal.calibrated
    knee = cal.knee_pct if calibrated and cal is not None else None

    parts: list[str] = []

    if fill_pct is None:
        # Before the first API call (and right after /compact) there is no
        # usage to report. Still show whatever else is real.
        parts.append("ctx —")
    else:
        fill = max(0.0, min(100.0, float(fill_pct)))
        if "ctx" in segments:
            color = _zone(fill, knee, p)
            parts.append(f"ctx {color}{fill:.0f}% {_bar(fill)}{p.reset}")
        if "tokens" in segments:
            seg = _tokens_segment(tokens, window, p)
            if seg:
                parts.append(seg)

    if "health" in segments:
        if fill_pct is None:
            # No fill to place on the curve, so quote only what stands alone.
            if calibrated and knee is not None:
                parts.append(f"{p.dim}knee ~{knee:.0f}%{p.reset}")
            elif not calibrated:
                parts.append(f"{p.dim}run contextrot to calibrate{p.reset}")
        else:
            parts.extend(_health_segments(max(0.0, min(100.0, float(fill_pct))), cal, p))

    if "plan" in segments and limits is not None:
        seg = _plan_segment(limits, p)
        if seg:
            parts.append(seg)

    if "cost" in segments:
        seg = _cost_segment(cost, p)
        if seg:
            parts.append(seg)

    return " · ".join(parts) if parts else "ctx —"


def render_statusline(
    payload: dict,
    cal: Calibration | None,
    *,
    segments: tuple[str, ...] = DEFAULT_SEGMENTS,
) -> str:
    """One printable line from Claude Code's statusline JSON + calibration."""
    try:
        return _render(payload, cal, segments)
    except Exception:  # noqa: BLE001 — a broken statusline helps nobody
        return "ctx —"


def _render(payload: dict, cal: Calibration | None, segments: tuple[str, ...]) -> str:
    ctx = payload.get("context_window")
    if not isinstance(ctx, dict):
        ctx = {}
    used = ctx.get("used_percentage")
    fill = float(used) if isinstance(used, (int, float)) and not isinstance(used, bool) else None

    tokens = ctx.get("total_input_tokens")
    window = ctx.get("context_window_size")
    limits = payload.get("rate_limits")
    cost_obj = payload.get("cost")
    cost = cost_obj.get("total_cost_usd") if isinstance(cost_obj, dict) else None

    return _compose(
        fill_pct=fill,
        cal=cal,
        p=ANSI,
        segments=segments,
        tokens=int(tokens) if isinstance(tokens, (int, float)) else None,
        window=int(window) if isinstance(window, (int, float)) else None,
        limits=limits if isinstance(limits, dict) else None,
        cost=cost,
    )
