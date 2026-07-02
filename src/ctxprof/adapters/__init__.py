"""Adapter registry."""

from __future__ import annotations

from ctxprof.adapters.base import SessionAdapter
from ctxprof.adapters.claude_code import ClaudeCodeAdapter

ADAPTERS: dict[str, SessionAdapter] = {
    ClaudeCodeAdapter.name: ClaudeCodeAdapter(),
}

__all__ = ["ADAPTERS", "SessionAdapter", "ClaudeCodeAdapter"]
