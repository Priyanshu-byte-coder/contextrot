"""The animation engine, and the property that makes it safe.

The property: a disabled animation is not a second code path, it is the same
render at ``t = 1.0``. Several tests here assert that directly, because it is
what lets every renderer be animated without a static counterpart to drift from.
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console
from rich.text import Text

from contextrot.anim import (
    EIGHTHS,
    STATIC,
    Checklist,
    Parsing,
    Reveal,
    bar,
    ease_out_cubic,
    ease_out_quint,
    enabled,
    play,
    rows,
)


def _console(*, tty: bool = False, width: int = 80) -> Console:
    sink = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    return Console(file=sink, width=width, force_terminal=tty or None, legacy_windows=False)


def _text(console: Console) -> str:
    console.file.flush()
    return console.file.buffer.getvalue().decode("utf-8")


# --- easing ------------------------------------------------------------------


@pytest.mark.parametrize("fn", [ease_out_cubic, ease_out_quint])
def test_easings_are_bounded_and_monotonic(fn) -> None:
    assert fn(0.0) == 0.0
    assert fn(1.0) == 1.0
    # Out of range in either direction is clamped rather than extrapolated: a
    # clock hiccup must not produce a bar longer than its own value.
    assert fn(-5.0) == 0.0
    assert fn(5.0) == 1.0
    seen = [fn(i / 20) for i in range(21)]
    assert seen == sorted(seen)


def test_easings_decelerate() -> None:
    """Ease-out means more than half the distance is covered in the first half."""
    for fn in (ease_out_cubic, ease_out_quint):
        assert fn(0.5) > 0.5


# --- Reveal ------------------------------------------------------------------


def test_static_is_the_finished_frame() -> None:
    assert STATIC.done
    assert STATIC.num(37.5) == 37.5
    assert STATIC.whole(812) == 812
    assert STATIC.width(40) == 40


def test_reveal_scales_every_kind_of_value() -> None:
    half = Reveal(0.5)
    assert half.num(10.0) == 5.0
    assert half.whole(10) == 5
    assert half.width(40) == 20
    assert not half.done


def test_whole_never_overshoots_its_target() -> None:
    for t in (0.0, 0.33, 0.9, 1.0):
        assert 0 <= Reveal(t).whole(7) <= 7


def test_stagger_arrives_in_order() -> None:
    """Item 0 must never lag item 1, or the cascade runs backwards."""
    for t in (0.1, 0.3, 0.6, 0.9, 1.0):
        rv = Reveal(t)
        locals_ = [rv.stagger(i, 5).t for i in range(5)]
        assert locals_ == sorted(locals_, reverse=True), (t, locals_)


def test_stagger_all_finished_at_the_end() -> None:
    rv = STATIC
    assert all(rv.stagger(i, 6).done for i in range(6))


def test_stagger_of_a_single_item_is_just_the_parent() -> None:
    assert Reveal(0.4).stagger(0, 1).t == pytest.approx(0.4)


def test_visible_grows_but_always_shows_something() -> None:
    items = list(range(10))
    assert list(Reveal(0.0).visible(items)) == [0]
    assert len(Reveal(0.5).visible(items)) == 5
    assert list(STATIC.visible(items)) == items
    assert list(STATIC.visible([])) == []


def test_gate_opens_once_passed() -> None:
    assert not Reveal(0.3).gate(0.5)
    assert Reveal(0.6).gate(0.5)


# --- the bar -----------------------------------------------------------------


def test_bar_reaches_exactly_full_width_at_its_maximum() -> None:
    assert bar(1.0, 1.0, 12) == "█" * 12


def test_bar_growing_changes_fill_not_width() -> None:
    """A table's geometry must be fixed for the whole animation."""
    widths = {len(bar(1.0, 1.0, 20, Reveal(t / 10))) for t in range(11)}
    # The drawn string gets longer, but it never exceeds the column.
    assert max(widths) == 20


def test_bar_uses_an_eighth_block_for_the_leading_edge() -> None:
    """Sub-cell resolution is what makes a short bar glide instead of tick."""
    grown = {bar(1.0, 1.0, 4, Reveal(t / 100)) for t in range(101)}
    partials = {b[-1] for b in grown if b and b[-1] != "█"}
    assert partials, "no partial cell ever drawn"
    assert partials <= set(EIGHTHS[1:])


