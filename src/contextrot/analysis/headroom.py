"""How much more work fits before the window runs out.

A percentage tells you where you are. It does not tell you how much longer you
can keep going, and those are different questions: 34% of a 1M window is a
different amount of remaining work than 34% of 200k, and the same number of
tokens buys very different amounts of work depending on what you do with them.

So this measures the one thing that converts tokens into work: **how much
context one turn actually adds, for this user.** Divide what's left by that
and you get an answer in the unit people plan in.

Measured per **turn**, not per step. Per-step growth was tried first and is
useless: the median step adds about a thousand tokens, mostly cache replay, so
660k of headroom reads as "686 steps left" — technically true and no help to
anyone. A turn is what a person actually spends, and its growth is an order of
magnitude larger, so the number lands in a range you can plan around.

The distribution matters more than the average. On real data the median turn
adds ~15k tokens and the 90th percentile nearly five times that — one wide
grep or a big file read. Quoting only the median would promise headroom that
a single expensive turn erases, so both are kept and callers show the typical
case with the heavy case beside it.
"""

from __future__ import annotations

from dataclasses import dataclass

from contextrot.models import Session

# Below this many observed turns the numbers are noise, and a headroom
# estimate built on noise is worse than none: it reads as a promise.
MIN_GROWTH_SAMPLES = 50


@dataclass
class GrowthStats:
    """Per-turn context growth, in tokens."""

    median: int
    p90: int
    samples: int

    @property
    def usable(self) -> bool:
        return self.samples >= MIN_GROWTH_SAMPLES and self.median > 0

    def turns_left(self, tokens_left: int) -> int | None:
        """Roughly how many more typical turns fit in what's left."""
        if not self.usable or tokens_left <= 0:
            return None
        return int(tokens_left // self.median)

    def heavy_turns_left(self, tokens_left: int) -> int | None:
        """The same, if every remaining turn were an expensive one."""
        if not self.usable or self.p90 <= 0 or tokens_left <= 0:
            return None
        return int(tokens_left // self.p90)


def _percentile(ordered: list[int], pct: float) -> int:
    if not ordered:
        return 0
    k = (len(ordered) - 1) * pct / 100.0
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return int(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo))


def turn_growth(sessions: list[Session]) -> GrowthStats:
    """Median and p90 context growth per user turn, across every session.

    A turn runs from one user prompt to the next, and its growth is the
    difference in prompt tokens between the step that opens it and the step
    that opens the following one — everything the agent read, ran and wrote in
    between.

    Negative differences are dropped rather than clamped: the context shrank,
    which means a compaction or a fresh branch, not a turn that cost negative
    tokens. Sessions whose adapter never marked a boundary contribute nothing
    rather than being guessed at.
    """
    growths: list[int] = []
    for session in sessions:
        opens = [s for s in session.steps if s.starts_turn]
        for prev, cur in zip(opens, opens[1:]):
            delta = cur.prompt_tokens - prev.prompt_tokens
            if delta > 0:
                growths.append(delta)

    if not growths:
        return GrowthStats(median=0, p90=0, samples=0)

    growths.sort()
    return GrowthStats(
        median=_percentile(growths, 50),
        p90=_percentile(growths, 90),
        samples=len(growths),
    )
