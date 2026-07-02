"""Claude Code transcript adapter.

Claude Code stores each session as a JSONL file under
``~/.claude/projects/<project-slug>/<session-uuid>.jsonl``. Relevant entry
types:

- ``assistant``: one model API call. ``message.usage`` carries token
  accounting (``input_tokens``, ``cache_creation_input_tokens``,
  ``cache_read_input_tokens``, ``output_tokens``); ``message.content`` is a
  list of blocks (``text``, ``thinking``, ``tool_use``).
- ``user``: either a human prompt (string content) or tool results
  (``tool_result`` blocks with ``tool_use_id`` and ``is_error``).
- ``isSidechain: true`` marks sub-agent traffic; it is counted but excluded
  from the main step list so fill percentages reflect the primary context
  window.

Format observed on Claude Code 2.x. Parsing is tolerant by design: fields
we don't recognize are ignored, lines that fail to decode are skipped.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ctxprof.adapters.base import SessionAdapter
from ctxprof.models import Session, Step, ToolCall

# Tool input keys used as the retry/re-read "target", in priority order.
_TARGET_KEYS = ("file_path", "path", "url", "pattern", "command", "query")


def _parse_ts(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _target_of(name: str, tool_input: dict) -> str | None:
    for key in _TARGET_KEYS:
        val = tool_input.get(key)
        if isinstance(val, str) and val:
            # For shell commands, the first line is enough to identify a retry.
            return val.split("\n", 1)[0][:300]
    return None


def _result_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return ""


class ClaudeCodeAdapter(SessionAdapter):
    name = "claude-code"

    def discover(self, data_dir: Path | None = None) -> list[Path]:
        root = data_dir or Path.home() / ".claude" / "projects"
        if not root.is_dir():
            return []
        return sorted(root.glob("*/*.jsonl"))

    def parse(self, path: Path) -> Session | None:
        session = Session(
            session_id=path.stem,
            source=self.name,
            project=path.parent.name,
        )
        # tool_use_id -> ToolCall, so results (which arrive in later user
        # entries) can be attached to the step that made the call.
        open_calls: dict[str, ToolCall] = {}

        try:
            with path.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(entry, dict):
                        continue
                    self._consume(entry, session, open_calls)
        except OSError:
            return None

        if not session.steps:
            return None

        # Use the real working directory as the project name when present.
        return session

    def _consume(self, entry: dict, session: Session, open_calls: dict[str, ToolCall]) -> None:
        etype = entry.get("type")
        if etype == "assistant":
            if entry.get("isSidechain"):
                session.sidechain_steps += 1
                return
            self._consume_assistant(entry, session, open_calls)
        elif etype == "user" and not entry.get("isSidechain"):
            self._consume_user(entry, session, open_calls)

        cwd = entry.get("cwd")
        if isinstance(cwd, str) and cwd:
            session.project = cwd

    def _consume_assistant(
        self, entry: dict, session: Session, open_calls: dict[str, ToolCall]
    ) -> None:
        message = entry.get("message")
        if not isinstance(message, dict):
            return
        usage = message.get("usage")
        ts = _parse_ts(entry.get("timestamp"))

        content = message.get("content")
        texts: list[str] = []
        calls: list[ToolCall] = []
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text" and isinstance(block.get("text"), str):
                    texts.append(block["text"])
                elif btype == "tool_use":
                    name = block.get("name") or "unknown"
                    raw_input = block.get("input")
                    tool_input: dict = raw_input if isinstance(raw_input, dict) else {}
                    call = ToolCall(
                        name=str(name),
                        tool_use_id=str(block.get("id") or ""),
                        target=_target_of(str(name), tool_input),
                    )
                    calls.append(call)
                    if call.tool_use_id:
                        open_calls[call.tool_use_id] = call

        # Claude Code streams one API call across several assistant entries
        # that share a requestId; usage rides on each. Merge by requestId so
        # a single call isn't double counted: only the entry that carries
        # usage starts a new step, subsequent content is folded in.
        if isinstance(usage, dict):
            step = Step(
                timestamp=ts,
                model=str(message.get("model") or "unknown"),
                input_tokens=int(usage.get("input_tokens") or 0),
                cache_creation_tokens=int(usage.get("cache_creation_input_tokens") or 0),
                cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                tool_calls=calls,
                assistant_text="\n".join(texts),
            )
            session.steps.append(step)
            if session.started_at is None:
                session.started_at = ts
            if ts is not None:
                session.ended_at = ts
        elif session.steps:
            last = session.steps[-1]
            last.tool_calls.extend(calls)
            if texts:
                last.assistant_text = (last.assistant_text + "\n" + "\n".join(texts)).strip()

    def _consume_user(self, entry: dict, session: Session, open_calls: dict[str, ToolCall]) -> None:
        message = entry.get("message")
        if not isinstance(message, dict):
            return
        content = message.get("content")
        if isinstance(content, str):
            session.user_message_chars += len(content)
            return
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                call = open_calls.pop(str(block.get("tool_use_id") or ""), None)
                if call is None:
                    continue
                text = _result_text(block.get("content"))
                call.result_chars = len(text)
                if block.get("is_error"):
                    call.is_error = True
                    call.error_text = text[:500]
            elif block.get("type") == "text" and isinstance(block.get("text"), str):
                session.user_message_chars += len(block["text"])
