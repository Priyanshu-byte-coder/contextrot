"""Tests for the Cline / Roo Code / Kilo Code adapter.

Fixtures are built from scratch so nothing real or private is committed —
they mirror the task-directory layout these VS Code extensions write:
``ui_messages.json`` (token accounting) + ``api_conversation_history.json``
(the model conversation with XML-style tool tags).
"""

from __future__ import annotations

import json
from pathlib import Path

from contextrot.adapters.cline import ClineAdapter
from contextrot.signals import extract_signals

_ENV_DETAILS = (
    "<environment_details>\n"
    "# Current Mode\n<model>anthropic/claude-sonnet-4.5</model>\n"
    "# Current Workspace Directory (c:/Users/dev/myapp) Files\nsrc/\n"
    "</environment_details>"
)


def _api_req(ts: int, tokens_in: int, tokens_out: int, *, reads: int = 0, writes: int = 0) -> dict:
    text = {
        "request": "...",
        "tokensIn": tokens_in,
        "tokensOut": tokens_out,
        "cacheWrites": writes,
        "cacheReads": reads,
        "cost": 0.01,
    }
    return {"ts": ts, "type": "say", "say": "api_req_started", "text": json.dumps(text)}


def _history() -> list[dict]:
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "<task>\nfix the login bug\n</task>"},
                {"type": "text", "text": _ENV_DETAILS},
            ],
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Let me read the file first.\n"
                        "<read_file>\n<path>src/login.js</path>\n</read_file>"
                    ),
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "[read_file for 'src/login.js'] Result:\nfunction login() {}",
                }
            ],
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Applying the fix.\n"
                        "<replace_in_file>\n<path>src/login.js</path>\n"
                        "<diff>-old\n+new</diff>\n</replace_in_file>"
                    ),
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "[replace_in_file for 'src/login.js'] Result:\n"
                        "The tool execution failed with the following error:\n"
                        "No sufficiently similar match found"
                    ),
                }
            ],
        },
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "Done — the fix is applied."}],
        },
    ]


def _write_task(
    root: Path,
    publisher: str = "saoudrizwan.claude-dev",
    task_id: str = "task-001",
    *,
    ui: list | None = None,
    history: list | None = None,
) -> Path:
    task_dir = root / publisher / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    if ui is None:
        ui = [
            {"ts": 1_776_873_000_000, "type": "say", "say": "text", "text": "fix the login bug"},
            _api_req(1_776_873_010_000, 9_000, 300),
            _api_req(1_776_873_020_000, 500, 250, reads=9_000, writes=600),
            # Zero-usage request (failed before start): must not become a step.
            _api_req(1_776_873_025_000, 0, 0),
            _api_req(1_776_873_030_000, 400, 100, reads=10_000),
        ]
    (task_dir / "ui_messages.json").write_text(json.dumps(ui), encoding="utf-8")
    if history is None:
        history = _history()
    (task_dir / "api_conversation_history.json").write_text(
        json.dumps(history), encoding="utf-8"
    )
    return task_dir / "ui_messages.json"


def test_discover_publisher_layout(tmp_path: Path) -> None:
    p1 = _write_task(tmp_path)
    p2 = _write_task(tmp_path, publisher="rooveterinaryinc.roo-cline", task_id="task-002")
    found = ClineAdapter().discover(tmp_path)
    assert found == sorted([p1, p2])


def test_parse_steps_tokens_and_tools(tmp_path: Path) -> None:
    path = _write_task(tmp_path)
    session = ClineAdapter().parse(path)
    assert session is not None
    assert session.source == "cline"
    assert session.session_id == "task-001"
    assert session.project == "c:/Users/dev/myapp"
    assert len(session.steps) == 3  # zero-usage request skipped

    s1 = session.steps[0]
    assert s1.model == "anthropic/claude-sonnet-4.5"
    assert s1.input_tokens == 9_000
    assert s1.output_tokens == 300
    assert len(s1.tool_calls) == 1
    assert s1.tool_calls[0].name == "read_file"
    assert s1.tool_calls[0].target == "src/login.js"
    assert not s1.tool_calls[0].is_error
    assert "Let me read the file" in s1.assistant_text
    assert "<read_file>" not in s1.assistant_text

    s2 = session.steps[1]
    # Anthropic-style accounting maps straight through.
    assert s2.prompt_tokens == 500 + 600 + 9_000
    edit = s2.tool_calls[0]
    assert edit.name == "replace_in_file"
    assert edit.is_error
    assert "No sufficiently similar match" in edit.error_text

    assert session.user_message_chars == len("\nfix the login bug\n")
    assert session.started_at is not None and session.ended_at is not None


def test_roo_source_label(tmp_path: Path) -> None:
    path = _write_task(tmp_path, publisher="rooveterinaryinc.roo-cline", task_id="task-002")
    session = ClineAdapter().parse(path)
    assert session is not None
    assert session.source == "roo-code"


def test_workspace_fallback_to_history_item(tmp_path: Path) -> None:
    history = _history()
    # Strip environment details so the workspace regex finds nothing.
    history[0]["content"] = [{"type": "text", "text": "<task>hi</task>"}]
    path = _write_task(tmp_path, task_id="task-003", history=history)
    (path.parent / "history_item.json").write_text(
        json.dumps({"id": "task-003", "workspace": "c:\\Users\\dev\\other"}), encoding="utf-8"
    )
    session = ClineAdapter().parse(path)
    assert session is not None
    assert session.project == "c:\\Users\\dev\\other"


def test_missing_history_still_yields_steps(tmp_path: Path) -> None:
    path = _write_task(tmp_path, task_id="task-004")
    (path.parent / "api_conversation_history.json").unlink()
    session = ClineAdapter().parse(path)
    assert session is not None
    assert len(session.steps) == 3
    assert all(not s.tool_calls for s in session.steps)


def test_all_requests_zero_usage_returns_none(tmp_path: Path) -> None:
    ui = [_api_req(1_776_873_010_000, 0, 0)]
    path = _write_task(tmp_path, task_id="task-005", ui=ui)
    assert ClineAdapter().parse(path) is None


def test_garbage_ui_returns_none(tmp_path: Path) -> None:
    task_dir = tmp_path / "saoudrizwan.claude-dev" / "tasks" / "task-006"
    task_dir.mkdir(parents=True)
    (task_dir / "ui_messages.json").write_text("not json", encoding="utf-8")
    assert ClineAdapter().parse(task_dir / "ui_messages.json") is None


def test_signals_pipeline_compat(tmp_path: Path) -> None:
    path = _write_task(tmp_path)
    session = ClineAdapter().parse(path)
    assert session is not None
    extracted = extract_signals(session, 200_000)
    assert len(extracted.steps) == 3
    # The failed replace_in_file registers as an edit failure.
    assert any(s.edit_failure for s in extracted.steps)
    assert all(0.0 <= s.fill_pct <= 100.0 for s in extracted.steps)
