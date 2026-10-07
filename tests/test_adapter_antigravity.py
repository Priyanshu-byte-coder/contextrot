"""Tests for the Antigravity adapter.

Antigravity stores each conversation as a SQLite database whose rows hold
protobuf blobs. The fixtures here build those databases from scratch — a tiny
protobuf encoder below writes exactly the fields the adapter reads, at the
field numbers decoded from real databases — so nothing real or private is
committed.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from contextrot.adapters import ADAPTERS
from contextrot.adapters.antigravity import AntigravityAdapter
from contextrot.analysis.by_source import agent_label
from contextrot.signals import extract_signals

T0 = int(datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc).timestamp())

# -- a minimal protobuf encoder ------------------------------------------------------


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def f(num: int, value: int | str | bytes) -> bytes:
    """One protobuf field: ints as varints, str/bytes as length-delimited."""
    if isinstance(value, int):
        return _varint(num << 3) + _varint(value)
    raw = value.encode() if isinstance(value, str) else value
    return _varint(num << 3 | 2) + _varint(len(raw)) + raw


def ts(seconds: int) -> bytes:
    return f(1, seconds) + f(2, 0)


# -- fixture builder ---------------------------------------------------------------

_SCHEMA = """
CREATE TABLE trajectory_meta (
    trajectory_id TEXT, cascade_id TEXT, trajectory_type INTEGER, source INTEGER
);
CREATE TABLE steps (idx INTEGER, step_type INTEGER, status INTEGER, has_subtrajectory NUMERIC,
    metadata BLOB, error_details BLOB, permissions BLOB, task_details BLOB, render_info BLOB,
    step_payload BLOB, step_format INTEGER);
