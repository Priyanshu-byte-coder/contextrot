"""Personal-curve calibration cache for live surfaces (statusline, hooks).

Every full analysis writes a tiny JSON snapshot of the user's measured rot
curve — knee, verdict, per-bucket failure rates — so that live surfaces
(the Claude Code statusline, the knee-crossing hook) can compare the
*current* session's context fill against the user's *own* history in
milliseconds, without re-parsing thousands of transcript steps.

This is a cache, not state: deleting the file loses nothing (the next
report run rewrites it), and nothing here ever leaves the machine.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from contextrot.analysis import AnalysisResult

SCHEMA_VERSION = 1

# A calibration built from fewer steps than this is too noisy to color a
# statusline with; live surfaces fall back to generic thresholds.
MIN_CALIBRATED_STEPS = 150

# A bucket needs this many steps before its rate is quoted as "your rate".
MIN_BUCKET_N = 30


def calibration_path() -> Path:
    """Where the calibration cache lives. Overridable for tests."""
    env = os.environ.get("CONTEXTROT_CALIBRATION")
    if env:
        return Path(env)
    return Path.home() / ".contextrot" / "calibration.json"


@dataclass
class Calibration:
    """Snapshot of the user's measured curve, as written by the last report."""

    knee_pct: float | None
    verdict_kind: str
    low_fill_rate: float
    high_fill_rate: float
    steps: int
    days: int | None
    computed_at: str
    buckets: list[dict] = field(default_factory=list)  # {"lo", "hi", "n", "rate"}

    @property
    def calibrated(self) -> bool:
        return self.steps >= MIN_CALIBRATED_STEPS

    def rate_at_fill(self, fill_pct: float) -> float | None:
        """The user's measured failure rate in the bucket containing fill_pct.

        Returns None when the bucket is too small to quote honestly.
        """
        for b in self.buckets:
            lo, hi = b.get("lo", 0), b.get("hi", 0)
            if lo <= fill_pct < hi or (hi >= 100 and fill_pct >= lo):
                if b.get("n", 0) >= MIN_BUCKET_N:
                    return float(b.get("rate", 0.0))
                return None
        return None


def save_calibration(result: AnalysisResult, path: Path | None = None) -> Path | None:
    """Write the calibration snapshot. Silent no-op on any failure."""
    target = path or calibration_path()
    payload = {
        "schema": SCHEMA_VERSION,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "days": result.days,
        "steps": len(result.steps),
        "verdict_kind": result.verdict_kind,
        "knee_pct": result.curve.knee_pct,
        "low_fill_rate": result.curve.low_fill_rate,
        "high_fill_rate": result.curve.high_fill_rate,
        "buckets": [
            {"lo": b.lo, "hi": b.hi, "n": b.n, "rate": round(b.rate, 4)}
            for b in result.curve.buckets
            if b.n
        ],
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return target
    except OSError:
        return None


def load_calibration(path: Path | None = None) -> Calibration | None:
    """Read the calibration snapshot. None when missing, stale-schema, or unreadable."""
    target = path or calibration_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA_VERSION:
        return None
    try:
        return Calibration(
            knee_pct=raw.get("knee_pct"),
            verdict_kind=str(raw.get("verdict_kind", "insufficient")),
            low_fill_rate=float(raw.get("low_fill_rate", 0.0)),
            high_fill_rate=float(raw.get("high_fill_rate", 0.0)),
            steps=int(raw.get("steps", 0)),
            days=raw.get("days"),
            computed_at=str(raw.get("computed_at", "")),
            buckets=[b for b in raw.get("buckets", []) if isinstance(b, dict)],
        )
    except (TypeError, ValueError):
        return None
