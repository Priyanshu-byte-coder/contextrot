"""Per-model rot comparison.

Groups steps by model family (e.g. "opus-4.8", "sonnet-3.5") and computes an
independent rot curve + verdict per family, reusing the exact statistics the
headline verdict uses. Models with too few steps are collapsed into a single
"Other" entry so nobody reads a verdict off ten data points.
"""

from __future__ import annotations

from dataclasses import dataclass

from contextrot.analysis.rot import RotCurve, build_rot_curve, verdict
from contextrot.modelkey import model_family, model_label
from contextrot.signals import StepSignals

# Below this many steps a model is folded into "Other" — same order of
# magnitude as VERDICT_MIN_N so per-model verdicts stay meaningful.
MODEL_MIN_STEPS = 150

# Re-exported: ``model_family``/``model_label`` moved to contextrot.modelkey
# (a dependency-free leaf the live surfaces can import cheaply), but they
# stay importable from here so existing callers keep working.
__all__ = ["MODEL_MIN_STEPS", "ModelStats", "build_model_comparison",
           "model_family", "model_label"]

@dataclass
class ModelStats:
    family: str
    label: str
    steps: int
    curve: RotCurve
    verdict_kind: str
    verdict_text: str
    is_other: bool = False


def build_model_comparison(
    steps: list[StepSignals], min_steps: int = MODEL_MIN_STEPS
) -> list[ModelStats]:
    """Per-model rot stats, or [] when fewer than two models qualify.

    A comparison against nothing is noise; callers hide the section on [].
    """
    groups: dict[str, list[StepSignals]] = {}
    for s in steps:
        groups.setdefault(model_family(s.model), []).append(s)

    qualifying = {fam: g for fam, g in groups.items() if len(g) >= min_steps}
    if len(qualifying) < 2:
        return []

    out: list[ModelStats] = []
    for fam, g in qualifying.items():
        curve = build_rot_curve(g)
        v_kind, v_text = verdict(curve)
        out.append(
            ModelStats(
                family=fam,
                label=model_label(fam),
                steps=len(g),
                curve=curve,
                verdict_kind=v_kind,
                verdict_text=v_text,
            )
        )
    out.sort(key=lambda m: m.steps, reverse=True)

    rest = [s for fam, g in groups.items() if fam not in qualifying for s in g]
    if rest:
        curve = build_rot_curve(rest)
        out.append(
            ModelStats(
                family="other",
                label="Other",
                steps=len(rest),
                curve=curve,
                verdict_kind="insufficient",
                verdict_text="",
                is_other=True,
            )
        )
    return out
