"""Headroom: turning "tokens left" into "how much more work fits".

The measurement that matters is per-*turn* growth. Per-step growth was tried
first and is useless — the median step is dominated by cache replay, so real
headroom renders as hundreds of steps and reads as unlimited. These tests pin
the turn-level behaviour and the refusals.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from contextrot.analysis.headroom import MIN_GROWTH_SAMPLES, GrowthStats, turn_growth
from contextrot.calibration import TurnCost
from contextrot.models import Session, Step
from contextrot.statusline import PLAIN, render_fill

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _session(turn_costs: list[int], steps_per_turn: int = 3) -> Session:
    """A session where each turn grows the context by a given amount.

    Each turn contributes several steps so the test would fail if the
    implementation silently went back to measuring per-step growth.
    """
    session = Session(session_id="s", source="claude-code", project="/repo")
    prompt = 10_000
    for t, cost in enumerate(turn_costs + [0]):
        for j in range(steps_per_turn):
            step = Step(
                timestamp=T0 + timedelta(minutes=t * 10 + j),
                model="claude-opus-5",
                input_tokens=prompt + j * 100,  # intra-turn drift, not turn cost
            )
            if j == 0:
                session.mark_turn_start()
            session.add_step(step)
        prompt += cost
    return session


def test_growth_is_measured_between_turn_starts():
    stats = turn_growth([_session([10_000] * 60)])
    assert stats.samples == 60
    assert stats.median == 10_000


def test_intra_turn_steps_do_not_count_as_turns():
    """Ten steps per turn must still yield one growth sample per turn."""
    stats = turn_growth([_session([8_000] * 60, steps_per_turn=10)])
    assert stats.samples == 60
    assert stats.median == 8_000


def test_shrinking_context_is_dropped_not_clamped():
    """A drop is a compaction, not a turn that cost negative tokens."""
    session = Session(session_id="s", source="claude-code", project="/repo")
    for i, prompt in enumerate([100_000, 120_000, 20_000, 40_000]):
        session.mark_turn_start()
        session.add_step(Step(timestamp=T0 + timedelta(minutes=i), model="m", input_tokens=prompt))
    stats = turn_growth([session])
    # +20k and +20k are real; the 120k -> 20k compaction is not a sample.
    assert stats.samples == 2
    assert stats.median == 20_000


def test_thin_data_is_refused():
    stats = turn_growth([_session([5_000] * (MIN_GROWTH_SAMPLES - 2))])
    assert not stats.usable
    assert stats.turns_left(500_000) is None


def test_no_turn_markers_yields_nothing():
    """A session whose adapter marked no boundaries contributes no guesses."""
    session = Session(session_id="s", source="x", project="/repo")
    for i in range(50):
        session.add_step(Step(timestamp=T0, model="m", input_tokens=1000 * i))
    assert turn_growth([session]).samples == 0


def test_headroom_arithmetic():
    stats = GrowthStats(median=10_000, p90=50_000, samples=500)
    assert stats.turns_left(100_000) == 10
    assert stats.heavy_turns_left(100_000) == 2
    # Nothing left means nothing fits.
    assert stats.turns_left(0) is None


# --- how it reaches the status line ----------------------------------------


def _line(fill, tokens, window, turn_cost) -> str:
    return _ANSI.sub("", render_fill(fill, None, PLAIN, tokens=tokens, window=window,
                                     turn_cost=turn_cost))


def test_statusline_shows_turns_when_measured():
    tc = TurnCost(median=15_000, p90=70_000, samples=800)
    out = _line(34.0, 340_000, 1_000_000, tc)
    assert "340k/1M" in out
    assert "~44 turns left" in out
    # Plenty of room: the heavy figure would only be noise here.
    assert "heavy" not in out


def test_statusline_adds_the_heavy_case_when_tight():
    tc = TurnCost(median=15_000, p90=70_000, samples=800)
    out = _line(85.0, 850_000, 1_000_000, tc)
    assert "~10 turns left" in out
    assert "~2 heavy" in out


def test_statusline_says_stop_rather_than_zero():
    """"~0 turns left, ~0 heavy" says the same thing twice."""
    tc = TurnCost(median=15_000, p90=70_000, samples=800)
    out = _line(99.5, 199_000, 200_000, tc)
    assert "no room for another turn" in out
    assert "~0" not in out


def test_statusline_falls_back_to_tokens_when_unmeasured():
    out = _line(34.0, 68_000, 200_000, TurnCost())
    assert "132k left" in out
    assert "turns" not in out


def test_statusline_falls_back_when_turn_cost_absent_entirely():
    out = _line(34.0, 68_000, 200_000, None)
    assert "132k left" in out
