from pathlib import Path

from contextrot.analysis import analyze
from contextrot.report.badge import badge_value, render_badge

FIXTURES = Path(__file__).parent / "fixtures"


class _Curve:
    def __init__(self, knee=None, ratio=None):
        self.knee_pct = knee
        self.degradation_ratio = ratio


class _Result:
    def __init__(self, kind, knee=None, ratio=None):
        self.verdict_kind = kind
        self.curve = _Curve(knee, ratio)


def test_badge_value_per_verdict():
    assert badge_value(_Result("clean")) == ("clean ✓", "#2da44e")
    text, color = badge_value(_Result("edge", knee=70))
    assert text == "edge · knee ~70%"
    assert color == "#d4a72c"
    text, color = badge_value(_Result("rot", ratio=3.24))
    assert text == "rot ✗ 3.2×"
    assert color == "#cf222e"
    assert badge_value(_Result("rot", ratio=float("inf")))[0] == "rot ✗"
    assert badge_value(_Result("insufficient"))[0] == "not enough data"


def test_render_badge_is_standalone_svg():
    result = analyze(data_dir=FIXTURES, days=None)
    svg = render_badge(result)
    assert svg.startswith("<svg")
    assert "context rot" in svg
    # Local-only: no external fetches beyond the SVG namespace declaration.
    assert "http" not in svg.replace("http://www.w3.org/2000/svg", "")
    # The value text made it in.
    value, _ = badge_value(result)
    assert value in svg
