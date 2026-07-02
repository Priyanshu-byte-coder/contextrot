"""Analysis orchestrator: transcripts in, AnalysisResult out."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from contextrot.adapters import ADAPTERS
from contextrot.analysis.composition import Composition, estimate_composition
from contextrot.analysis.prescriptions import Prescription, prescribe
from contextrot.analysis.rot import RotCurve, build_rot_curve
from contextrot.models import Session
from contextrot.pricing import DEFAULT_CONTEXT_WINDOW, context_window_for
from contextrot.signals import StepSignals, extract_signals


@dataclass
class AnalysisResult:
    sessions: list[Session]
    steps: list[StepSignals]
    curve: RotCurve
    composition: Composition
    prescriptions: list[Prescription]
    context_window: int
    total_cost_usd: float
    rework_cost_usd: float  # cost of degraded steps + their outputs
    steps_past_knee: int
    days: int | None
    skipped_sessions: int = 0
    signal_rates: dict[str, float] = field(default_factory=dict)


def load_sessions(
    data_dir: Path | None = None,
    project_filter: str | None = None,
    days: int | None = None,
    min_steps: int = 3,
) -> tuple[list[Session], int]:
    """Discover and parse sessions across all adapters. Returns (sessions, skipped)."""
    sessions: list[Session] = []
    skipped = 0
    cutoff = datetime.now(UTC) - timedelta(days=days) if days else None

    for adapter in ADAPTERS.values():
        for path in adapter.discover(data_dir):
            if cutoff is not None:
                try:
                    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
                    if mtime < cutoff:
                        continue
                except OSError:
                    continue
            session = adapter.parse(path)
            if session is None or len(session.steps) < min_steps:
                skipped += 1
                continue
            if project_filter and project_filter.lower() not in session.project.lower():
                continue
            sessions.append(session)

    sessions.sort(key=lambda s: (s.started_at or datetime.min.replace(tzinfo=UTC)))
    return sessions, skipped


def analyze(
    data_dir: Path | None = None,
    project_filter: str | None = None,
    days: int | None = 30,
    window_override: int | None = None,
) -> AnalysisResult:
    sessions, skipped = load_sessions(data_dir, project_filter, days)

    all_steps: list[StepSignals] = []
    window = window_override or DEFAULT_CONTEXT_WINDOW
    for s in sessions:
        model = s.steps[0].model if s.steps else ""
        session_window = context_window_for(model, window_override)
        window = max(window, session_window)
        all_steps.extend(extract_signals(s, session_window).steps)

    curve = build_rot_curve(all_steps)
    comp = estimate_composition(sessions, window)

    total_cost = sum(st.cost_usd for st in all_steps)
    rework_cost = sum(st.cost_usd for st in all_steps if st.degraded)
    knee = curve.knee_pct
    past_knee = sum(1 for st in all_steps if knee is not None and st.fill_pct >= knee)

    n = max(len(all_steps), 1)
    signal_rates = {name: count / n for name, count in curve.signal_totals.items()}

    return AnalysisResult(
        sessions=sessions,
        steps=all_steps,
        curve=curve,
        composition=comp,
        prescriptions=prescribe(curve, comp, rework_cost, past_knee),
        context_window=window,
        total_cost_usd=total_cost,
        rework_cost_usd=rework_cost,
        steps_past_knee=past_knee,
        days=days,
        skipped_sessions=skipped,
        signal_rates=signal_rates,
    )
