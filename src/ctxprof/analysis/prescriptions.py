"""Prescription engine v1.

Rule-based recommendations, each quantified from the user's own data.
A prescription is only emitted when its evidence threshold is met — an
empty list is a valid, honest output.
"""

from __future__ import annotations

from dataclasses import dataclass

from ctxprof.analysis.composition import Composition
from ctxprof.analysis.rot import RotCurve


@dataclass
class Prescription:
    title: str
    detail: str
    impact: str  # quantified expected benefit
    priority: int  # lower = more important


def prescribe(
    curve: RotCurve,
    comp: Composition,
    rework_cost_usd: float,
    steps_past_knee: int,
) -> list[Prescription]:
    out: list[Prescription] = []

    if curve.knee_pct is not None and curve.high_fill_rate and curve.low_fill_rate:
        out.append(
            Prescription(
                title=f"Compact or restart sessions before ~{curve.knee_pct}% context fill",
                detail=(
                    f"Your failure-signal rate rises from "
                    f"{curve.low_fill_rate:.1%} below {int(curve.knee_pct)}% fill to "
                    f"{curve.high_fill_rate:.1%} in deep context. "
                    f"{steps_past_knee} of your recent steps ran past that threshold."
                ),
                impact=(
                    f"Estimated ${rework_cost_usd:.2f} of recent spend went to degraded "
                    "steps and their retries; most of it is concentrated past the knee."
                ),
                priority=1,
            )
        )

    if comp.overhead_pct_of_window >= 15:
        out.append(
            Prescription(
                title="Audit your session startup overhead",
                detail=(
                    f"On average, ~{comp.overhead_tokens:,} tokens "
                    f"({comp.overhead_pct_of_window:.0f}% of the context window) are "
                    "loaded before your first word — system prompt, MCP tool schemas, "
                    "CLAUDE.md. Disable MCP servers you don't use in this project and "
                    "trim stale CLAUDE.md sections."
                ),
                impact=(
                    "Every point of startup overhead is a point of working context "
                    "you never get back, in every session."
                ),
                priority=2,
            )
        )

    total_growth = comp.tool_output_tokens + comp.conversation_tokens + comp.other_growth_tokens
    if total_growth > 0 and comp.tool_output_tokens / total_growth >= 0.5:
        out.append(
            Prescription(
                title="Tool outputs dominate your context growth",
                detail=(
                    f"~{comp.tool_output_tokens:,} tokens (est.) of context growth come "
                    "from tool results. Prefer targeted reads (offsets, limits), "
                    "narrower searches, and quieter commands over dumping whole files "
                    "and logs into the window."
                ),
                impact="Slower fill means more steps before the degradation zone.",
                priority=3,
            )
        )

    reread_total = curve.signal_totals.get("reread", 0)
    if curve.total_steps and reread_total / curve.total_steps >= 0.08:
        out.append(
            Prescription(
                title="Your agent frequently re-reads files it already read",
                detail=(
                    f"Re-reads fired on {reread_total} steps "
                    f"({reread_total / curve.total_steps:.0%}). That usually means the "
                    "original content scrolled out of effective attention. Splitting "
                    "large tasks into shorter sessions keeps files 'fresh'."
                ),
                impact="Fewer re-reads is both cheaper and a direct rot symptom removed.",
                priority=4,
            )
        )

    return sorted(out, key=lambda p: p.priority)