def test_bar_is_monotonic_in_both_value_and_reveal() -> None:
    assert len(bar(0.2, 1.0, 20)) < len(bar(0.8, 1.0, 20))
    lengths = [len(bar(0.8, 1.0, 20, Reveal(t / 10))) for t in range(11)]
    assert lengths == sorted(lengths)


def test_bar_degenerate_inputs_draw_nothing() -> None:
    assert bar(1.0, 0.0, 10) == ""
    assert bar(1.0, 1.0, 0) == ""


def test_bar_cannot_exceed_its_maximum() -> None:
    """A value above the scale is clamped, not allowed to overflow the column."""
    assert bar(5.0, 1.0, 8) == "█" * 8


# --- when animation is off ---------------------------------------------------


def test_disabled_by_a_pipe() -> None:
    assert enabled(_console()) is False


def test_disabled_by_the_flag_even_on_a_terminal() -> None:
    assert enabled(_console(tty=True), want=False) is False


def test_disabled_by_environment(monkeypatch) -> None:
    monkeypatch.setenv("CONTEXTROT_NO_ANIM", "1")
    assert enabled(_console(tty=True)) is False


def test_disabled_in_ci(monkeypatch) -> None:
    """A CI log replays at once; thousands of frames there are pure noise."""
    monkeypatch.setenv("CI", "true")
    assert enabled(_console(tty=True)) is False


def test_enabled_on_a_plain_terminal(monkeypatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("CONTEXTROT_NO_ANIM", raising=False)
    assert enabled(_console(tty=True)) is True


# --- the driver --------------------------------------------------------------


def test_play_prints_the_finished_frame_when_disabled() -> None:
    console = _console()
    seen: list[float] = []

    def build(rv: Reveal):
        seen.append(rv.t)
        return Text(f"value {rv.whole(100)}")

    play(console, build, animate=False)
    assert seen == [1.0], "a disabled animation must render exactly once, at the end"
    assert "value 100" in _text(console)


def test_play_ends_on_the_exact_finished_frame(monkeypatch) -> None:
    """A dropped frame or a clock hiccup must never leave a half-drawn number."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("CONTEXTROT_NO_ANIM", raising=False)
    console = _console(tty=True)
    seen: list[float] = []

    play(console, lambda rv: (seen.append(rv.t), Text("x"))[1], seconds=0.05, animate=True)
    assert seen[-1] == 1.0
    assert len(seen) > 1, "an enabled animation should draw more than one frame"


def test_play_in_a_pipe_matches_play_disabled() -> None:
    """The safety property, asserted directly."""

    def build(rv: Reveal):
        return Text(f"{rv.whole(42)} | {bar(1.0, 1.0, 10, rv)}")

    a, b = _console(), _console()
    play(a, build, animate=False)
    play(b, build, animate=True)
    assert _text(a) == _text(b)


def test_rows_reveals_a_prefix_and_finishes_whole() -> None:
    console = _console()
    calls: list[int] = []

    def build(visible):
        calls.append(len(visible))
        return Text(", ".join(str(v) for v in visible))

    rows(console, build, [1, 2, 3, 4], animate=False)
    assert calls == [4]
    assert "1, 2, 3, 4" in _text(console)


def test_play_survives_a_builder_that_raises_on_the_first_frame() -> None:
    """Cosmetics must never be the reason a report fails to print."""
    console = _console()
    with pytest.raises(ZeroDivisionError):
        play(console, lambda rv: Text(str(1 / 0)), animate=False)


# --- progress and checklist --------------------------------------------------


def test_parsing_is_a_silent_no_op_when_disabled() -> None:
    console = _console()
    with Parsing(console, animate=False) as p:
        p.set_total(10)
        for _ in range(10):
            p.advance(agent="claude-code", sessions=3)
    assert _text(console) == ""


def test_parsing_tolerates_advance_without_a_total() -> None:
    """Adapters that cannot count up front still have to tick the bar."""
    console = _console()
    with Parsing(console, animate=False) as p:
        p.advance(agent="codex")


def test_checklist_keeps_its_lines_when_disabled() -> None:
    console = _console()
    with Checklist(console, animate=False) as checks:
        checks.checking("looking for claude-code")
        checks.resolved(Text("✓ claude-code"))
        checks.resolved(Text("· codex"))
    assert len(checks.lines) == 2


def test_checklist_closes_even_if_the_body_raises() -> None:
    console = _console()
    with pytest.raises(RuntimeError), Checklist(console, animate=False) as checks:
        checks.resolved(Text("one"))
        raise RuntimeError("probe blew up")
