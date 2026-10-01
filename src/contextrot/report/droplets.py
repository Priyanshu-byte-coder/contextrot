"""The water animation: droplets falling into a filling tank.

A terminal is a grid of cells, which is normally what stops terminal animation
from looking good — water that climbs a whole row at a time reads as a progress
bar, not as water. Three things fix that here:

**Sub-cell resolution.** The surface is tracked in eighths of a row and drawn
with the vertical block characters ``▁▂▃▄▅▆▇█``, so it moves eight times per
row and the meniscus lands between cells rather than on them.

**A real surface, not a line.** Height per column is two sine waves at
different frequencies travelling in opposite directions, so the crests never
line up the same way twice and the surface never visibly loops. Each landing
droplet adds a decaying ripple on top — a travelling cosine with both a
distance and a time envelope — which is what makes a splash read as a splash.

**Easing.** Level and number share one ease-out curve, so the count-up and the
water stay locked together and both decelerate into the final value instead of
stopping dead.

Rendering is a pure function of simulation state, and the simulation advances
by a fixed ``dt`` from a seeded RNG, so a given (seed, dt, frame count) always
produces the same frames — which is what makes any of this testable.

Degrades on purpose: no TTY, or a terminal that cannot encode the block
characters, falls back to ASCII glyphs or to a single static frame. The water
is the fun part, never the payload.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Callable

from rich.console import Console, Group, RenderableType
from rich.text import Text

# Vertical eighths, filling a cell from the bottom. Index 0 is "empty" and is
# never drawn as a water cell — an empty cell is background instead.
_EIGHTHS_UP = " ▁▂▃▄▅▆▇█"

# How many sub-cell steps make up one row. The whole simulation runs in these
# units so the surface can sit between cells.
SUBCELLS = 8


@dataclass(frozen=True)
class Glyphs:
    """Characters for one output target."""

    eighths: str
    full: str
    drop: str
    trail: str
    tl: str
    tr: str
    bl: str
    br: str
    h: str
    v: str


UNICODE = Glyphs(_EIGHTHS_UP, "█", "•", "·", "╭", "╮", "╰", "╯", "─", "│")
# Four ASCII heights instead of eight: the resolution is halved, but a terminal
# that cannot encode block characters cannot do better, and a coarse animation
# beats a screen of replacement characters.
ASCII = Glyphs(" ....::::", "#", "o", ".", "+", "+", "+", "+", "-", "|")

# Depth ramp, surface first. Water reads as water because the colour changes
# with depth; a single blue reads as a bar chart.
_WATER_RAMP = ("#9beeff", "#45c2f0", "#2a86d6", "#1b56ad", "#133b86")
# Crest highlights, picked up by the shimmer term.
_FOAM = "#d9fbff"
_GLASS = "#3f5878"

# Sim constants. These are tuned by eye; the comments say what each one does to
# the feel, because that is the only thing they can be judged against.
_WAVE_AMPLITUDE = 1.7  # eighths. Higher = choppier surface.
_RIPPLE_AMPLITUDE = 3.2  # eighths at the point of impact.
_RIPPLE_DECAY = 0.75  # seconds for a splash to die away.
_RIPPLE_SPREAD = 7.0  # cells a splash travels before it flattens.
_DROP_SPEED = 15.0  # rows per second. Fast enough to streak, slow enough to see.


@dataclass
class _Drop:
    x: int
    y: float  # rows from the top
    speed: float


@dataclass
class _Ripple:
    x: float
    born: float


@dataclass
class Scene:
    """A tank filling with water, advanced by fixed time steps."""

    width: int
    height: int
    target_ml: float
    fill_seconds: float = 3.6
    seed: int = 7
    glyphs: Glyphs = UNICODE

    # Set this (0..1) to drive the level from outside instead of from the clock,
    # for the live view, where the water is as deep as real data says it is. The
    # shown level eases toward it rather than snapping, so a jump in the data
    # still looks like water arriving.
    live_target: float | None = None

    t: float = 0.0
    drops: list = field(default_factory=list)
    ripples: list = field(default_factory=list)
    _rng: random.Random = field(default_factory=lambda: random.Random(7))
    _next_spawn: float = 0.0
    _eased: float = 0.0

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._next_spawn = 0.0

    # --- simulation ----------------------------------------------------------

    # How fast the shown level closes the gap to live_target, per second. Slow
    # enough that a rising number reads as filling, fast enough not to lag.
    APPROACH_PER_SECOND = 2.0

    @property
    def progress(self) -> float:
        """Eased 0..1. Shared by the water level and the number above it."""
        if self.live_target is not None:
            return self._eased
        raw = 1.0 if self.fill_seconds <= 0 else min(1.0, self.t / self.fill_seconds)
        return 1.0 - (1.0 - raw) ** 3

    @property
    def shown_ml(self) -> float:
        return self.target_ml * self.progress

    @property
    def level_subcells(self) -> float:
        """Resting water height from the tank floor, in eighths of a row."""
        return self.progress * self.height * SUBCELLS

    def step(self, dt: float) -> None:
        self.t += dt
        if self.live_target is not None:
            target = max(0.0, min(1.0, self.live_target))
            self._eased += (target - self._eased) * min(1.0, dt * self.APPROACH_PER_SECOND)
        self._spawn()
        self._fall(dt)
        # A ripple contributes nothing once its envelope has decayed; dropping
        # it keeps the per-column surface loop O(live splashes).
        cutoff = self.t - _RIPPLE_DECAY * 4
        self.ripples = [r for r in self.ripples if r.born > cutoff]

    def _spawn(self) -> None:
        """Rain hard while filling, then taper to the occasional drip.

        The taper is the satisfying part: the scene calms down instead of
        cutting out, so the end feels like settling rather than stopping.
        """
        if self.t < self._next_spawn:
            return
        remaining = max(0.0, 1.0 - self.progress)
        gap = 0.07 + 0.9 * (1.0 - remaining) ** 2
        self._next_spawn = self.t + gap * self._rng.uniform(0.6, 1.5)
        self.drops.append(
            _Drop(
                x=self._rng.randrange(self.width),
                y=0.0,
                speed=_DROP_SPEED * self._rng.uniform(0.8, 1.25),
            )
        )

    def _fall(self, dt: float) -> None:
        surface_row = self.height - self.level_subcells / SUBCELLS
        still_falling: list = []
        for drop in self.drops:
            drop.y += drop.speed * dt
            if drop.y >= surface_row:
                self.ripples.append(_Ripple(x=float(drop.x), born=self.t))
                continue
            still_falling.append(drop)
        self.drops = still_falling

    def surface_at(self, x: int) -> float:
        """Water height at column ``x``, in eighths from the floor."""
        if self.progress <= 0:
            return 0.0
        h = self.level_subcells
        # Two travelling waves at incommensurate frequencies: their crests
        # never realign, so the surface has no visible period.
        h += _WAVE_AMPLITUDE * math.sin(0.55 * x + 2.1 * self.t)
        h += 0.6 * _WAVE_AMPLITUDE * math.sin(0.23 * x - 1.3 * self.t + 1.1)
        for ripple in self.ripples:
            age = self.t - ripple.born
            if age < 0:
                continue
            distance = abs(x - ripple.x)
            envelope = math.exp(-age / _RIPPLE_DECAY) * math.exp(-distance / _RIPPLE_SPREAD)
            if envelope < 0.01:
                continue
            h += _RIPPLE_AMPLITUDE * envelope * math.cos(1.1 * distance - 7.0 * age)
        return max(0.0, min(float(self.height * SUBCELLS), h))

    # --- rendering -----------------------------------------------------------

    def render(self) -> list:
        """The tank, as one Text per row including its borders."""
        g = self.glyphs
        heights = [self.surface_at(x) for x in range(self.width)]
        rows: list = [Text(g.tl + g.h * self.width + g.tr, style=_GLASS)]

        for row in range(self.height):
            # Distance of this row's floor from the tank floor, in eighths.
            floor = (self.height - 1 - row) * SUBCELLS
            line = Text()
            line.append(g.v, style=_GLASS)
            for x in range(self.width):
                filled = heights[x] - floor
                if filled <= 0:
                    line.append(" ")
                    continue
                if filled >= SUBCELLS:
                    line.append(g.full, style=self._body_style(x, row, heights[x]))
                    continue
                eighths = max(1, min(SUBCELLS - 1, int(round(filled))))
                line.append(g.eighths[eighths], style=_FOAM)
            line.append(g.v, style=_GLASS)
            rows.append(line)

        rows.append(Text(g.bl + g.h * self.width + g.br, style=_GLASS))
        self._paint_drops(rows)
        return rows

    def _body_style(self, x: int, row: int, column_height: float) -> str:
        """Depth colour, lifted where the shimmer term crests.

        The shimmer is a product of two sines in x and depth, drifting with
        time: enough moving light on the body of the water to stop a block of
        solid colour from looking like a solid block.
        """
        # Rows between the surface and the top edge of this cell. The topmost
        # submerged cell sits at ~0 and takes the lightest blue.
        depth_rows = max(0.0, column_height / SUBCELLS - (self.height - row))
        # Normalised against the water's own depth, not the tank's: a shallow
        # pool still shows the whole ramp instead of one flat shade of cyan.
        span = max(1.0, column_height / SUBCELLS)
        idx = min(len(_WATER_RAMP) - 1, int(depth_rows / span * len(_WATER_RAMP)))
        shimmer = math.sin(0.9 * x + 2.6 * self.t) * math.sin(1.4 * row - 1.2 * self.t)
        if shimmer > 0.86 and idx > 0:
            idx -= 1
        return _WATER_RAMP[idx]

    def _paint_drops(self, rows: list) -> None:
        """Overwrite falling-droplet cells in place, inside the borders.

        Drawn last so a droplet is never hidden by the water it is about to
        hit, and written per cell rather than rebuilt per row because a Text
        that is already assembled is cheaper to patch than to recreate.
        """
        g = self.glyphs
        for drop in self.drops:
            for offset, char, style in (
                (0, g.drop, _FOAM),
                (-1, g.trail, _WATER_RAMP[1]),
            ):
                row = int(drop.y) + offset
                if row < 0 or row >= self.height:
                    continue
                cell = 1 + drop.x  # past the left border
                line = rows[row + 1]  # past the top border
                if cell >= len(line.plain):
                    continue
                if line.plain[cell] != " ":
                    continue  # water already owns this cell
                line.plain = line.plain[:cell] + char + line.plain[cell + 1 :]
                line.stylize(style, cell, cell + 1)


# --- the big number ----------------------------------------------------------

# A 3x5 block font. Only the glyphs a formatted volume can contain, because
# carrying a full font for "4.12 L" would be dead weight.
_FONT: dict = {
    "0": ("███", "█ █", "█ █", "█ █", "███"),
    "1": ("  █", "  █", "  █", "  █", "  █"),
    "2": ("███", "  █", "███", "█  ", "███"),
    "3": ("███", "  █", "███", "  █", "███"),
    "4": ("█ █", "█ █", "███", "  █", "  █"),
    "5": ("███", "█  ", "███", "  █", "███"),
    "6": ("███", "█  ", "███", "█ █", "███"),
    "7": ("███", "  █", "  █", "  █", "  █"),
    "8": ("███", "█ █", "███", "█ █", "███"),
    "9": ("███", "█ █", "███", "  █", "███"),
    ".": ("   ", "   ", "   ", "   ", " █ "),
    ",": ("   ", "   ", "   ", " █ ", "█  "),
    "L": ("█  ", "█  ", "█  ", "█  ", "███"),
    "m": ("   ", "   ", "███", "█ █", "█ █"),
    "l": (" █ ", " █ ", " █ ", " █ ", " █ "),
    " ": ("   ", "   ", "   ", "   ", "   "),
}
_FONT_ROWS = 5


def big_number(text: str, glyphs: Glyphs = UNICODE) -> list:
    """``4.12 L`` as five Text rows, lit top-down like water catching light."""
    rows: list = []
    for r in range(_FONT_ROWS):
        line = Text()
        # Brightest at the top, deepest at the bottom: the same ramp the water
        # uses, so the number reads as part of the same scene.
        style = _WATER_RAMP[min(len(_WATER_RAMP) - 1, r * len(_WATER_RAMP) // _FONT_ROWS)]
        for char in text:
            glyph = _FONT.get(char)
            if glyph is None:
                continue
            line.append(glyph[r].replace("█", glyphs.full), style=style)
            line.append(" ")
        rows.append(line)
    return rows


# --- the frame ---------------------------------------------------------------


def frame(scene: Scene, caption: str, headline: str, width: int = 0) -> RenderableType:
    """One complete frame: the number, the caption, the tank.

    ``width`` right-pads the headline to a fixed character count. The count-up
    passes through "0.00 ml", "812 ml" and "4.12 L", and letting the block
    digits change width mid-climb makes the whole scene twitch sideways.
    """
    pad = " " * 2
    body: list = [Text()]
    for row in big_number(headline.rjust(width), scene.glyphs):
        body.append(Text(pad) + row)
    body.append(Text())
    # Never wrapped: a caption that reflows changes the frame's height, and a
    # Live region that changes height mid-animation jumps instead of animating.
    body.append(Text(pad + caption, style="#7f8fa6", no_wrap=True, overflow="ellipsis"))
    body.append(Text())
    for row in scene.render():
        body.append(Text(pad) + row)
    return Group(*body)


def can_animate(console: Console) -> bool:
    """Animation needs a terminal that is watching. Pipes and CI get a frame."""
    return bool(console.is_terminal) and not console.is_jupyter


def glyphs_for(console: Console) -> Glyphs:
    """Unicode blocks unless the terminal's encoding would mangle them."""
    if getattr(console, "legacy_windows", False):
        return ASCII
    encoding = getattr(console.file, "encoding", None) or "utf-8"
    try:
        (UNICODE.eighths + UNICODE.full + UNICODE.drop + UNICODE.tl).encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return ASCII
    return UNICODE


