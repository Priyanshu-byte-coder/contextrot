"""Tests for the OpenCode file-based (JSON) storage adapter.

Builds the current on-disk layout from scratch under a temp dir — nothing real
or private is committed — mirroring what a live OpenCode install writes:

    <data>/storage/session/{projectID}/{sessionID}.json
    <data>/storage/message/{sessionID}/{messageID}.json
    <data>/storage/part/{messageID}/{partID}.json
    <data>/storage/project/{projectID}.json
"""

from __future__ import annotations

import json
from pathlib import Path

from contextrot.adapters.opencode import OpenCodeAdapter
from contextrot.signals import extract_signals


class _Store:
    def __init__(self, root: Path) -> None:
        self.storage = root / "storage"
        self._t = 1000

    def _t_next(self) -> int:
        self._t += 10
        return self._t

    def write(self, *key: str, data: dict) -> None:
        path = self.storage.joinpath(*key).with_suffix(".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def project(self, pid: str, worktree: str) -> None:
        self.write("project", pid, data={"id": pid, "worktree": worktree})

    def session(self, sid: str, pid: str, parent: str | None = None) -> None:
        data = {"id": sid, "projectID": pid, "time": {"created": self._t_next()}}
        if parent:
            data["parentID"] = parent
        self.write("session", pid, sid, data=data)

    def assistant(self, mid: str, sid: str, tokens: dict,
                  model: str = "claude-sonnet-4-6") -> None:
        self.write("message", sid, mid, data={
            "id": mid, "role": "assistant", "modelID": model,
            "time": {"created": self._t_next()}, "tokens": tokens})

    def user(self, mid: str, sid: str) -> None:
        self.write("message", sid, mid, data={
            "id": mid, "role": "user", "time": {"created": self._t_next()}})

    def text_part(self, pid: str, mid: str, text: str) -> None:
        self.write("part", mid, pid, data={"id": pid, "type": "text", "text": text})

    def tool_part(self, pid: str, mid: str, tool: str, *, target_key: str = "filePath",
                  target: str = "", status: str = "completed", output: str = "",
                  error: str = "", call_id: str = "c") -> None:
        state: dict = {"status": status, "input": {target_key: target}}
        if output:
            state["output"] = output
        if error:
            state["error"] = error
        self.write("part", mid, pid, data={
            "id": pid, "type": "tool", "tool": tool, "callID": call_id, "state": state})


def _build(root: Path) -> _Store:
    s = _Store(root)
    s.project("proj1", "/home/user/myapp")
    s.session("ses_main", "proj1")
    s.session("ses_child", "proj1", parent="ses_main")

    s.user("u1", "ses_main")
    s.text_part("u1p1", "u1", "please fix the bug in a.py")

    s.assistant("a1", "ses_main", {"input": 10, "output": 80, "cache": {"read": 0, "write": 20000}})
    s.text_part("a1p1", "a1", "Looking at the file.")
    s.tool_part("a1p2", "a1", "read", target="/home/user/myapp/a.py",
                output="def f():\n    return 1\n", call_id="t1")

    s.assistant("a2", "ses_main",
                {"input": 40, "output": 60, "cache": {"read": 20000, "write": 9960}})
    s.tool_part("a2p1", "a2", "edit", target="/home/user/myapp/a.py",
                status="error", error="Error: oldString not found in file", call_id="t2")

    s.assistant("a3", "ses_main",
                {"input": 22, "output": 30, "cache": {"read": 130000, "write": 9978}})
    s.text_part("a3p1", "a3", "I apologize, let me fix that.")
    s.tool_part("a3p2", "a3", "edit", target="/home/user/myapp/a.py", output="ok", call_id="t3")

    # sub-agent (child) session with one assistant step → sidechain
    s.assistant("c1", "ses_child", {"input": 5, "output": 5, "cache": {"read": 0, "write": 0}})
    s.tool_part("c1p1", "c1", "bash", target_key="command", target="ls", call_id="t4")
    return s


def test_discover_json_top_level_only(tmp_path: Path):
    _build(tmp_path)
    paths = OpenCodeAdapter().discover(tmp_path)
    assert len(paths) == 1  # child session excluded
    assert paths[0].name == "ses_main.json"


def test_parse_json_structure(tmp_path: Path):
    _build(tmp_path)
    adapter = OpenCodeAdapter()
    session = adapter.parse(adapter.discover(tmp_path)[0])
    assert session is not None
    assert session.source == "opencode"
    assert session.session_id == "ses_main"
    assert session.project == "/home/user/myapp"
    assert len(session.steps) == 3
    assert session.sidechain_steps == 1
    assert session.user_message_chars == len("please fix the bug in a.py")


def test_json_token_accounting(tmp_path: Path):
    _build(tmp_path)
    adapter = OpenCodeAdapter()
    session = adapter.parse(adapter.discover(tmp_path)[0])
    assert session is not None
    first, _mid, last = session.steps
    assert first.model == "claude-sonnet-4-6"
    assert first.prompt_tokens == 10 + 0 + 20000
    assert last.prompt_tokens == 22 + 130000 + 9978


def test_json_signals_fire(tmp_path: Path):
    _build(tmp_path)
    adapter = OpenCodeAdapter()
    session = adapter.parse(adapter.discover(tmp_path)[0])
    assert session is not None
    steps = extract_signals(session, 200_000).steps
    assert steps[1].edit_failure and steps[1].tool_error
    assert steps[2].retry and steps[2].self_correction


def test_storage_dir_directly(tmp_path: Path):
    # --data-dir pointed straight at the storage/ dir also works.
    _build(tmp_path)
    paths = OpenCodeAdapter().discover(tmp_path / "storage")
    assert len(paths) == 1


def test_env_var_discovery(tmp_path: Path, monkeypatch):
    # With no --data-dir, OPENCODE_DATA_DIR must locate the store.
    _build(tmp_path)
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(tmp_path))
    paths = OpenCodeAdapter().discover(None)
    assert len(paths) == 1
    session = OpenCodeAdapter()
    p = session.discover(None)
    assert session.parse(p[0]) is not None


def test_empty_dir_discovers_nothing(tmp_path: Path):
    assert OpenCodeAdapter().discover(tmp_path) == []
