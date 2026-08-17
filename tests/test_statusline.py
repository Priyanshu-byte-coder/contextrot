import re
import time

from contextrot.calibration import Calibration
from contextrot.statusline import (
    DEFAULT_SEGMENTS,
    SEGMENT_NAMES,
    parse_segments,
    render_fill,
    render_statusline,
)

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(s: str) -> str:
    return _ANSI.sub("", s)


def _cal(steps: int = 5000, knee=70.0, verdict="edge") -> Calibration:
    return Calibration(
        knee_pct=knee,
        verdict_kind=verdict,
        low_fill_rate=0.033,
        high_fill_rate=0.048,
        steps=steps,
        days=30,
        computed_at="2026-07-12T00:00:00+00:00",
        buckets=[
            {"lo": 0, "hi": 50, "n": 500, "rate": 0.033},
            {"lo": 50, "hi": 70, "n": 300, "rate": 0.035},
            {"lo": 70, "hi": 100, "n": 400, "rate": 0.048},
        ],
    )


def _payload(used, **extra) -> dict:
    ctx = {"used_percentage": used}
    ctx.update(extra.pop("context_window", {}))
    payload = {"context_window": ctx}
    payload.update(extra)
    return payload


def test_past_knee_marks_and_quotes_personal_rate():
    out = _plain(render_statusline(_payload(72), _cal()))
    assert "72%" in out
    assert "past knee ~70%" in out
    # "slip" is labeled as the historical base rate it is, not as a forecast.
    assert "slip 4.8%" in out
    assert "1.5× fresh" in out


def test_below_knee_shows_knee_quietly():
    out = _plain(render_statusline(_payload(30), _cal()))
    assert "30%" in out
    assert "knee ~70%" in out
    assert "past knee" not in out
    assert "nearing knee" not in out
    # Below the knee the baseline is spelled out rather than a multiplier.
    assert "(fresh 3.3%)" in out


def test_nearing_knee_warns_before_crossing():
    out = _plain(render_statusline(_payload(64), _cal()))
    assert "nearing knee ~70%" in out


# --- no-knee wording: the three cases must not be conflated -----------------


def test_clean_verdict_stays_silent():
    """Silence is the good case: the green bar is the whole message."""
    cal = _cal(steps=20100, knee=None, verdict="clean")
    out = _plain(render_statusline(_payload(34), cal))
    assert out == "ctx 34% ███▍░░░░░░"
    # Neither the old error-sounding phrasing nor its verbose replacement.
    assert "no knee in your data" not in out
    assert "no rot found" not in out
    # A bare slip rate is a number without a question — not on its own.
    assert "slip" not in out


def test_clean_verdict_depth_evidence_lives_on_calibration():
    """Trimmed from the line, but still available to doctor and the API."""
    cal = Calibration(
        knee_pct=None,
        verdict_kind="clean",
        low_fill_rate=0.051,
        high_fill_rate=0.035,
        steps=20100,
        days=30,
        computed_at="2026-08-14T13:00:47+00:00",
        buckets=[
            {"lo": 0, "hi": 10, "n": 3748, "rate": 0.0656},
            {"lo": 70, "hi": 80, "n": 439, "rate": 0.0364},
            {"lo": 80, "hi": 90, "n": 8, "rate": 0.0},  # too thin to count
        ],
    )
    assert cal.deepest_reliable_fill() == 80.0
    assert "80%" not in _plain(render_statusline(_payload(34), cal))


def test_edge_verdict_without_knee_does_not_claim_all_clear():
    cal = _cal(knee=None, verdict="edge")
    out = _plain(render_statusline(_payload(80), cal))
    assert "no rot found" not in out
    assert "deep runs hotter" in out
    # A warning DOES earn the slip rate beside it.
    assert "slip 4.8%" in out


def test_rot_verdict_without_knee_stays_red():
    out = _plain(render_statusline(_payload(80), _cal(knee=None, verdict="rot")))
    assert "rot measured" in out
    assert "no rot found" not in out


