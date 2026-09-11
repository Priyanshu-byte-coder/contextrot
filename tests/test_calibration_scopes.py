"""Scoped calibration: a threshold measured on one agent must not be shown on another.

The bug this guards against: calibration used to store a single curve blended
across every agent and model, and every live surface read it. A user whose
OpenCode sessions degraded at 60% fill would see "knee ~60%" while sitting in
Claude Code, whose own curve had no knee at all.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from contextrot.analysis.by_source import build_agent_comparison
from contextrot.analysis.rot import build_rot_curve, verdict
from contextrot.calibration import (
    MIN_CALIBRATED_STEPS,
    Calibration,
    CalibrationSet,
    load_calibration,
    save_calibration,
    scope_key,
)
from contextrot.models import Step, ToolCall
from contextrot.signals import extract_signals
from contextrot.statusline import render_statusline

WINDOW = 200_000
T0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
PER_BUCKET = 40

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(s: str) -> str:
    return _ANSI.sub("", s)


def _session(source: str, model: str, rate_fn, tag: str):
    """A session sweeping 0-99% fill, with failures placed per fill bucket.

    Placing exactly k failures in each bucket (rather than every Nth step)
    keeps the failure pattern from aliasing against the fill sweep and
    manufacturing a knee that isn't there.
    """
    from contextrot.models import Session

    steps, n = [], 0
    for b in range(100):
        fill = b + 0.5
        prompt = int(fill / 100.0 * WINDOW)
        n_fail = int(round(PER_BUCKET * rate_fn(fill)))
        for j in range(PER_BUCKET):
            uid = f"{tag}{b}_{j}"
            steps.append(
                Step(
                    timestamp=T0 + timedelta(minutes=n),
                    model=model,
                    input_tokens=prompt,
                    output_tokens=50,
                    tool_calls=[
                        ToolCall(
                            name="Read",
                            tool_use_id=f"t{uid}",
                            # Globally unique target: no accidental re-read signal.
                            target=f"/repo/f_{uid}.py",
                            is_error=j < n_fail,
                            error_text="ENOENT" if j < n_fail else "",
                        )
                    ],
                )
            )
            n += 1
    return Session(session_id=f"{source}-1", source=source, project="/repo", steps=steps)


def _mixed_history():
    """OpenCode degrading hard above 60% fill; Claude Code flat everywhere."""
    oc = _session("opencode", "claude-sonnet-4-6", lambda f: 0.20 if f >= 60 else 0.02, "oc")
    cc = _session("claude-code", "claude-opus-4-8", lambda f: 0.03, "cc")
    steps = []
    for s in (oc, cc):
        steps.extend(extract_signals(s, WINDOW).steps)
    return steps


def _curve_of(steps) -> Calibration:
    curve = build_rot_curve(steps)
    kind, _ = verdict(curve)
    return curve, kind


def test_the_two_agents_really_do_differ():
    """Guards the fixture itself: without this the regression test proves nothing."""
    steps = _mixed_history()
    agents = {a.key: a for a in build_agent_comparison(steps, require_two=False)}
    assert agents["opencode"].curve.knee_pct is not None
    assert agents["claude-code"].curve.knee_pct is None
    # And the blend has a knee, which is exactly the number that used to leak.
    blended, _ = _curve_of(steps)
    assert blended.knee_pct is not None


def _saved_set(tmp_path: Path) -> CalibrationSet:
    """Run the real save/load path over the mixed history."""
    from contextrot.analysis import AnalysisResult
    from contextrot.analysis.by_model import build_model_comparison
    from contextrot.analysis.by_project import build_project_comparison

    steps = _mixed_history()
    curve, kind = _curve_of(steps)
    result = AnalysisResult(
        sessions=[],
        steps=steps,
        curve=curve,
        reversal_curve=build_rot_curve([]),
        composition=None,
        prescriptions=[],
        context_window=WINDOW,
        total_cost_usd=0.0,
        rework_cost_usd=0.0,
        steps_past_knee=0,
        days=30,
        skipped_sessions=0,
        signal_rates={},
        verdict_kind=kind,
        verdict_text="",
        models=build_model_comparison(steps),
        projects=build_project_comparison(steps),
        agents=build_agent_comparison(steps, require_two=False),
    )
    target = tmp_path / "calibration.json"
    assert save_calibration(result, target) == target
    loaded = load_calibration(target)
    assert loaded is not None
    return loaded


def test_claude_code_never_inherits_opencodes_knee(tmp_path: Path):
    """The reported bug, end to end."""
    cal_set = _saved_set(tmp_path)

    cc = cal_set.resolve(agent="claude-code", model="claude-opus-4-8")
    oc = cal_set.resolve(agent="opencode", model="claude-sonnet-4-6")

    assert cc.knee_pct is None, "Claude Code has no knee of its own"
    assert oc.knee_pct is not None, "OpenCode does"
    assert cc.scope_kind in ("agent+model", "model", "agent")
    assert not cc.is_fallback

    # And it must not reach the rendered line either.
    line = _plain(render_statusline({"context_window": {"used_percentage": 80}}, cc))
    assert "threshold" not in line
    assert "60%" not in line


def test_scopes_are_stored_for_each_axis(tmp_path: Path):
    cal_set = _saved_set(tmp_path)
    assert scope_key("agent", agent="opencode") in cal_set.scopes
    assert scope_key("model", model_key="sonnet-4.6") in cal_set.scopes
    assert scope_key("agent+model", "claude-code", "opus-4.8") in cal_set.scopes
    # The blend is still kept, as the last resort.
    assert cal_set.global_curve.knee_pct is not None


def test_resolution_prefers_the_narrowest_trustworthy_scope():
    """agent+model wins; thin scopes fall through instead of quoting noise."""

    def curve(knee, steps, kind):
        return Calibration(
            knee_pct=knee,
            verdict_kind="edge",
            low_fill_rate=0.03,
            high_fill_rate=0.06,
            steps=steps,
            scope_kind=kind,
            scope_label=kind,
        )

    cal_set = CalibrationSet(
        computed_at="",
        days=30,
        global_curve=curve(10.0, 9999, "global"),
        scopes={
            scope_key("agent+model", "claude-code", "opus-4.8"): curve(40.0, 5000, "agent+model"),
            scope_key("model", model_key="opus-4.8"): curve(50.0, 5000, "model"),
            scope_key("agent", agent="claude-code"): curve(60.0, 5000, "agent"),
        },
    )
    assert cal_set.resolve("claude-code", "claude-opus-4-8").knee_pct == 40.0

    # Drop the pair -> model answers.
    del cal_set.scopes[scope_key("agent+model", "claude-code", "opus-4.8")]
    assert cal_set.resolve("claude-code", "claude-opus-4-8").knee_pct == 50.0

    # Drop the model -> agent answers.
    del cal_set.scopes[scope_key("model", model_key="opus-4.8")]
    assert cal_set.resolve("claude-code", "claude-opus-4-8").knee_pct == 60.0

    # An unknown model with no agent match -> global, flagged as borrowed.
    got = cal_set.resolve("some-other-agent", "some-other-model")
    assert got.knee_pct == 10.0
    assert got.is_fallback


def test_thin_scope_is_skipped_rather_than_quoted():
    """A scope below the trust floor must not answer, even though it exists."""
    thin = Calibration(
        knee_pct=99.0,
        verdict_kind="edge",
        low_fill_rate=0.03,
        high_fill_rate=0.06,
        steps=MIN_CALIBRATED_STEPS - 1,
        scope_kind="agent+model",
    )
    fat = Calibration(
        knee_pct=55.0,
        verdict_kind="edge",
        low_fill_rate=0.03,
        high_fill_rate=0.06,
        steps=MIN_CALIBRATED_STEPS,
        scope_kind="model",
    )
    cal_set = CalibrationSet(
        computed_at="",
        days=30,
        global_curve=Calibration(None, "clean", 0.0, 0.0, 9999),
        scopes={
            scope_key("agent+model", "claude-code", "opus-4.8"): thin,
            scope_key("model", model_key="opus-4.8"): fat,
        },
    )
    assert cal_set.resolve("claude-code", "claude-opus-4-8").knee_pct == 55.0


def test_single_agent_history_is_not_flagged_as_borrowed():
    """With nothing narrower to offer, the global curve IS your curve."""
    cal_set = CalibrationSet(
        computed_at="",
        days=30,
        global_curve=Calibration(70.0, "edge", 0.03, 0.06, 5000),
        scopes={},
    )
    got = cal_set.resolve("claude-code", "claude-opus-4-8")
    assert got.knee_pct == 70.0
    assert not got.is_fallback
    assert "all agents" not in _plain(
        render_statusline({"context_window": {"used_percentage": 75}}, got)
    )


def test_borrowed_threshold_is_marked_in_the_line():
    cal_set = CalibrationSet(
        computed_at="",
        days=30,
        global_curve=Calibration(70.0, "edge", 0.03, 0.06, 5000, blended_axis="both"),
        scopes={scope_key("agent", agent="opencode"): Calibration(60.0, "rot", 0.02, 0.2, 5000)},
    )
    got = cal_set.resolve("gemini-cli", "gemini-3-pro")
    assert got.is_fallback
    line = _plain(render_statusline({"context_window": {"used_percentage": 75}}, got))
    assert "past threshold ~70%" in line
    assert "(all agents)" in line


def test_resolve_never_mutates_the_shared_global_curve():
    cal_set = CalibrationSet(
        computed_at="",
        days=30,
        global_curve=Calibration(70.0, "edge", 0.03, 0.06, 5000, blended_axis="both"),
        scopes={scope_key("agent", agent="opencode"): Calibration(60.0, "rot", 0.02, 0.2, 5000)},
    )
    assert cal_set.resolve("gemini-cli", "gemini-3-pro").is_fallback
    assert not cal_set.global_curve.is_fallback
