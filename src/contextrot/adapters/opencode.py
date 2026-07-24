"""OpenCode transcript adapter.

OpenCode (github.com/sst/opencode) has used two on-disk formats. This adapter
supports both, preferring whichever a given install actually has:

1. **File-based storage (current).** JSON files under
   ``<data>/storage/`` (``data`` defaults to ``~/.local/share/opencode``):

   - ``storage/session/{projectID}/{sessionID}.json`` — one file per session
     (``parentID`` non-null marks a sub-agent session; excluded from the main
     step list, counted as ``sidechain_steps``).
   - ``storage/message/{sessionID}/{messageID}.json`` — one file per message.
     An ``assistant`` message carries token accounting under ``tokens``
     (``input``, ``output``, ``cache.read``, ``cache.write``) and ``modelID``.
   - ``storage/part/{messageID}/{partID}.json`` — the message's content parts;
     ``type == "text"`` holds assistant text, ``type == "tool"`` a tool call
     whose outcome is embedded under ``state`` (``status``/``input``/``output``
     /``error``).
   - ``storage/project/{projectID}.json`` — the project (``worktree``).

2. **SQLite (legacy).** A single ``opencode.db`` with ``session``/``message``
   /``part`` tables carrying the same JSON payloads. Kept as a fallback for
   installs that predate the file-storage migration.

Data-dir resolution honors ``OPENCODE_DATA_DIR`` / ``XDG_DATA_HOME`` and probes
the usual per-OS locations (Linux/macOS ``~/.local/share/opencode``, Windows
``%APPDATA%``/``%LOCALAPPDATA%``), so a daily OpenCode user is found without
``--data-dir``. Point ``--data-dir`` at the opencode data folder, its
``storage`` dir, or an ``opencode.db`` to override.

Parsing is tolerant by design: unknown fields are ignored, malformed JSON is
skipped, and a partially parsed session beats a crash. Reads are local and
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


# ---------------------------------------------------------------------------
# Data-dir resolution
# ---------------------------------------------------------------------------
def _candidate_data_dirs() -> list[Path]:
    """Every plausible OpenCode data directory on this machine, in priority order."""
    out: list[Path] = []

    def add(p: Path | None) -> None:
        if p is not None and p not in out:
            out.append(p)

    env = os.environ.get("OPENCODE_DATA_DIR")
    if env:
        add(Path(env))
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        add(Path(xdg) / "opencode")
    home = Path.home()
    add(home / ".local" / "share" / "opencode")  # Linux, and macOS default
    add(home / "Library" / "Application Support" / "opencode")  # macOS alt
    appdata = os.environ.get("APPDATA")
    if appdata:
        add(Path(appdata) / "opencode")
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        add(Path(local_appdata) / "opencode")
    return out


def _storage_root(data_dir: Path) -> Path | None:
    """Return the file-storage root under ``data_dir`` if it exists."""
    for candidate in (data_dir / "storage", data_dir):
        if (candidate / "session").is_dir():
            return candidate
    return None


def _legacy_db(data_dir: Path) -> Path | None:
    for candidate in (data_dir / "opencode.db", data_dir / "opencode" / "opencode.db"):
        if candidate.is_file():
            return candidate
    return None


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


def _created_ms(data: dict) -> object:
    """The message/session creation time, tolerating the couple of shapes seen."""
    time = _as_dict(data.get("time"))
    return time.get("created") or data.get("created") or data.get("time_created")


# ---------------------------------------------------------------------------
# Shared record -> model translation (identical for both storage formats)
# ---------------------------------------------------------------------------
def _step_from_message(data: dict, parts: list[dict]) -> Step:
    tokens = _as_dict(data.get("tokens"))
    cache = _as_dict(tokens.get("cache"))
    ts = _ms_to_dt(_created_ms(data))

    texts: list[str] = []
    calls: list[ToolCall] = []
    for part in parts:
        ptype = part.get("type")
        if ptype == "text" and isinstance(part.get("text"), str):
            texts.append(part["text"])
        elif ptype == "tool":
            calls.append(_tool_call(part))

    return Step(
        timestamp=ts,
        model=str(data.get("modelID") or data.get("model") or "unknown"),
        input_tokens=_int(tokens.get("input")),
        cache_creation_tokens=_int(cache.get("write")),
        cache_read_tokens=_int(cache.get("read")),
        output_tokens=_int(tokens.get("output")),
        tool_calls=calls,
        assistant_text="\n".join(texts),
    )


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


class OpenCodeAdapter(SessionAdapter):
    name = "opencode"

    def __init__(self) -> None:
        # Parse jobs queued by discover(), consumed one-per-path by parse().
        # Each job is ("json", session_file) or ("sqlite", session_id).
        self._jobs: deque[tuple[str, object]] = deque()
        self._storage: Path | None = None
        self._db: Path | None = None
        self._children: dict[str, list[str]] = {}

    # -- discovery ----------------------------------------------------------
    def discover(self, data_dir: Path | None = None) -> list[Path]:
        self._jobs.clear()
        self._storage = None
        self._db = None
        self._children = {}

        # An explicit --data-dir pointing straight at a db file: SQLite mode.
        if data_dir is not None and Path(data_dir).is_file():
            return self._discover_sqlite(Path(data_dir))

        roots = self._resolve_roots(data_dir)
        for root in roots:
            storage = _storage_root(root)
            if storage is not None:
                return self._discover_json(storage)
            db = _legacy_db(root)
            if db is not None:
                return self._discover_sqlite(db)
        return []

    def _resolve_roots(self, data_dir: Path | None) -> list[Path]:
        if data_dir is None:
            return _candidate_data_dirs()
        # A --data-dir may point at the storage dir itself, the data folder, or
        # a dir containing opencode.db; hand it to the probes below.
        return [Path(data_dir)]

    def _discover_json(self, storage: Path) -> list[Path]:
        self._storage = storage
        session_files = sorted((storage / "session").glob("*/*.json"))
        # Build the parent -> children map so sub-agent steps can be counted.
        top_level: list[Path] = []
        for sf in session_files:
            data = _load_json_file(sf)
            if not isinstance(data, dict):
                continue
            sid = str(data.get("id") or sf.stem)
            parent = data.get("parentID") or data.get("parent_id")
            if parent:
                self._children.setdefault(str(parent), []).append(sid)
            else:
                top_level.append(sf)
        for sf in top_level:
            self._jobs.append(("json", sf))
        # One path per session — the session file itself, so the --days mtime
        # filter reflects real per-session recency.
        return [sf for sf in top_level]

    def _discover_sqlite(self, db: Path) -> list[Path]:
        self._db = db
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
        ids = [str(r[0]) for r in rows]
        for sid in ids:
            self._jobs.append(("sqlite", sid))
        return [db for _ in ids]

    # -- parsing ------------------------------------------------------------
    def parse(self, path: Path) -> Session | None:
        if not self._jobs:
            return None
        kind, payload = self._jobs.popleft()
        if kind == "json":
            return self._parse_json_session(Path(str(payload)))
        return self._parse_sqlite_session(str(payload))

    def _parse_json_session(self, session_file: Path) -> Session | None:
        assert self._storage is not None
        data = _load_json_file(session_file)
        if not isinstance(data, dict):
            return None
        session_id = str(data.get("id") or session_file.stem)
        session = Session(
            session_id=session_id,
            source=self.name,
            project=self._json_project(data),
        )

        msg_dir = self._storage / "message" / session_id
        for mf in sorted(msg_dir.glob("*.json")):
            mdata = _load_json_file(mf)
            if not isinstance(mdata, dict):
                continue
            role = mdata.get("role")
            message_id = str(mdata.get("id") or mf.stem)
            parts = self._json_parts(message_id)
            if role == "assistant":
                step = _step_from_message(mdata, parts)
                session.steps.append(step)
                if session.started_at is None:
                    session.started_at = step.timestamp
                if step.timestamp is not None:
                    session.ended_at = step.timestamp
            elif role == "user":
                for part in parts:
                    if part.get("type") == "text" and isinstance(part.get("text"), str):
                        session.user_message_chars += len(part["text"])

        if not session.steps:
            return None
        session.sidechain_steps = self._json_sidechain_steps(session_id)
        return session

    def _json_parts(self, message_id: str) -> list[dict]:
        assert self._storage is not None
        part_dir = self._storage / "part" / message_id
        out: list[dict] = []
        for pf in sorted(part_dir.glob("*.json")):
            parsed = _load_json_file(pf)
            if isinstance(parsed, dict):
                out.append(parsed)
        return out

    def _json_project(self, session_data: dict) -> str:
        assert self._storage is not None
        project_id = session_data.get("projectID") or session_data.get("project_id")
        if project_id:
            pdata = _load_json_file(self._storage / "project" / f"{project_id}.json")
            if isinstance(pdata, dict):
                worktree = pdata.get("worktree") or pdata.get("directory")
                if isinstance(worktree, str) and worktree:
                    return worktree
        directory = session_data.get("directory")
        if isinstance(directory, str) and directory:
            return directory
        return str(session_data.get("id") or "unknown")

    def _json_sidechain_steps(self, session_id: str) -> int:
        assert self._storage is not None
        total = 0
        for child_id in self._children.get(session_id, []):
            msg_dir = self._storage / "message" / child_id
            for mf in msg_dir.glob("*.json"):
                mdata = _load_json_file(mf)
                if isinstance(mdata, dict) and mdata.get("role") == "assistant":
                    total += 1
        return total

    # -- legacy sqlite parsing ---------------------------------------------
    def _parse_sqlite_session(self, session_id: str) -> Session | None:
        db = self._db
        if db is None:
            return None
        conn = _connect(db)
        if conn is None:
            return None
        try:
            return self._parse_sqlite(conn, session_id)
        except sqlite3.Error:
            return None
        finally:
            conn.close()

    def _parse_sqlite(self, conn: sqlite3.Connection, session_id: str) -> Session | None:
        session = Session(
            session_id=session_id,
            source=self.name,
            project=self._sqlite_project(conn, session_id),
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
                parts = self._sqlite_parts(conn, str(message_id))
                step = _step_from_message(data, parts)
                session.steps.append(step)
                if session.started_at is None:
                    session.started_at = step.timestamp
                if step.timestamp is not None:
                    session.ended_at = step.timestamp
            elif role == "user":
                for part in self._sqlite_parts(conn, str(message_id)):
                    if part.get("type") == "text" and isinstance(part.get("text"), str):
                        session.user_message_chars += len(part["text"])
        if not session.steps:
            return None
        session.sidechain_steps = self._sqlite_sidechain(conn, session_id)
        return session

    def _sqlite_parts(self, conn: sqlite3.Connection, message_id: str) -> list[dict]:
        rows = conn.execute(
            "SELECT data FROM part WHERE message_id = ? ORDER BY time_created ASC, id ASC",
            (message_id,),
        ).fetchall()
        out: list[dict] = []
        for (raw,) in rows:
            parsed = _load_json(raw)
            if isinstance(parsed, dict):
                out.append(parsed)
        return out

    def _sqlite_project(self, conn: sqlite3.Connection, session_id: str) -> str:
        for query in (
            "SELECT p.worktree FROM session s JOIN project p ON p.id = s.project_id "
            "WHERE s.id = ?",
            "SELECT directory FROM session WHERE id = ?",
        ):
            try:
                row = conn.execute(query, (session_id,)).fetchone()
            except sqlite3.Error:
                row = None
            if row and isinstance(row[0], str) and row[0]:
                return row[0]
        return session_id

    def _sqlite_sidechain(self, conn: sqlite3.Connection, session_id: str) -> int:
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM message m JOIN session s ON s.id = m.session_id "
                "WHERE s.parent_id = ? AND json_extract(m.data, '$.role') = 'assistant'",
                (session_id,),
            ).fetchone()
        except sqlite3.Error:
            return 0
        return int(row[0]) if row and row[0] is not None else 0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _connect(db: Path) -> sqlite3.Connection | None:
    try:
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


def _load_json_file(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


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