CREATE TABLE gen_metadata (idx INTEGER, data BLOB, size INTEGER);
CREATE TABLE trajectory_metadata_blob (id TEXT, data BLOB);
"""


class Conversation:
    def __init__(self, path: Path, workspace: str | None = "file:///home/dev/web-app") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(_SCHEMA)
        self.steps = 0
        self.calls = 0
        if workspace:
            self.conn.execute(
                "INSERT INTO trajectory_metadata_blob VALUES (?, ?)",
                ("meta", f(1, f(1, workspace))),
            )

    def call(self, at: int, fresh: int, cached: int = 0, output: int = 100,
             thinking: int = 0, model: str | None = "gemini-pro-default",
             enum: str | None = None) -> None:
        usage = f(1, 1016) + f(2, fresh) + f(3, output)
        if cached:
            usage += f(5, cached)
        if thinking:
            usage += f(9, thinking)
        body = f(4, usage) + f(9, f(4, ts(at)))
        if model:
            body += f(19, model)
        if enum:
            body += f(20, f(1, "model_enum") + f(2, enum))
        self.conn.execute(
            "INSERT INTO gen_metadata VALUES (?, ?, ?)", (self.calls, f(1, body), 0)
        )
        self.calls += 1

    def step(self, at: int, step_type: int, payload: bytes = b"", status: int = 3,
             error: bytes | None = None, header: bytes = b"") -> None:
        # Field 5 is the step header: its creation time, plus the tool call
        # (field 4) when the step is one.
        self.conn.execute(
            "INSERT INTO steps (idx, step_type, status, error_details, step_payload, step_format) "
            "VALUES (?, ?, ?, ?, ?, 1)",
            (self.steps, step_type, status, error, f(5, f(1, ts(at)) + header) + payload),
        )
        self.steps += 1

    def user(self, at: int) -> None:
        self.step(at, 14)

    def text(self, at: int, words: str) -> None:
        self.step(at, 15, f(20, f(1, words)))

    def tool(self, at: int, name: str, args: dict, *, step_type: int = 8, status: int = 3,
             error: bytes | None = None, exit_code: int | None = None) -> None:
        payload = f(28, f(6, exit_code)) if exit_code is not None else b""
        header = f(4, f(2, name) + f(3, json.dumps(args)))
        self.step(at, step_type, payload, status=status, error=error, header=header)

    def save(self) -> None:
        self.conn.commit()
        self.conn.close()


def _basic(root: Path, cid: str = "conv-1") -> Path:
    path = root / "antigravity-cli" / "conversations" / f"{cid}.db"
    c = Conversation(path)
    c.user(T0)
    c.call(T0, fresh=40_000, output=600, thinking=50)
    c.tool(T0 + 5, "view_file", {"AbsolutePath": "/home/dev/web-app/app.py"})
    c.text(T0 + 6, "Reading the app first.")
    c.call(T0 + 10, fresh=2_000, cached=40_600, output=500)
    c.tool(T0 + 15, "replace_file_content", {"TargetFile": "/home/dev/web-app/app.py"},
           step_type=5)
    c.save()
    return path


# -- tests -------------------------------------------------------------------------


def test_registered_and_labelled():
    assert isinstance(ADAPTERS["antigravity"], AntigravityAdapter)
    assert agent_label("antigravity-cli") == "Antigravity CLI"
    assert agent_label("antigravity") == "Antigravity"


def test_discover_finds_cli_and_ide_conversations(tmp_path: Path):
    _basic(tmp_path, "cli-conv")
    _basic(tmp_path / "x", "ide-conv")  # nested one level too deep: not a data dir
    ide = tmp_path / "antigravity-ide" / "conversations" / "ide-conv.db"
    Conversation(ide).save()
    found = AntigravityAdapter().discover(tmp_path)
    assert sorted(p.stem for p in found) == ["cli-conv", "ide-conv"]


def test_discover_keeps_the_newest_copy_of_a_conversation(tmp_path: Path):
    old = tmp_path / "antigravity" / "conversations" / "same.db"
    new = tmp_path / "antigravity-ide" / "conversations" / "same.db"
    Conversation(old).save()
    Conversation(new).save()
    os.utime(old, (1_000_000, 1_000_000))
    found = AntigravityAdapter().discover(tmp_path)
    assert found == [new]


def test_token_accounting(tmp_path: Path):
    s = AntigravityAdapter().parse(_basic(tmp_path))
    assert s is not None
    assert s.source == "antigravity-cli"
    assert s.project == "/home/dev/web-app"
    first, second = s.steps
    assert first.prompt_tokens == 40_000
    assert first.output_tokens == 650  # output plus thinking
    assert second.input_tokens == 2_000
    assert second.cache_read_tokens == 40_600
    assert second.prompt_tokens == 42_600
    assert first.model == "gemini-pro-default"
    assert s.started_at == datetime.fromtimestamp(T0, tz=timezone.utc)


def test_tools_text_and_turns_attach_by_time(tmp_path: Path):
    s = AntigravityAdapter().parse(_basic(tmp_path))
    first, second = s.steps
    assert first.starts_turn and not second.starts_turn
    assert [c.name for c in first.tool_calls] == ["view_file"]
    assert first.tool_calls[0].target == "/home/dev/web-app/app.py"
    assert first.assistant_text == "Reading the app first."
    assert [c.name for c in second.tool_calls] == ["replace_file_content"]


def test_model_falls_back_to_enum(tmp_path: Path):
    path = tmp_path / "antigravity-cli" / "conversations" / "c.db"
    c = Conversation(path)
    c.call(T0, fresh=1_000, model=None, enum="MODEL_PLACEHOLDER_M26")
    c.call(T0 + 1, fresh=1_200, model=None, enum="SOMETHING_NEW")
    c.save()
    s = AntigravityAdapter().parse(path)
    assert [st.model for st in s.steps] == ["claude-opus-4-6-thinking", "unknown"]


def test_errors_exit_codes_and_invalid_calls(tmp_path: Path):
    path = tmp_path / "antigravity-cli" / "conversations" / "c.db"
    c = Conversation(path)
    c.call(T0, fresh=5_000)
    c.tool(T0 + 1, "run_command", {"CommandLine": "npm test\n--watch"}, step_type=21,
           exit_code=1)
    c.tool(T0 + 2, "run_command", {"CommandLine": "npm run build"}, step_type=21,
           exit_code=0)
    c.tool(T0 + 3, "replace_file_content", {"TargetFile": "/a.py"}, step_type=5,
           status=7, error=b"\x0a\x03bad")
    c.step(T0 + 4, 17, f(24, f(3, f(1, "The model produced an invalid tool call."))))
    c.save()
    calls = AntigravityAdapter().parse(path).steps[0].tool_calls
    assert [(t.name, t.is_error) for t in calls] == [
        ("run_command", True),
        ("run_command", False),
        ("replace_file_content", True),
        ("invalid_tool_call", True),
    ]
    assert calls[0].target == "npm test"
    assert calls[0].error_text == "exit code 1"
    assert calls[3].error_text == "The model produced an invalid tool call."


def test_signals_fire_end_to_end(tmp_path: Path):
    path = tmp_path / "antigravity-cli" / "conversations" / "c.db"
    c = Conversation(path)
    c.call(T0, fresh=5_000)
    c.tool(T0 + 1, "view_file", {"AbsolutePath": "/a.py"})
    c.call(T0 + 10, fresh=6_000)
    c.tool(T0 + 11, "view_file", {"AbsolutePath": "/a.py"})
    c.call(T0 + 20, fresh=7_000)
    c.tool(T0 + 21, "replace_file_content", {"TargetFile": "/a.py"}, step_type=5,
           status=7, error=b"\x0a\x03bad")
    c.save()
    sig = extract_signals(AntigravityAdapter().parse(path), 1_048_576).steps
    assert [s.reread for s in sig] == [False, True, False]
    assert sig[2].edit_failure and sig[2].tool_error


def test_unusable_conversations_return_none(tmp_path: Path):
    adapter = AntigravityAdapter()
    no_usage = tmp_path / "antigravity-cli" / "conversations" / "empty.db"
    c = Conversation(no_usage)
    c.user(T0)
    c.save()
    assert adapter.parse(no_usage) is None

    garbage = tmp_path / "antigravity-cli" / "conversations" / "garbage.db"
    garbage.write_bytes(b"not a database")
    assert adapter.parse(garbage) is None


def test_malformed_blobs_are_skipped(tmp_path: Path):
    path = tmp_path / "antigravity-cli" / "conversations" / "c.db"
    c = Conversation(path)
    c.call(T0, fresh=5_000)
    c.conn.execute("INSERT INTO gen_metadata VALUES (9, ?, 0)", (b"\xff\xff\xff",))
    c.conn.execute(
        "INSERT INTO steps (idx, step_type, status, step_payload) VALUES (9, 8, 3, ?)",
        (b"\x0a\xff",),
    )
    c.save()
    s = AntigravityAdapter().parse(path)
    assert len(s.steps) == 1


def test_doctor_note_counts_encrypted_conversations(tmp_path: Path):
    adapter = AntigravityAdapter()
    _basic(tmp_path, "readable")
    conv = tmp_path / "antigravity-cli" / "conversations"
    (conv / "readable.pb").write_bytes(os.urandom(64))  # has a .db too: not counted
    (conv / "old-1.pb").write_bytes(os.urandom(64))
    (conv / "old-2.pb").write_bytes(os.urandom(64))
    note = adapter.unreadable_note(tmp_path)
    assert note is not None and note.startswith("2 older Antigravity conversations are")
    (conv / "old-2.pb").unlink()
    assert adapter.unreadable_note(tmp_path).startswith("1 older Antigravity conversation is")


def test_no_data_discovers_nothing(tmp_path: Path):
    adapter = AntigravityAdapter()
    assert adapter.discover(tmp_path) == []
    assert adapter.unreadable_note(tmp_path) is None
