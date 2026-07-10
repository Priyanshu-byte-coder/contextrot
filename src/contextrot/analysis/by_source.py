"""Per-agent rot comparison.

Groups steps by the agent CLI that produced them (the adapter source) and
computes an independent rot curve + verdict per agent, reusing the exact
statistics the headline verdict uses. Agents with too few steps are collapsed
into a single "Other" entry so nobody reads a verdict off a handful of data
points.

This mirrors ``by_model.py`` / ``by_project.py`` — same shape, different
grouping key — so the comparison axes stay consistent in the reports.
"""

from __future__ import annotations

from dataclasses import dataclass

from contextrot.analysis.rot import RotCurve, build_rot_curve, verdict
from contextrot.signals import StepSignals

# Below this many steps an agent is folded into "Other" — same order of
# magnitude as VERDICT_MIN_N so per-agent verdicts stay meaningful.
AGENT_MIN_STEPS = 150

# Adapter source names -> display labels.
_AGENT_LABELS = {
    "claude-code": "Claude Code",
    "opencode": "OpenCode",
    "codex": "Codex CLI",
    "gemini-cli": "Gemini CLI",
    "qwen-code": "Qwen Code",
    "cline": "Cline",
    "roo-code": "Roo Code",
    "kilo-code": "Kilo Code",
}


def agent_label(source: str) -> str:
    if not source:
        return "unknown"
    return _AGENT_LABELS.get(source, source)


@dataclass
class AgentStats:
    key: str  # adapter source name, e.g. "claude-code"
    label: str  # display name, e.g. "Claude Code"
    steps: int
    curve: RotCurve
    verdict_kind: str
    verdict_text: str
    is_other: bool = False


def build_agent_comparison(
    steps: list[StepSignals],
    min_steps: int = AGENT_MIN_STEPS,
    require_two: bool = True,
) -> list[AgentStats]:
    """Per-agent rot stats.

    Returns ``[]`` when fewer than two agents qualify and ``require_two`` is
    set (the default) — a comparison against nothing is noise, so the
    auto-embedded report section hides on ``[]``. The dedicated ``agents``
    subcommand passes ``require_two=False`` so a single-agent user still gets
    that agent's own curve + verdict.
    """
    groups: dict[str, list[StepSignals]] = {}
    for s in steps:
        groups.setdefault(s.source, []).append(s)

    qualifying = {key: g for key, g in groups.items() if len(g) >= min_steps}
    if require_two and len(qualifying) < 2:
        return []
    if not qualifying:
        return []

    out: list[AgentStats] = []
    for key, g in qualifying.items():
        curve = build_rot_curve(g)
        v_kind, v_text = verdict(curve)
        out.append(
            AgentStats(
                key=key,
                label=agent_label(key),
                steps=len(g),
                curve=curve,
                verdict_kind=v_kind,
                verdict_text=v_text,
            )
        )
    out.sort(key=lambda a: a.steps, reverse=True)

    rest = [s for key, g in groups.items() if key not in qualifying for s in g]
    if rest:
        curve = build_rot_curve(rest)
        out.append(
            AgentStats(
                key="other",
                label="Other",
                steps=len(rest),
                curve=curve,
                verdict_kind="insufficient",
                verdict_text="",
                is_other=True,
            )
        )
    return out
