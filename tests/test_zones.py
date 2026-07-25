"""Fresh/deep zone selection.

With a 1M-token window, "deep = over 60% full" means over 600k tokens — which
most agents never reach because they compact first. Fixed zones would then leave
the deep side permanently empty and no verdict ever possible, so the zones fall
back to the user's own fill range. These tests pin both paths.
"""

from __future__ import annotations

from contextrot.analysis.rot import (
    ADAPTIVE_MIN_GAP,
    HIGH_FILL_MIN,
    LOW_FILL_MAX,
    VERDICT_MIN_N,
    build_rot_curve,
    pick_zones,
)
from contextrot.signals import StepSignals


def _steps(fills_and_degraded: list[tuple[float, bool]]) -> list[StepSignals]:
    out = []
    for i, (fill, degraded) in enumerate(fills_and_degraded):
        s = StepSignals(step_index=i, prompt_tokens=int(fill * 10_000), fill_pct=fill, model="m")
        if degraded:
            s.tool_error = True
        out.append(s)
    return out


def test_absolute_zones_when_both_sides_are_populated():
    fills = [5.0] * 200 + [80.0] * 200
    mode, low, high = pick_zones(fills)
    assert mode == "absolute"
    assert (low, high) == (LOW_FILL_MAX, HIGH_FILL_MIN)


def test_adapts_when_the_deep_zone_is_unreachable():
    # A realistic 1M-window distribution: nothing ever passes 60% fill.
    fills = [5.0] * 300 + [12.0] * 300 + [25.0] * 300 + [40.0] * 300
    mode, low, high = pick_zones(fills)
    assert mode == "adaptive"
    assert high - low >= ADAPTIVE_MIN_GAP
    assert high < HIGH_FILL_MIN  # the whole point: below the fixed threshold
    assert sum(1 for f in fills if f <= low) >= VERDICT_MIN_N
    assert sum(1 for f in fills if f >= high) >= VERDICT_MIN_N


def test_stays_absolute_when_fill_barely_varies():
    # Every step at nearly the same fill — there is no contrast to measure, and
    # inventing one would be dishonest.
    fills = [11.0] * 400 + [12.0] * 400
    mode, _low, _high = pick_zones(fills)
    assert mode == "absolute"


def test_stays_absolute_when_there_is_too_little_data():
    fills = [5.0] * 20 + [30.0] * 20
    assert pick_zones(fills)[0] == "absolute"


def test_curve_reports_its_zones_and_yields_a_verdict_when_adaptive():
    # Emptier steps fail more often than fuller ones → a real "clean" signal
    # that fixed zones could never surface for this distribution.
    steps = _steps(
        [(5.0, i % 10 == 0) for i in range(400)]      # 10% at low fill
        + [(30.0, i % 50 == 0) for i in range(400)]   # 2% at high fill
    )
    curve = build_rot_curve(steps)
    assert curve.zone_mode == "adaptive"
    assert curve.low_fill_n >= VERDICT_MIN_N
    assert curve.high_fill_n >= VERDICT_MIN_N
    assert curve.low_fill_rate is not None and curve.high_fill_rate is not None
    assert curve.degradation_ratio is not None and curve.degradation_ratio < 1.0


def test_absolute_curve_keeps_its_documented_boundaries():
    steps = _steps([(10.0, False)] * 200 + [(90.0, True)] * 200)
    curve = build_rot_curve(steps)
    assert curve.zone_mode == "absolute"
    assert curve.low_zone_max == LOW_FILL_MAX
    assert curve.high_zone_min == HIGH_FILL_MIN
    assert curve.low_fill_rate == 0.0
    assert curve.high_fill_rate == 1.0
