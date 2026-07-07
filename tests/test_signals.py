from pathlib import Path

from contextrot.adapters.claude_code import ClaudeCodeAdapter
from contextrot.models import Session, Step, ToolCall
from contextrot.signals import extract_signals

SESSION_FILE = (
    Path(__file__).parent
    / "fixtures"
    / "demo-project"
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


def test_reversal_counter_uses_prior_events_only():
    steps = _signals()

    assert [step.reversals_so_far for step in steps] == [0, 0, 0, 1, 1]
    assert not steps[1].reversal  # first failed edit has no earlier edit target
    assert steps[2].reversal  # retry plus self-correction affects later steps
    assert steps[3].reversals_so_far == 1


def test_cost_positive():
    steps = _signals()
    assert all(s.cost_usd > 0 for s in steps)


def test_tool_name_matching_is_case_insensitive():
    # Agents disagree on casing: Claude Code capitalizes (Edit/Read), OpenCode
    # lowercases (edit/read). edit_failure and reread must fire regardless.
    session = Session(
        session_id="s",
        source="opencode",
        project="p",
        steps=[
            Step(
                timestamp=None,
                model="claude-sonnet-4-6",
                tool_calls=[
                    ToolCall(name="read", tool_use_id="r1", target="a.py", result_chars=10)
                ],
            ),
            Step(
                timestamp=None,
                model="claude-sonnet-4-6",
                tool_calls=[
                    ToolCall(
                        name="edit",
                        tool_use_id="e1",
                        target="a.py",
                        is_error=True,
                        error_text="oldString not found",
                    )
                ],
            ),
            Step(
                timestamp=None,
                model="claude-sonnet-4-6",
                tool_calls=[
                    ToolCall(name="read", tool_use_id="r2", target="a.py", result_chars=10)
                ],
            ),
        ],
    )
    steps = extract_signals(session, WINDOW).steps
    assert steps[1].edit_failure  # lowercase "edit" error still counts
    assert steps[1].tool_error
    assert steps[2].reread  # lowercase "read" of an already-read file
    assert not steps[0].reread
