"""The water animation: determinism, bounds, and the fallbacks."""

from __future__ import annotations

import io

from rich.console import Console

from contextrot.report.droplets import (
    ASCII,
    SUBCELLS,
    UNICODE,
    Scene,
    big_number,
    can_animate,
    frame,
    glyphs_for,
    play,
    watch,
)


def _console(width: int = 72, legacy: bool = False, **kw) -> Console:
    sink = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    return Console(width=width, file=sink, legacy_windows=legacy, **kw)


def _plain(scene: Scene) -> str:
    return "\n".join(row.plain for row in scene.render())


def _advance(scene: Scene, frames: int, dt: float = 1 / 24) -> None:
    for _ in range(frames):
        scene.step(dt)


# --- determinism -------------------------------------------------------------


def test_same_seed_and_steps_give_identical_frames() -> None:
    """The droplets are random-looking, not random: frames have to be testable."""
    a = Scene(width=30, height=8, target_ml=4_000, seed=11)
    b = Scene(width=30, height=8, target_ml=4_000, seed=11)
    _advance(a, 30)
    _advance(b, 30)
    assert _plain(a) == _plain(b)


def test_different_seeds_place_droplets_differently() -> None:
    a = Scene(width=40, height=8, target_ml=4_000, seed=1)
    b = Scene(width=40, height=8, target_ml=4_000, seed=2)
    _advance(a, 8)
    _advance(b, 8)
    assert _plain(a) != _plain(b)


# --- the fill ----------------------------------------------------------------


def test_progress_starts_empty_and_eases_to_full() -> None:
    scene = Scene(width=20, height=8, target_ml=1_000, fill_seconds=2.0)
    assert scene.progress == 0.0
    assert scene.shown_ml == 0.0

    _advance(scene, 24)  # one second in: eased, so well past halfway
    assert scene.progress > 0.5
    assert scene.progress < 1.0

    _advance(scene, 48)
    assert scene.progress == 1.0
    assert scene.shown_ml == 1_000


def test_an_empty_tank_has_no_surface() -> None:
    scene = Scene(width=12, height=6, target_ml=500)
    assert all(scene.surface_at(x) == 0.0 for x in range(scene.width))
    assert _plain(scene).count("█") == 0


def test_the_surface_stays_inside_the_tank() -> None:
    """Ripples add to the wave, so the sum has to be clamped or water escapes."""
    scene = Scene(width=36, height=8, target_ml=4_000, fill_seconds=1.0, seed=5)
    ceiling = float(scene.height * SUBCELLS)
    for _ in range(120):
        scene.step(1 / 24)
        for x in range(scene.width):
            assert 0.0 <= scene.surface_at(x) <= ceiling


def test_every_rendered_row_is_the_same_width() -> None:
    """A row that drifts a character wide tears the tank's borders apart."""
    scene = Scene(width=28, height=7, target_ml=2_000, fill_seconds=1.0, seed=3)
    _advance(scene, 20)
    widths = {len(row.plain) for row in scene.render()}
    assert widths == {scene.width + 2}  # the two borders


def test_the_surface_is_not_flat() -> None:
    scene = Scene(width=40, height=8, target_ml=4_000, fill_seconds=0.5)
    _advance(scene, 40)
    heights = {round(scene.surface_at(x), 3) for x in range(scene.width)}
    assert len(heights) > 1


def test_droplets_fall_and_then_land() -> None:
    scene = Scene(width=30, height=10, target_ml=4_000, fill_seconds=4.0, seed=9)
    _advance(scene, 6)
    assert scene.drops, "droplets should be in the air early on"
    _advance(scene, 120)
    # Everything spawned has either landed (making a ripple) or is still falling;
    # either way nothing is left stuck above a full tank.
    assert all(drop.y < scene.height for drop in scene.drops)


def test_spawning_calms_down_as_the_tank_fills() -> None:
    """The taper is what makes the end feel like settling rather than stopping."""
    early = Scene(width=30, height=10, target_ml=4_000, fill_seconds=4.0, seed=4)
    _advance(early, 24)
    early_count = len(early.drops) + len(early.ripples)

    late = Scene(width=30, height=10, target_ml=4_000, fill_seconds=4.0, seed=4)
    _advance(late, 24 * 8)
    late_count = len(late.drops) + len(late.ripples)

    assert late_count < early_count


# --- the number --------------------------------------------------------------


