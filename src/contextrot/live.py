"""Agent-agnostic detection of the session you're in *right now*.

The Claude Code statusline gets its context fill handed to it on stdin. No other
agent CLI offers that: Codex exposes only fixed native status items, OpenCode and
Gemini CLI have open feature requests for a command-backed statusline. So for
everyone else contextrot *pulls* instead of waiting to be pushed to — it finds the
most recently written transcript across every supported agent and reads the
current context fill straight off its tail.

That makes one command (``contextrot status``) usable from anywhere that can run a
shell command on a timer: tmux's status bar, a Starship module, a shell prompt, a
Waybar block — with any agent, including ones that expose no hook API at all.

Cheap by design: discovery only ``stat()``s files, and fill comes from the last
few KB of the newest transcript rather than a full parse. Reads are local and
read-only; contextrot makes zero network calls.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

# How much of a transcript's tail to scan for the latest usage entry.
TAIL_BYTES = 262_144


@dataclass
class LiveSession:
    """The most recently active agent session found on this machine."""

    source: str  # adapter name, e.g. "claude-code"
    fill_pct: float
    model: str
    path: Path
    age_seconds: float
    project: str = ""
    # Absolute context accounting, so a status bar can show 68k/200k rather
    # than only a percentage. 0 when the transcript didn't reveal them.
    prompt_tokens: int = 0
    window: int = 0

    @property
    def tokens_left(self) -> int:
        return max(0, self.window - self.prompt_tokens)


def _prompt_and_model(entry: dict) -> tuple[int, str, int | None] | None:
    """(prompt_tokens, model, window_hint) from one transcript line, if it has usage.

    Handles the JSONL shapes that carry token accounting per step:

    - Claude Code: ``{"type": "assistant", "message": {"model", "usage": {...}}}``
      where usage splits fresh input from cache reads/creation.
    - Codex CLI: ``{"type": "event_msg", "payload": {"type": "token_count",
      "info": {"last_token_usage": {...}, "model_context_window": N}}}`` where
      ``input_tokens`` already *includes* the cached prefix (OpenAI style).
    """
    etype = entry.get("type")

    if etype == "assistant":
        message = entry.get("message")
        if not isinstance(message, dict):
            return None
        usage = message.get("usage")
        if not isinstance(usage, dict):
            return None
        prompt = (
            int(usage.get("input_tokens") or 0)
            + int(usage.get("cache_creation_input_tokens") or 0)
            + int(usage.get("cache_read_input_tokens") or 0)
        )
        if prompt <= 0:
            return None
        return prompt, str(message.get("model") or ""), None

    if etype == "event_msg":
        payload = entry.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            return None
        info = payload.get("info")
        if not isinstance(info, dict):
            return None
        usage = info.get("last_token_usage") or info.get("total_token_usage")
        if not isinstance(usage, dict):
            return None
        # input_tokens already includes the cached prefix here, so it *is* the
        # context size — don't add cached_input_tokens on top of it.
        prompt = int(usage.get("input_tokens") or 0)
        if prompt <= 0:
            return None
        window = info.get("model_context_window")
        hint = int(window) if isinstance(window, int) and window > 0 else None
        return prompt, str(info.get("model") or ""), hint

    return None


def tail_fill(path: Path, max_bytes: int = TAIL_BYTES) -> float | None:
    """Context fill % from the last usage-bearing entry of a JSONL transcript.

    Returns None when the file isn't readable or holds no recognizable usage —
    callers fall back to a full adapter parse.
    """
    usage = tail_usage(path, max_bytes)
    if usage is None:
        return None
    prompt, window, _ = usage
    return min(100.0, 100.0 * prompt / max(window, 1))


def tail_usage(path: Path, max_bytes: int = TAIL_BYTES) -> tuple[int, int, str] | None:
    """(prompt_tokens, window, model) from the last usage entry of a transcript.

    The absolute numbers, not just the ratio, so a status bar can show
    ``68k/200k`` and how many tokens are left. Returns None when the file isn't
    readable or holds no recognizable usage.
    """
    from contextrot.pricing import context_window_for

    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()  # drop the partial first line
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None

    # Scanning backwards, the usage entry itself sometimes omits the model (and
    # the window depends on it), so remember the nearest model seen after it.
    nearest_model = ""
    for line in reversed(tail.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        found = _prompt_and_model(entry)
        if found is None:
            nearest_model = nearest_model or _model_of(entry)
            continue
        prompt, model, hint = found
        resolved = model or nearest_model
        window = context_window_for(resolved, hint)
        return prompt, window, resolved
    return None


def _model_of(entry: dict) -> str:
    """Any model id this transcript line mentions, for window resolution."""
    message = entry.get("message")
    if isinstance(message, dict) and isinstance(message.get("model"), str):
        return message["model"]
    payload = entry.get("payload")
    if isinstance(payload, dict) and isinstance(payload.get("model"), str):
        return payload["model"]
    if isinstance(entry.get("model"), str):
        return entry["model"]
    return ""


def _fill_via_adapter(
    adapter, path: Path, repeats: int = 1
) -> tuple[float, str, str, int, int] | None:
    """(fill_pct, model, project, prompt_tokens, window) from a full parse.

    For non-JSONL stores whose latest step can't be read off a tail.

    Covers OpenCode (SQLite / JSON file storage), Cline, and anything else whose
    latest step can't be read off a tail.

    ``repeats`` handles OpenCode's legacy SQLite mode, where ``discover()``
    returns the one database file once per session and ``parse()`` consumes them
    oldest-first from an internal queue: draining it and keeping the last
    successful parse gives the *newest* session rather than the oldest.
    """
    from contextrot.pricing import context_window_for

    latest = None
    for _ in range(max(1, repeats)):
        try:
            session = adapter.parse(path)
        except Exception:  # noqa: BLE001 — a live status must never crash a prompt
            break
        if session is None:
            break
        if session.steps:
            latest = session
    if latest is None:
        return None
    step = latest.steps[-1]
    window = context_window_for(step.model, latest.context_window_hint)
    fill = min(100.0, 100.0 * step.prompt_tokens / max(window, 1))
    return fill, step.model, latest.project, step.prompt_tokens, window


def _candidates(data_dir: Path | None) -> list[tuple[float, Path, object, str, int]]:
    """(mtime, path, adapter, source, repeats) for every discoverable transcript."""
    from contextrot.adapters import ADAPTERS

    out: list[tuple[float, Path, object, str, int]] = []
    for name, adapter in ADAPTERS.items():
        try:
            paths = adapter.discover(data_dir)
        except Exception:  # noqa: BLE001 — one broken adapter can't break status
            continue
        # A path can repeat (OpenCode's legacy single-database mode lists it once
        # per session); count the repeats instead of stat()ing it again.
        counts: dict[Path, int] = {}
        for p in paths:
            counts[p] = counts.get(p, 0) + 1
        for p, repeats in counts.items():
            try:
                out.append((p.stat().st_mtime, p, adapter, name, repeats))
            except OSError:
                continue
    return out


def detect_live_session(
    data_dir: Path | None = None,
    within_minutes: float | None = None,
) -> LiveSession | None:
    """The most recently written session across all agents, with its context fill.

    ``within_minutes`` keeps a prompt or status bar from showing a stale number:
    when the newest transcript is older than that, this returns None.
    """
    candidates = _candidates(data_dir)
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0], reverse=True)
    now = time.time()

    for mtime, path, adapter, source, repeats in candidates:
        age = max(0.0, now - mtime)
        if within_minutes is not None and age > within_minutes * 60:
            # Sorted newest-first, so nothing later can be fresh enough either.
            return None
        model = ""
        project = ""
        usage = tail_usage(path)
        if usage is not None:
            prompt_tokens, window, model = usage
            fill = min(100.0, 100.0 * prompt_tokens / max(window, 1))
        else:
            parsed = _fill_via_adapter(adapter, path, repeats)
            if parsed is None:
                continue
            fill, model, project, prompt_tokens, window = parsed
        return LiveSession(
            source=source,
            fill_pct=fill,
            model=model,
            path=path,
            age_seconds=age,
            project=project,
            prompt_tokens=prompt_tokens,
            window=window,
        )
    return None
