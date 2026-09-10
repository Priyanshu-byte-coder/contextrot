"""Personal-curve calibration cache for live surfaces (statusline, hooks).

Every full analysis writes a tiny JSON snapshot of the user's measured rot
curves — knee, verdict, per-bucket failure rates — so that live surfaces (the
Claude Code statusline, the knee-crossing hook, ``contextrot status``) can
compare the *current* session's context fill against the user's *own* history
in milliseconds, without re-parsing thousands of transcript steps.

**Curves are scoped.** Schema 1 stored a single curve blended across every
agent, model and project, and every live surface read that one number. That
was wrong in a way that produced confident nonsense: a user whose OpenCode
sessions degrade at 60% fill would see "knee ~60%" while sitting in Claude
Code, whose own curve had no knee at all. Model mixing was worse still, since
a 200k-window model and a 1M-window model have different curves *and*
different denominators, and averaging them describes neither.

So the snapshot now stores one curve per scope — per agent, per model family,
and per agent+model pair — alongside the global one, and live surfaces
resolve the scope that matches the session in front of them:

    agent+model  ->  model  ->  agent  ->  global

Each rung must clear ``MIN_CALIBRATED_STEPS`` on its own before it is
trusted, so a narrow scope with thin data falls through to a broader one
rather than quoting a threshold built from noise. When the answer comes from
``global`` while narrower curves exist, callers are told, because a knee
borrowed from every agent at once is a weaker claim than your own.

This is a cache, not state: deleting the file loses nothing (the next report
run rewrites it), and nothing here ever leaves the machine.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from contextrot.modelkey import model_family

if TYPE_CHECKING:  # pragma: no cover
    from contextrot.analysis import AnalysisResult

SCHEMA_VERSION = 2

# A calibration built from fewer steps than this is too noisy to color a
# statusline with; live surfaces fall back to generic thresholds.
MIN_CALIBRATED_STEPS = 150

# A bucket needs this many steps before its rate is quoted as "your rate".
MIN_BUCKET_N = 30

# Scope kinds, most specific first. This is the resolution order.
SCOPE_ORDER = ("agent+model", "model", "agent", "global")


def calibration_path() -> Path:
    """Where the calibration cache lives. Overridable for tests."""
    env = os.environ.get("CONTEXTROT_CALIBRATION")
    if env:
        return Path(env)
    return Path.home() / ".contextrot" / "calibration.json"


def scope_key(kind: str, agent: str = "", model_key: str = "") -> str:
    """Stable dict key for one scope, e.g. ``agent+model:claude-code|opus-4.8``."""
    if kind == "global":
        return "global"
    if kind == "agent":
        return f"agent:{agent}"
    if kind == "model":
        return f"model:{model_key}"
    return f"agent+model:{agent}|{model_key}"


@dataclass
class Calibration:
    """One measured curve — for a single scope, or for everything combined.

    Live surfaces take one of these. They never see the whole file, so they
    cannot accidentally render a number from the wrong scope.
    """

    knee_pct: float | None
    verdict_kind: str
    low_fill_rate: float
    high_fill_rate: float
    steps: int
    days: int | None = None
    computed_at: str = ""
    buckets: list[dict] = field(default_factory=list)  # {"lo", "hi", "n", "rate"}
    # Which slice of your history produced this curve.
    scope_kind: str = "global"
    scope_label: str = ""
    # Which axis this curve mixes over: "" (measured on exactly this slice),
    # "agent" (one model, several agents), "model" (one agent, several models),
    # or "both". A blended curve can still carry another slice's threshold, so
    # live surfaces label it instead of presenting it as yours.
    blended_axis: str = ""
    # True when this curve is broader than the session that asked for it —
    # set by CalibrationSet.resolve when it fell back to the global curve
    # despite narrower ones existing. Callers surface it so a blended
    # threshold never passes for a personal one.
    is_fallback: bool = False

    @property
    def calibrated(self) -> bool:
        return self.steps >= MIN_CALIBRATED_STEPS

    @property
    def blend_note(self) -> str:
        """Short label naming what this curve mixes, or "" when it is exact."""
        return {
            "agent": "all agents",
            "model": "all models",
            "both": "all agents",
        }.get(self.blended_axis) or ""

    def rate_at_fill(self, fill_pct: float) -> float | None:
        """The measured failure rate in the bucket containing fill_pct.

        Returns None when the bucket is too small to quote honestly.
        """
        for b in self.buckets:
            lo, hi = b.get("lo", 0), b.get("hi", 0)
            if lo <= fill_pct < hi or (hi >= 100 and fill_pct >= lo):
                if b.get("n", 0) >= MIN_BUCKET_N:
                    return float(b.get("rate", 0.0))
                return None
        return None

    def deepest_reliable_fill(self) -> float | None:
        """Top of the deepest bucket that has enough steps to speak for itself.

        A flat curve means one of two very different things: context fill does
        not hurt this user, or they never fill the window far enough to find
        out. Quoting how deep the data actually reaches keeps those apart —
        with a 1M-token window most sessions never pass 80%.
        """
        best: float | None = None
        for b in self.buckets:
            if b.get("n", 0) >= MIN_BUCKET_N:
                try:
                    hi = float(b.get("hi", 0))
                except (TypeError, ValueError):
                    continue
                if best is None or hi > best:
                    best = hi
        return best


@dataclass
class CalibrationSet:
    """Every scoped curve from the last report run, plus the global one."""

    computed_at: str
    days: int | None
    global_curve: Calibration
    scopes: dict = field(default_factory=dict)  # scope key -> Calibration

    def resolve(self, agent: str = "", model: str = "") -> Calibration:
        """The narrowest trustworthy curve for this agent + model.

        Walks ``SCOPE_ORDER`` and returns the first scope that both exists and
        clears ``MIN_CALIBRATED_STEPS``. Falls back to the global curve, marked
        as a fallback when narrower curves exist so the caller can say so.
        """
        key = model_family(model) if model else ""
        candidates = []
        if agent and key:
            candidates.append(scope_key("agent+model", agent, key))
        if key:
            candidates.append(scope_key("model", model_key=key))
        if agent:
            candidates.append(scope_key("agent", agent=agent))

        for name in candidates:
            curve = self.scopes.get(name)
            if curve is not None and curve.calibrated:
                # A scope that blends over the other axis is still worth
                # quoting — it fixes at least one variable — but it is not
                # measured on exactly this slice, so it says so.
                return replace(curve, is_fallback=bool(curve.blended_axis))

        # Nothing specific enough is on file. The global curve is only a
        # *fallback* when narrower curves existed and none fit; with a
        # single-agent, single-model history it simply is your curve, and
        # marking it would be noise. Copy so repeated resolves never mutate
        # the shared instance.
        return replace(self.global_curve, is_fallback=bool(self.scopes))


def _curve_payload(curve, steps: int, verdict_kind: str) -> dict:
    """Serialize one RotCurve. Buckets with no steps are dropped."""
    return {
        "steps": steps,
        "verdict_kind": verdict_kind,
        "knee_pct": curve.knee_pct,
        "low_fill_rate": curve.low_fill_rate,
        "high_fill_rate": curve.high_fill_rate,
        "buckets": [
            {"lo": b.lo, "hi": b.hi, "n": b.n, "rate": round(b.rate, 4)}
            for b in curve.buckets
            if b.n
        ],
    }


def _scope_payloads(result: AnalysisResult) -> dict:
    """Every per-scope curve worth storing, keyed by scope.

    Grouped here rather than reused from the report's comparison builders: the
    curve maths is identical (``build_rot_curve`` + ``verdict``, the same pair
    the headline verdict uses), but the *inclusion* rules differ on purpose.
    A comparison hides a single-model user's only model, because a comparison
    against nothing is noise. A calibration must still store it, because that
    user still has a statusline.

    Each scope also records which axis it blends over. ``model:sonnet-4.6`` is
    a fine curve, but if two different agents contributed to it then it can
    still carry one agent's knee into the other's session — so the scope is
    marked, and the live surfaces say so rather than passing it off as yours.
    """
    from contextrot.analysis.by_source import agent_label
    from contextrot.analysis.rot import build_rot_curve, verdict
    from contextrot.modelkey import model_label

    by_agent: dict[str, list] = {}
    by_model: dict[str, list] = {}
    by_pair: dict[tuple[str, str], list] = {}
    agents_of_model: dict[str, set] = {}
    models_of_agent: dict[str, set] = {}

    for st in result.steps:
        if not st.source or not st.model:
            continue
        family = model_family(st.model)
        by_agent.setdefault(st.source, []).append(st)
        by_model.setdefault(family, []).append(st)
        by_pair.setdefault((st.source, family), []).append(st)
        agents_of_model.setdefault(family, set()).add(st.source)
        models_of_agent.setdefault(st.source, set()).add(family)

    out: dict = {}

    def add(key: str, group: list, label: str, kind: str, blended_axis: str) -> None:
        # Below the trust floor a scope can never be quoted anyway, so storing
        # it would only pad the file.
        if len(group) < MIN_CALIBRATED_STEPS:
            return
        curve = build_rot_curve(group)
        v_kind, _ = verdict(curve)
        out[key] = dict(
            _curve_payload(curve, len(group), v_kind),
            label=label,
            scope_kind=kind,
            blended_axis=blended_axis,
        )

    for source, group in by_agent.items():
        add(
            scope_key("agent", agent=source),
            group,
            agent_label(source),
            "agent",
            "model" if len(models_of_agent.get(source, ())) > 1 else "",
        )

    for family, group in by_model.items():
        add(
            scope_key("model", model_key=family),
            group,
            model_label(family),
            "model",
            "agent" if len(agents_of_model.get(family, ())) > 1 else "",
        )

    # The most specific scope, and the only one that separates "OpenCode
    # running Sonnet" from "Claude Code running Sonnet".
    for (source, family), group in by_pair.items():
        add(
            scope_key("agent+model", source, family),
            group,
            f"{agent_label(source)} + {model_label(family)}",
            "agent+model",
            "",
        )

    return out


def save_calibration(result: AnalysisResult, path: Path | None = None) -> Path | None:
    """Write the calibration snapshot. Silent no-op on any failure."""
    target = path or calibration_path()
    payload = {
        "schema": SCHEMA_VERSION,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "days": result.days,
        "global": dict(
            _curve_payload(result.curve, len(result.steps), result.verdict_kind),
            label="all agents and models",
            scope_kind="global",
            blended_axis="both",
        ),
        "scopes": _scope_payloads(result),
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return target
    except OSError:
        return None


def _rate(value: object) -> float:
    """A stored failure rate, tolerating the null a not-yet-populated zone writes."""
    if value is None:
        return 0.0
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _curve_from(raw: object, days: int | None, computed_at: str) -> Calibration | None:
    if not isinstance(raw, dict):
        return None
    try:
        return Calibration(
            knee_pct=raw.get("knee_pct"),
            verdict_kind=str(raw.get("verdict_kind", "insufficient")),
            # Rates are null when a zone has no steps yet (e.g. nothing has run
            # deep into a 1M-token window). Treat that as 0.0 rather than failing
            # the whole load — a dead calibration silently kills the statusline
            # and the hook.
            low_fill_rate=_rate(raw.get("low_fill_rate")),
            high_fill_rate=_rate(raw.get("high_fill_rate")),
            steps=int(raw.get("steps", 0)),
            days=days,
            computed_at=computed_at,
            buckets=[b for b in raw.get("buckets", []) if isinstance(b, dict)],
            scope_kind=str(raw.get("scope_kind", "global")),
            scope_label=str(raw.get("label", "")),
            blended_axis=str(raw.get("blended_axis", "")),
        )
    except (TypeError, ValueError):
        return None


def load_calibration(path: Path | None = None) -> CalibrationSet | None:
    """Read the calibration snapshot.

    None when missing, unreadable, or written by a different schema version.
    A stale schema is treated as absent rather than upgraded: this is a cache,
    and the next ``contextrot`` run rewrites it correctly.
    """
    target = path or calibration_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA_VERSION:
        return None

    days = raw.get("days")
    computed_at = str(raw.get("computed_at", ""))
    global_curve = _curve_from(raw.get("global"), days, computed_at)
    if global_curve is None:
        return None

    scopes: dict = {}
    for key, value in (raw.get("scopes") or {}).items():
        curve = _curve_from(value, days, computed_at)
        if curve is not None:
            scopes[str(key)] = curve

    return CalibrationSet(
        computed_at=computed_at,
        days=days if isinstance(days, int) else None,
        global_curve=global_curve,
        scopes=scopes,
    )
