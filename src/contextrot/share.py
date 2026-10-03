"""Your curve, anonymized, ready to add to a community dataset.

Every claim about context rot so far comes from lab benchmarks — needle in a
haystack, synthetic retrieval. Nobody knows what the curve looks like on real
coding work across many people, because nobody has had the data. contextrot is
the only thing that produces it, one machine at a time. This is how those curves
get pooled.

**There is no telemetry, and there never will be.** ``contextrot share`` prints
a JSON block — optionally copying it to your clipboard — and stops. Nothing is
sent anywhere. You read it, decide, and paste it into a GitHub issue yourself.
A pooled dataset does not need a network call in the tool; it needs a ritual
people can trust, and "you can read every byte before it leaves" is that ritual.

What the block contains is aggregate statistics only: the verdict, the rate and
step count per fill bucket, the snowball table, the five signal rates, the factor
comparisons, and per-agent and per-model summaries. What it never contains:
project names, file paths, session ids, timestamps, prompts, code, model output,
or dollar figures. ``tests/test_share.py`` enforces that by walking every string
in the payload.

Counts are integers, not just rates, so that curves from different people can be
pooled exactly — summing failures and steps per bucket — rather than averaged.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from contextrot.analysis import AnalysisResult

#: Bump when a field changes meaning or is removed. Adding a field does not
#: need a bump: a pooling script should ignore keys it doesn't know.
SCHEMA = 1

#: Where a share is pasted. A plain link to an issue form — no data in the URL,
#: because a query string is logged by every server it passes through, and the
#: promise here is that nothing leaves until *you* paste it.
SUBMIT_URL = (
    "https://github.com/Priyanshu-byte-coder/contextrot/issues/new"
    "?template=share_your_curve.yml"
)


# Model vendors whose names are public. Model *families* are derived from the
# raw model id, so a private fine-tune called "acme-internal-coder" would surface
# as "acme" — and an employer's name is exactly what a share must never carry.
# Anything not on this list is pooled as "other". Matched on the family's first
# word, lowercased: "opus-5" -> "opus", "GPT 5.4" -> "gpt".
PUBLIC_MODEL_VENDORS = frozenset(
    {
        "opus", "sonnet", "haiku", "fable", "mythos", "claude",
        "gpt", "o", "codex",
        "gemini", "gemma",
        "qwen", "deepseek", "glm", "kimi", "minimax",
        "llama", "mistral", "codestral", "devstral",
        "grok", "nemotron", "phi", "command",
    }
)


def _public_model(name: str) -> str:
    """A model name if its vendor is public, otherwise "other"."""
    head = name.replace("-", " ").split(" ", 1)[0].lower()
    return name if head in PUBLIC_MODEL_VENDORS else "other"


def _r(x: float | None, places: int = 4) -> float | None:
    """Round, passing None and infinity through as None (JSON has no infinity)."""
    if x is None or x == float("inf") or x != x:  # x != x catches NaN
        return None
    return round(x, places)


def _group_summary(stats) -> dict:
    """One agent's or model's verdict and zone rates. No project data."""
    c = stats.curve
    return {
        "steps": stats.steps,
        "verdict": stats.verdict_kind,
        "fresh_rate": _r(c.low_fill_rate),
        "deep_rate": _r(c.high_fill_rate),
        "ratio": _r(c.degradation_ratio, 3),
        "threshold_pct": c.knee_pct,
    }


def build_share(result: AnalysisResult, *, version: str) -> dict:
    """The anonymized payload for one machine's sessions."""
    curve = result.curve
    total = result.total_cost_usd
    waste = (result.rework_cost_usd / total) if total > 0 else None

    factors = []
    for f in result.factors:
        groups: dict[str, dict] = {}
        for g in f.groups:
            label = _public_model(g.label) if f.key == "model" else g.label
            merged = groups.setdefault(label, {"label": label, "n": 0, "failures": 0})
            merged["n"] += g.n
            merged["failures"] += g.failures
        factors.append(
            {
                "factor": f.key,
                "strength": f.strength,
                "ordinal": f.ordinal,
                "ratio": _r(f.ratio, 3),
                "groups": list(groups.values()),
            }
        )

    return {
        "schema": SCHEMA,
        "tool": "contextrot",
        "version": version,
        "days": result.days or None,  # 0 means "all history"
        "sessions": len(result.sessions),
        "steps": len(result.steps),
        "agents": sorted({s.source for s in result.sessions if s.source}),
        "max_window": result.context_window,
        "verdict": {
            "kind": result.verdict_kind,
            "threshold_pct": curve.knee_pct,
            "fresh_rate": _r(curve.low_fill_rate),
            "deep_rate": _r(curve.high_fill_rate),
            "fresh_n": curve.low_fill_n,
            "deep_n": curve.high_fill_n,
            "ratio": _r(curve.degradation_ratio, 3),
            "significant": curve.ratio_significant,
            "zones": curve.zone_mode,
            "fresh_max_pct": _r(curve.low_zone_max, 1),
            "deep_min_pct": _r(curve.high_zone_min, 1),
        },
        "curve": [
            {"lo": b.lo, "hi": b.hi, "n": b.n, "failures": b.degraded}
            for b in curve.buckets
            if b.n
        ],
        "snowball": [
            {"reversals": b.label, "n": b.n, "failures": b.degraded}
            for b in result.reversal_curve.buckets
            if b.n
        ],
        "signals": {name: _r(rate) for name, rate in sorted(result.signal_rates.items())},
        "factors": factors,
        "by_agent": {a.key: _group_summary(a) for a in result.agents if not a.is_other},
        # Unlisted vendors are dropped here rather than merged: these are finished
        # verdicts, and two models' verdicts cannot be averaged into a third.
        "by_model": {
            m.family: _group_summary(m)
            for m in result.models
            if not m.is_other and _public_model(m.family) != "other"
        },
        "waste_share": _r(waste),
        "startup_share_of_window": _r(result.composition.overhead_pct_of_window / 100.0),
    }


