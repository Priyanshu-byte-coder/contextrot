"""How much water your sessions drank.

Inference runs in datacenters that evaporate water to stay cool, so every
token carries a small, real water cost. This module turns the token counts
contextrot already parses into litres — and, unlike everything else in this
codebase, it is an **estimate rather than a measurement**, which the output
says out loud everywhere it appears.

The chain, with every constant traceable:

1. **Tokens to energy.** Decoding an output token is a full forward pass;
   prefilling an input token is batched and roughly an order of magnitude
   cheaper per token; replaying a cached prefix recomputes nothing at all and
   costs little more than memory bandwidth. Hence three separate rates
   (``WH_PER_1K_OUTPUT``, ``WH_PER_1K_PREFILL``, ``WH_PER_1K_CACHE_READ``)
   rather than one rate applied to a token total — a coding agent's context is
   mostly cache reads, so collapsing them would overstate the figure several
   times over.

2. **Model size.** A Haiku-class model is not an Opus-class model. A coarse
   three-tier multiplier (``_TIERS``) keeps a small model from being quoted at
   frontier cost. Three tiers, not a curve: the honest resolution here is
   "small / mid / frontier", and anything finer would be invented.

3. **Energy to water, in two parts.** Water is consumed twice over: once in
   the datacenter's cooling towers, and again at the power station that fed
   it. ``ML_PER_WH_COOLING = 1.08`` is not a free parameter — it is Google's
   own published pair for a median Gemini text prompt, 0.26 mL against
   0.24 Wh, divided, and it matches their reported fleet water-usage
   effectiveness of ~1.1 L/kWh. ``ML_PER_WH_GENERATION = 1.8`` is the
   consumptive water intensity of US grid electricity, which is *larger* than
   the cooling term and is what makes reporting cooling alone misleading:
   "how much water did this use" means both.

Everything is per-step and additive, so the same function serves the live
statusline (one session, incrementally) and the ``water`` command (every
session on disk). Pure stdlib — the statusline imports this on every render
and must not pull in the analysis layer.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

# --- Energy, in watt-hours per 1,000 tokens, for a frontier-sized model ------

# One forward pass per token. This is where almost all the compute goes, and it
# is the best-anchored rate here: 1,000 prefill tokens plus 300 output tokens
# comes to 0.24 Wh on these constants, which is exactly Google's published
# median for a text prompt. Independently, Epoch AI put a typical GPT-4o query
# at ~0.3 Wh for ~500 output tokens, i.e. the same 0.6 per 1k.
WH_PER_1K_OUTPUT = 0.60
# Prefill reads the whole prompt in parallel, so per token it is far cheaper
# than decode — and a cache hit recomputes nothing at all, costing little more
# than moving the KV tensors.
#
# Both are set from the ratios providers *price* these at, which is the only
# external signal available for them. Anthropic charges 20% of the output rate
# for fresh input and 2% for a cache read (Opus 5: $5.00 / $0.50 / $25.00 per
# MTok). An earlier version of this module used 10% and 1% — half of that —
# which put the whole estimate roughly 2x low, and badly so for coding agents,
# where cache reads are over 90% of all tokens.
WH_PER_1K_PREFILL = 0.12
WH_PER_1K_CACHE_READ = 0.012

# --- Energy to water ---------------------------------------------------------

# On-site cooling: mL of water evaporated in the datacenter per watt-hour.
# Google's published 0.26 mL / 0.24 Wh for a median text prompt, divided.
ML_PER_WH_COOLING = 1.08

# Off-site generation: mL consumed producing that watt-hour, at the US grid
# average. Thermoelectric plants evaporate cooling water of their own and
# hydro reservoirs evaporate from their surface; wind and solar consume almost
# none, so a datacenter on a clean grid sits far below this and one on a
# coal-or-hydro grid far above.
ML_PER_WH_GENERATION = 1.80

# The number reported by default. Quoting cooling alone understates the
# footprint by nearly 3x, and "how much water did this use" plainly means all
# of it — so the total is the headline and the split is shown beneath it.
ML_PER_WH = ML_PER_WH_COOLING + ML_PER_WH_GENERATION

# Honest error bar on the whole chain, quoted wherever the figure is. The
# constants above are public medians; a specific datacenter on a specific day
# sits well either side of them.
UNCERTAINTY_FACTOR = 2.0

# Coarse size multiplier on the energy rates, matched by substring against the
# lowercased model id, first hit wins. Small models come first: "gpt-4o-mini"
# contains both "-mini" and "gpt-4".
_TIERS: tuple[tuple[str, float], ...] = (
    ("-nano", 0.10),
    ("-mini", 0.15),
    ("haiku", 0.15),
    ("flash", 0.15),
    ("qwen", 0.30),
    ("sonnet", 0.50),
    ("gpt-4", 0.50),
    ("gemini-3", 1.00),
    ("gemini", 0.50),
    ("opus", 1.00),
    ("fable", 1.00),
    ("mythos", 1.00),
    ("gpt-5", 1.00),
)
# An unrecognised model is assumed mid-sized rather than frontier: guessing
# high would quietly inflate the headline number for every model we don't know.
_DEFAULT_TIER = 0.50


def energy_scale(model: str) -> float:
    """Coarse energy multiplier for a model id. Mid-tier when unrecognised."""
    m = (model or "").lower().replace(".", "-")
    for needle, scale in _TIERS:
        if needle in m:
            return scale
    return _DEFAULT_TIER


def step_energy_wh(
    input_tokens: int,
    cache_creation: int,
    cache_read: int,
    output_tokens: int,
    model: str,
) -> float:
    """Watt-hours for one model call.

    Cache creation counts as prefill: those tokens are read in full exactly
    once, and the write into the cache is the cheap part.
    """
    per_1k = (
        max(0, input_tokens) * WH_PER_1K_PREFILL
        + max(0, cache_creation) * WH_PER_1K_PREFILL
        + max(0, cache_read) * WH_PER_1K_CACHE_READ
        + max(0, output_tokens) * WH_PER_1K_OUTPUT
    )
    return per_1k / 1000.0 * energy_scale(model)


def step_water_ml(
    input_tokens: int,
    cache_creation: int,
    cache_read: int,
    output_tokens: int,
    model: str,
) -> float:
    """Millilitres of water for one model call."""
    wh = step_energy_wh(input_tokens, cache_creation, cache_read, output_tokens, model)
    return wh * ML_PER_WH


# --- Totals ------------------------------------------------------------------

# The three buckets, biggest-contributor-first for a coding agent. That order
# is the point: people expect their output tokens to dominate, and for an
# agent replaying a large context they do not.
BUCKETS = ("cache_read", "output", "prefill")

_BUCKET_LABELS = {
    "cache_read": "cache reads",
    "output": "output",
    "prefill": "fresh input",
}


@dataclass
class WaterTotals:
    """Accumulated water, with enough breakdown to say where it went."""

    ml: float = 0.0
    wh: float = 0.0
    steps: int = 0
    sessions: int = 0
    input_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0
    # Millilitres by bucket / agent / model family, for the breakdown tables.
    by_bucket: dict = field(default_factory=dict)
    by_agent: dict = field(default_factory=dict)
    by_model: dict = field(default_factory=dict)

    def add_step(
        self,
        input_tokens: int,
        cache_creation: int,
        cache_read: int,
        output_tokens: int,
        model: str,
        *,
        agent: str = "",
    ) -> float:
        """Fold one model call in. Returns the millilitres it added."""
        from contextrot.modelkey import model_family

        scale = energy_scale(model)
        prefill_wh = (max(0, input_tokens) + max(0, cache_creation)) * WH_PER_1K_PREFILL / 1000.0
        read_wh = max(0, cache_read) * WH_PER_1K_CACHE_READ / 1000.0
        out_wh = max(0, output_tokens) * WH_PER_1K_OUTPUT / 1000.0
        wh = (prefill_wh + read_wh + out_wh) * scale
        ml = wh * ML_PER_WH

        self.wh += wh
        self.ml += ml
        self.steps += 1
        self.input_tokens += max(0, input_tokens)
        self.cache_creation_tokens += max(0, cache_creation)
        self.cache_read_tokens += max(0, cache_read)
        self.output_tokens += max(0, output_tokens)

        per_wh = ML_PER_WH * scale
        _bump(self.by_bucket, "prefill", prefill_wh * per_wh)
        _bump(self.by_bucket, "cache_read", read_wh * per_wh)
        _bump(self.by_bucket, "output", out_wh * per_wh)
        if agent:
            _bump(self.by_agent, agent, ml)
        _bump(self.by_model, model_family(model), ml)
        return ml

    @property
    def cooling_ml(self) -> float:
        """The datacenter's share: cooling towers and evaporative loops."""
        return self.wh * ML_PER_WH_COOLING

    @property
    def generation_ml(self) -> float:
        """The power station's share, producing the electricity that got used."""
        return self.wh * ML_PER_WH_GENERATION

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
            + self.output_tokens
        )

    def dominant_bucket(self) -> tuple[str, float] | None:
        """(label, share) for the biggest contributor, or None when empty."""
        if self.ml <= 0 or not self.by_bucket:
            return None
        key, ml = max(self.by_bucket.items(), key=lambda kv: kv[1])
        return _BUCKET_LABELS.get(key, key), ml / self.ml

    def bucket_rows(self) -> list[tuple[str, float, float]]:
        """[(label, ml, share)] in BUCKETS order, skipping empty buckets."""
        out: list[tuple[str, float, float]] = []
        for key in BUCKETS:
            ml = self.by_bucket.get(key, 0.0)
            if ml <= 0:
                continue
            out.append((_BUCKET_LABELS.get(key, key), ml, ml / self.ml if self.ml else 0.0))
        return out

    def ranked(self, bucket: dict, limit: int = 5) -> list[tuple[str, float, float]]:
        """[(name, ml, share)] from by_agent / by_model, biggest first."""
        rows = sorted(bucket.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        return [(name, ml, ml / self.ml if self.ml else 0.0) for name, ml in rows if ml > 0]


def _bump(bucket: dict, key: str, ml: float) -> None:
    bucket[key] = bucket.get(key, 0.0) + ml


def totals_for_sessions(sessions: list) -> WaterTotals:
    """Water for every step of every session handed in."""
    totals = WaterTotals()
    for session in sessions:
        if not session.steps:
            continue
        totals.sessions += 1
        for step in session.steps:
            totals.add_step(
                step.input_tokens,
                step.cache_creation_tokens,
                step.cache_read_tokens,
                step.output_tokens,
                step.model,
                agent=session.source,
            )
    return totals


# --- Human-scale formatting --------------------------------------------------

# Everyday volumes, ascending, for "about N of these". Each is something you
# can picture holding. A count of millilitres is not.
_COMPARISONS: tuple[tuple[float, str, str], ...] = (
    (5.0, "a teaspoon", "teaspoons"),
    (240.0, "a coffee cup", "coffee cups"),
    (500.0, "a water bottle", "water bottles"),
    (19_000.0, "an office water cooler jug", "office water cooler jugs"),
    (150_000.0, "a bathtub", "bathtubs"),
    (2_500_000.0, "a backyard swimming pool", "backyard swimming pools"),
)


def fmt_volume(ml: float) -> str:
    """A volume at readable precision: 0.40 ml, 3.6 ml, 36 ml, 1.20 L, 47.3 L, 1,240 L."""
    ml = max(0.0, float(ml))
    if ml < 1:
        return f"{ml:.2f} ml"
    if ml < 10:
        return f"{ml:.1f} ml"
    if ml < 1000:
        return f"{ml:.0f} ml"
    litres = ml / 1000.0
    if litres < 10:
        return f"{litres:.2f} L"
    if litres < 100:
        return f"{litres:.1f} L"
    return f"{litres:,.0f} L"


def fmt_energy(wh: float) -> str:
    """0.40 Wh, 36 Wh, 1.20 kWh."""
    wh = max(0.0, float(wh))
    if wh < 1:
        return f"{wh:.2f} Wh"
    if wh < 1000:
        return f"{wh:.0f} Wh"
    kwh = wh / 1000.0
    return f"{kwh:.2f} kWh" if kwh < 10 else f"{kwh:,.1f} kWh"


def fmt_tokens(n: int) -> str:
    """950, 68k, 1.2M, 9.6B.

    Reaches billions, unlike the statusline's own token formatter: that one
    prints a context window, which cannot exceed a few million, while this one
    prints every cache replay ever made and routinely passes a billion.
    """
    n = max(0, int(n))
    for size, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "k")):
        if n >= size:
            scaled = n / size
            return f"{scaled:.0f}{suffix}" if scaled >= 100 else f"{scaled:.1f}{suffix}"
    return str(n)


