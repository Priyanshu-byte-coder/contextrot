"""What-moves-your-failure-rate: grouping, the two comparison modes, honesty."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from contextrot.analysis.factors import (
    FACTOR_MIN_N,
    STRENGTHS,
    Factor,
    FactorGroup,
    build_factors,
    factor_dict,
    strongest,
)
from contextrot.signals import StepSignals


def _steps(n: int, fail_every: int | None, **kw) -> list[StepSignals]:
    """``n`` steps failing once every ``fail_every`` (None = never)."""
    out = []
    for i in range(n):
        st = StepSignals(
            step_index=i,
            prompt_tokens=1000,
            fill_pct=kw.get("fill", 10.0),
            model=kw.get("model", "claude-opus-5"),
            source=kw.get("source", "claude-code"),
            timestamp=kw.get("timestamp"),
            reversals_so_far=kw.get("reversals", 0),
            steps_since_prompt=kw.get("since", 1),
        )
        st.tool_error = fail_every is not None and i % fail_every == 0
        out.append(st)
    return out


def _by_key(factors: list[Factor]) -> dict[str, Factor]:
    return {f.key: f for f in factors}


def _local(hour: int) -> datetime:
    """A timestamp that reads as ``hour`` on the local clock the analysis uses."""
    return datetime(2026, 9, 1, hour, 30).astimezone().astimezone(timezone.utc)


# --- groups ------------------------------------------------------------------


def test_group_rate_and_eligibility() -> None:
    g = FactorGroup(label="x", phrase="in x", n=FACTOR_MIN_N, failures=FACTOR_MIN_N // 10)
    assert g.rate == pytest.approx(0.1, abs=0.01)
    assert g.eligible
    assert not FactorGroup(label="y", phrase="in y", n=FACTOR_MIN_N - 1).eligible


def test_empty_group_has_zero_rate() -> None:
    assert FactorGroup(label="z", phrase="in z").rate == 0.0


# --- strength ----------------------------------------------------------------


def test_a_large_separated_gap_is_clear() -> None:
    night = _steps(600, 5, timestamp=_local(2))  # 20%
    morning = _steps(600, 50, timestamp=_local(9))  # 2%
    f = _by_key(build_factors(night + morning))["time_of_day"]
    assert f.strength == "clear"
    assert f.worst is not None and f.worst.label == "night"
    assert f.best is not None and f.best.label == "morning"
    assert "night" in f.finding and f.action


def test_identical_groups_are_no_effect() -> None:
    a = _steps(400, 20, timestamp=_local(2))
    b = _steps(400, 20, timestamp=_local(9))
    f = _by_key(build_factors(a + b))["time_of_day"]
    assert f.strength == "none"
    assert not f.action, "no effect must not come with advice"


def test_one_group_is_insufficient() -> None:
    f = _by_key(build_factors(_steps(400, 10, timestamp=_local(9))))["time_of_day"]
    assert f.strength == "insufficient"
    assert f.worst is None and f.best is None


def test_small_groups_do_not_take_part() -> None:
    """A tiny group with an extreme rate must not become 'the worst'."""
    big = _steps(500, 40, timestamp=_local(9))
    tiny = _steps(20, 1, timestamp=_local(2))  # 100% but n=20
    f = _by_key(build_factors(big + tiny))["time_of_day"]
    assert f.strength == "insufficient"


# --- ordinal axes compare their ends ------------------------------------------


def test_ordinal_axis_ignores_a_bump_in_the_middle() -> None:
    """The bug this design exists to avoid: noise in a middle bucket read as a trend."""
    low = _steps(400, 25, reversals=0)  # 4%
    bump = _steps(400, 8, reversals=2)  # 12.5% — a middle bucket
    high = _steps(400, 25, reversals=7)  # 4%, back to baseline
    f = _by_key(build_factors(low + bump + high))["mistakes"]
    assert f.ordinal
    assert f.strength == "none"


def test_ordinal_axis_finds_a_real_rise() -> None:
    low = _steps(500, 50, reversals=0)  # 2%
    high = _steps(500, 5, reversals=7)  # 20%
    f = _by_key(build_factors(low + high))["mistakes"]
    assert f.strength == "clear"
    assert "fresh session" in f.action


def test_a_falling_ordinal_axis_gets_the_reverse_advice() -> None:
    """Fill that *helps* must not be told to compact."""
    fresh = _steps(500, 5, fill=10.0)  # 20%
    deep = _steps(500, 50, fill=90.0)  # 2%
    f = _by_key(build_factors(fresh + deep))["context_fill"]
    assert f.strength == "clear"
    assert "isn't what hurts you" in f.action


# --- axis-specific rules -------------------------------------------------------


def test_autonomy_excludes_the_first_step_after_a_prompt() -> None:
    """Step 0 can't be a retry, so it would fake an autonomy effect."""
    first = _steps(800, None, since=0)
    later = _steps(800, 10, since=5)
    f = _by_key(build_factors(first + later))["autonomy"]
    assert all(g.label != "0" for g in f.groups)


def test_autonomy_skips_sessions_without_turn_markers() -> None:
    f = _by_key(build_factors(_steps(500, 10, since=None)))["autonomy"]
    assert f.groups == []


def test_steps_without_timestamps_have_no_hour() -> None:
    f = _by_key(build_factors(_steps(500, 10, timestamp=None)))["time_of_day"]
    assert f.groups == []


def test_unknown_models_are_not_compared() -> None:
    f = _by_key(build_factors(_steps(500, 10, model="")))["model"]
    assert f.groups == []


# --- ranking and output --------------------------------------------------------


def test_factors_are_ranked_by_strength_then_gap() -> None:
    night = _steps(600, 5, timestamp=_local(2))
    morning = _steps(600, 50, timestamp=_local(9))
    ranked = build_factors(night + morning)
    order = [STRENGTHS.index(f.strength) for f in ranked]
    assert order == sorted(order)


def test_strongest_respects_exclusions() -> None:
    fresh = _steps(500, 5, fill=10.0, timestamp=_local(9))
    deep = _steps(500, 50, fill=90.0, timestamp=_local(9))
    factors = build_factors(fresh + deep)
    assert strongest(factors) is not None
    top = strongest(factors, exclude=("context_fill",))
    assert top is None or top.key != "context_fill"


def test_factor_dict_is_plain_json() -> None:
    import json

    night = _steps(600, 5, timestamp=_local(2))
    morning = _steps(600, 50, timestamp=_local(9))
    for f in build_factors(night + morning):
        json.dumps(factor_dict(f))  # must not raise


def test_every_axis_is_always_reported() -> None:
    """An axis with nothing to say is still an answer — it must not vanish."""
    keys = {f.key for f in build_factors(_steps(10, None))}
    assert keys == {"mistakes", "time_of_day", "autonomy", "model", "agent", "context_fill"}
