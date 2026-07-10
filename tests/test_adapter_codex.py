"""Tests for the Codex CLI rollout adapter.

The fixture rollout is built from scratch line by line so nothing real or
private is committed — it mirrors the entry shapes the adapter reads from a
real ``rollout-*.jsonl``.
"""

from __future__ import annotations

import json
from pathlib import Path

from contextrot.adapters.codex import CodexAdapter
from contextrot.signals import extract_signals


def _line(ts: str, etype: str, payload: dict) -> str:
    return json.dumps({"timestamp": ts, "type": etype, "payload": payload})


def _token_count(
    ts: str, *, input_tokens: int, cached: int, output: int, window: int = 258_400
) -> str:
    return _line(
        ts,
        "event_msg",
        {
            "type": "token_count",
            "info": {
                "last_token_usage": {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached,
                    "output_tokens": output,
                    "total_tokens": input_tokens + output,
                },
                "model_context_window": window,
            },
            "rate_limits": {"limit_id": "codex"},
        },
    )


def _write_rollout(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _demo_lines() -> list[str]:
    return [
        _line(
            "2026-04-23T06:07:35.398Z",
            "session_meta",
            {
                "id": "0000-1111",
                "timestamp": "2026-04-23T06:05:06.407Z",
                "cwd": "C:\\code\\myapp",
                "cli_version": "0.122.0",
            },
        ),
        _line(
            "2026-04-23T06:07:35.420Z",
            "turn_context",
            {"turn_id": "t1", "cwd": "C:\\code\\myapp", "model": "gpt-5.4"},
        ),
        _line(
            "2026-04-23T06:07:35.424Z",
            "event_msg",
            {"type": "user_message", "message": "fix the failing build"},
        ),
        # Step 1: a shell call that fails, closed by a token_count.
        _line(
            "2026-04-23T06:07:52.157Z",
            "response_item",
            {
                "type": "function_call",
                "name": "shell_command",
                "arguments": json.dumps({"command": "npm test", "workdir": "C:\\code\\myapp"}),
                "call_id": "call_1",
            },
        ),
        _line(
            "2026-04-23T06:07:52.200Z",
            "response_item",
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Running the tests first."}],
            },
        ),
        _token_count("2026-04-23T06:07:52.306Z", input_tokens=12_246, cached=2_432, output=289),
        _line(
            "2026-04-23T06:07:55.055Z",
            "response_item",
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": "Exit code: 1\nWall time: 2.1 seconds\nOutput:\nFAIL src/app.test.js",
            },
        ),
        # Step 2: an apply_patch custom tool call that succeeds.
        _line(
            "2026-04-23T06:18:09.175Z",
            "response_item",
            {
                "type": "custom_tool_call",
                "status": "completed",
                "call_id": "call_2",
                "name": "apply_patch",
                "input": (
                    "*** Begin Patch\n*** Update File: src/app.js\n@@\n-old\n+new\n*** End Patch"
                ),
            },
        ),
        _token_count("2026-04-23T06:18:09.500Z", input_tokens=20_000, cached=18_000, output=150),
        _line(
            "2026-04-23T06:18:10.537Z",
            "response_item",
            {
                "type": "custom_tool_call_output",
                "call_id": "call_2",
                "output": json.dumps({"output": "Success.", "metadata": {"exit_code": 0}}),
            },
        ),
        # Rate-limit-only heartbeat: info null, must not create a step.
        _line("2026-04-23T06:18:11.000Z", "event_msg", {"type": "token_count", "info": None}),
        # Step 3: no tool calls, just text.
        _line(
            "2026-04-23T06:20:00.000Z",
            "response_item",
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Patched; tests pass now."}],
            },
        ),
        _token_count("2026-04-23T06:20:01.000Z", input_tokens=25_000, cached=24_000, output=80),
    ]


def _rollout_path(root: Path) -> Path:
    return root / "2026" / "04" / "23" / "rollout-2026-04-23T06-05-06-0000-1111.jsonl"


def test_discover_nested_layout(tmp_path: Path) -> None:
    path = _rollout_path(tmp_path)
    _write_rollout(path, _demo_lines())
    # A stray non-rollout jsonl must not be picked up.
    (tmp_path / "other.jsonl").write_text("{}\n", encoding="utf-8")
    found = CodexAdapter().discover(tmp_path)
    assert found == [path]


def test_discover_missing_root(tmp_path: Path) -> None:
    assert CodexAdapter().discover(tmp_path / "nope") == []


def test_parse_steps_and_tokens(tmp_path: Path) -> None:
    path = _rollout_path(tmp_path)
    _write_rollout(path, _demo_lines())
    session = CodexAdapter().parse(path)
    assert session is not None
    assert session.session_id == "0000-1111"
    assert session.project == "C:\\code\\myapp"
    assert session.context_window_hint == 258_400
    assert len(session.steps) == 3  # info-null heartbeat ignored

    s1 = session.steps[0]
    assert s1.model == "gpt-5.4"
    # Cached tokens are a subset of input_tokens: fresh input is the difference,
    # so prompt_tokens equals the true context size.
    assert s1.input_tokens == 12_246 - 2_432
    assert s1.cache_read_tokens == 2_432
    assert s1.prompt_tokens == 12_246
    assert s1.output_tokens == 289
    assert "Running the tests" in s1.assistant_text

    # Tool call attached to the step whose token_count closed it; result
    # arrives later and is matched by call_id.
    assert len(s1.tool_calls) == 1
    call = s1.tool_calls[0]
    assert call.name == "shell_command"
    assert call.target == "npm test"
    assert call.is_error
    assert "Exit code: 1" in call.error_text

    s2 = session.steps[1]
    assert len(s2.tool_calls) == 1
    patch = s2.tool_calls[0]
    assert patch.name == "apply_patch"
    assert patch.target == "src/app.js"
    assert not patch.is_error
    assert patch.result_chars > 0

    assert session.user_message_chars == len("fix the failing build")
    assert session.started_at is not None
    assert session.ended_at is not None
    assert session.ended_at > session.started_at


def test_parse_tolerates_garbage(tmp_path: Path) -> None:
    path = _rollout_path(tmp_path)
    lines = ["not json", json.dumps(["a", "list"]), json.dumps({"type": "mystery"})]
    lines += _demo_lines()
    _write_rollout(path, lines)
    session = CodexAdapter().parse(path)
    assert session is not None
    assert len(session.steps) == 3


def test_parse_empty_returns_none(tmp_path: Path) -> None:
    path = _rollout_path(tmp_path)
    _write_rollout(path, [_line("2026-04-23T06:07:35.398Z", "session_meta", {"id": "x"})])
    assert CodexAdapter().parse(path) is None


def test_signals_pipeline_compat(tmp_path: Path) -> None:
    path = _rollout_path(tmp_path)
    _write_rollout(path, _demo_lines())
    session = CodexAdapter().parse(path)
    assert session is not None
    extracted = extract_signals(session, session.context_window_hint or 258_400)
    assert len(extracted.steps) == 3
    # The failing shell call registers as a tool-error signal.
    assert any(s.tool_error for s in extracted.steps)
    assert all(0.0 <= s.fill_pct <= 100.0 for s in extracted.steps)
