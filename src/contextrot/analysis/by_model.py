"""Per-model rot comparison.

Groups steps by model family (e.g. "opus-4.8", "sonnet-3.5") and computes an
independent rot curve + verdict per family, reusing the exact statistics the
headline verdict uses. Models with too few steps are collapsed into a single
"Other" entry so nobody reads a verdict off ten data points.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from contextrot.analysis.rot import RotCurve, build_rot_curve, verdict
from contextrot.signals import StepSignals

# Below this many steps a model is folded into "Other" — same order of
# magnitude as VERDICT_MIN_N so per-model verdicts stay meaningful.
MODEL_MIN_STEPS = 150

_PREFIX_RE = re.compile(r"^(?:(?:us|eu|apac)\.)?(?:anthropic\.)?(?:claude-)?")
_SUFFIX_RES = (
    re.compile(r"-v\d+:\d+$"),  # bedrock "-v1:0"
    re.compile(r"\[\dm\]$"),  # "[1m]" long-context marker
    re.compile(r"-latest$"),
    re.compile(r"-\d{8}$"),  # trailing date "-20241022"
)
_FAMILY_RE = re.compile(r"(opus|sonnet|haiku)")


def model_family(model_id: str) -> str:
    """Canonical family key for a raw model id.

    "claude-opus-4-8" -> "opus-4.8"; "claude-3-5-sonnet-20241022" -> "sonnet-3.5";
    "us.anthropic.claude-sonnet-4-6-v1:0" -> "sonnet-4.6"; unknown -> "unknown".
    """
    s = (model_id or "").strip().lower()
    if not s:
        return "unknown"
    s = _PREFIX_RE.sub("", s)
    for rx in _SUFFIX_RES:
        s = rx.sub("", s)
    m = _FAMILY_RE.search(s)
    if not m:
        return "unknown"
    family = m.group(1)
    before = s[: m.start()].strip("-")
    after = s[m.end() :].strip("-")
    # Version digits sit after the family word in new ids ("sonnet-4-6"),
    # before it in old ones ("3-5-sonnet").
    digits = after if re.fullmatch(r"\d+(-\d+)*", after or "") else None
    if digits is None and re.fullmatch(r"\d+(-\d+)*", before or ""):
        digits = before
    if digits:
        return f"{family}-{digits.replace('-', '.')}"
    return family


def model_label(family: str) -> str:
    """Display label: "opus-4.8" -> "Opus 4.8"."""
    parts = family.split("-", 1)
    name = parts[0].capitalize()
    return f"{name} {parts[1]}" if len(parts) > 1 else name


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
