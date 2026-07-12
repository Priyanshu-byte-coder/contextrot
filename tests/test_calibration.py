import json
from pathlib import Path

from contextrot.analysis import analyze
from contextrot.calibration import (
    MIN_CALIBRATED_STEPS,
    Calibration,
    load_calibration,
    save_calibration,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _cal(steps: int = 5000, knee=70.0, buckets=None) -> Calibration:
    return Calibration(
        knee_pct=knee,
        verdict_kind="edge",
        low_fill_rate=0.033,
        high_fill_rate=0.048,
        steps=steps,
        days=30,
        computed_at="2026-07-12T00:00:00+00:00",
        buckets=buckets
        if buckets is not None
        else [
            {"lo": 0, "hi": 50, "n": 500, "rate": 0.033},
            {"lo": 50, "hi": 70, "n": 10, "rate": 0.2},  # too small to quote
            {"lo": 70, "hi": 100, "n": 400, "rate": 0.048},
        ],
    )


def test_save_load_roundtrip(tmp_path: Path):
    result = analyze(data_dir=FIXTURES, days=None)
    target = tmp_path / "calibration.json"
    written = save_calibration(result, target)
    assert written == target

    cal = load_calibration(target)
    assert cal is not None
    assert cal.steps == len(result.steps)
    assert cal.verdict_kind == result.verdict_kind
    assert cal.knee_pct == result.curve.knee_pct
    assert all({"lo", "hi", "n", "rate"} <= set(b) for b in cal.buckets)


def test_load_missing_and_garbage(tmp_path: Path):
    assert load_calibration(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_calibration(bad) is None
    wrong_schema = tmp_path / "old.json"
    wrong_schema.write_text(json.dumps({"schema": 999}), encoding="utf-8")
    assert load_calibration(wrong_schema) is None


def test_calibrated_threshold():
    assert _cal(steps=MIN_CALIBRATED_STEPS).calibrated
    assert not _cal(steps=MIN_CALIBRATED_STEPS - 1).calibrated


def test_rate_at_fill_buckets():
    cal = _cal()
    assert cal.rate_at_fill(10.0) == 0.033
    assert cal.rate_at_fill(85.0) == 0.048
    # Top edge belongs to the last bucket.
    assert cal.rate_at_fill(100.0) == 0.048
    # Bucket with n below the floor is never quoted.
    assert cal.rate_at_fill(60.0) is None
    # Outside every bucket.
    assert Calibration(
        knee_pct=None,
        verdict_kind="clean",
        low_fill_rate=0.0,
        high_fill_rate=0.0,
        steps=1000,
        days=30,
        computed_at="",
        buckets=[],
    ).rate_at_fill(50.0) is None
