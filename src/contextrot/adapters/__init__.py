"""Adapter registry."""

from __future__ import annotations

from contextrot.adapters.base import SessionAdapter
from contextrot.adapters.claude_code import ClaudeCodeAdapter
from contextrot.adapters.opencode import OpenCodeAdapter

ADAPTERS: dict[str, SessionAdapter] = {
    ClaudeCodeAdapter.name: ClaudeCodeAdapter(),
    OpenCodeAdapter.name: OpenCodeAdapter(),
}

__all__ = ["ADAPTERS", "ClaudeCodeAdapter", "OpenCodeAdapter", "SessionAdapter"]