def comparison(ml: float) -> str | None:
    """The largest everyday unit that still counts at least one of itself.

    Returns e.g. ``about 8 water bottles``, or None below a teaspoon, where
    every comparison is a rounding error dressed up as a fact.
    """
    ml = max(0.0, float(ml))
    chosen: tuple[float, str, str] | None = None
    for size, one, many in _COMPARISONS:
        if ml >= size:
            chosen = (size, one, many)
    if chosen is None:
        return None
    size, one, many = chosen
    count = ml / size
    if count < 1.05:
        return f"about {one}"
    text = f"{count:.1f}" if count < 10 else f"{count:,.0f}"
    if text.endswith(".0"):
        text = text[:-2]
    return f"about {text} {many}"


# Tank milestones for the live view. A live meter needs a ceiling to fill
# toward, and "the next round number up" is the one people already think in.
_MILESTONE_STEPS = (
    (1_000.0, 100.0),  # under 1 L, fill toward the next 100 ml
    (10_000.0, 1_000.0),  # under 10 L, toward the next litre
    (100_000.0, 10_000.0),  # under 100 L, toward the next 10 L
)
_MILESTONE_TOP = 100_000.0  # above 100 L, toward the next 100 L


def milestone(ml: float) -> tuple[float, float]:
    """(next round volume above ``ml``, how far along the way we are 0..1).

    Gives the live tank something to fill toward and something to splash over,
    which is the difference between a meter that is pleasant to leave open and a
    number that happens to be moving.
    """
    ml = max(0.0, float(ml))
    step = _MILESTONE_TOP
    for ceiling, candidate in _MILESTONE_STEPS:
        if ml < ceiling:
            step = candidate
            break
    floor = (int(ml // step)) * step
    return floor + step, (ml - floor) / step


def provenance() -> str:
    """Where the number comes from. Shown with it, every time."""
    return (
        f"Estimate, not a measurement: {WH_PER_1K_OUTPUT} Wh per 1k output tokens "
        f"({WH_PER_1K_PREFILL} prefill, {WH_PER_1K_CACHE_READ} cache replay — the ratios "
        f"providers price these at), scaled by model size. That rate reproduces Google's "
        f"published 0.24 Wh median text prompt. Energy becomes water at "
        f"{ML_PER_WH_COOLING} mL/Wh of datacenter cooling plus {ML_PER_WH_GENERATION} mL/Wh "
        f"consumed generating the electricity, at the US grid average. Long-context "
        f"attention is not priced separately, which biases this low on deep sessions. "
        f"Assume plus or minus {UNCERTAINTY_FACTOR:.0f}x."
    )


# --- Live session cursor cache -----------------------------------------------
#
# The statusline needs this session's running total on every render, and a long
# transcript is tens of megabytes — far too much to re-parse each time. So the
# bytes already counted are remembered, and only the new tail is read.
#
# This file is a *cache*, not a record: delete it and the next render recomputes
# from the transcript. Nothing in it is a source of truth, which is why it can
# be pruned, reset on any inconsistency, and lost to a race without consequence.

CACHE_SCHEMA = 2


def _model_fingerprint() -> str:
    """Identifies the constants a cached total was computed with.

    Stored alongside the totals and compared on load. Without it, changing any
    rate leaves every cached session holding a figure computed half under the old
    constants and half under the new ones — which is exactly what happened when
    the prefill and replay rates were corrected in 1.9.0, and it is invisible
    because the number still looks plausible. Derived from the constants
    themselves rather than hand-bumped, so it cannot be forgotten next time.
    """
    payload = repr(
        (
            WH_PER_1K_OUTPUT,
            WH_PER_1K_PREFILL,
            WH_PER_1K_CACHE_READ,
            ML_PER_WH_COOLING,
            ML_PER_WH_GENERATION,
            _TIERS,
            _DEFAULT_TIER,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

# Per-render read ceiling. A steady-state render reads a few KB and takes about a
# millisecond; this only bites on the first sight of an existing transcript,
# where everything before now has to be counted in one go. Scanning measures at
# roughly 150 MB/s, so 64 MB is a worst case of about 0.4s, once — large enough
# that real transcripts finish in a single pass rather than climbing to the
# right answer over several renders, small enough not to stall a prompt.
MAX_CATCHUP_BYTES = 64 * 1024 * 1024

# Keep the cache small and self-pruning: a session untouched this long is over,
# and its water lives in the `water` command's full scan instead.
CACHE_TTL_SECONDS = 7 * 24 * 3600
MAX_CACHE_ENTRIES = 64


def cache_path() -> Path:
    return Path.home() / ".contextrot" / "water-live.json"


@dataclass
class SessionWater:
    """One transcript's running total, plus where reading left off."""

    offset: int = 0
    size: int = 0
    ml: float = 0.0
    wh: float = 0.0
    steps: int = 0
    updated: float = 0.0
    # How many times this session has been rendered. The statusline's droplet
    # animation uses it as a frame index: a status line is redrawn on events,
    # not on a timer, so a wall-clock phase would jump around while a render
    # count advances by exactly one each time — which is what a loop needs.
    renders: int = 0

    def to_json(self) -> dict:
        # Totals are stored at full precision deliberately. Rounding them makes
        # the reloaded value differ from the one just returned, so two calls
        # with nothing appended in between would disagree — and callers are
        # entitled to treat an unchanged transcript as an unchanged number.
        return {
            "offset": self.offset,
            "size": self.size,
            "ml": self.ml,
            "wh": self.wh,
            "steps": self.steps,
            "updated": round(self.updated, 1),
            "renders": self.renders,
        }

    @classmethod
    def from_json(cls, raw: object) -> SessionWater | None:
        if not isinstance(raw, dict):
            return None
        try:
            return cls(
                offset=int(raw.get("offset") or 0),
                size=int(raw.get("size") or 0),
                ml=float(raw.get("ml") or 0.0),
                wh=float(raw.get("wh") or 0.0),
                steps=int(raw.get("steps") or 0),
                updated=float(raw.get("updated") or 0.0),
                renders=int(raw.get("renders") or 0),
            )
        except (TypeError, ValueError):
            return None


def _load_cache(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict) or raw.get("schema") != CACHE_SCHEMA:
        return {}
    if raw.get("model") != _model_fingerprint():
        # Computed under different constants. It is a cache, so throw it away
        # and recount rather than carry a figure nobody can reproduce.
        return {}
    sessions = raw.get("sessions")
    if not isinstance(sessions, dict):
        return {}
    out: dict = {}
    for key, value in sessions.items():
        entry = SessionWater.from_json(value)
        if entry is not None and isinstance(key, str):
            out[key] = entry
    return out


def _save_cache(path: Path, entries: dict) -> None:
    """Atomically write the cache, keeping whichever record read further.

    Two statusline processes can render at once: both read, both advance, both
    write — and the second write would otherwise roll the first one back and
    recount those bytes. Offsets only ever move forward, so re-reading the file
    at write time and keeping the larger offset turns a lost race into a no-op
    rather than a double count.
    """
    now = time.time()
    merged = dict(_load_cache(path))
    for key, entry in entries.items():
        existing = merged.get(key)
        if existing is None or entry.offset >= existing.offset:
            merged[key] = entry
    fresh = {k: v for k, v in merged.items() if now - v.updated <= CACHE_TTL_SECONDS}
    if len(fresh) > MAX_CACHE_ENTRIES:
        newest = sorted(fresh.items(), key=lambda kv: kv[1].updated, reverse=True)
        fresh = dict(newest[:MAX_CACHE_ENTRIES])

    payload = {
        "schema": CACHE_SCHEMA,
        "model": _model_fingerprint(),
        "sessions": {k: v.to_json() for k, v in fresh.items()},
    }
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()


@dataclass(frozen=True)
class LiveWater:
    """What a live surface needs: the running total, and a frame to draw."""

    ml: float
    #: Renders of this session so far. The statusline animates off this rather
    #: than the clock, so its droplet advances one frame per redraw.
    frame: int = 0


def session_water(transcript: Path | str | None, cache: Path | None = None) -> LiveWater | None:
    """Water used so far by one live transcript.

    Incremental: only the bytes appended since the last call are parsed. None
    when there is nothing readable to report, so callers stay silent instead of
    printing a confident zero.
    """
    try:
        return _session_water(transcript, cache)
    except Exception:  # noqa: BLE001 — never break a statusline over a vanity metric
        return None


def _session_water(transcript: Path | str | None, cache: Path | None) -> LiveWater | None:
    if not transcript:
        return None
    path = Path(transcript)
    try:
        stat = path.stat()
    except OSError:
        return None
    if not stat.st_size:
        return None

    cache_file = cache or cache_path()
    entries = _load_cache(cache_file)
    key = str(path)
    entry = entries.get(key) or SessionWater()

    # A file that shrank is a different file: rotated, truncated, or a reused
    # path. Counting on from a stale offset would start mid-line.
    if stat.st_size < entry.size or entry.offset > stat.st_size:
        entry = SessionWater()

    if stat.st_size > entry.offset:
        read_to = min(stat.st_size, entry.offset + MAX_CATCHUP_BYTES)
        consumed, ml, wh, steps = _scan_tail(path, entry.offset, read_to)
        entry.offset += consumed
        entry.ml += ml
        entry.wh += wh
        entry.steps += steps

    entry.size = stat.st_size
    entry.updated = time.time()
    entry.renders += 1
    entries[key] = entry
    _save_cache(cache_file, entries)
    return LiveWater(ml=entry.ml, frame=entry.renders) if entry.steps else None


def _scan_tail(path: Path, start: int, stop: int) -> tuple[int, float, float, int]:
    """Parse whole JSONL lines in [start, stop). Returns (bytes used, ml, wh, steps).

    Only complete lines are consumed: the transcript is being appended to while
    this runs, so the final line is routinely a half-written object. Its bytes
    stay uncounted and are picked up on the next call.

    Sub-agent steps are counted here, unlike in the rot analysis, which excludes
    them so that one session's curve describes one conversation. A sub-agent's
    tokens were really generated and really cooled, so for water they belong in
    the total.
    """
    from contextrot.live import entry_usage

    try:
        with path.open("rb") as f:
            f.seek(start)
            chunk = f.read(max(0, stop - start))
    except OSError:
        return 0, 0.0, 0.0, 0

    if not chunk:
        return 0, 0.0, 0.0, 0
    cut = chunk.rfind(b"\n")
    if cut < 0:
        return 0, 0.0, 0.0, 0
    consumed = cut + 1

    ml = wh = 0.0
    steps = 0
    for raw in chunk[:consumed].decode("utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line[0] != "{":
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        usage = entry_usage(obj)
        if usage is None:
            continue
        step_wh = step_energy_wh(
            usage.input_tokens,
            usage.cache_creation_tokens,
            usage.cache_read_tokens,
            usage.output_tokens,
            usage.model,
        )
        if step_wh <= 0:
            continue
        wh += step_wh
        ml += step_wh * ML_PER_WH
        steps += 1
    return consumed, ml, wh, steps
