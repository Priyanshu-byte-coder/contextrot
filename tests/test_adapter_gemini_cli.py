"""Tests for the Gemini CLI / Qwen Code adapter.

Fixtures are built from scratch so nothing real or private is committed —
they mirror both on-disk formats: the legacy single-JSON ConversationRecord
and the current JSONL stream with ``$set`` / ``$rewindTo`` records.
"""

from __future__ import annotations

import json
from pathlib import Path

from contextrot.adapters.gemini_cli import GeminiCliAdapter
from contextrot.signals import extract_signals


def _gemini_msg(
    mid: str,
    ts: str,
    text: str = "",
    *,
    tokens: dict | None = None,
    tool_calls: list | None = None,
    model: str = "gemini-2.5-pro",
) -> dict:
    msg: dict = {"id": mid, "timestamp": ts, "type": "gemini", "content": text, "model": model}
    if tokens is not None:
        msg["tokens"] = tokens
    if tool_calls is not None:
        msg["toolCalls"] = tool_calls
    return msg


def _user_msg(mid: str, ts: str, text: str) -> dict:
    return {"id": mid, "timestamp": ts, "type": "user", "content": text}


def _demo_messages() -> list[dict]:
    return [
        _user_msg("m1", "2026-05-01T10:00:00.000Z", "please fix the bug"),
        _gemini_msg(
            "m2",
            "2026-05-01T10:00:05.000Z",
            "Reading the file first.",
            tokens={
                "input": 10_000, "output": 200, "cached": 4_000, "thoughts": 50, "total": 10_250,
            },
            tool_calls=[
                {
                    "id": "t1",
                    "name": "read_file",
                    "args": {"absolute_path": "/home/user/app/main.py"},
                    "status": "success",
                    "result": "def main(): ...",
                }
            ],
        ),
        _gemini_msg(
            "m3",
            "2026-05-01T10:00:20.000Z",
            "The edit failed.",
            tokens={"input": 16_000, "output": 120, "cached": 15_000, "total": 16_120},
            tool_calls=[
                {
                    "id": "t2",
                    "name": "replace",
                    "args": {"file_path": "/home/user/app/main.py"},
                    "status": "error",
                    "result": "Failed to edit, could not find the string to replace",
                }
            ],
        ),
        # No token accounting: must not become a step.
        _gemini_msg("m4", "2026-05-01T10:00:30.000Z", "thinking out loud"),
        _gemini_msg(
            "m5",
            "2026-05-01T10:00:40.000Z",
            "Done.",
            tokens={"input": 17_000, "output": 60, "cached": 16_500, "total": 17_060},
        ),
    ]


def _legacy_record(messages: list[dict]) -> dict:
    return {
        "sessionId": "sess-legacy-1",
        "projectHash": "abc123",
        "startTime": "2026-05-01T10:00:00.000Z",
        "lastUpdated": "2026-05-01T10:00:40.000Z",
        "directories": ["/home/user/app"],
        "messages": messages,
    }


def _write_legacy(root: Path, record: dict, name: str = "session-2026-05-01-abcd1234.json") -> Path:
    chats = root / "hash1" / "chats"
    chats.mkdir(parents=True, exist_ok=True)
    path = chats / name
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def _write_jsonl(
    root: Path, lines: list[dict], name: str = "session-2026-05-01-ef567890.jsonl"
) -> Path:
    chats = root / "hash2" / "chats"
    chats.mkdir(parents=True, exist_ok=True)
    path = chats / name
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return path


def test_discover_both_formats(tmp_path: Path) -> None:
    p1 = _write_legacy(tmp_path, _legacy_record(_demo_messages()))
    p2 = _write_jsonl(tmp_path, [{"sessionId": "s2", "projectHash": "h2"}, *_demo_messages()])
    # Non-session files must not be picked up.
    (tmp_path / "hash1" / "logs.json").write_text("[]", encoding="utf-8")
    found = GeminiCliAdapter().discover(tmp_path)
    assert found == sorted([p1, p2])


def test_parse_legacy_json(tmp_path: Path) -> None:
    path = _write_legacy(tmp_path, _legacy_record(_demo_messages()))
    session = GeminiCliAdapter().parse(path)
    assert session is not None
    assert session.session_id == "sess-legacy-1"
    assert session.source == "gemini-cli"
    assert session.project == "/home/user/app"
    assert len(session.steps) == 3  # tokenless message m4 skipped

    s1 = session.steps[0]
    assert s1.model == "gemini-2.5-pro"
    # tokens.input includes the cached prefix: fresh input is the difference.
    assert s1.input_tokens == 10_000 - 4_000
    assert s1.cache_read_tokens == 4_000
    assert s1.prompt_tokens == 10_000
    assert s1.output_tokens == 200 + 50  # thoughts are generated output
    assert len(s1.tool_calls) == 1
    assert s1.tool_calls[0].name == "read_file"
    assert s1.tool_calls[0].target == "/home/user/app/main.py"
    assert not s1.tool_calls[0].is_error

    s2 = session.steps[1]
    assert s2.tool_calls[0].is_error
    assert "could not find" in s2.tool_calls[0].error_text

    assert session.user_message_chars == len("please fix the bug")
    assert session.started_at is not None and session.ended_at is not None


def test_parse_jsonl_with_rewind(tmp_path: Path) -> None:
    messages = _demo_messages()
    lines: list[dict] = [
        {
            "sessionId": "sess-jsonl-1",
            "projectHash": "h2",
            "startTime": "2026-05-01T10:00:00.000Z",
        },
        *messages,
        # Rewind to m3: m4 and m5 are dropped from the record.
        {"$rewindTo": "m3"},
        {"$set": {"directories": ["/home/user/app"]}},
    ]
    path = _write_jsonl(tmp_path, lines)
    session = GeminiCliAdapter().parse(path)
    assert session is not None
    assert session.session_id == "sess-jsonl-1"
    assert session.project == "/home/user/app"  # applied via $set
    assert len(session.steps) == 2  # m5 rewound away, m4 tokenless


def test_subagent_sessions_skipped(tmp_path: Path) -> None:
    record = _legacy_record(_demo_messages())
    record["kind"] = "subagent"
    path = _write_legacy(tmp_path, record)
    assert GeminiCliAdapter().parse(path) is None


def test_qwen_root_labeled_qwen_code(tmp_path: Path) -> None:
    root = tmp_path / ".qwen" / "tmp"
    path = _write_legacy(root, _legacy_record(_demo_messages()))
    session = GeminiCliAdapter().parse(path)
    assert session is not None
    assert session.source == "qwen-code"


def test_parse_garbage_returns_none(tmp_path: Path) -> None:
    chats = tmp_path / "hash1" / "chats"
    chats.mkdir(parents=True)
    bad = chats / "session-bad.json"
    bad.write_text("not json at all", encoding="utf-8")
    assert GeminiCliAdapter().parse(bad) is None


def test_signals_pipeline_compat(tmp_path: Path) -> None:
    path = _write_legacy(tmp_path, _legacy_record(_demo_messages()))
    session = GeminiCliAdapter().parse(path)
    assert session is not None
    extracted = extract_signals(session, 1_048_576)
    assert len(extracted.steps) == 3
    assert any(s.tool_error for s in extracted.steps)
    assert all(0.0 <= s.fill_pct <= 100.0 for s in extracted.steps)