def test_insufficient_verdict_says_so():
    out = _plain(render_statusline(_payload(80), _cal(knee=None, verdict="insufficient")))
    assert "need deeper sessions" in out


# --- absolute token accounting ----------------------------------------------


def test_tokens_segment_shows_used_window_and_remaining():
    payload = _payload(
        34,
        context_window={"total_input_tokens": 68_000, "context_window_size": 200_000},
    )
    out = _plain(render_statusline(payload, _cal()))
    assert "68k/200k" in out
    assert "132k left" in out


def test_tokens_segment_handles_million_windows():
    payload = _payload(
        36,
        context_window={"total_input_tokens": 364_193, "context_window_size": 1_000_000},
    )
    out = _plain(render_statusline(payload, _cal()))
    assert "364k/1M" in out
    assert "636k left" in out


def test_tokens_segment_absent_when_unknown():
    out = _plain(render_statusline(_payload(34), _cal()))
    assert "left" not in out


def test_render_fill_accepts_absolute_tokens():
    out = _plain(render_fill(50.0, _cal(), tokens=100_000, window=200_000))
    assert "100k/200k" in out
    assert "100k left" in out


# --- subscription rate limits -----------------------------------------------


def test_plan_limits_render_both_windows_as_meters():
    payload = _payload(
        20,
        rate_limits={
            "five_hour": {"used_percentage": 23.5, "resets_at": 0},
            "seven_day": {"used_percentage": 41.2, "resets_at": 0},
        },
    )
    out = _plain(render_statusline(payload, _cal()))
    # 5 cells: 23.5% = 1.175 cells -> one full + a 1/8 sliver.
    assert "5h █▏░░░ 24%" in out
    # 41.2% = 2.06 cells -> the remainder is under 1/8, so no sliver.
    assert "wk ██░░░ 41%" in out


def test_plan_limits_show_reset_eta_only_when_high():
    soon = time.time() + 3600 + 720  # 1h12m
    payload = _payload(
        20,
        rate_limits={"five_hour": {"used_percentage": 82.0, "resets_at": soon}},
    )
    out = _plain(render_statusline(payload, _cal()))
    assert "82%" in out
    assert "1h12m" in out


def test_plan_limits_absent_for_api_key_users():
    out = _plain(render_statusline(_payload(20), _cal()))
    assert "5h" not in out
    assert "wk" not in out


def test_plan_limits_tolerate_partial_windows():
    payload = _payload(20, rate_limits={"seven_day": {"used_percentage": 41.2}})
    out = _plain(render_statusline(payload, _cal()))
    assert "wk ██░░░ 41%" in out
    assert "5h" not in out


def test_garbage_rate_limits_never_crash():
    for junk in ("nope", 5, [], {"five_hour": "nope"}, {"five_hour": {}}):
        out = _plain(render_statusline(_payload(20, rate_limits=junk), _cal()))
        assert out.startswith("ctx 20%")


# --- segment selection ------------------------------------------------------


def test_parse_segments_is_tolerant_and_order_normalized():
    assert parse_segments(None) == DEFAULT_SEGMENTS
    assert parse_segments("") == DEFAULT_SEGMENTS
    assert parse_segments("   ") == DEFAULT_SEGMENTS
    assert parse_segments("all") == SEGMENT_NAMES
    # Order follows SEGMENT_NAMES, not the user's spelling order.
    assert parse_segments("health,ctx") == ("ctx", "health")
    assert parse_segments(" CTX , Tokens ") == ("ctx", "tokens")
    # A spec of pure junk falls back rather than rendering an empty line.
    assert parse_segments("nonsense,bogus") == DEFAULT_SEGMENTS


def test_cost_segment_is_opt_in():
    payload = _payload(20, cost={"total_cost_usd": 0.1234})
    assert "$0.12" not in _plain(render_statusline(payload, _cal()))
    out = _plain(render_statusline(payload, _cal(), segments=parse_segments("all")))
    assert "$0.12" in out


