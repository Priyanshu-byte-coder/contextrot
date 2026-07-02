"""Rot-curve statistics.

Buckets steps by context-fill percentage and measures how often failure
signals fire in each bucket. All statistics are observational: this is a
diagnostic on your own sessions, not a controlled experiment, and the
report says so. Wilson score intervals are used because bucket counts are
often small and rates are near the boundary.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from contextrot.signals import SIGNAL_NAMES, StepSignals

BUCKET_WIDTH = 10  # percent
LOW_FILL_MAX = 40.0  # "fresh context" zone
HIGH_FILL_MIN = 60.0  # "deep context" zone
MIN_BUCKET_N = 15  # buckets below this are shown but marked low-confidence
KNEE_RATIO = 1.5  # bucket rate vs baseline that marks the degradation knee


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, center - margin), min(1.0, center + margin))


@dataclass
class Bucket:
    lo: int  # inclusive fill %
    hi: int  # exclusive fill %
    n: int = 0
    degraded: int = 0
    by_signal: dict[str, int] = field(default_factory=dict)

    @property
    def rate(self) -> float:
        return self.degraded / self.n if self.n else 0.0

    @property
    def ci(self) -> tuple[float, float]:
        return wilson_interval(self.degraded, self.n)

    @property
    def low_confidence(self) -> bool:
        return self.n < MIN_BUCKET_N


@dataclass
class RotCurve:
    buckets: list[Bucket]
    total_steps: int
    total_degraded: int
    low_fill_rate: float | None  # rate below LOW_FILL_MAX
    high_fill_rate: float | None  # rate at/above HIGH_FILL_MIN
    low_fill_n: int
    high_fill_n: int
    degradation_ratio: float | None  # high / low
    ratio_significant: bool  # Wilson CIs of the two zones don't overlap
    knee_pct: int | None  # start of first bucket where rate >= KNEE_RATIO * baseline
    signal_totals: dict[str, int] = field(default_factory=dict)

    @property
    def overall_rate(self) -> float:
        return self.total_degraded / self.total_steps if self.total_steps else 0.0


def build_rot_curve(steps: list[StepSignals]) -> RotCurve:
    buckets = [Bucket(lo, lo + BUCKET_WIDTH) for lo in range(0, 100, BUCKET_WIDTH)]
    signal_totals = dict.fromkeys(SIGNAL_NAMES, 0)

    low_n = low_d = high_n = high_d = 0
    total_degraded = 0

    for s in steps:
        idx = min(int(s.fill_pct // BUCKET_WIDTH), len(buckets) - 1)
        b = buckets[idx]
        b.n += 1
        if s.degraded:
            b.degraded += 1
            total_degraded += 1
        for name in SIGNAL_NAMES:
            if getattr(s, name):
                b.by_signal[name] = b.by_signal.get(name, 0) + 1
                signal_totals[name] += 1

        if s.fill_pct < LOW_FILL_MAX:
            low_n += 1
            low_d += 1 if s.degraded else 0
        elif s.fill_pct >= HIGH_FILL_MIN:
            high_n += 1
            high_d += 1 if s.degraded else 0

    low_rate = low_d / low_n if low_n else None
    high_rate = high_d / high_n if high_n else None

    ratio = None
    significant = False
    if low_rate is not None and high_rate is not None and low_n and high_n:
        ratio = high_rate / low_rate if low_rate > 0 else (float("inf") if high_rate > 0 else 1.0)
        lo_ci = wilson_interval(low_d, low_n)
        hi_ci = wilson_interval(high_d, high_n)
        significant = hi_ci[0] > lo_ci[1]  # high zone's floor above low zone's ceiling

    knee = None
    if low_rate is not None and low_rate > 0:
        for b in buckets:
            if b.lo < LOW_FILL_MAX or b.low_confidence:
                continue
            if b.rate >= KNEE_RATIO * low_rate:
                knee = b.lo
                break

    return RotCurve(
        buckets=buckets,
        total_steps=len(steps),
        total_degraded=total_degraded,
        low_fill_rate=low_rate,
        high_fill_rate=high_rate,
        low_fill_n=low_n,
        high_fill_n=high_n,
        degradation_ratio=ratio,
        ratio_significant=significant,
        knee_pct=knee,
        signal_totals=signal_totals,
    )
