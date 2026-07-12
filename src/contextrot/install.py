"""Safe installer for Claude Code live surfaces (statusline, hooks).

Same safety contract as ``contextrot fix``: dry-run by default, an explicit
``--apply`` plus confirmation to write, a ``.contextrot.bak`` backup beside
any file touched, and never clobbering configuration that isn't ours
without ``--force``.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def claude_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def surface_command(surface: str) -> str:
    """The shell command Claude Code should run for a live surface.

    Prefers the console script when it's on PATH; otherwise falls back to
    the current interpreter so uvx/venv installs still work.
    """
    if shutil.which("contextrot"):
        return f"contextrot {surface}"
    py = sys.executable or "python"
    quoted = f'"{py}"' if " " in py else py
    return f"{quoted} -m contextrot {surface}"


def read_settings(path: Path) -> dict:
    """Parse a settings file. Missing file is an empty config; invalid JSON raises."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("settings root is not a JSON object")
    return raw


def backup_path_for(path: Path) -> Path:
    return Path(str(path) + ".contextrot.bak")


def write_settings_with_backup(path: Path, settings: dict) -> Path | None:
    """Write settings JSON, copying the previous file to a backup first."""
    backup: Path | None = None
    if path.exists():
        backup = backup_path_for(path)
        shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return backup


def is_contextrot_entry(value: object) -> bool:
    """True when a settings value was written by contextrot (safe to replace)."""
    try:
        return "contextrot" in json.dumps(value)
    except (TypeError, ValueError):
        return False


def statusline_entry() -> dict:
    return {"type": "command", "command": surface_command("statusline")}


def hook_entry() -> dict:
    """The PostToolUse matcher entry for the knee-crossing warning."""
    return {
        "matcher": "",
        "hooks": [{"type": "command", "command": surface_command("hook"), "timeout": 10}],
    }


def _post_tool_use(settings: dict) -> list:
    hooks_cfg = settings.get("hooks")
    if not isinstance(hooks_cfg, dict):
        return []
    entries = hooks_cfg.get("PostToolUse")
    return entries if isinstance(entries, list) else []


def has_hook(settings: dict) -> bool:
    return any(is_contextrot_entry(e) for e in _post_tool_use(settings))


def add_hook(settings: dict) -> None:
    """Append our PostToolUse entry, preserving everything already there."""
    hooks_cfg = settings.setdefault("hooks", {})
    entries = hooks_cfg.setdefault("PostToolUse", [])
    entries.append(hook_entry())


def remove_hook(settings: dict) -> bool:
    """Remove our PostToolUse entries only. Returns True when something was removed."""
    entries = _post_tool_use(settings)
    kept = [e for e in entries if not is_contextrot_entry(e)]
    if len(kept) == len(entries):
        return False
    settings["hooks"]["PostToolUse"] = kept
    if not kept:
        del settings["hooks"]["PostToolUse"]
    if not settings["hooks"]:
        del settings["hooks"]
    return True