def watch(
    console: Console,
    read: Callable[[], tuple[float, str] | None],
    *,
    fps: int = 20,
    poll_seconds: float = 1.0,
    max_seconds: float | None = None,
) -> None:
    """Animate a live water meter until interrupted.

    This exists because a Claude Code status line cannot animate: the host re-runs
    the status command on conversation events, not on a timer, so a frame-per-render
    loop advances a few times a minute. Smooth motion needs a process that owns its
    own clock — a split pane, a second terminal, a tmux window.

    ``read()`` returns ``(millilitres, caption)`` for the live session, or None when
    there isn't one. It is called every ``poll_seconds`` rather than every frame:
    reading is cheap but not free, and the level eases between samples anyway, so
    polling faster would buy nothing visible.
    """
    from contextrot.water import fmt_volume, milestone

    glyphs = glyphs_for(console)
    scene = Scene(
        width=max(24, min(56, console.width - 8)),
        height=10,
        target_ml=0.0,
        glyphs=glyphs,
        live_target=0.0,
    )
    ml, caption = 0.0, "waiting for a session"
    label_width = 0

    def shot() -> RenderableType:
        return frame(scene, caption, fmt_volume(ml), label_width)

    from rich.live import Live

    dt = 1.0 / max(1, fps)
    started = time.monotonic()
    next_poll = 0.0
    try:
        with Live(shot(), console=console, refresh_per_second=fps, transient=False) as live:
            while True:
                now = time.monotonic() - started
                if max_seconds is not None and now >= max_seconds:
                    break
                if now >= next_poll:
                    next_poll = now + max(0.1, poll_seconds)
                    reading = read()
                    if reading is not None:
                        ml, caption = reading
                        ceiling, fraction = milestone(ml)
                        scene.live_target = fraction
                        caption = f"{caption} · next splash at {fmt_volume(ceiling)}"
                        label_width = max(label_width, len(fmt_volume(ml)))
                scene.step(dt)
                live.update(shot())
                time.sleep(dt)
    except KeyboardInterrupt:
        # Ctrl-C is how you leave a live view, not an error. Live's context
        # manager has already restored the cursor by the time this is reached.
        pass


