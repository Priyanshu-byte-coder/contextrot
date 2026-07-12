import json
from pathlib import Path

import pytest

from contextrot.calibration import Calibration
from contextrot.hook import evaluate, tail_fill_pct


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CONTEXTROT_HOOK_STATE", str(tmp_path / "state"))


def _cal(knee=70.0, steps: int = 5000) -> Calibration:
    return Calibration(
        knee_pct=knee,
        verdict_kind="edge",
        low_fill_rate=0.033,
        high_fill_rate=0.048,
        steps=steps,
        days=30,
        computed_at="2026-07-12T00:00:00+00:00",
        buckets=[
            {"lo": 0, "hi": 70, "n": 800, "rate": 0.033},
            {"lo": 70, "hi": 100, "n": 400, "rate": 0.066},
        ],
    )


def _transcript(
    tmp_path: Path, prompt_tokens: int, model="claude-opus-4-8", name="transcript.jsonl"
) -> Path:
    """Claude Code-shaped transcript whose last assistant step has the given usage."""
    path = tmp_path / name
    lines = [
        json.dumps({"type": "user", "message": {"content": "hi"}}),
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "model": model,
                    "usage": {
                        "input_tokens": 1000,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": prompt_tokens - 1000,
                        "output_tokens": 50,
                    },
                },
            }
        ),
        "not json at all",
        json.dumps({"type": "system"}),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_tail_fill_pct_reads_last_usage(tmp_path: Path):
    # 150k of a 200k window (claude-opus) = 75%.
    t = _transcript(tmp_path, 150_000)
    fill = tail_fill_pct(t)
    assert fill == pytest.approx(75.0, abs=0.5)


def test_tail_fill_pct_missing_file(tmp_path: Path):
    assert tail_fill_pct(tmp_path / "nope.jsonl") is None


def test_warns_once_past_knee(tmp_path: Path):
    t = _transcript(tmp_path, 150_000)  # 75% > knee 70%
    payload = {"session_id": "s1", "transcript_path": str(t)}
    msg = evaluate(payload, _cal())
    assert msg is not None
    assert "75%" in msg
    assert "~70%" in msg
    assert "2.0× fresh" in msg  # 0.066 / 0.033
    # Second call: marker set, no nag.
    assert evaluate(payload, _cal()) is None


def test_rearms_after_compact(tmp_path: Path):
    high_t = _transcript(tmp_path, 150_000, name="high.jsonl")
    high = {"session_id": "s2", "transcript_path": str(high_t)}
    assert evaluate(high, _cal()) is not None
    # Fill drops well below the knee (compact) → marker cleared → warns again.
    low_t = _transcript(tmp_path, 40_000, name="low.jsonl")  # 20%
    low = {"session_id": "s2", "transcript_path": str(low_t)}
    assert evaluate(low, _cal()) is None
    assert evaluate(high, _cal()) is not None


def test_silent_below_knee(tmp_path: Path):
    t = _transcript(tmp_path, 100_000)  # 50%
    assert evaluate({"session_id": "s3", "transcript_path": str(t)}, _cal()) is None


def test_silent_without_calibration_or_knee(tmp_path: Path):
    t = _transcript(tmp_path, 190_000)
    payload = {"session_id": "s4", "transcript_path": str(t)}
    assert evaluate(payload, None) is None
    assert evaluate(payload, _cal(knee=None)) is None
    assert evaluate(payload, _cal(steps=10)) is None


def test_silent_on_missing_transcript():
    assert evaluate({"session_id": "s5"}, _cal()) is None
    assert evaluate({"session_id": "s5", "transcript_path": "/nope.jsonl"}, _cal()) is None