def _flat(value: object) -> bool:
    """A dict or list holding only scalars — small enough to read on one line."""
    if isinstance(value, dict):
        return all(not isinstance(v, (dict, list)) for v in value.values())
    if isinstance(value, list):
        return all(not isinstance(v, (dict, list)) for v in value)
    return True


def _dump(value: object, indent: int) -> str:
    if _flat(value):
        return json.dumps(value, ensure_ascii=True, separators=(", ", ": "))
    pad, inner = " " * indent, " " * (indent + 2)
    nl = "\n"
    if isinstance(value, dict):
        items = [f"{inner}{json.dumps(k)}: {_dump(v, indent + 2)}" for k, v in value.items()]
        return "{" + nl + ("," + nl).join(items) + nl + pad + "}"
    assert isinstance(value, list)
    items = [f"{inner}{_dump(v, indent + 2)}" for v in value]
    return "[" + nl + ("," + nl).join(items) + nl + pad + "]"


def to_json(payload: dict) -> str:
    """Serialised for pasting: readable, and ASCII-only so every clipboard takes it.

    Flat objects stay on one line — a fill bucket is one row, not six — because
    the trust in this whole mechanism rests on people reading the block before
    they paste it, and nobody reads three hundred lines. It is still plain JSON;
    ``json.loads`` gives back exactly the payload.
    """
    return _dump(payload, 0)


def copy_to_clipboard(text: str) -> bool:
    """Put ``text`` on the system clipboard via the OS's own tool. True on success.

    A subprocess to a local program, not a library and not a network call:
    ``clip`` on Windows, ``pbcopy`` on macOS, and whichever of ``wl-copy``,
    ``xclip`` or ``xsel`` exists on Linux. Returns False rather than raising
    when none is available — the block is printed either way.
    """
    if sys.platform == "win32":
        candidates = [["clip"]]
    elif sys.platform == "darwin":
        candidates = [["pbcopy"]]
    else:
        candidates = [
            ["wl-copy"],
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
        ]
    data = text.encode("ascii", errors="replace")
    for cmd in candidates:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            subprocess.run(cmd, input=data, check=True, timeout=5, capture_output=True)
        except (OSError, subprocess.SubprocessError):
            continue
        return True
    return False


__all__ = ["SCHEMA", "SUBMIT_URL", "build_share", "copy_to_clipboard", "to_json"]
