"""Context-composition estimation.

Transcripts don't record the literal context content, but token accounting
lets us attribute where the window goes with useful accuracy:

- session overhead: prompt tokens of the *first* API call — system prompt,
  tool schemas, MCP schemas, CLAUDE.md — everything loaded before the user
  typed a word
- tool outputs: estimated from result characters (chars/4 heuristic)
- conversation: user + assistant text, same heuristic
- other growth: whatever remains of peak prompt size (thinking, file
  snapshots, framework bookkeeping)

Figures are labeled as estimates in every report.
"""

from __future__ import annotations

from dataclasses import dataclass

from contextrot.models import Session

CHARS_PER_TOKEN = 4


@dataclass
class Composition:
    overhead_tokens: int  # loaded before the first user word
    tool_output_tokens: int
    conversation_tokens: int
    other_growth_tokens: int
    peak_prompt_tokens: int
    context_window: int

    @property
    def overhead_pct_of_window(self) -> float:
        return 100.0 * self.overhead_tokens / max(self.context_window, 1)


def estimate_composition(sessions: list[Session], context_window: int) -> Composition:
    """Per-session average composition, so all figures share one scale.

    Tool-output and conversation figures are tokens that *flowed through*
    the session; with compaction they can exceed the window itself, which
    is exactly the point — that flow is what fills it.
    """
    n = max(len(sessions), 1)
    overhead_sum = tool_out = convo = 0
    peak_sum = 0
    for s in sessions:
        if s.steps:
            overhead_sum += s.steps[0].prompt_tokens
        peak_sum += s.peak_prompt_tokens
        for st in s.steps:
            convo += len(st.assistant_text) // CHARS_PER_TOKEN
            for c in st.tool_calls:
                tool_out += c.result_chars // CHARS_PER_TOKEN
        convo += s.user_message_chars // CHARS_PER_TOKEN

    overhead = overhead_sum // n
    avg_peak = peak_sum // n
    avg_tool = tool_out // n
    avg_convo = convo // n
    other = max(0, avg_peak - overhead - avg_tool - avg_convo)
    return Composition(
        overhead_tokens=overhead,
        tool_output_tokens=avg_tool,
        conversation_tokens=avg_convo,
        other_growth_tokens=other,
        peak_prompt_tokens=avg_peak,
        context_window=context_window,
    )