def test_segments_can_trim_the_line():
    payload = _payload(
        20,
        context_window={"total_input_tokens": 40_000, "context_window_size": 200_000},
    )
    out = _plain(render_statusline(payload, _cal(), segments=parse_segments("ctx")))
    assert out == "ctx 20% ██░░░░░░░░"


# --- degradation paths ------------------------------------------------------


def test_null_used_percentage():
    out = _plain(render_statusline(_payload(None), _cal()))
    assert out.startswith("ctx —")
    assert "knee ~70%" in out


def test_null_used_percentage_calibrated_no_knee():
    out = _plain(render_statusline(_payload(None), _cal(knee=None, verdict="clean")))
    assert out == "ctx —"  # calibrated: no bogus "calibrate" nag


def test_null_used_percentage_still_shows_plan_limits():
    """Right after /compact there is no fill, but the quota still matters."""
    payload = _payload(None, rate_limits={"five_hour": {"used_percentage": 55.0}})
    out = _plain(render_statusline(payload, _cal(knee=None, verdict="clean")))
    assert out.startswith("ctx —")
    # 55% = 2.75 cells -> two full plus a 6/8 sliver.
    assert "5h ██▊░░ 55%" in out


def test_uncalibrated_hint():
    out = _plain(render_statusline(_payload(42), None))
    assert "42%" in out
    assert "run contextrot to calibrate" in out
    # Too few steps counts as uncalibrated too.
    out = _plain(render_statusline(_payload(42), _cal(steps=10)))
    assert "run contextrot to calibrate" in out


def test_never_raises_on_garbage():
    assert render_statusline({}, None).startswith("ctx —")
    # A non-dict context_window loses the fill but not the calibration.
    out = _plain(render_statusline({"context_window": "what"}, _cal()))
    assert out.startswith("ctx —")
    assert "150%" not in render_statusline(_payload(150), _cal())  # clamped
    assert render_statusline({"context_window": {"used_percentage": True}}, None) is not None


def test_bar_is_ten_cells():
    out = _plain(render_statusline(_payload(50), None))
    m = re.search(r"[█░]+", out)
    assert m is not None
    assert len(m.group(0)) == 10


# --- smooth bars ------------------------------------------------------------


def test_bar_width_is_constant_across_every_percent():
    """Any width drift would make the whole line jitter as the number climbs."""
    for pct in range(0, 101):
        out = _plain(render_statusline(_payload(pct), None))
        m = re.search(r"[\u2588\u2589\u258a\u258b\u258c\u258d\u258e\u258f\u2591]+", out)
        assert m is not None, pct
        assert len(m.group(0)) == 10, (pct, m.group(0))


def test_bar_uses_partial_cells_between_whole_ones():
    """Whole-cell-only bars sit still for 10% then lurch; these move at ~1.25%."""
    seen = {_plain(render_statusline(_payload(p), None)) for p in range(30, 40)}
    # 10 distinct percentages inside one cell must give more than one bar.
    assert len(seen) == 10
    thirty_four = _plain(render_statusline(_payload(34), None))
    assert "\u2588\u2588\u2588\u258d" in thirty_four  # 3 full + 3/8


def test_bar_endpoints_are_exact():
    assert "\u2591" * 10 in _plain(render_statusline(_payload(0), None))
    assert "\u2588" * 10 in _plain(render_statusline(_payload(100), None))
    # Clamped, and still exactly ten cells.
    assert "\u2588" * 10 in _plain(render_statusline(_payload(150), None))


def test_stale_reset_timestamp_does_not_invent_urgency():
    """A reset in the past means bad data, not 'resets any second now'."""
    payload = _payload(20, rate_limits={"seven_day": {"used_percentage": 72.5, "resets_at": 0}})
    out = _plain(render_statusline(payload, _cal()))
    assert "72%" in out
    assert "<1m" not in out
