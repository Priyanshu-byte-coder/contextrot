from pathlib import Path

from ctxprof.adapters.claude_code import ClaudeCodeAdapter
from ctxprof.signals import extract_signals

SESSION_FILE = (
    Path(__file__).parent / "fixtures" / "demo-project"
    / "11111111-2222-3333-4444-555555555555.jsonl"
)

WINDOW = 200_000


def _signals():
    session = ClaudeCodeAdapter().parse(SESSION_FILE)
    assert session is not None
    return extract_signals(session, WINDOW).steps


def test_edit_failure_detected():
    steps = _signals()
    assert steps[1].edit_failure
    assert steps[1].tool_error
    assert steps[1].degraded


def test_retry_detected_after_error():
    steps = _signals()
    # Step 2 repeats Edit on the same file right after step 1's error.
    assert steps[2].retry


def test_self_correction_detected():
    steps = _signals()
    assert steps[2].self_correction


def test_reread_detected():
    steps = _signals()
    # Step 3 Reads a.py, which step 0 already read.
    assert steps[3].reread
    assert not steps[0].reread


def test_clean_step_not_degraded():
    steps = _signals()
    assert not steps[4].degraded


def test_fill_pct_computed():
    steps = _signals()
    assert steps[0].fill_pct == (20000 / WINDOW) * 100
    assert 0 < steps[4].fill_pct <= 100


def test_cost_positive():
    steps = _signals()
    assert all(s.cost_usd > 0 for s in steps)
