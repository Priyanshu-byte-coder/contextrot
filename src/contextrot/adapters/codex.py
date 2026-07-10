"""Codex CLI transcript adapter.

Codex CLI (github.com/openai/codex) writes one JSONL "rollout" file per
session under ``~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<uuid>.jsonl``
(the date nesting appeared in recent versions; discovery is recursive so flat
layouts work too). Each line is ``{"timestamp": ..., "type": ..., "payload":
{...}}``. The types this adapter reads, as observed on Codex CLI 0.x rollouts:

- ``session_meta``: session id, ``cwd`` (the project), CLI version.
- ``turn_context``: carries the ``model`` in effect for the turn (and a
  possibly updated ``cwd``).
- ``response_item`` payloads — the durable model-conversation record:
  - ``function_call``: a tool call; ``name``, ``call_id``, and a JSON-encoded
    ``arguments`` string (``command``/``file_path``/... used as the target).
  - ``custom_tool_call``: free-form tools such as ``apply_patch``; ``input``
    is the raw patch text, from which the first touched file is the target.
  - ``function_call_output`` / ``custom_tool_call_output``: the result,
    matched back by ``call_id``. Shell outputs start with ``Exit code: N``;
    custom outputs are often JSON with ``metadata.exit_code``.
  - ``message`` with ``role: assistant``: assistant text (``output_text``
    blocks). ``user``/``developer`` messages are injected context and are
    counted only via the ``user_message`` event below.
- ``event_msg`` payloads — UI events; two matter:
  - ``token_count``: closes one model API call. ``info.last_token_usage``
    carries ``input_tokens`` (cached included, OpenAI-style),
    ``cached_input_tokens`` and ``output_tokens``; ``info.model_context_window``
    is the effective window, kept as the session's window hint. Entries with
    ``info: null`` are rate-limit-only heartbeats and are skipped.
  - ``user_message``: a real human prompt (used for user-typed chars, keeping
    injected ``<environment_context>`` out of the count).

Because ``input_tokens`` *includes* the cached prefix, the step stores
``input_tokens - cached_input_tokens`` as fresh input and the cached part as
``cache_read_tokens``, so ``Step.prompt_tokens`` (the sum) equals the true
context size and nothing is double counted. Reasoning tokens are already part
of ``output_tokens``.

Tool calls accumulate as ``response_item``s arrive and are attached to the
step created by the next ``token_count`` — the usage event for the API call
that emitted them. Results arrive later and are matched by ``call_id``.

Parsing is tolerant by design: unknown types and fields are ignored, lines
that fail to decode are skipped, and a partially parsed session beats a
crash. Reads are local and read-only; no network access.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from contextrot.adapters.base import SessionAdapter
from contextrot.models import Session, Step, ToolCall

# Tool argument keys used as the retry/re-read "target", in priority order.
_TARGET_KEYS = ("file_path", "path", "url", "pattern", "command", "query")

# First file touched by an apply_patch input, used as its target.
_PATCH_FILE_RE = re.compile(r"\*\*\* (?:Update|Add|Delete) File: (.+)")

# Shell outputs lead with their exit code.
_EXIT_CODE_RE = re.compile(r"^Exit code: (-?\d+)")


def _parse_ts(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _target_of(tool_input: dict) -> str | None:
    for key in _TARGET_KEYS:
        val = tool_input.get(key)
        if isinstance(val, str) and val:
            # For shell commands, the first line is enough to identify a retry.
            return val.split("\n", 1)[0][:300]
    return None


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _output_error(output: str) -> tuple[bool, str]:
    """Detect failure in a tool output string.

    Returns (is_error, error_text). Shell outputs start with ``Exit code: N``;
    custom tool outputs are often JSON carrying ``metadata.exit_code``.
    """
    m = _EXIT_CODE_RE.match(output)
    if m:
        return (m.group(1) != "0", output[:500] if m.group(1) != "0" else "")
    if output.startswith("{"):
        try:
            parsed = json.loads(output)
        except (json.JSONDecodeError, ValueError):
            return False, ""
        if isinstance(parsed, dict):
            exit_code = _as_dict(parsed.get("metadata")).get("exit_code")
            if isinstance(exit_code, int) and exit_code != 0:
                return True, output[:500]
    return False, ""


class CodexAdapter(SessionAdapter):
    name = "codex"

    def discover(self, data_dir: Path | None = None) -> list[Path]:
        root = data_dir or Path.home() / ".codex" / "sessions"
        if not root.is_dir():
            return []
        return sorted(root.rglob("rollout-*.jsonl"))

    def parse(self, path: Path) -> Session | None:
        session = Session(session_id=path.stem, source=self.name, project="")
        model = "unknown"
        # Tool calls made since the last token_count; the next one owns them.
        pending_calls: list[ToolCall] = []
        pending_texts: list[str] = []
        # call_id -> ToolCall so later *_output items can attach results.
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
                    model = self._consume(
                        entry, session, model, pending_calls, pending_texts, open_calls
                    )
        except OSError:
            return None

        if not session.steps:
            return None
        if not session.project:
            session.project = path.stem
        return session

    # -- internals ------------------------------------------------------------

    def _consume(
        self,
        entry: dict,
        session: Session,
        model: str,
        pending_calls: list[ToolCall],
        pending_texts: list[str],
        open_calls: dict[str, ToolCall],
    ) -> str:
        """Consume one rollout line; returns the (possibly updated) model."""
        etype = entry.get("type")
        payload = _as_dict(entry.get("payload"))
        ptype = payload.get("type")

        if etype == "session_meta":
            sid = payload.get("id")
            if isinstance(sid, str) and sid:
                session.session_id = sid
            cwd = payload.get("cwd")
            if isinstance(cwd, str) and cwd:
                session.project = cwd
            if session.started_at is None:
                session.started_at = _parse_ts(payload.get("timestamp"))
            return model

        if etype == "turn_context":
            new_model = payload.get("model")
            cwd = payload.get("cwd")
            if isinstance(cwd, str) and cwd:
                session.project = cwd
            return new_model if isinstance(new_model, str) and new_model else model

        if etype == "response_item":
            self._consume_response_item(payload, ptype, pending_calls, pending_texts, open_calls)
            return model

        if etype == "event_msg":
            if ptype == "token_count":
                self._consume_token_count(
                    payload, entry, session, model, pending_calls, pending_texts
                )
            elif ptype == "user_message" and isinstance(payload.get("message"), str):
                session.user_message_chars += len(payload["message"])
            return model

        return model

    def _consume_response_item(
        self,
        payload: dict,
        ptype: object,
        pending_calls: list[ToolCall],
        pending_texts: list[str],
        open_calls: dict[str, ToolCall],
    ) -> None:
        if ptype == "function_call":
            raw_args = payload.get("arguments")
            args: dict = {}
            if isinstance(raw_args, str):
                try:
                    parsed = json.loads(raw_args)
                    args = parsed if isinstance(parsed, dict) else {}
                except (json.JSONDecodeError, ValueError):
                    pass
            call = ToolCall(
                name=str(payload.get("name") or "unknown"),
                tool_use_id=str(payload.get("call_id") or ""),
                target=_target_of(args),
            )
            pending_calls.append(call)
            if call.tool_use_id:
                open_calls[call.tool_use_id] = call

        elif ptype == "custom_tool_call":
            raw_input = payload.get("input")
            target = None
            if isinstance(raw_input, str):
                m = _PATCH_FILE_RE.search(raw_input)
                target = m.group(1).strip()[:300] if m else None
            call = ToolCall(
                name=str(payload.get("name") or "unknown"),
                tool_use_id=str(payload.get("call_id") or ""),
                target=target,
            )
            pending_calls.append(call)
            if call.tool_use_id:
                open_calls[call.tool_use_id] = call

        elif ptype in ("function_call_output", "custom_tool_call_output"):
            call = open_calls.pop(str(payload.get("call_id") or ""), None)  # type: ignore[arg-type]
            output = payload.get("output")
            if call is None or not isinstance(output, str):
                return
            call.result_chars = len(output)
            call.is_error, call.error_text = _output_error(output)

        elif ptype == "message" and payload.get("role") == "assistant":
            content = payload.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and isinstance(block.get("text"), str):
                        pending_texts.append(block["text"])

    def _consume_token_count(
        self,
        payload: dict,
        entry: dict,
        session: Session,
        model: str,
        pending_calls: list[ToolCall],
        pending_texts: list[str],
    ) -> None:
        info = payload.get("info")
        if not isinstance(info, dict):
            return  # rate-limit-only heartbeat
        usage = _as_dict(info.get("last_token_usage")) or _as_dict(info.get("total_token_usage"))
        if not usage:
            return
        window = info.get("model_context_window")
        if isinstance(window, int) and window > 0:
            session.context_window_hint = window

        raw_input = _int(usage.get("input_tokens"))
        cached = min(_int(usage.get("cached_input_tokens")), raw_input)
        ts = _parse_ts(entry.get("timestamp"))
        step = Step(
            timestamp=ts,
            model=model,
            input_tokens=raw_input - cached,
            cache_creation_tokens=0,
            cache_read_tokens=cached,
            output_tokens=_int(usage.get("output_tokens")),
            tool_calls=list(pending_calls),
            assistant_text="\n".join(pending_texts),
        )
        pending_calls.clear()
        pending_texts.clear()
        session.steps.append(step)
        if session.started_at is None:
            session.started_at = ts
        if ts is not None:
            session.ended_at = ts