def test_big_number_is_five_rows_of_fixed_width() -> None:
    rows = big_number("4.12 L")
    assert len(rows) == 5
    assert {len(row.plain) for row in rows} == {len("4.12 L") * 4}


def test_big_number_covers_every_character_a_volume_can_contain() -> None:
    from contextrot.water import fmt_volume

    for ml in (0.4, 3.4, 812.0, 4_123.0, 47_000.0, 1_240_000.0):
        text = fmt_volume(ml)
        rows = big_number(text)
        # Nothing silently dropped: every character contributed a glyph.
        assert {len(row.plain) for row in rows} == {len(text) * 4}


def test_ascii_number_uses_no_block_characters() -> None:
    rows = big_number("500 ml", ASCII)
    assert all("█" not in row.plain for row in rows)


# --- output targets ----------------------------------------------------------


def test_legacy_windows_falls_back_to_ascii() -> None:
    assert glyphs_for(_console(legacy=True)) is ASCII


def test_a_utf8_terminal_keeps_the_blocks() -> None:
    assert glyphs_for(_console()) is UNICODE


def test_an_encoding_that_cannot_hold_blocks_falls_back() -> None:
    sink = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    console = Console(width=72, file=sink, legacy_windows=False)
    assert glyphs_for(console) is ASCII


def test_a_pipe_gets_no_animation() -> None:
    assert can_animate(_console()) is False
    assert can_animate(_console(force_terminal=True)) is True


def test_play_without_a_terminal_still_prints_the_tank() -> None:
    console = _console()
    play(console, 4_123.0, "of water", animate=True)
    console.file.flush()
    out = console.file.buffer.getvalue().decode("utf-8")
    assert "╭" in out and "█" in out


def test_frame_renders_at_a_narrow_width() -> None:
    console = _console(width=40)
    scene = Scene(width=20, height=6, target_ml=500, glyphs=glyphs_for(console))
    _advance(scene, 12)
    console.print(frame(scene, "a very long caption " * 6, "500 ml", 6))
    console.file.flush()
    out = console.file.buffer.getvalue().decode("utf-8")
    # Exact, not an upper bound: the caption is truncated rather than wrapped, so
    # a frame is always 1 blank + 5 number + 1 blank + 1 caption + 1 blank +
    # (2 borders + height) rows. Wrapping would show up here as extra lines.
    assert out.count("\n") == 9 + (scene.height + 2)


# --- the live view ------------------------------------------------------------


def test_the_level_eases_toward_a_live_target_rather_than_snapping():
    """A jump in the data should still look like water arriving."""
    scene = Scene(width=20, height=10, target_ml=0, live_target=0.9)
    assert scene.progress == 0.0

    seen = []
    for _ in range(30):
        scene.step(1 / 20)
        seen.append(scene.progress)

    assert seen == sorted(seen), "the level should only climb toward a higher target"
    assert 0.0 < seen[0] < 0.5
    assert 0.8 < seen[-1] <= 0.9


def test_the_level_follows_a_target_back_down():
    """Crossing a milestone resets the fraction, so the tank has to drain too."""
    scene = Scene(width=20, height=10, target_ml=0, live_target=0.95)
    for _ in range(60):
        scene.step(1 / 20)
    scene.live_target = 0.05
    for _ in range(60):
        scene.step(1 / 20)
    assert scene.progress < 0.1


def test_watch_polls_on_its_own_clock_and_stops_when_told():
    console = _console(force_terminal=True)
    calls = []

    def read():
        calls.append(len(calls))
        return 38_209.0 + len(calls) * 500.0, "claude-code · about 3.1 bathtubs"

    watch(console, read, fps=20, poll_seconds=0.1, max_seconds=0.6)
    # Polling is independent of the frame rate: far fewer reads than frames.
    assert 3 <= len(calls) <= 10
    console.file.flush()
    assert b"\xe2\x95\xad" in console.file.buffer.getvalue()  # the tank's top border


def test_watch_tolerates_having_no_live_session():
    """No session is a normal state, not an error — it just keeps waiting."""
    console = _console(force_terminal=True)
    watch(console, lambda: None, fps=20, poll_seconds=0.1, max_seconds=0.4)
    console.file.flush()
    assert console.file.buffer.getvalue()


def test_watch_exits_cleanly_on_interrupt():
    console = _console(force_terminal=True)

    def read():
        raise KeyboardInterrupt

    watch(console, read, fps=20, poll_seconds=0.05, max_seconds=1.0)
