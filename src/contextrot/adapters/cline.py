"""Cline / Roo Code / Kilo Code transcript adapter.

Cline (github.com/cline/cline) and its forks Roo Code and Kilo Code are
VS Code extensions that store one directory per task under the host
editor's global storage::

    <globalStorage>/<publisher>/tasks/<task-id>/
        ui_messages.json               # UI event stream, incl. token accounting
        api_conversation_history.json  # the raw model conversation
        history_item.json              # (Roo) task metadata incl. workspace

``<globalStorage>`` is ``%APPDATA%/<app>/User/globalStorage`` on Windows,
``~/Library/Application Support/<app>/User/globalStorage`` on macOS and
``~/.config/<app>/User/globalStorage`` on Linux. Because these extensions run
in several editors, all common hosts are scanned: VS Code, VS Code Insiders,
VSCodium, Cursor, and Windsurf. Publisher directories map to the source
label: ``saoudrizwan.claude-dev`` → ``cline``, ``rooveterinaryinc.roo-cline``
→ ``roo-code``, ``kilocode.kilo-code`` → ``kilo-code``.

Token accounting: every model API call appends a ``{"type": "say", "say":
"api_req_started", "text": "{...}"}`` entry to ``ui_messages.json`` whose
``text`` JSON is updated in place once the request finishes with
``tokensIn``, ``tokensOut``, ``cacheWrites``, ``cacheReads`` and ``cost``.
These are Anthropic-style figures (``tokensIn`` excludes the cache), so they
map directly onto the normalized Step fields; requests that never recorded
any tokens (cancelled/failed before start) are skipped.

Tool calls: these extensions drive tools through XML-style tags embedded in
the assistant's text (``<read_file><path>...</path></read_file>``), one tool
per message; the outcome comes back in the *next* user message as a
``[tool_name for '...'] Result: ...`` block. The adapter pairs each
``api_req_started`` entry with the corresponding assistant message in
``api_conversation_history.json`` (both are in request order), extracts the
tool tag and its ``path``/``command``-like target, and judges failure from
well-known error phrases at the start of the result block ("Error", "The
tool execution failed", "Unable to apply diff", "The user denied", ...).
This is necessarily more heuristic than adapters with structured outcomes —
the format simply doesn't record a status flag — and it is documented here
so results can be interpreted accordingly.

The project is the workspace directory announced in the environment details
of the first user message (``# Current Workspace Directory (...)``), falling
back to ``history_item.json``'s ``workspace``.

Parsing is tolerant by design: unknown fields are ignored, malformed JSON is
skipped, and a partially parsed task beats a crash. Reads are local and
read-only; no network access.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from contextrot.adapters.base import SessionAdapter
from contextrot.models import Session, Step, ToolCall

_PUBLISHERS = {
    "saoudrizwan.claude-dev": "cline",
    "rooveterinaryinc.roo-cline": "roo-code",
    "kilocode.kilo-code": "kilo-code",
}

_HOST_APPS = ("Code", "Code - Insiders", "VSCodium", "Cursor", "Windsurf")

# One XML-style tool tag per assistant message; these are the file/command
# tools shared by Cline and its forks.
_TOOL_TAG_RE = re.compile(
    r"<(execute_command|read_file|write_to_file|replace_in_file|apply_diff"
    r"|insert_content|search_and_replace|search_files|list_files"
    r"|list_code_definition_names|browser_action|use_mcp_tool"
    r"|access_mcp_resource|codebase_search|edit_file|fetch_instructions)>"
    r"(.*?)</\1>",
    re.DOTALL,
)

# Target keys inside a tool tag, in priority order.
_INNER_TAGS = ("path", "file_path", "url", "regex", "command", "query")

_WORKSPACE_RE = re.compile(r"# Current Workspace Directory \(([^)]+)\)")
_MODEL_RE = re.compile(r"<model>([^<]+)</model>")
_USER_TEXT_RE = re.compile(
    r"<(task|user_message|feedback|answer)>(.*?)</\1>", re.DOTALL
)

# A result block opens with "[tool_name ..." — failures announce themselves
# in its first stretch with one of these phrases. A bare "error" only counts
# when the result *starts* with it, so ordinary file content mentioning
# errors is not flagged.
_ERROR_PHRASES = (
    "the tool execution failed",
    "unable to apply",
    "no sufficiently similar match",
    "the user denied",
    "did not match anything",
    "missing value for required parameter",
)


def _default_roots() -> list[Path]:
    home = Path.home()
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA") or (home / "AppData" / "Roaming"))
        bases = [appdata / app for app in _HOST_APPS]
    elif sys.platform == "darwin":
        support = home / "Library" / "Application Support"
        bases = [support / app for app in _HOST_APPS]
    else:
        bases = [home / ".config" / app for app in _HOST_APPS]
    return [b / "User" / "globalStorage" for b in bases]


def _ms_to_dt(raw: object) -> datetime | None:
    if not isinstance(raw, (int, float)) or raw <= 0:
        return None
    try:
        return datetime.fromtimestamp(raw / 1000, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _load_json_file(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _message_text(content: object) -> str:
    """Flatten an Anthropic-style content field (str | list of blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return ""


def _target_of(tag_body: str) -> str | None:
    for tag in _INNER_TAGS:
        m = re.search(rf"<{tag}>(.*?)</{tag}>", tag_body, re.DOTALL)
        if m:
            value = m.group(1).strip()
            if value:
                # For shell commands, the first line identifies a retry.
                return value.split("\n", 1)[0][:300]
    return None


def _result_block(user_text: str, tool_name: str) -> str | None:
    """Slice the ``[tool_name ...] Result:`` block out of a user message."""
    marker = f"[{tool_name}"
    start = user_text.find(marker)
    if start == -1:
        return None
    end = user_text.find("\n[", start + 1)
    return user_text[start : end if end != -1 else len(user_text)]


def _is_error_result(block: str) -> bool:
    head = block.split("Result:", 1)[-1].strip()[:250].lower()
    if head.startswith("error"):
        return True
    return any(phrase in head for phrase in _ERROR_PHRASES)


class ClineAdapter(SessionAdapter):
    name = "cline"

    def discover(self, data_dir: Path | None = None) -> list[Path]:
        found: list[Path] = []
        if data_dir is not None:
            # Accept a publisher dir (tasks/ beneath) or a globalStorage-like
            # dir (publisher/tasks/ beneath).
            for pattern in ("tasks/*/ui_messages.json", "*/tasks/*/ui_messages.json"):
                found.extend(data_dir.glob(pattern))
            return sorted(set(found))
        for root in _default_roots():
            if not root.is_dir():
                continue
            for publisher in _PUBLISHERS:
                found.extend(root.glob(f"{publisher}/tasks/*/ui_messages.json"))
        return sorted(set(found))

    def parse(self, path: Path) -> Session | None:
        task_dir = path.parent
        source = self.name
        for part in path.parts:
            label = _PUBLISHERS.get(part.lower())
            if label:
                source = label
                break

        ui = _load_json_file(path)
        if not isinstance(ui, list):
            return None
        requests = self._api_requests(ui)
        if not requests:
            return None

        history = _load_json_file(task_dir / "api_conversation_history.json")
        assistant_turns = self._assistant_turns(history if isinstance(history, list) else [])

        session = Session(
            session_id=task_dir.name,
            source=source,
            project=self._project(history if isinstance(history, list) else [], task_dir),
        )
        model = self._model(history if isinstance(history, list) else [])

        for i, req in enumerate(requests):
            calls, text = assistant_turns[i] if i < len(assistant_turns) else ([], "")
            ts = _ms_to_dt(req.get("ts"))
            step = Step(
                timestamp=ts,
                model=model,
                input_tokens=_int(req.get("tokensIn")),
                cache_creation_tokens=_int(req.get("cacheWrites")),
                cache_read_tokens=_int(req.get("cacheReads")),
                output_tokens=_int(req.get("tokensOut")),
                tool_calls=calls,
                assistant_text=text,
            )
            session.steps.append(step)
            if session.started_at is None:
                session.started_at = ts
            if ts is not None:
                session.ended_at = ts

        session.user_message_chars = self._user_chars(
            history if isinstance(history, list) else []
        )
        if not session.steps:
            return None
        return session

    # -- internals ------------------------------------------------------------

    def _api_requests(self, ui: list) -> list[dict]:
        """api_req_started entries with real token usage, in request order."""
        out: list[dict] = []
        for entry in ui:
            if not isinstance(entry, dict) or entry.get("say") != "api_req_started":
                continue
            raw = entry.get("text")
            if not isinstance(raw, str):
                continue
            try:
                info = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(info, dict):
                continue
            usage = sum(
                _int(info.get(k)) for k in ("tokensIn", "tokensOut", "cacheWrites", "cacheReads")
            )
            if usage == 0:
                continue  # cancelled / failed before the request produced anything
            info["ts"] = entry.get("ts")
            out.append(info)
        return out

    def _assistant_turns(self, history: list) -> list[tuple[list[ToolCall], str]]:
        """Per assistant message: its tool calls (with outcomes) and its text.

        The outcome of message N's tool call arrives in user message N+1 as a
        ``[tool_name ...] Result:`` block; both lists are in request order.
        """
        turns: list[tuple[list[ToolCall], str]] = []
        pending: list[ToolCall] = []
        for msg in history:
            if not isinstance(msg, dict):
                continue
            text = _message_text(msg.get("content"))
            role = msg.get("role")
            if role == "assistant":
                calls = []
                for m in _TOOL_TAG_RE.finditer(text):
                    calls.append(
                        ToolCall(
                            name=m.group(1),
                            tool_use_id="",
                            target=_target_of(m.group(2)),
                        )
                    )
                clean_text = _TOOL_TAG_RE.sub("", text).strip()
                turns.append((calls, clean_text))
                pending = calls
            elif role == "user" and pending:
                for call in pending:
                    block = _result_block(text, call.name)
                    if block is None:
                        continue
                    call.result_chars = max(len(block) - len(call.name) - 12, 0)
                    if _is_error_result(block):
                        call.is_error = True
                        call.error_text = block[:500]
                pending = []
        return turns

    def _project(self, history: list, task_dir: Path) -> str:
        for msg in history:
            if isinstance(msg, dict) and msg.get("role") == "user":
                m = _WORKSPACE_RE.search(_message_text(msg.get("content")))
                if m:
                    return m.group(1).strip()
        item = _load_json_file(task_dir / "history_item.json")
        if isinstance(item, dict) and isinstance(item.get("workspace"), str):
            return item["workspace"]
        return task_dir.name

    def _model(self, history: list) -> str:
        for msg in history:
            if isinstance(msg, dict) and msg.get("role") == "user":
                m = _MODEL_RE.search(_message_text(msg.get("content")))
                if m:
                    return m.group(1).strip()
        return "unknown"

    def _user_chars(self, history: list) -> int:
        total = 0
        for msg in history:
            if isinstance(msg, dict) and msg.get("role") == "user":
                for m in _USER_TEXT_RE.finditer(_message_text(msg.get("content"))):
                    total += len(m.group(2))
        return total
