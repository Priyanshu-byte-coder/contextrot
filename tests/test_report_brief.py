"""The short report: answers the question, then stops.

The contract worth protecting is editorial, not cosmetic — every line has to
change what the reader does next. These tests pin the things that would
quietly turn it back into the full report: statistical apparatus leaking in,
an unbounded list of actions, or a number quoted from data too thin to carry
it.
"""

from __future__ import annotations

import io

from rich.console import Console

from contextrot.analysis import AnalysisResult
from contextrot.analysis.prescriptions import Prescription
from contextrot.analysis.rot import Bucket, RotCurve
from contextrot.report.brief import MAX_ACTIONS, render


def _curve(
    low=0.03,
    high=0.09,
    knee=None,
    ratio=3.0,
    total=5000,
    buckets=None,
) -> RotCurve:
    return RotCurve(
        buckets=buckets if buckets is not None else [],
        total_steps=total,
        total_degraded=int(total * high),
        low_fill_rate=low,
        high_fill_rate=high,
        low_fill_n=2000,
        high_fill_n=2000,
        degradation_ratio=ratio,
        ratio_significant=True,
        knee_pct=knee,
    )


def _result(kind="rot", curve=None, prescriptions=None, total_cost=100.0, rework=9.0):
    return AnalysisResult(
        sessions=[],
        steps=[],
        curve=curve if curve is not None else _curve(),
        reversal_curve=None,
        composition=None,
        prescriptions=prescriptions if prescriptions is not None else [],
        context_window=200_000,
        total_cost_usd=total_cost,
        rework_cost_usd=rework,
        steps_past_knee=0,
        days=30,
        verdict_kind=kind,
        verdict_text="text",
    )


def _out(result) -> str:
    buf = io.StringIO()
    render(result, Console(file=buf, width=100, no_color=True, legacy_windows=False))
    return buf.getvalue()


def test_rot_states_the_finding_and_the_threshold():
    out = _out(_result("rot", _curve(low=0.031, high=0.084, knee=55.0, ratio=2.7)))
    assert "CONTEXT ROT DETECTED" in out
    assert "8.4%" in out and "3.1%" in out
    assert "2.7× worse" in out
    assert "~55% full" in out


def test_clean_says_fill_is_not_the_problem():
    out = _out(_result("clean", _curve(low=0.040, high=0.033, ratio=0.8)))
    assert "NO MEASURABLE ROT" in out
    assert "not what's hurting your output" in out
    assert "your setup is holding up" in out


def test_insufficient_says_what_is_missing():
    out = _out(_result("insufficient", _curve()))
    assert "NOT ENOUGH DATA YET" in out
    assert "isn't enough data" in out


# --- what must NOT leak in from the full report ----------------------------


def test_no_statistical_apparatus():
    """CIs, per-bucket counts and the snowball table live in --full."""
    import re

    out = _out(_result("rot", _curve(low=0.031, high=0.084, knee=55.0))).lower()
    # Whole words: a substring check would flag "ci" inside "specific".
    for jargon in ("confidence", "ci", "wilson", "snowball", "reversal", "bucket", "interval"):
        assert not re.search(rf"{jargon}", out), jargon


def test_actions_are_capped():
    """A list of eight things to try is a backlog, not advice."""
    many = [
        Prescription(title=f"Fix number {i}", detail="d", impact=f"impact {i}", priority=i)
        for i in range(8)
    ]
    out = _out(_result("rot", prescriptions=many))
    assert out.count("→") == MAX_ACTIONS
    assert "Fix number 0" in out
    assert "Fix number 7" not in out


def test_actions_come_in_priority_order():
    """Lowest priority number first, and the overflow is dropped, not shuffled."""
    out = _out(
        _result(
            "rot",
            prescriptions=[
                Prescription(title="Least urgent", detail="d", impact="i", priority=9),
                Prescription(title="Middle", detail="d", impact="i", priority=5),
                Prescription(title="Most urgent", detail="d", impact="i", priority=1),
            ],
        )
    )
    assert out.index("Most urgent") < out.index("Middle")
    # Three offered, MAX_ACTIONS shown: the least urgent is the one dropped.
    assert "Least urgent" not in out


# --- honesty about thin data -----------------------------------------------


def test_waste_share_is_hidden_without_a_verdict():
    """A cost share off a handful of steps is confident noise."""
    out = _out(_result("insufficient", total_cost=100.0, rework=76.0))
    assert "76" not in out
    assert "token spend" not in out


def test_waste_share_shown_once_there_is_a_verdict():
    out = _out(_result("rot", total_cost=100.0, rework=9.0))
    assert "9.0%" in out
    assert "token spend" in out


def test_waste_share_absent_when_cost_is_unknown():
    out = _out(_result("rot", total_cost=0.0, rework=0.0))
    assert "token spend" not in out


def test_depth_caveat_quotes_only_buckets_with_enough_steps():
    """Flat because fill is harmless != flat because you never fill it."""
    curve = _curve(
        low=0.04,
        high=0.033,
        ratio=0.8,
        buckets=[
            Bucket(lo=0, hi=10, n=3000, degraded=120),
            Bucket(lo=70, hi=80, n=400, degraded=13),
            # Too thin to count as "measured".
            Bucket(lo=80, hi=90, n=8, degraded=0),
        ],
    )
    out = _out(_result("clean", curve))
    assert "up to 80% full" in out
    assert "90% full" not in out


def test_points_at_the_full_report():
    out = _out(_result("clean"))
    assert "contextrot --full" in out


def test_stays_short():
    """The whole point. If this grows, the split has failed."""
    out = _out(_result("rot", _curve(low=0.031, high=0.084, knee=55.0)))
    assert len([ln for ln in out.splitlines() if ln.strip()]) <= 12
