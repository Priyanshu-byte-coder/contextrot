"""Tests for the OpenCode SQLite adapter.

The fixture database is built from scratch with the stdlib ``sqlite3`` module so
nothing real or private is committed — it mirrors the columns the adapter reads
from a real ``opencode.db``.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from contextrot.adapters.opencode import OpenCodeAdapter

_SCHEMA = """
CREATE TABLE project (id TEXT PRIMARY KEY, worktree TEXT NOT NULL);
CREATE TABLE session (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, parent_id TEXT,
    directory TEXT NOT NULL, time_created INTEGER NOT NULL
);
CREATE TABLE message (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
    time_created INTEGER NOT NULL, data TEXT NOT NULL
);
CREATE TABLE part (
    id TEXT PRIMARY KEY, message_id TEXT NOT NULL,
    time_created INTEGER NOT NULL, data TEXT NOT NULL
);
"""


class _Builder:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._t = 1000

    def next_time(self) -> int:
        self._t += 10
        return self._t

    def message(self, mid: str, sid: str, role: str, tokens: dict | None = None,
                model: str = "claude-sonnet-4-6") -> None:
        t = self.next_time()
        data: dict = {"role": role, "time": {"created": t}}
        if role == "assistant":
            data["modelID"] = model
            data["tokens"] = tokens or {}
        self.conn.execute(
            "INSERT INTO message VALUES (?,?,?,?)",
            (mid, sid, t, json.dumps(data)),
        )

    def part(self, pid: str, mid: str, data: dict, *, raw: str | None = None) -> None:
        t = self.next_time()
        self.conn.execute(
            "INSERT INTO part VALUES (?,?,?,?)",
            (pid, mid, t, raw if raw is not None else json.dumps(data)),
        )

    def text_part(self, pid: str, mid: str, text: str) -> None:
        self.part(pid, mid, {"type": "text", "text": text})

    def tool_part(self, pid: str, mid: str, tool: str, *, target_key: str = "filePath",
                  target: str = "", status: str = "completed", output: str = "",
                  error: str = "", call_id: str = "c") -> None:
        state: dict = {"status": status, "input": {target_key: target}}
        if output:
            state["output"] = output
        if error:
            state["error"] = error
        self.part(pid, mid, {"type": "tool", "tool": tool, "callID": call_id, "state": state})


def _build_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_SCHEMA)
        conn.execute("INSERT INTO project VALUES ('proj1', '/home/user/myapp')")
        conn.execute(
            "INSERT INTO session VALUES ('ses_main','proj1',NULL,'/home/user/myapp',10)"
        )
        conn.execute(
            "INSERT INTO session VALUES ('ses_child','proj1','ses_main','/home/user/myapp',50)"
        )
        b = _Builder(conn)

        # Human prompt (not a step, but counts toward user_message_chars).
        b.message("u1", "ses_main", "user")
        b.text_part("u1p1", "u1", "please fix the bug in a.py")

        # Step 1: a successful read + assistant text.
        b.message("a1", "ses_main", "assistant",
                  tokens={"input": 10, "output": 80, "cache": {"read": 0, "write": 20000}})
        b.text_part("a1p1", "a1", "Looking at the file.")
        b.tool_part("a1p2", "a1", "read", target="/home/user/myapp/a.py",
                    output="def f():\n    return 1\n", call_id="t1")

        # Step 2: a failing edit.
        b.message("a2", "ses_main", "assistant",
                  tokens={"input": 40, "output": 60, "cache": {"read": 20000, "write": 9960}})
        b.tool_part("a2p1", "a2", "edit", target="/home/user/myapp/a.py",
                    status="error", error="Error: oldString not found in file", call_id="t2")

        # Step 3: a self-corrected retry of the same edit.
        b.message("a3", "ses_main", "assistant",
                  tokens={"input": 22, "output": 30, "cache": {"read": 130000, "write": 9978}})
        b.text_part("a3p1", "a3", "I apologize, let me fix that.")
        b.tool_part("a3p2", "a3", "edit", target="/home/user/myapp/a.py",
                    output="ok", call_id="t3")

        # A sub-agent (child) session with one assistant step → sidechain.
        b.message("c1", "ses_child", "assistant",
                  tokens={"input": 5, "output": 5, "cache": {"read": 0, "write": 0}})
        b.tool_part("c1p1", "c1", "bash", target_key="command", target="ls", call_id="t4")

        conn.commit()
    finally:
        conn.close()


def _db(tmp_path: Path) -> Path:
    path = tmp_path / "opencode.db"
    _build_db(path)
    return path


def test_discover_finds_top_level_sessions_only(tmp_path: Path):
    db = _db(tmp_path)
    paths = OpenCodeAdapter().discover(tmp_path)
    # One path per top-level session; the sub-agent session is excluded.
    assert len(paths) == 1
    assert all(p == db for p in paths)


def test_parse_basic_structure(tmp_path: Path):
    _db(tmp_path)
    adapter = OpenCodeAdapter()
    paths = adapter.discover(tmp_path)
    session = adapter.parse(paths[0])
    assert session is not None
    assert session.source == "opencode"
    assert session.session_id == "ses_main"
    assert session.project == "/home/user/myapp"
    assert len(session.steps) == 3  # user message is not a step
    assert session.sidechain_steps == 1  # the child session's assistant step
    assert session.started_at is not None and session.ended_at is not None
    assert session.started_at < session.ended_at
    assert session.user_message_chars == len("please fix the bug in a.py")


def test_token_accounting_includes_cache(tmp_path: Path):
    _db(tmp_path)
    adapter = OpenCodeAdapter()
    session = adapter.parse(adapter.discover(tmp_path)[0])
    assert session is not None
    first, _mid, last = session.steps
    assert first.model == "claude-sonnet-4-6"
    # prompt_tokens = input + cache_read + cache_write(=creation)
    assert first.prompt_tokens == 10 + 0 + 20000
    assert last.prompt_tokens == 22 + 130000 + 9978
    assert last.output_tokens == 30


def test_tool_outcomes_and_targets(tmp_path: Path):
    _db(tmp_path)
    adapter = OpenCodeAdapter()
    session = adapter.parse(adapter.discover(tmp_path)[0])
    assert session is not None
    read = session.steps[0].tool_calls[0]
    assert read.name == "read"
    assert not read.is_error
    assert read.target == "/home/user/myapp/a.py"
    assert read.result_chars > 0

    failed_edit = session.steps[1].tool_calls[0]
    assert failed_edit.name == "edit"
    assert failed_edit.is_error
    assert "not found" in failed_edit.error_text

    # Same (tool, target) as the failed edit → the signals layer flags the retry.
    retried = session.steps[2].tool_calls[0]
    assert retried.name == "edit"
    assert retried.target == "/home/user/myapp/a.py"
    assert not retried.is_error
    assert "I apologize" in session.steps[2].assistant_text


def test_discover_parse_pairing_is_in_order(tmp_path: Path):
    # Two top-level sessions must map to two Sessions in discovery order.
    db = tmp_path / "opencode.db"
    _build_db(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO session VALUES ('ses_second','proj1',NULL,'/home/user/other',5)"
    )
    conn.execute(
        "INSERT INTO message VALUES ('b1','ses_second',6,?)",
        (json.dumps({"role": "assistant", "modelID": "claude-opus-4-6",
                     "time": {"created": 6},
                     "tokens": {"input": 3, "output": 3, "cache": {"read": 1, "write": 1}}}),),
    )
    for i in range(3):  # >= min_steps worth of parts across messages
        conn.execute(
            "INSERT INTO message VALUES (?, 'ses_second', ?, ?)",
            (f"b{i + 2}", 7 + i,
             json.dumps({"role": "assistant", "modelID": "claude-opus-4-6",
                         "time": {"created": 7 + i},
                         "tokens": {"input": 1, "output": 1, "cache": {"read": 0, "write": 0}}})),
        )
    conn.commit()
    conn.close()

    adapter = OpenCodeAdapter()
    paths = adapter.discover(tmp_path)
    assert len(paths) == 2  # ses_second (time 5) sorts before ses_main (time 10)
    first = adapter.parse(paths[0])
    second = adapter.parse(paths[1])
    assert first is not None and second is not None
    assert {first.session_id, second.session_id} == {"ses_main", "ses_second"}
    # ordered by session.time_created ASC → ses_second first
    assert first.session_id == "ses_second"


def test_malformed_parts_are_skipped(tmp_path: Path):
    db = tmp_path / "opencode.db"
    conn = sqlite3.connect(db)
    conn.executescript(_SCHEMA)
    conn.execute("INSERT INTO project VALUES ('p','/w')")
    conn.execute("INSERT INTO session VALUES ('s','p',NULL,'/w',1)")
    conn.execute(
        "INSERT INTO message VALUES ('m','s',2,?)",
        (json.dumps({"role": "assistant", "modelID": "x",
                     "time": {"created": 2}, "tokens": {"input": 5}}),),
    )
    conn.execute("INSERT INTO part VALUES ('p1','m',3,'not valid json')")
    conn.execute(
        "INSERT INTO part VALUES ('p2','m',4,?)",
        (json.dumps({"type": "text", "text": "hello"}),),
    )
    conn.commit()
    conn.close()

    adapter = OpenCodeAdapter()
    session = adapter.parse(adapter.discover(tmp_path)[0])
    assert session is not None
    assert len(session.steps) == 1
    assert session.steps[0].assistant_text == "hello"


def test_session_without_assistant_returns_none(tmp_path: Path):
    db = tmp_path / "opencode.db"
    conn = sqlite3.connect(db)
    conn.executescript(_SCHEMA)
    conn.execute("INSERT INTO project VALUES ('p','/w')")
    conn.execute("INSERT INTO session VALUES ('s','p',NULL,'/w',1)")
    conn.execute(
        "INSERT INTO message VALUES ('m','s',2,?)",
        (json.dumps({"role": "user", "time": {"created": 2}}),),
    )
    conn.commit()
    conn.close()

    adapter = OpenCodeAdapter()
    paths = adapter.discover(tmp_path)
    assert adapter.parse(paths[0]) is None


def test_missing_db_discovers_nothing(tmp_path: Path):
    assert OpenCodeAdapter().discover(tmp_path) == []
