"""Gemini CLI (and Qwen Code) transcript adapter.

Gemini CLI (github.com/google-gemini/gemini-cli) records sessions under
``~/.gemini/tmp/<project-hash>/chats/``. Two on-disk formats exist:

- **Current (JSONL)**: ``session-<timestamp>-<shortid>.jsonl``. The first
  line is session metadata (``sessionId``, ``projectHash``, ``directories``,
  ``kind``); subsequent lines are message records, metadata patches
  (``{"$set": {...}}``), or rewinds (``{"$rewindTo": <messageId>}`` — the
  conversation was rolled back to that message, so later messages are
  dropped).
- **Legacy (single JSON)**: ``session-*.json`` holding one
  ``ConversationRecord`` object with the same metadata plus a ``messages``
  array.

A message record is ``{id, timestamp, type, content, ...}``; records with
``type: "gemini"`` are model API calls and carry ``model``, a ``tokens``
summary (``input``, ``output``, ``cached``, ``thoughts``, ``tool``,
``total``) and ``toolCalls`` (``{id, name, args, status, result}``). As with
the Gemini API's ``promptTokenCount``, ``tokens.input`` *includes* the cached
prefix, so the step stores ``input - cached`` as fresh input and ``cached``
as ``cache_read_tokens`` — ``Step.prompt_tokens`` then equals the true
context size. ``thoughts`` tokens are generated output and are added to
``output_tokens``.

Sub-agent sessions (``kind: "subagent"``, or files nested one directory
deeper than ``chats/``) are excluded from discovery/parsing, mirroring how
sidechains are excluded for other agents.

**Qwen Code** (github.com/QwenLM/qwen-code) is a Gemini CLI fork and keeps
the same layout under ``~/.qwen/tmp/``. Both roots are scanned by default;
sessions found under a ``.qwen`` root are labeled ``qwen-code`` so the two
CLIs stay distinguishable in reports.

Parsing is tolerant by design: unknown types and fields are ignored, records
that fail to decode are skipped, and a partially parsed session beats a
crash. Reads are local and read-only; no network access.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from contextrot.adapters.base import SessionAdapter
from contextrot.models import Session, Step, ToolCall

# Tool argument keys used as the retry/re-read "target", in priority order.
# Gemini CLI's read tools use ``absolute_path``; the rest mirror common shapes.
_TARGET_KEYS = (
    "absolute_path",
    "file_path",
    "path",
    "url",
    "pattern",
    "command",
    "query",
)


def _parse_ts(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _target_of(args: dict) -> str | None:
    for key in _TARGET_KEYS:
        val = args.get(key)
        if isinstance(val, str) and val:
            # For shell commands, the first line is enough to identify a retry.
            return val.split("\n", 1)[0][:300]
    return None


def _part_text(content: object) -> str:
    """Flatten a PartListUnion (str | Part | list of either) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        text = content.get("text")
        return text if isinstance(text, str) else ""
    if isinstance(content, list):
        return "\n".join(t for t in (_part_text(p) for p in content) if t)
    return ""


def _tool_call(record: dict) -> ToolCall:
    result = record.get("result")
    if isinstance(result, str):
        result_chars = len(result)
    elif result is not None:
        result_chars = len(_part_text(result)) or len(str(result))
    else:
        result_chars = 0
    status = str(record.get("status") or "").lower()
    is_error = status == "error"
    return ToolCall(
        name=str(record.get("name") or "unknown"),
        tool_use_id=str(record.get("id") or ""),
        target=_target_of(_as_dict(record.get("args"))),
        is_error=is_error,
        error_text=_part_text(result)[:500] if is_error else "",
        result_chars=result_chars,
    )


class GeminiCliAdapter(SessionAdapter):
    name = "gemini-cli"

    def discover(self, data_dir: Path | None = None) -> list[Path]:
        if data_dir is not None:
            roots = [data_dir]
        else:
            roots = [Path.home() / ".gemini" / "tmp", Path.home() / ".qwen" / "tmp"]
        found: list[Path] = []
        for root in roots:
            if not root.is_dir():
                continue
            for pattern in (
                "*/chats/session-*.json",
                "*/chats/session-*.jsonl",
                "chats/session-*.json",
                "chats/session-*.jsonl",
            ):
                found.extend(root.glob(pattern))
        return sorted(set(found))

    def parse(self, path: Path) -> Session | None:
        if path.suffix == ".jsonl":
            meta, messages = self._read_jsonl(path)
        else:
            meta, messages = self._read_json(path)
        if meta is None:
            return None
        if str(meta.get("kind") or "") == "subagent":
            return None

        source = self.name
        if ".qwen" in {p.lower() for p in path.parts}:
            source = "qwen-code"

        directories = meta.get("directories")
        project = ""
        if isinstance(directories, list) and directories and isinstance(directories[0], str):
            project = directories[0]
        if not project:
            project = str(meta.get("projectHash") or path.parent.parent.name or path.stem)

        session = Session(
            session_id=str(meta.get("sessionId") or path.stem),
            source=source,
            project=project,
            started_at=_parse_ts(meta.get("startTime")),
        )

        for record in messages:
            self._consume_message(record, session)

        if not session.steps:
            return None
        return session

    # -- internals ------------------------------------------------------------

    def _read_json(self, path: Path) -> tuple[dict | None, list[dict]]:
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError, ValueError):
            return None, []
        if not isinstance(data, dict):
            return None, []
        raw = data.get("messages")
        messages = [m for m in raw if isinstance(m, dict)] if isinstance(raw, list) else []
        return data, messages

    def _read_jsonl(self, path: Path) -> tuple[dict | None, list[dict]]:
        meta: dict | None = None
        messages: list[dict] = []
        try:
            with path.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(record, dict):
                        continue
                    if "$rewindTo" in record:
                        target = str(record["$rewindTo"])
                        for i, m in enumerate(messages):
                            if str(m.get("id")) == target:
                                del messages[i + 1 :]
                                break
                        continue
                    if "$set" in record:
                        patch = _as_dict(record["$set"])
                        if meta is not None:
                            meta.update(patch)
                        continue
                    if "type" in record and "id" in record:
                        messages.append(record)
                    elif "sessionId" in record:
                        meta = record if meta is None else {**meta, **record}
        except OSError:
            return None, []
        return meta if meta is not None else ({} if messages else None), messages

    def _consume_message(self, record: dict, session: Session) -> None:
        mtype = record.get("type")
        ts = _parse_ts(record.get("timestamp"))
        if mtype == "user":
            session.user_message_chars += len(_part_text(record.get("content")))
            return
        if mtype != "gemini":
            return

        tokens = _as_dict(record.get("tokens"))
        if not tokens:
            return  # no token accounting for this call — unusable for fill %
        raw_input = _int(tokens.get("input"))
        cached = min(_int(tokens.get("cached")), raw_input)
        calls = []
        raw_calls = record.get("toolCalls")
        if isinstance(raw_calls, list):
            calls = [_tool_call(c) for c in raw_calls if isinstance(c, dict)]

        step = Step(
            timestamp=ts,
            model=str(record.get("model") or "unknown"),
            input_tokens=raw_input - cached,
            cache_creation_tokens=0,
            cache_read_tokens=cached,
            output_tokens=_int(tokens.get("output")) + _int(tokens.get("thoughts")),
            tool_calls=calls,
            assistant_text=_part_text(record.get("content")),
        )
        session.steps.append(step)
        if session.started_at is None:
            session.started_at = ts
        if ts is not None:
            session.ended_at = ts