def play(
    console: Console,
    target_ml: float,
    caption: str,
    *,
    seconds: float = 5.0,
    fps: int = 24,
    animate: bool = True,
) -> None:
    """Fill the tank on screen, then leave the finished frame in the scrollback.

    ``seconds`` covers fill plus settle: the water reaches its level in the
    first 70% and the rest is surface motion with the number already final,
    because a scene that stops the instant it arrives feels truncated.
    """
    from contextrot.water import fmt_volume

    scene = Scene(
        width=max(24, min(56, console.width - 8)),
        height=10,
        target_ml=target_ml,
        fill_seconds=max(0.3, seconds * 0.7),
        glyphs=glyphs_for(console),
    )
    final = fmt_volume(target_ml)
    # The count-up changes unit on the way ("812 ml" -> "1.20 L"), so reserve
    # the widest label any frame can need rather than the final one's width.
    label_width = max(len(final), len(fmt_volume(target_ml * 0.99)))

    def shot() -> RenderableType:
        return frame(scene, caption, fmt_volume(scene.shown_ml), label_width)

    if not animate or not can_animate(console):
        # One frame, fully filled, so piped and CI output still show the tank.
        scene.t = scene.fill_seconds
        console.print(shot())
        return

    from rich.live import Live

    dt = 1.0 / max(1, fps)
    with Live(shot(), console=console, refresh_per_second=fps, transient=False) as live:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            scene.step(dt)
            live.update(shot())
            time.sleep(dt)
