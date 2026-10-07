"""Google Antigravity (CLI and IDE) adapter.

Antigravity keeps its data under ``~/.gemini/``: the CLI (which replaces Gemini
CLI) in ``antigravity-cli/``, the IDE in ``antigravity-ide/`` and, for older
IDE versions, ``antigravity/``. Each conversation is a SQLite database,
``conversations/<conversation-id>.db``. Older IDE versions wrote encrypted
``conversations/<id>.pb`` files instead; those cannot be read and are skipped.
Neither format is documented, so everything below was established by decoding
real databases and checking the result against the plain-text transcripts
Antigravity also writes for some conversations
(``brain/<id>/.system_generated/logs/transcript_full.jsonl``). The transcripts
alone are no use here: they carry no token counts.

Two tables matter, and both hold protobuf blobs:

- ``gen_metadata``: one row per model call. Field 1 holds the call:
  ``1.4`` is token usage (``.2`` fresh input, ``.5`` cache read, ``.3``
  output, ``.9`` thinking), ``1.19`` the model id, ``1.9.4`` the request
  time (seconds, nanos) and ``1.20`` string key/value pairs, among them
  ``model_enum`` when the model id is missing. Prompt size is fresh input
  plus cache read, which grows call to call by the previous output plus the
  new turn, as a context should.
- ``steps``: the conversation's steps, with an integer ``step_type`` (14 user
  input, 15 model response, 17 error message, others tool calls), a
  ``status`` (7 = error, alongside a non-null ``error_details``) and a
  payload whose ``5.1`` is the creation time, ``5.4.2`` the tool name and
  ``5.4.3`` the tool arguments as JSON. A ``run_command`` step stores its
  exit code at ``28.6``; a model response its text at ``20.1``.

Calls and steps carry no shared key that is always present, so steps are
attached by time: a tool step belongs to the latest call made before it, and
a user input opens a turn for the next call.

Antigravity manages its own context, compacting well before the model's
window is full, so its sessions rarely reach deep context. That is what the
data says, and the analysis reports it as such rather than rescaling.

Reads are local and read-only, and parsing is tolerant: a blob that doesn't
decode is skipped and a partially parsed conversation beats a crash.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from contextrot.adapters.base import SessionAdapter
from contextrot.models import Session, Step, ToolCall

# Each data directory and the source label its conversations get.
_ROOTS = (
    ("antigravity-cli", "antigravity-cli"),
    ("antigravity-ide", "antigravity"),
    ("antigravity", "antigravity"),
)

_USER_INPUT = 14
_MODEL_RESPONSE = 15
_ERROR_MESSAGE = 17
_STATUS_ERROR = 7

# Tool argument keys used as the retry/re-read "target", in priority order.
_TARGET_KEYS = (
    "AbsolutePath",
    "TargetFile",
    "DirectoryPath",
    "SearchPath",
    "CommandLine",
    "Query",
    "Url",
)

# Model ids sometimes missing from a call, recoverable from its enum.
_MODEL_ENUMS = {
    "MODEL_PLACEHOLDER_M16": "gemini-pro-default",
    "MODEL_PLACEHOLDER_M26": "claude-opus-4-6-thinking",
}


# -- protobuf wire format ---------------------------------------------------------


def _varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7
        if shift > 70:
            raise ValueError("varint too long")


def _fields(buf: object) -> dict[int, list]:
    """One level of a protobuf message: field number -> values (int or bytes)."""
    out: dict[int, list] = {}
    if not isinstance(buf, (bytes, bytearray)) or not buf:
        return out
    buf = bytes(buf)
    i, n = 0, len(buf)
    try:
        while i < n:
            key, i = _varint(buf, i)
            field, wire = key >> 3, key & 7
            if field == 0:
                break
            value: int | bytes
            if wire == 0:
                value, i = _varint(buf, i)
            elif wire == 2:
                size, i = _varint(buf, i)
                value = buf[i : i + size]
                i += size
            elif wire == 1:
                value, i = buf[i : i + 8], i + 8
            elif wire == 5:
                value, i = buf[i : i + 4], i + 4
            else:
                break
            out.setdefault(field, []).append(value)
    except (IndexError, ValueError):
        pass  # keep what decoded cleanly
    return out


def _get(buf: object, *path: int) -> object:
    """First value at a field path, descending into nested messages."""
    value: object = buf
    for field in path:
        if not isinstance(value, (bytes, bytearray)):
            return None
        found = _fields(bytes(value)).get(field)
        if not found:
            return None
        value = found[0]
    return value


def _int(value: object) -> int:
    return value if isinstance(value, int) else 0


def _str(value: object) -> str:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="replace")
    return ""


def _time(msg: object) -> datetime | None:
    """A google.protobuf.Timestamp (seconds, nanos) as an aware datetime."""
    if not isinstance(msg, (bytes, bytearray)):
        return None
    f = _fields(bytes(msg))
    seconds = _int((f.get(1) or [0])[0])
    if seconds <= 0:
        return None
    nanos = _int((f.get(2) or [0])[0])
    try:
        return datetime.fromtimestamp(seconds + nanos / 1e9, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


# -- SQLite ------------------------------------------------------------------------


def _connect(db: Path) -> sqlite3.Connection | None:
    # Read-only, honouring the WAL so a conversation still in progress is read
    # in full; immutable mode (which ignores the WAL) only as a fallback.
    for uri in (f"file:{db}?mode=ro", f"file:{db}?immutable=1"):
        try:
            conn = sqlite3.connect(uri, uri=True)
            conn.execute("SELECT 1 FROM gen_metadata LIMIT 1")
            return conn
        except sqlite3.Error:
            continue
    return None


def _rows(conn: sqlite3.Connection, sql: str) -> list[tuple]:
    try:
        return conn.execute(sql).fetchall()
    except sqlite3.Error:
        return []


class AntigravityAdapter(SessionAdapter):
    name = "antigravity"

    def discover(self, data_dir: Path | None = None) -> list[Path]:
        if data_dir is not None:
            candidates = list(data_dir.glob("conversations/*.db"))
            candidates += list(data_dir.glob("*/conversations/*.db"))
        else:
            home = Path.home() / ".gemini"
            candidates = []
            for folder, _ in _ROOTS:
                candidates += (home / folder / "conversations").glob("*.db")
        # The IDE has kept the same conversation in two data directories
        # across versions; count each conversation once, from its newest copy.
        newest: dict[str, Path] = {}
        for path in candidates:
            keep = newest.get(path.stem)
            if keep is None or _mtime(path) > _mtime(keep):
                newest[path.stem] = path
        return sorted(newest.values())

    def parse(self, path: Path) -> Session | None:
        conn = _connect(path)
        if conn is None:
            return None
        try:
            calls = self._calls(conn)
            if not calls:
                return None
            events = self._steps(conn)
            project = self._project(conn)
        finally:
            conn.close()

        session = Session(
            session_id=path.stem,
            source=_source_of(path),
            project=project or path.parent.parent.name,
        )

        # Merge calls and steps on one timeline. At equal times a user input
        # precedes the call it prompted, and a tool step follows its call.
        order = {"user": 0, "call": 1, "text": 2, "tool": 2}
        timeline: list[tuple[datetime, int, str, object]] = [
            (t, order["call"], "call", step) for t, step in calls
        ]
        timeline += [(t, order[kind], kind, item) for t, kind, item in events]
        timeline.sort(key=lambda e: (e[0], e[1]))

        current: Step | None = None
        for _, _, kind, item in timeline:
            if kind == "user":
                session.mark_turn_start()
            elif isinstance(item, Step):
                current = item
                session.add_step(current)
            elif current is None:
                continue
            elif isinstance(item, ToolCall):
                current.tool_calls.append(item)
            elif isinstance(item, str) and not current.assistant_text:
                current.assistant_text = item

        if not session.steps:
            return None
        stamps = [s.timestamp for s in session.steps if s.timestamp is not None]
        session.started_at = min(stamps, default=None)
        session.ended_at = max(stamps, default=None)
        return session

    def unreadable_note(self, data_dir: Path | None = None) -> str | None:
        if data_dir is None:
            folders = [Path.home() / ".gemini" / folder for folder, _ in _ROOTS]
        elif data_dir.is_dir():
            folders = [data_dir, *(p for p in data_dir.iterdir() if p.is_dir())]
        else:
            folders = []
        readable = {p.stem for p in self.discover(data_dir)}
        encrypted = {
            pb.stem
            for folder in folders
            for pb in (folder / "conversations").glob("*.pb")
            if pb.stem not in readable
        }
        if not encrypted:
            return None
        n = len(encrypted)
        return (
            f"{n} older Antigravity conversation{'s are' if n != 1 else ' is'} encrypted "
            "(.pb) and can't be read; conversations saved since Antigravity moved to "
            "SQLite are counted."
        )

    # -- internals ---------------------------------------------------------------

    def _calls(self, conn: sqlite3.Connection) -> list[tuple[datetime, Step]]:
        out = []
        for (blob,) in _rows(conn, "SELECT data FROM gen_metadata ORDER BY idx"):
            call = _get(blob, 1)
            usage = _get(call, 4)
            if not isinstance(usage, (bytes, bytearray)):
                continue  # a call without token accounting can't place a fill %
            u = _fields(usage)
            fresh = _int((u.get(2) or [0])[0])
            cached = _int((u.get(5) or [0])[0])
            if fresh + cached <= 0:
                continue
            ts = _time(_get(call, 9, 4))
            if ts is None:
                continue
            out.append((ts, Step(
                timestamp=ts,
                model=self._model(call),
                input_tokens=fresh,
                cache_read_tokens=cached,
                output_tokens=_int((u.get(3) or [0])[0]) + _int((u.get(9) or [0])[0]),
            )))
        return out

    @staticmethod
    def _model(call: object) -> str:
        model = _str(_get(call, 19))
        if model:
            return model
        for pair in _fields(call).get(20, []):
            if isinstance(pair, (bytes, bytearray)) and _str(_get(pair, 1)) == "model_enum":
                return _MODEL_ENUMS.get(_str(_get(pair, 2)), "unknown")
        return "unknown"

    def _steps(self, conn: sqlite3.Connection) -> list[tuple[datetime, str, object]]:
        out: list[tuple[datetime, str, object]] = []
        sql = "SELECT idx, step_type, status, error_details, step_payload FROM steps ORDER BY idx"
        for idx, step_type, status, error_details, payload in _rows(conn, sql):
            ts = _time(_get(payload, 5, 1))
            if ts is None:
                continue
            if step_type == _USER_INPUT:
                out.append((ts, "user", None))
                continue
            if step_type == _MODEL_RESPONSE:
                text = _str(_get(payload, 20, 1))
                if text:
                    out.append((ts, "text", text))
                continue
            name = _str(_get(payload, 5, 4, 2))
            if not name and step_type != _ERROR_MESSAGE:
                continue  # system and housekeeping steps, not tool calls
            args = _args(_str(_get(payload, 5, 4, 3)))
            is_error = status == _STATUS_ERROR or error_details is not None
            error_text = ""
            if step_type == _ERROR_MESSAGE:
                is_error = True
                error_text = _str(_get(payload, 24, 3, 1))[:500]
            exit_code = _get(payload, 28, 6)
            if name == "run_command" and isinstance(exit_code, int) and exit_code != 0:
                is_error = True
                error_text = f"exit code {exit_code}"
            out.append((ts, "tool", ToolCall(
                name=name or "invalid_tool_call",
                tool_use_id=str(idx),
                target=_target_of(args),
                is_error=is_error,
                error_text=error_text,
            )))
        return out

    @staticmethod
    def _project(conn: sqlite3.Connection) -> str:
        """The workspace folder, from the conversation's metadata."""
        for (blob,) in _rows(conn, "SELECT data FROM trajectory_metadata_blob"):
            for path in ((1, 1), (1, 2), (7,)):
                uri = _str(_get(blob, *path))
                if uri.startswith("file://"):
                    return _uri_to_path(uri)
        return ""


def _args(raw: str) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _target_of(args: dict) -> str | None:
    for key in _TARGET_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value:
            # For shell commands, the first line is enough to identify a retry.
            return value.split("\n", 1)[0][:300]
    return None


def _uri_to_path(uri: str) -> str:
    from urllib.parse import unquote, urlparse

    path = unquote(urlparse(uri).path)
    # file:///c:/Users/... -> c:/Users/...
    if len(path) > 2 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return path


def _source_of(path: Path) -> str:
    parts = {p.lower() for p in path.parts}
    for folder, label in _ROOTS:
        if folder in parts:
            return label
    return AntigravityAdapter.name


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
