"""Outcome-signal extraction.

Turns a normalized Session into per-step quality signals. Each signal is an
independent, deliberately simple heuristic; they are reported separately as
well as combined, so one noisy signal can't silently dominate the analysis.

Signals:

- tool_error:       any tool call in the step returned is_error
- edit_failure:     an editing tool (Edit/Write/MultiEdit/NotebookEdit)
                    returned is_error — the strongest "agent lost the plot"
                    signal for coding agents
- retry:            the step repeats a (tool, target) pair that errored in a
                    recent previous step
- reread:           the step re-Reads a file already read earlier in the
                    session (a proxy for the model losing track of context
                    it already had)
- self_correction:  assistant text contains apology/correction language
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ctxprof.models import Session

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "str_replace_editor", "apply_patch"}
READ_TOOLS = {"Read", "NotebookRead"}

_SELF_CORRECTION = re.compile(
    r"\b("
    r"i apologize|apologies|my mistake|my error|i made a mistake|i made an error"
    r"|let me (fix|correct) (that|this|my)"
    r"|that was (wrong|incorrect)|that's (wrong|incorrect)"
    r"|i was wrong|oops|correcting my"
    r")\b",
    re.IGNORECASE,
)

# How many steps back an error stays "recent" for retry matching.
_RETRY_WINDOW = 6

SIGNAL_NAMES = ["tool_error", "edit_failure", "retry", "reread", "self_correction"]


@dataclass
class StepSignals:
    """Signals for one step, alongside its context-fill measurement."""

    step_index: int
    prompt_tokens: int
    fill_pct: float
    model: str
    tool_error: bool = False
    edit_failure: bool = False
    retry: bool = False
    reread: bool = False
    self_correction: bool = False
    cost_usd: float = 0.0

    @property
    def degraded(self) -> bool:
        """Composite: any failure signal fired on this step."""
        return (
            self.tool_error
            or self.edit_failure
            or self.retry
            or self.reread
            or self.self_correction
        )

    def as_dict(self) -> dict:
        return {
            "step_index": self.step_index,
            "prompt_tokens": self.prompt_tokens,
            "fill_pct": round(self.fill_pct, 2),
            "model": self.model,
            **{name: getattr(self, name) for name in SIGNAL_NAMES},
            "degraded": self.degraded,
            "cost_usd": round(self.cost_usd, 6),
        }


@dataclass
class SessionSignals:
    session: Session
    steps: list[StepSignals] = field(default_factory=list)


def extract_signals(session: Session, context_window: int) -> SessionSignals:
    from ctxprof.pricing import step_cost_usd

    out = SessionSignals(session=session)
    # (tool, target) pairs that errored, mapped to the step index of the error.
    recent_errors: dict[tuple[str, str], int] = {}
    files_read: set[str] = set()

    for i, step in enumerate(session.steps):
        sig = StepSignals(
            step_index=i,
            prompt_tokens=step.prompt_tokens,
            fill_pct=min(100.0, 100.0 * step.prompt_tokens / max(context_window, 1)),
            model=step.model,
            cost_usd=step_cost_usd(
                step.input_tokens,
                step.cache_creation_tokens,
                step.cache_read_tokens,
                step.output_tokens,
                step.model,
            ),
        )

        for call in step.tool_calls:
            key = (call.name, call.target or "")

            if call.name in READ_TOOLS and call.target:
                if call.target in files_read:
                    sig.reread = True
                files_read.add(call.target)

            # A repeat of a recently errored (tool, target) is a retry,
            # whether or not this attempt succeeds.
            error_step = recent_errors.get(key)
            if error_step is not None and call.target and i - error_step <= _RETRY_WINDOW:
                sig.retry = True

            if call.is_error:
                sig.tool_error = True
                if call.name in EDIT_TOOLS:
                    sig.edit_failure = True
                if call.target:
                    recent_errors[key] = i

        if step.assistant_text and _SELF_CORRECTION.search(step.assistant_text):
            sig.self_correction = True

        out.steps.append(sig)

    return out
