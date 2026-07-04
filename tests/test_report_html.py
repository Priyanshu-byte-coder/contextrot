from pathlib import Path

from contextrot.analysis import AnalysisResult
from contextrot.analysis.by_model import build_model_comparison
from contextrot.analysis.composition import Composition
from contextrot.analysis.rot import build_rot_curve, verdict
from contextrot.report.html import _chart_max_rate, render_html
from contextrot.signals import StepSignals


def _step(fill: float, degraded: bool, model: str = "claude-opus-4-8") -> StepSignals:
    return StepSignals(
        step_index=0,
        prompt_tokens=int(fill * 2000),
        fill_pct=fill,
        model=model,
        tool_error=degraded,
        cost_usd=0.01,
    )


def _result(steps: list[StepSignals]) -> AnalysisResult:
    curve = build_rot_curve(steps)
    kind, text = verdict(curve)
    return AnalysisResult(
        sessions=[],
        steps=steps,
        curve=curve,
        composition=Composition(
            overhead_tokens=30000,
            tool_output_tokens=20000,
            conversation_tokens=8000,
            other_growth_tokens=10000,
            peak_prompt_tokens=90000,
            context_window=200000,
        ),
        prescriptions=[],
        context_window=200000,
        total_cost_usd=10.0,
        rework_cost_usd=1.0,
        steps_past_knee=0,
        days=30,
        verdict_kind=kind,
        verdict_text=text,
        models=build_model_comparison(steps),
    )


def test_chart_max_rate_ignores_low_confidence_buckets():
    # 200 real steps at ~5% + 4 steps whose Wilson CI tops out near 49%.
    steps = [_step(35.0, i % 20 == 0) for i in range(200)]
    steps += [_step(5.0, False) for _ in range(4)]
    curve = build_rot_curve(steps)
    max_rate = _chart_max_rate(curve.buckets)
    # Without the low-confidence exclusion this would be ~0.49 and squash
    # every real bar (regression seen in a real user's report).
    assert max_rate < 0.2


def test_chart_max_rate_all_low_confidence_fallback():
    steps = [_step(35.0, i == 0) for i in range(5)]
    curve = build_rot_curve(steps)
    assert _chart_max_rate(curve.buckets) > 0.0


def _render(result: AnalysisResult, tmp_path: Path) -> str:
    out = render_html(result, tmp_path / "r.html")
    return out.read_text(encoding="utf-8")


def _mixed_steps() -> list[StepSignals]:
    steps = [_step(15.0, i % 20 == 0) for i in range(200)]
    steps += [_step(75.0, i % 4 == 0) for i in range(200)]
    return steps


def test_share_card_present_and_self_contained(tmp_path: Path):
    html = _render(_result(_mixed_steps()), tmp_path)
    assert 'id="share-card"' in html
    assert "Save as PNG" in html
    assert "pip install contextrot" in html
    # Self-containment: no absolute URLs anywhere, including the card SVG
    # (XMLSerializer adds the namespace at runtime; the source must not).
    assert "http://" not in html
    assert 'src="https' not in html and 'href="https' not in html


def test_hero_rot_shows_ratio(tmp_path: Path):
    result = _result(_mixed_steps())
    assert result.verdict_kind == "rot"
    html = _render(result, tmp_path)
    assert "CONTEXT ROT DETECTED" in html
    assert "hero-num" in html


def test_hero_insufficient_shows_steps_needed(tmp_path: Path):
    result = _result([_step(15.0, False) for _ in range(20)])
    assert result.verdict_kind == "insufficient"
    html = _render(result, tmp_path)
    assert "NOT ENOUGH DATA YET" in html
    assert "more steps needed" in html


def test_model_section_present_with_two_models(tmp_path: Path):
    steps = [_step(f, i % 10 == 0, "claude-opus-4-8") for i, f in enumerate([15.0, 75.0] * 100)]
    steps += [_step(f, i % 25 == 0, "claude-sonnet-5") for i, f in enumerate([15.0, 75.0] * 100)]
    html = _render(_result(steps), tmp_path)
    assert "By model" in html
    assert "Opus 4.8" in html and "Sonnet 5" in html


def test_model_section_absent_with_one_model(tmp_path: Path):
    html = _render(_result(_mixed_steps()), tmp_path)
    assert "By model" not in html
