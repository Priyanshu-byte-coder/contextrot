"""OpenCode transcript adapter.

OpenCode (github.com/sst/opencode) stores sessions in a single SQLite database
at ``~/.local/share/opencode/opencode.db`` (override the directory with
``XDG_DATA_HOME``). Unlike Claude Code's one-file-per-session JSONL, everything
lives in three tables:

- ``session(id, project_id, parent_id, ...)`` — one row per session. Sub-agent
  sessions have a non-null ``parent_id`` and are excluded from the main step
  list (their step count is surfaced as ``sidechain_steps``).
- ``message(id, session_id, data)`` — one row per message; ``data`` is JSON. An
  ``assistant`` message is one model API call and carries token accounting under
  ``data.tokens`` (``input``, ``output``, ``cache.read``, ``cache.write``).
- ``part(id, message_id, data)`` — the message's content parts; ``data`` is
  JSON. ``type == "text"`` holds assistant text; ``type == "tool"`` holds a tool
  call whose *outcome is embedded in the same part* under ``state`` (``status``
  ``completed``/``error``/…, ``input``, ``output``, ``error``) — so, unlike
  Claude Code, there is no separate tool-result message to reconcile.

Fitting one SQLite file with many sessions into contextrot's
``discover() -> paths`` / ``parse(path) -> one Session`` contract: ``discover()``
returns the database path once per top-level session and records the session ids
in order; ``parse()`` consumes them in the same order (the loader iterates the
two calls strictly one-to-one). Every returned path is the real database file,
so the ``--days`` ``path.stat()`` filter still works.

Parsing is tolerant by design: unknown fields are ignored, malformed JSON rows
are skipped, and a partially parsed session beats a crash. Reads are local and
read-only; no network access.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from contextrot.adapters.base import SessionAdapter
from contextrot.models import Session, Step, ToolCall

# Tool input keys used as the retry/re-read "target", in priority order.
# OpenCode uses camelCase ``filePath``; the rest mirror common tool shapes.
_TARGET_KEYS = (
    "filePath",
    "file_path",
    "path",
    "url",
    "pattern",
    "command",
    "query",
)


def _default_db_path() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data_home) / "opencode" / "opencode.db"


def _resolve_db(data_dir: Path | None) -> Path:
    """Resolve the opencode.db path from an optional --data-dir override.

    Accepts either the database file directly or a directory containing it (or
    an ``opencode/opencode.db`` beneath it), mirroring how a user might point
    ``--data-dir`` at their opencode data folder.
    """
    if data_dir is None:
        return _default_db_path()
    p = Path(data_dir)
    if p.is_file():
        return p
    for candidate in (p / "opencode.db", p / "opencode" / "opencode.db"):
        if candidate.is_file():
            return candidate
    return p / "opencode.db"


def _ms_to_dt(raw: object) -> datetime | None:
    if not isinstance(raw, (int, float)) or raw <= 0:
        return None
    try:
        return datetime.fromtimestamp(raw / 1000, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _target_of(tool_input: dict) -> str | None:
    for key in _TARGET_KEYS:
        val = tool_input.get(key)
        if isinstance(val, str) and val:
            # For shell commands, the first line is enough to identify a retry.
            return val.split("\n", 1)[0][:300]
    return None


def _connect(db: Path) -> sqlite3.Connection | None:
    try:
        # Immutable open: read-only and no locking, safe against a live opencode.
        return sqlite3.connect(f"file:{db}?immutable=1", uri=True)
    except sqlite3.Error:
        try:
            return sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        except sqlite3.Error:
            return None


def _has_tables(conn: sqlite3.Connection, *tables: str) -> bool:
    have = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    return all(t in have for t in tables)


class OpenCodeAdapter(SessionAdapter):
    name = "opencode"

    def __init__(self) -> None:
        # Session ids queued by discover(), consumed one-per-path by parse().
        self._queue: deque[str] = deque()
        self._db: Path | None = None

    def discover(self, data_dir: Path | None = None) -> list[Path]:
        db = _resolve_db(data_dir)
        self._db = db
        self._queue.clear()
        if not db.is_file():
            return []
        conn = _connect(db)
        if conn is None:
            return []
        try:
            if not _has_tables(conn, "session", "message", "part"):
                return []
            rows = conn.execute(
                "SELECT id FROM session WHERE parent_id IS NULL ORDER BY time_created ASC"
            ).fetchall()
        except sqlite3.Error:
            return []
        finally:
            conn.close()

        session_ids = [str(r[0]) for r in rows]
        self._queue.extend(session_ids)
        # One path per session (the real DB file, so path.stat() works for the
        # --days filter); parse() maps each back to a session id in order.
        return [db for _ in session_ids]

    def parse(self, path: Path) -> Session | None:
        if not self._queue:
            return None
        session_id = self._queue.popleft()
        db = self._db or path
        conn = _connect(db)
        if conn is None:
            return None
        try:
            return self._parse_session(conn, session_id)
        except sqlite3.Error:
            return None
        finally:
            conn.close()

    # -- internals ----------------------------------------------------------

    def _parse_session(
        self, conn: sqlite3.Connection, session_id: str
    ) -> Session | None:
        session = Session(
            session_id=session_id,
            source=self.name,
            project=self._project_name(conn, session_id),
        )

        messages = conn.execute(
            "SELECT id, data FROM message WHERE session_id = ? "
            "ORDER BY time_created ASC, id ASC",
            (session_id,),
        ).fetchall()

        for message_id, raw in messages:
            data = _load_json(raw)
            if not isinstance(data, dict):
                continue
            role = data.get("role")
            if role == "assistant":
                self._consume_assistant(conn, str(message_id), data, session)
            elif role == "user":
                session.user_message_chars += self._user_chars(conn, str(message_id))

        if not session.steps:
            return None

        session.sidechain_steps = self._sidechain_steps(conn, session_id)
        return session

    def _consume_assistant(
        self,
        conn: sqlite3.Connection,
        message_id: str,
        data: dict,
        session: Session,
    ) -> None:
        tokens = _as_dict(data.get("tokens"))
        cache = _as_dict(tokens.get("cache"))
        ts = _ms_to_dt(_as_dict(data.get("time")).get("created"))

        texts: list[str] = []
        calls: list[ToolCall] = []
        for part in self._parts(conn, message_id):
            ptype = part.get("type")
            if ptype == "text" and isinstance(part.get("text"), str):
                texts.append(part["text"])
            elif ptype == "tool":
                calls.append(_tool_call(part))

        step = Step(
            timestamp=ts,
            model=str(data.get("modelID") or "unknown"),
            input_tokens=_int(tokens.get("input")),
            cache_creation_tokens=_int(cache.get("write")),
            cache_read_tokens=_int(cache.get("read")),
            output_tokens=_int(tokens.get("output")),
            tool_calls=calls,
            assistant_text="\n".join(texts),
        )
        session.steps.append(step)
        if session.started_at is None:
            session.started_at = ts
        if ts is not None:
            session.ended_at = ts

    def _parts(self, conn: sqlite3.Connection, message_id: str) -> list[dict]:
        rows = conn.execute(
            "SELECT data FROM part WHERE message_id = ? "
            "ORDER BY time_created ASC, id ASC",
            (message_id,),
        ).fetchall()
        out: list[dict] = []
        for (raw,) in rows:
            parsed = _load_json(raw)
            if isinstance(parsed, dict):
                out.append(parsed)
        return out

    def _user_chars(self, conn: sqlite3.Connection, message_id: str) -> int:
        total = 0
        for part in self._parts(conn, message_id):
            if part.get("type") == "text" and isinstance(part.get("text"), str):
                total += len(part["text"])
        return total

    def _project_name(self, conn: sqlite3.Connection, session_id: str) -> str:
        try:
            row = conn.execute(
                "SELECT p.worktree FROM session s "
                "JOIN project p ON p.id = s.project_id WHERE s.id = ?",
                (session_id,),
            ).fetchone()
        except sqlite3.Error:
            row = None
        if row and isinstance(row[0], str) and row[0]:
            return row[0]
        try:
            row = conn.execute(
                "SELECT directory FROM session WHERE id = ?", (session_id,)
            ).fetchone()
        except sqlite3.Error:
            row = None
        if row and isinstance(row[0], str) and row[0]:
            return row[0]
        return session_id

    def _sidechain_steps(self, conn: sqlite3.Connection, session_id: str) -> int:
        """Count assistant messages in this session's sub-agent (child) sessions."""
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM message m "
                "JOIN session s ON s.id = m.session_id "
                "WHERE s.parent_id = ? "
                "AND json_extract(m.data, '$.role') = 'assistant'",
                (session_id,),
            ).fetchone()
        except sqlite3.Error:
            return 0
        return int(row[0]) if row and row[0] is not None else 0


def _tool_call(part: dict) -> ToolCall:
    state = _as_dict(part.get("state"))
    tool_input = _as_dict(state.get("input"))
    status = state.get("status")
    output = state.get("output")
    error_text = state.get("error")
    return ToolCall(
        name=str(part.get("tool") or "unknown"),
        tool_use_id=str(part.get("callID") or ""),
        target=_target_of(tool_input),
        is_error=(status == "error"),
        error_text=str(error_text)[:500] if error_text else "",
        result_chars=len(output) if isinstance(output, str) else 0,
    )


def _load_json(raw: object) -> object:
    if not isinstance(raw, (str, bytes, bytearray)):
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0
