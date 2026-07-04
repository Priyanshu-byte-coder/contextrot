import pytest

from contextrot.analysis.by_model import (
    build_model_comparison,
    model_family,
    model_label,
)
from contextrot.analysis.rot import build_rot_curve, verdict
from contextrot.signals import StepSignals


@pytest.mark.parametrize(
    ("model_id", "family"),
    [
        ("claude-opus-4-8", "opus-4.8"),
        ("claude-sonnet-5", "sonnet-5"),
        ("claude-sonnet-4-6", "sonnet-4.6"),
        ("claude-3-5-sonnet-20241022", "sonnet-3.5"),
        ("claude-3-opus-20240229", "opus-3"),
        ("us.anthropic.claude-sonnet-4-6-v1:0", "sonnet-4.6"),
        ("claude-haiku-4-5-20251001", "haiku-4.5"),
        ("claude-sonnet-4-5-latest", "sonnet-4.5"),
        ("CLAUDE-OPUS-4-8", "opus-4.8"),
        ("", "unknown"),
        ("gpt-4o", "unknown"),
    ],
)
def test_model_family(model_id: str, family: str):
    assert model_family(model_id) == family


def test_model_label():
    assert model_label("opus-4.8") == "Opus 4.8"
    assert model_label("sonnet-5") == "Sonnet 5"
    assert model_label("unknown") == "Unknown"


def _step(fill: float, degraded: bool, model: str) -> StepSignals:
    return StepSignals(
        step_index=0,
        prompt_tokens=int(fill * 2000),
        fill_pct=fill,
        model=model,
        tool_error=degraded,
    )


def _steps_for(model: str, n: int, deep_fail: bool) -> list[StepSignals]:
    """Half fresh (2% fail), half deep (30% fail if deep_fail else 2%)."""
    steps = [_step(15.0, i % 50 == 0, model) for i in range(n // 2)]
    deep_rate = 3 if deep_fail else 50  # every 3rd vs every 50th step fails
    steps += [_step(75.0, i % deep_rate == 0, model) for i in range(n // 2)]
    return steps


def test_comparison_two_models_plus_other():
    steps = (
        _steps_for("claude-opus-4-8", 400, deep_fail=True)
        + _steps_for("claude-sonnet-5", 400, deep_fail=False)
        + _steps_for("claude-haiku-4-5", 10, deep_fail=False)
    )
    models = build_model_comparison(steps)

    assert [m.family for m in models] == ["opus-4.8", "sonnet-5", "other"]
    opus, sonnet, other = models
    assert opus.steps == 400 and not opus.is_other
    assert other.is_other and other.steps == 10 and other.verdict_kind == "insufficient"
    # The rotting model shows a higher ratio than the clean one.
    assert (opus.curve.degradation_ratio or 0) > (sonnet.curve.degradation_ratio or 0)


def test_comparison_reuses_verdict_logic():
    group = _steps_for("claude-opus-4-8", 400, deep_fail=True)
    steps = group + _steps_for("claude-sonnet-5", 400, deep_fail=False)
    models = build_model_comparison(steps)
    expected_kind, expected_text = verdict(build_rot_curve(group))
    assert models[0].verdict_kind == expected_kind
    assert models[0].verdict_text == expected_text


def test_single_model_returns_empty():
    steps = _steps_for("claude-opus-4-8", 400, deep_fail=True)
    assert build_model_comparison(steps) == []


def test_two_tiny_models_return_empty():
    steps = _steps_for("claude-opus-4-8", 20, deep_fail=True) + _steps_for(
        "claude-sonnet-5", 20, deep_fail=False
    )
    assert build_model_comparison(steps) == []
