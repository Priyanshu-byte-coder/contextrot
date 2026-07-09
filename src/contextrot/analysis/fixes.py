"""Actionable-fix inspection.

Turns the observational report into concrete, checkable targets:

- which MCP servers are *configured* but never actually used in the analyzed
  window (so their tool schemas sit in every session's startup overhead for
  nothing), and
- how big the CLAUDE.md loaded before your first word is.

Everything here is **read-only**. The only component that writes is the
``fix --apply`` path in the CLI, and it edits nothing except the top-level
``mcpServers`` block, always after a full backup. Config paths are injectable
so this module is testable without touching the real home directory.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from contextrot.analysis.composition import CHARS_PER_TOKEN
from contextrot.models import Session

# Claude Code namespaces MCP tools as ``mcp__<server>__<tool>``.
_MCP_TOOL_RE = re.compile(r"^mcp__([^_].*?)__")


def used_mcp_servers(sessions: list[Session]) -> set[str]:
    """Server names whose tools were actually called in the analyzed sessions."""
    used: set[str] = set()
    for session in sessions:
        for step in session.steps:
            for call in step.tool_calls:
                m = _MCP_TOOL_RE.match(call.name or "")
                if m:
                    used.add(m.group(1))
    return used


@dataclass
class ConfiguredServer:
    name: str
    scope: str  # "global" or "project"
    # For global servers: the config file to edit. For project servers: the
    # project path, used only to render a `claude mcp remove` hint.
    source: str


def configured_mcp_servers(claude_json: Path) -> list[ConfiguredServer]:
    """Read MCP servers from a Claude Code ``~/.claude.json``-shaped file.

    Returns global servers (top-level ``mcpServers``) and per-project servers
    (``projects[path].mcpServers``). A missing or malformed file yields ``[]``
    — this is a diagnostic, never a hard dependency.
    """
    try:
        data = json.loads(claude_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []

    out: list[ConfiguredServer] = []
    for name in (data.get("mcpServers") or {}):
        out.append(ConfiguredServer(name=name, scope="global", source=str(claude_json)))

    projects = data.get("projects")
    if isinstance(projects, dict):
        for path, pd in projects.items():
            if not isinstance(pd, dict):
                continue
            for name in (pd.get("mcpServers") or {}):
                out.append(ConfiguredServer(name=name, scope="project", source=path))
    return out


@dataclass
class UnusedServers:
    global_unused: list[ConfiguredServer] = field(default_factory=list)
    project_unused: list[ConfiguredServer] = field(default_factory=list)

    @property
    def any(self) -> bool:
        return bool(self.global_unused or self.project_unused)


def unused_mcp_servers(sessions: list[Session], claude_json: Path) -> UnusedServers:
    """Configured servers whose tools never fired in the analyzed window.

    A server is judged unused only if *no* analyzed session used it, so a
    server you rely on in one project is never flagged because another project
    doesn't touch it. Global and project-scoped servers are reported
    separately: only global ones are safe to auto-disable.
    """
    used = used_mcp_servers(sessions)
    result = UnusedServers()
    for srv in configured_mcp_servers(claude_json):
        if srv.name in used:
            continue
        if srv.scope == "global":
            result.global_unused.append(srv)
        else:
            result.project_unused.append(srv)
    return result


@dataclass
class ClaudeMdReport:
    path: str
    chars: int
    token_estimate: int


def claude_md_report(claude_md: Path) -> ClaudeMdReport | None:
    """Size of a CLAUDE.md, in chars and estimated tokens. ``None`` if absent."""
    try:
        text = claude_md.read_text(encoding="utf-8")
    except OSError:
        return None
    chars = len(text)
    return ClaudeMdReport(
        path=str(claude_md),
        chars=chars,
        token_estimate=chars // CHARS_PER_TOKEN,
    )


def disable_global_servers(
    claude_json: Path, names: list[str]
) -> tuple[Path, list[str]]:
    """Move named global servers out of ``mcpServers`` into a reversible stash.

    Writes a full ``<file>.contextrot.bak`` backup first, then moves each named
    server from the top-level ``mcpServers`` into ``contextrotDisabledMcpServers``
    so Claude Code stops loading it while the definition stays fully recoverable.
    Nothing else in the file is altered beyond these two keys. Returns the backup
    path and the list of names actually moved.

    This is the *only* function in contextrot that writes to the user's config,
    and the CLI calls it only under ``fix --apply`` with per-server confirmation.
    """
    data = json.loads(claude_json.read_text(encoding="utf-8"))
    servers = data.get("mcpServers") or {}
    stash = data.get("contextrotDisabledMcpServers") or {}

    moved: list[str] = []
    for name in names:
        if name in servers:
            stash[name] = servers.pop(name)
            moved.append(name)
    if not moved:
        return claude_json, []

    backup = claude_json.with_suffix(claude_json.suffix + ".contextrot.bak")
    backup.write_text(claude_json.read_text(encoding="utf-8"), encoding="utf-8")

    data["mcpServers"] = servers
    data["contextrotDisabledMcpServers"] = stash
    claude_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return backup, moved
