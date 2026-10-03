"""The animation engine: one render path, replayed at interpolated values.

The obvious way to animate a report is to write an animated version of each
renderer beside the static one. That doubles the surface area and guarantees the
two drift apart. This does the opposite: **every renderer takes a ``Reveal``**,
and a ``Reveal`` at ``t = 1.0`` reproduces the finished frame exactly. Animation
is then nothing more than calling the same function with ``t`` climbing from 0,
and turning animation off is passing ``STATIC``.

That gives one property worth more than any effect: with animation disabled, the
output is byte-identical to what it was before any of this existed, because it
is literally the same code at the same value.

The rules the effects follow, learned from the water animation:

**Animation carries data or it doesn't ship.** A bar growing to 18% *is* the
18%; a spinner next to the number is noise. Every effect here is an
interpolation of a real value — bars grow to their height, counters count to
their total, rows arrive in rank order. Nothing pulses, blinks or bounces.

**Never delay the answer by more than a moment.** Sections animate for a few
hundred milliseconds each, not seconds. A report you have read twice should not
make you wait a third time.

**Per section, never the whole screen.** ``rich.Live`` crops content taller than
the terminal, so a full report animated in one Live would lose its bottom half on
a short window. Each panel animates where it is printed and then stays in
scrollback, which also reads better: the report assembles instead of appearing.

**A pipe gets the final frame.** No TTY, ``NO_COLOR``, ``CI``,
``CONTEXTROT_NO_ANIM``, or ``--no-animate`` all collapse to a single static
render, so scripts, CI logs and ``--json`` are untouched.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from rich.console import Console, RenderableType

T = TypeVar("T")

# Frame rate for every animation in the package. 30 is smooth enough that eased
# motion reads as motion rather than as steps, and cheap enough that rebuilding
# a table per frame stays well inside the budget.
FPS = 30

# Default length of one section's reveal. Deliberately short: this is the tax
# every run pays, including the hundredth run. The full report has six sections,
# so this is multiplied by six there — which is why it is a third of a second and
# not a comfortable-feeling one. Anyone who wants it gone has --no-animate.
SECTION_SECONDS = 0.3

# Environment switches, checked on every call so tests can flip them.
ENV_DISABLE = "CONTEXTROT_NO_ANIM"


def ease_out_cubic(t: float) -> float:
    """Fast start, gentle landing. The default for everything that grows."""
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def ease_out_quint(t: float) -> float:
    """A harder deceleration, for counters that would otherwise crawl at the end."""
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 5


def enabled(console: Console, want: bool = True) -> bool:
    """Whether to animate at all.

    Every reason to decline is a reason the output is being read by something
    other than a person watching it happen.
    """
    if not want:
        return False
    if os.environ.get(ENV_DISABLE):
        return False
    # CI logs replay at once; an animation there is thousands of wasted lines.
    if os.environ.get("CI"):
        return False
    return bool(console.is_terminal) and not console.is_jupyter


@dataclass(frozen=True)
class Reveal:
    """How far through a reveal we are, and how to read values at that point.

    ``t`` is already eased, so renderers never do easing themselves — they just
    scale. At ``t = 1.0`` every method returns the true value, which is what makes
    the static path and the animated path the same code.
    """

    t: float = 1.0

    @property
    def done(self) -> bool:
        return self.t >= 1.0

    def num(self, value: float) -> float:
        """A number on its way to ``value``."""
        return value * self.t

    def whole(self, value: int) -> int:
        """An integer count on its way to ``value``, never overshooting."""
        return int(round(value * self.t))

    def width(self, cells: int) -> int:
        """How many cells of a ``cells``-wide bar are drawn yet."""
        return int(round(cells * self.t))

    def stagger(self, index: int, count: int) -> Reveal:
        """A sub-reveal for item ``index`` of ``count``, arriving in order.

        Each item has its own window inside the parent's, so a table fills top
        to bottom instead of every row growing at once. Rank order matters in
        every table here — biggest first — so arrival order carries meaning too.
        """
        if count <= 1 or self.done:
            return Reveal(self.t if count <= 1 else 1.0)
        # Windows overlap: item i starts before item i-1 has finished, which
        # reads as a cascade rather than a queue.
        span = 1.0 / (count + 1)
        start = index * span
        local = (self.t - start) / (1.0 - start) if start < 1.0 else 1.0
        return Reveal(ease_out_cubic(max(0.0, min(1.0, local))))

    def visible(self, items: Sequence[T]) -> Sequence[T]:
        """The prefix of ``items`` that has arrived. Always at least one."""
        if self.done:
            return items
        if not items:
            return items
        shown = max(1, int(self.t * len(items) + 0.999))
        return items[:shown]

    def gate(self, at: float) -> bool:
        """True once the reveal has passed ``at``, for things that just appear."""
        return self.t >= at


#: The finished frame. Passing this is how a renderer renders statically.
STATIC = Reveal(1.0)

# Partial eighth-blocks, 1/8 through 7/8. Index 0 is unused: a cell with no fill
# is drawn as nothing rather than as a fractional block.
EIGHTHS = " ▏▎▍▌▋▊▉"


def bar(value: float, maximum: float, cells: int, rv: Reveal = STATIC) -> str:
    """A horizontal bar, optionally part-way through growing to its length.

    The single bar implementation for the whole package. Two properties matter:

    * Growing scales the **filled** length, never the column width, so a table's
      geometry is fixed for the entire animation and nothing reflows mid-play.
    * The leading edge is an eighth-block, so a 12-cell bar moves in 96 steps
      instead of 12 and reads as sliding rather than ticking.
    """
    if maximum <= 0 or cells <= 0:
        return ""
    exact = min(float(cells), cells * value / maximum) * rv.t
    full = int(exact)
    out = "█" * full
    if full < cells:
        eighths = int((exact - full) * 8)
        if eighths:
            out += EIGHTHS[eighths]
    return out


def play(
    console: Console,
    build: Callable[[Reveal], RenderableType],
    *,
    seconds: float = SECTION_SECONDS,
    animate: bool = True,
    easing: Callable[[float], float] = ease_out_cubic,
) -> None:
    """Print one section, growing into place.

    ``build`` must be cheap and pure — it is called about 30 times a second — and
    must return the finished renderable when handed ``STATIC``. The last thing
    printed is always ``build(STATIC)``, so a dropped frame or a clock hiccup can
    never leave a half-drawn number on screen.
    """
    if not enabled(console, animate) or seconds <= 0:
        console.print(build(STATIC))
        return

    from rich.live import Live

    frame = 1.0 / FPS
    try:
        with Live(
            build(Reveal(0.0)),
            console=console,
            refresh_per_second=FPS,
            transient=False,
        ) as live:
            started = time.monotonic()
            # Sleep the *remainder* of each frame's budget, not a whole frame on
            # top of however long the render took. Sleeping a full frame after
            # the work makes every animation overrun its requested duration by
            # the render cost — which on a wide report added about 20% to a
            # six-section reveal. Now a slow render drops frames instead of
            # stretching the clock, which is the trade an animation wants.
            next_frame = started
            while True:
                elapsed = time.monotonic() - started
                if elapsed >= seconds:
                    break
                live.update(build(Reveal(easing(elapsed / seconds))))
                next_frame += frame
                delay = next_frame - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
            # Land on the exact finished frame rather than wherever the clock
            # happened to stop.
            live.update(build(STATIC))
    except KeyboardInterrupt:
        # Someone impatient. Give them the answer, not a traceback.
        console.print(build(STATIC))


def rows(
    console: Console,
    build: Callable[[Sequence[T]], RenderableType],
    items: Sequence[T],
    *,
    seconds: float = SECTION_SECONDS,
    animate: bool = True,
) -> None:
    """Print a table whose rows arrive one at a time, in the order given.

    Every ranked table in this package is already sorted worst-first, so arrival
    order carries the ranking: the row that lands first is the one that matters
    most. ``build`` is handed a prefix of ``items`` and must return the table for
    just those rows.
    """
    play(
        console,
        lambda rv: build(rv.visible(items)),
        seconds=seconds,
        animate=animate,
    )


def sequence(
    console: Console,
    builders: Iterable[Callable[[Reveal], RenderableType]],
    *,
    seconds: float = SECTION_SECONDS,
    animate: bool = True,
) -> None:
    """Play several sections one after another, each left in scrollback."""
    for build in builders:
        play(console, build, seconds=seconds, animate=animate)


class Checklist:
    """Checks that resolve one by one, as they actually complete.

    Unlike the rest of this module, this is not an interpolation of a known value
    — the work genuinely takes time (probing six agents' data directories, each a
    filesystem walk), and until now it happened in silence and then printed a
    finished table. Showing each probe land as it lands is the honest version of
    what was already happening.

    Falls back to printing the finished rows, so a piped ``doctor`` is unchanged.
    """

    def __init__(self, console: Console, *, animate: bool = True):
        self._console = console
        self._on = enabled(console, animate)
        self._live: Any = None
        self._lines: list = []
        self._pending = ""

    def __enter__(self) -> Checklist:
        if self._on:
            from rich.live import Live

            self._live = Live(
                self._render(), console=self._console, refresh_per_second=FPS, transient=True
            )
            self._live.start()
        return self

    def __exit__(self, *exc) -> None:
        if self._live is not None:
            self._live.stop()
        return None

    def _render(self) -> RenderableType:
        from rich.console import Group
        from rich.text import Text

        body = list(self._lines)
        if self._pending:
            body.append(Text(f"  … {self._pending}", style="dim"))
        return Group(*body)

    def checking(self, what: str) -> None:
        """Name the check now in flight."""
        self._pending = what
        if self._live is not None:
            self._live.update(self._render())

    def resolved(self, line: RenderableType) -> None:
        """Record a finished check. ``line`` is kept and printed either way."""
        self._lines.append(line)
        self._pending = ""
        if self._live is not None:
            self._live.update(self._render())

    @property
    def lines(self) -> list:
        return list(self._lines)


class Parsing:
    """Progress while transcripts are read — the one genuinely slow step.

    Everything else in this module is polish on output that was already instant.
    This is different: parsing tens of thousands of steps across six adapters
    takes seconds, and before this it was seconds of nothing. Showing the agent
    being read, and the running session count, is the difference between "slow"
    and "working".

    A context manager so the bar always closes, including on Ctrl-C, and a no-op
    when animation is off so piped runs stay silent.
    """

    def __init__(self, console: Console, *, animate: bool = True, total: int | None = None):
        self._console = console
        self._on = enabled(console, animate)
        self._total = total
        # Any, not the real rich types: rich.progress is imported lazily inside
        # __enter__ so that a piped run never pays for it, which means the types
        # are not available at module scope to annotate with.
        self._progress: Any = None
        self._task: Any = None
        self._sessions = 0

    def __enter__(self) -> Parsing:
        if not self._on:
            return self
        from rich.progress import (
            BarColumn,
            Progress,
            SpinnerColumn,
            TextColumn,
            TimeElapsedColumn,
        )

        progress = Progress(
            SpinnerColumn(style="cyan"),
            TextColumn("[cyan]reading[/cyan] {task.fields[what]}"),
            BarColumn(bar_width=24, complete_style="cyan", finished_style="cyan"),
            TextColumn("[dim]{task.fields[found]}[/dim]"),
            TimeElapsedColumn(),
            console=self._console,
            transient=True,  # the report is the output; this was scaffolding
        )
        progress.start()
        self._task = progress.add_task("parse", total=self._total, what="transcripts", found="")
        self._progress = progress
        return self

    def __exit__(self, *exc) -> None:
        if self._progress is not None:
            self._progress.stop()
        return None

    def set_total(self, total: int) -> None:
        """Called once discovery knows how many files there are."""
        if self._progress is not None and self._task is not None:
            self._progress.update(self._task, total=total)

    def advance(self, *, agent: str = "", sessions: int | None = None) -> None:
        """One transcript handled."""
        if sessions is not None:
            self._sessions = sessions
        if self._progress is None or self._task is None:
            return
        found = f"{self._sessions} session{'' if self._sessions == 1 else 's'}"
        self._progress.update(
            self._task, advance=1, what=agent or "transcripts", found=found
        )


__all__ = [
    "EIGHTHS",
    "FPS",
    "SECTION_SECONDS",
    "STATIC",
    "Checklist",
    "Parsing",
    "Reveal",
    "bar",
    "ease_out_cubic",
    "ease_out_quint",
    "enabled",
    "play",
    "rows",
    "sequence",
]
