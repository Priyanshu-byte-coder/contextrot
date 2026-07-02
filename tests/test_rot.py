from contextrot.analysis.rot import build_rot_curve, verdict, wilson_interval
from contextrot.signals import StepSignals


def _step(fill: float, degraded: bool) -> StepSignals:
    return StepSignals(
        step_index=0,
        prompt_tokens=int(fill * 2000),
        fill_pct=fill,
        model="claude-sonnet-4-6",
        tool_error=degraded,
    )


def test_wilson_interval_bounds():
    lo, hi = wilson_interval(5, 10)
    assert 0.2 < lo < 0.5 < hi < 0.9
    assert wilson_interval(0, 0) == (0.0, 1.0)
    lo0, _ = wilson_interval(0, 50)
    assert lo0 == 0.0


def test_curve_detects_degradation():
    # 100 fresh steps at 5% failure, 100 deep steps at 40% failure.
    steps = [_step(15.0, i % 20 == 0) for i in range(100)]
    steps += [_step(75.0, i % 5 < 2) for i in range(100)]
    curve = build_rot_curve(steps)

    assert curve.total_steps == 200
    assert curve.low_fill_rate == 0.05
    assert curve.high_fill_rate == 0.40
    assert curve.degradation_ratio == 8.0
    assert curve.ratio_significant
    assert curve.knee_pct == 70


def test_no_knee_when_flat():
    steps = [_step(f, i % 10 == 0) for i, f in enumerate([15.0, 75.0] * 100)]
    curve = build_rot_curve(steps)
    assert curve.knee_pct is None


def test_small_buckets_marked_low_confidence():
    steps = [_step(95.0, True) for _ in range(3)]
    curve = build_rot_curve(steps)
    bucket = curve.buckets[-1]
    assert bucket.n == 3
    assert bucket.low_confidence


def test_verdict_rot():
    steps = [_step(15.0, i % 20 == 0) for i in range(200)]
    steps += [_step(75.0, i % 5 < 2) for i in range(200)]
    kind, text = verdict(build_rot_curve(steps))
    assert kind == "rot"
    assert "8.0×" in text


def test_verdict_clean_on_flat_curve():
    steps = [_step(f, i % 10 == 0) for i, f in enumerate([15.0, 75.0] * 200)]
    kind, text = verdict(build_rot_curve(steps))
    assert kind == "clean"


def test_verdict_edge_when_only_extreme_fill_degrades():
    # Flat 5% failure everywhere except 90-100% fill, where it's 40%.
    steps = [_step(f, i % 20 == 0) for i, f in enumerate([15.0, 75.0] * 200)]
    steps += [_step(95.0, i % 5 < 2) for i in range(100)]
    curve = build_rot_curve(steps)
    kind, text = verdict(curve)
    assert kind == "edge"
    assert "~90%" in text


def test_verdict_insufficient_on_small_sample():
    steps = [_step(15.0, False) for _ in range(10)] + [_step(75.0, True) for _ in range(10)]
    kind, _ = verdict(build_rot_curve(steps))
    assert kind == "insufficient"


def test_empty_input():
    curve = build_rot_curve([])
    assert curve.total_steps == 0
    assert curve.degradation_ratio is None
    assert curve.knee_pct is None
