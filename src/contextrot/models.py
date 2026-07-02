"""Normalized session model.

Every adapter converts its native transcript format into these structures.
All analysis code depends only on this module, never on a specific agent's
file format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ToolCall:
    """A single tool invocation and its outcome."""

    name: str
    tool_use_id: str
    # Coarse target used for retry/re-read detection: a file path for
    # file tools, the first token of a command for shell tools, etc.
    target: str | None = None
    is_error: bool = False
    error_text: str = ""
    result_chars: int = 0


@dataclass
class Step:
    """One model API call within a session.

    A step carries the token accounting for the request that produced it,
    the tool calls it made, and the assistant text it emitted. Context fill
    is derived from prompt-side tokens: everything the model had to read
    before producing this step.
    """

    timestamp: datetime | None
    model: str
    input_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0
    tool_calls: list[ToolCall] = field(default_factory=list)
    assistant_text: str = ""

    @property
    def prompt_tokens(self) -> int:
        """Total tokens the model read for this call (the context size)."""
        return self.input_tokens + self.cache_creation_tokens + self.cache_read_tokens


@dataclass
class Session:
    """A normalized agent session."""

    session_id: str
    source: str  # adapter name, e.g. "claude-code"
    project: str  # human-readable project identifier (cwd or slug)
    steps: list[Step] = field(default_factory=list)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    sidechain_steps: int = 0  # sub-agent steps excluded from main analysis
    user_message_chars: int = 0

    @property
    def peak_prompt_tokens(self) -> int:
        return max((s.prompt_tokens for s in self.steps), default=0)

    @property
    def total_cost_tokens(self) -> dict[str, int]:
        totals = {"input": 0, "cache_creation": 0, "cache_read": 0, "output": 0}
        for s in self.steps:
            totals["input"] += s.input_tokens
            totals["cache_creation"] += s.cache_creation_tokens
            totals["cache_read"] += s.cache_read_tokens
            totals["output"] += s.output_tokens
        return totals
