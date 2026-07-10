"""Tests for the per-agent comparison."""

from __future__ import annotations

from contextrot.analysis.by_source import agent_label, build_agent_comparison
from contextrot.signals import StepSignals


def _step(i: int, fill: float, source: str, *, error: bool = False) -> StepSignals:
    return StepSignals(
        step_index=i,
        prompt_tokens=int(fill * 2000),
        fill_pct=fill,
        model="claude-sonnet-4-6",
        source=source,
        tool_error=error,
    )


def _rotting(source: str, n: int = 200) -> list[StepSignals]:
    # Clean when fresh, failing when deep.
    steps = []
    for i in range(n):
        fill = (i / n) * 100
        steps.append(_step(i, fill, source, error=fill > 60 and i % 2 == 0))
    return steps


def _clean(source: str, n: int = 200) -> list[StepSignals]:
    return [_step(i, (i / n) * 100, source) for i in range(n)]


def test_agent_label() -> None:
    assert agent_label("claude-code") == "Claude Code"
    assert agent_label("codex") == "Codex CLI"
    assert agent_label("qwen-code") == "Qwen Code"
    assert agent_label("something-new") == "something-new"
    assert agent_label("") == "unknown"


def test_two_agents_plus_other() -> None:
    steps = _rotting("claude-code") + _clean("codex") + _clean("gemini-cli", n=10)
    stats = build_agent_comparison(steps)
    assert [a.key for a in stats] == ["claude-code", "codex", "other"]
    assert stats[0].label == "Claude Code"
    assert not stats[0].is_other and not stats[1].is_other
    assert stats[2].is_other
    assert stats[2].steps == 10
    # The rotting agent shows a worse deep rate than the clean one.
    assert (stats[0].curve.high_fill_rate or 0) > (stats[1].curve.high_fill_rate or 0)


def test_single_agent_returns_empty_by_default() -> None:
    assert build_agent_comparison(_rotting("claude-code")) == []


def test_single_agent_with_require_two_false() -> None:
    stats = build_agent_comparison(_rotting("claude-code"), require_two=False)
    assert len(stats) == 1
    assert stats[0].key == "claude-code"


def test_two_tiny_agents_return_empty() -> None:
    steps = _clean("claude-code", n=20) + _clean("codex", n=20)
    assert build_agent_comparison(steps) == []
