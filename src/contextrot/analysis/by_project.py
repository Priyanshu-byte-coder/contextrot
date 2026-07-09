"""Per-project rot comparison.

Groups steps by the project (working directory) they ran in and computes an
independent rot curve + verdict per project, reusing the exact statistics the
headline verdict uses. Projects with too few steps are collapsed into a single
"Other" entry so nobody reads a verdict off a handful of data points.

This mirrors ``by_model.py`` — same shape, different grouping key — so the two
comparison axes stay consistent in the reports.
"""

from __future__ import annotations

from dataclasses import dataclass

from contextrot.analysis.rot import RotCurve, build_rot_curve, verdict
from contextrot.signals import StepSignals

# Below this many steps a project is folded into "Other" — same order of
# magnitude as VERDICT_MIN_N so per-project verdicts stay meaningful.
PROJECT_MIN_STEPS = 150


def project_label(project: str) -> str:
    """Last path component of a project working directory.

    Transcripts record the project as the agent's cwd, which may be a Windows
    path even when contextrot runs elsewhere (shared fixtures, copied transcript
    dirs) — so ``os.path`` can't be trusted here.
    """
    if not project:
        return "unknown"
    return project.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] or project


@dataclass
class ProjectStats:
    key: str  # raw project identifier (full cwd/slug)
    label: str  # display basename
    steps: int
    curve: RotCurve
    verdict_kind: str
    verdict_text: str
    is_other: bool = False


def build_project_comparison(
    steps: list[StepSignals],
    min_steps: int = PROJECT_MIN_STEPS,
    require_two: bool = True,
) -> list[ProjectStats]:
    """Per-project rot stats.

    Returns ``[]`` when fewer than two projects qualify and ``require_two`` is
    set (the default) — a comparison against nothing is noise, so the
    auto-embedded report section hides on ``[]``. The dedicated ``projects``
    subcommand passes ``require_two=False`` so a single-project user still gets
    that project's own curve + verdict.
    """
    groups: dict[str, list[StepSignals]] = {}
    for s in steps:
        groups.setdefault(s.project, []).append(s)

    qualifying = {key: g for key, g in groups.items() if len(g) >= min_steps}
    if require_two and len(qualifying) < 2:
        return []
    if not qualifying:
        return []

    out: list[ProjectStats] = []
    for key, g in qualifying.items():
        curve = build_rot_curve(g)
        v_kind, v_text = verdict(curve)
        out.append(
            ProjectStats(
                key=key,
                label=project_label(key),
                steps=len(g),
                curve=curve,
                verdict_kind=v_kind,
                verdict_text=v_text,
            )
        )
    out.sort(key=lambda p: p.steps, reverse=True)

    rest = [s for key, g in groups.items() if key not in qualifying for s in g]
    if rest:
        curve = build_rot_curve(rest)
        out.append(
            ProjectStats(
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
