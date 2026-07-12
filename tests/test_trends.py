from datetime import datetime, timedelta, timezone

from contextrot.analysis.trends import MIN_WEEK_STEPS, build_trend, trend_verdict
from contextrot.signals import StepSignals


def _week_steps(monday: datetime, n: int, fail_every: int, start_index: int = 0):
    """n steps in the given week; every fail_every-th step is a tool error."""
    out = []
    for i in range(n):
        out.append(
            StepSignals(
                step_index=start_index + i,
                prompt_tokens=50_000,
                fill_pct=25.0,
                model="claude-opus-4-8",
                timestamp=monday + timedelta(hours=i % 100),
                tool_error=(i % fail_every == 0),
            )
        )
    return out


_MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday


def test_build_trend_groups_by_week():
    steps = _week_steps(_MONDAY, 100, 10) + _week_steps(_MONDAY + timedelta(days=7), 200, 5)
    trend = build_trend(steps)
    assert len(trend) == 2
    assert trend[0].steps == 100
    assert trend[0].rate == 0.10
    assert trend[1].steps == 200
    assert trend[1].rate == 0.20
    assert trend[0].week_start < trend[1].week_start


def test_build_trend_skips_untimestamped_and_limits_weeks():
    steps = [
        StepSignals(step_index=0, prompt_tokens=1, fill_pct=1.0, model="m", timestamp=None)
    ]
    for k in range(12):
        steps += _week_steps(_MONDAY + timedelta(days=7 * k), 40, 40)
    trend = build_trend(steps, weeks=8)
    assert len(trend) == 8  # capped, untimestamped step dropped


def test_startup_tokens_from_first_steps():
    monday = _MONDAY
    steps = _week_steps(monday, 50, 50)
    # step_index 0 exists once with prompt_tokens 50k.
    trend = build_trend(steps)
    assert trend[0].startup_tokens == 50_000


def test_verdict_improving():
    steps = _week_steps(_MONDAY, 400, 5)  # 20%
    steps += _week_steps(_MONDAY + timedelta(days=7), 400, 50, start_index=1)  # 2%
    kind, text = trend_verdict(build_trend(steps))
    assert kind == "improving"
    assert "clears statistical noise" in text


def test_verdict_worsening():
    steps = _week_steps(_MONDAY, 400, 50, start_index=1)  # 2%
    steps += _week_steps(_MONDAY + timedelta(days=7), 400, 5)  # 20%
    kind, _ = trend_verdict(build_trend(steps))
    assert kind == "worsening"


def test_verdict_flat_when_noise():
    steps = _week_steps(_MONDAY, 200, 10)
    steps += _week_steps(_MONDAY + timedelta(days=7), 200, 11, start_index=1)
    kind, text = trend_verdict(build_trend(steps))
    assert kind == "flat"
    assert "within statistical noise" in text


def test_verdict_insufficient():
    kind, _ = trend_verdict(build_trend(_week_steps(_MONDAY, MIN_WEEK_STEPS - 1, 5)))
    assert kind == "insufficient"
    kind, _ = trend_verdict(build_trend(_week_steps(_MONDAY, 400, 5)))  # one solid week
    assert kind == "insufficient"
