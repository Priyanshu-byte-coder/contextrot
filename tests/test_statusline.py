import re

from contextrot.calibration import Calibration
from contextrot.statusline import render_statusline

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(s: str) -> str:
    return _ANSI.sub("", s)


def _cal(steps: int = 5000, knee=70.0) -> Calibration:
    return Calibration(
        knee_pct=knee,
        verdict_kind="edge",
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


def _payload(used) -> dict:
    return {"context_window": {"used_percentage": used}}


def test_past_knee_marks_and_quotes_personal_rate():
    out = _plain(render_statusline(_payload(72), _cal()))
    assert "72%" in out
    assert "past your knee (~70%)" in out
    assert "fail here 4.8%" in out
    assert "× fresh" in out


def test_below_knee_shows_knee_quietly():
    out = _plain(render_statusline(_payload(30), _cal()))
    assert "30%" in out
    assert "knee ~70%" in out
    assert "past your knee" not in out


def test_no_knee_in_calibration():
    out = _plain(render_statusline(_payload(80), _cal(knee=None)))
    assert "no knee in your data" in out


def test_null_used_percentage():
    out = _plain(render_statusline(_payload(None), _cal()))
    assert out.startswith("ctx —")
    assert "knee ~70%" in out


def test_null_used_percentage_calibrated_no_knee():
    out = _plain(render_statusline(_payload(None), _cal(knee=None)))
    assert out == "ctx —"  # calibrated: no bogus "calibrate" nag


def test_uncalibrated_hint():
    out = _plain(render_statusline(_payload(42), None))
    assert "42%" in out
    assert "run contextrot to calibrate" in out
    # Too few steps counts as uncalibrated too.
    out = _plain(render_statusline(_payload(42), _cal(steps=10)))
    assert "run contextrot to calibrate" in out


def test_never_raises_on_garbage():
    assert render_statusline({}, None).startswith("ctx —")
    assert render_statusline({"context_window": "what"}, _cal()) == "ctx —"
    assert "150%" not in render_statusline(_payload(150), _cal())  # clamped


def test_bar_is_ten_cells():
    out = _plain(render_statusline(_payload(50), None))
    m = re.search(r"[█░]+", out)
    assert m is not None
    assert len(m.group(0)) == 10
