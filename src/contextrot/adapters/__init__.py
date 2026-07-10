"""Adapter registry."""

from __future__ import annotations

from contextrot.adapters.base import SessionAdapter
from contextrot.adapters.claude_code import ClaudeCodeAdapter
from contextrot.adapters.codex import CodexAdapter
from contextrot.adapters.gemini_cli import GeminiCliAdapter
from contextrot.adapters.opencode import OpenCodeAdapter

ADAPTERS: dict[str, SessionAdapter] = {
    ClaudeCodeAdapter.name: ClaudeCodeAdapter(),
    OpenCodeAdapter.name: OpenCodeAdapter(),
    CodexAdapter.name: CodexAdapter(),
    GeminiCliAdapter.name: GeminiCliAdapter(),
}

__all__ = [
    "ADAPTERS",
    "ClaudeCodeAdapter",
    "CodexAdapter",
    "GeminiCliAdapter",
    "OpenCodeAdapter",
    "SessionAdapter",
]
