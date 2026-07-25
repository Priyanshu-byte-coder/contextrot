"""Model pricing and context-window tables.

Prices are USD per million tokens, based on published API list prices.
Subscription users (Claude Pro/Max, Copilot, etc.) don't pay per token;
for them these figures are the *API-equivalent value* of the tokens, which
is still the honest way to size waste. Unknown models fall back to a
conservative default and are flagged as estimated in reports.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_CONTEXT_WINDOW = 200_000


@dataclass(frozen=True)
class ModelPricing:
    input: float  # $ / MTok
    output: float
    cache_write: float
    cache_read: float
    context_window: int = DEFAULT_CONTEXT_WINDOW
    estimated: bool = False


_MILLION = 1_000_000

# Matched by substring against the normalized model id, first hit wins — so the
# most specific families must come first ("opus-4-8" before the generic
# "opus-4", which still covers the 200k-window 4.5/4.1/4.0 generation).
#
# Windows matter more than prices here: they're the denominator of every
# context-fill percentage, so a stale window silently distorts the whole
# analysis. The current Anthropic frontier models (Opus 4.6+, Sonnet 4.6+,
# Opus 5, Sonnet 5, Fable/Mythos 5) carry 1M-token windows; only Haiku 4.5 and
# the older 4.5-and-earlier generation are 200k.
_PRICING: list[tuple[str, ModelPricing]] = [
    # Anthropic — current generation (1M context)
    ("fable-5", ModelPricing(10.0, 50.0, 12.50, 1.00, _MILLION)),
    ("mythos-5", ModelPricing(10.0, 50.0, 12.50, 1.00, _MILLION)),
    ("opus-5", ModelPricing(5.0, 25.0, 6.25, 0.50, _MILLION)),
    ("opus-4-8", ModelPricing(5.0, 25.0, 6.25, 0.50, _MILLION)),
    ("opus-4-7", ModelPricing(5.0, 25.0, 6.25, 0.50, _MILLION)),
    ("opus-4-6", ModelPricing(5.0, 25.0, 6.25, 0.50, _MILLION)),
    ("sonnet-5", ModelPricing(3.0, 15.0, 3.75, 0.30, _MILLION)),
    ("sonnet-4-6", ModelPricing(3.0, 15.0, 3.75, 0.30, _MILLION)),
    # Anthropic — 200k generation
    ("haiku-4", ModelPricing(1.0, 5.0, 1.25, 0.10)),
    ("haiku-3", ModelPricing(0.80, 4.0, 1.0, 0.08)),
    ("opus-4", ModelPricing(15.0, 75.0, 18.75, 1.50)),
    ("opus-3", ModelPricing(15.0, 75.0, 18.75, 1.50)),
    ("sonnet-4", ModelPricing(3.0, 15.0, 3.75, 0.30)),
    ("sonnet-3", ModelPricing(3.0, 15.0, 3.75, 0.30)),
    # Other vendors
    ("gpt-5", ModelPricing(1.25, 10.0, 1.25, 0.125, context_window=272_000, estimated=True)),
    ("gpt-4", ModelPricing(2.50, 10.0, 2.50, 1.25, context_window=128_000, estimated=True)),
    ("gemini-2.5-flash", ModelPricing(0.30, 2.50, 0.30, 0.075, 1_048_576, estimated=True)),
    ("gemini-3", ModelPricing(2.0, 12.0, 2.0, 0.20, 1_048_576, estimated=True)),
    ("gemini", ModelPricing(1.25, 10.0, 1.625, 0.31, 1_048_576, estimated=True)),
    ("qwen", ModelPricing(1.0, 5.0, 1.0, 0.10, 262_144, estimated=True)),
]

_FALLBACK = ModelPricing(3.0, 15.0, 3.75, 0.30, estimated=True)

# Context-window sizes actually shipped by current agent models, ascending.
# Used to rescue an unknown model whose observed prompt exceeds the window we
# assumed for it (see infer_window).
WINDOW_TIERS = (128_000, 200_000, 262_144, 272_000, _MILLION, 2 * _MILLION)


def _normalize(model: str) -> str:
    """Lowercase and use one separator, so "Opus-4.8" and "opus-4-8" both match."""
    return (model or "").lower().replace(".", "-")


def pricing_for(model: str) -> ModelPricing:
    m = _normalize(model)
    for needle, p in _PRICING:
        if needle in m:
            return p
    return _FALLBACK


def context_window_for(model: str, override: int | None = None) -> int:
    if override:
        return override
    return pricing_for(model).context_window


def infer_window(observed_peak_tokens: int, assumed_window: int) -> int:
    """Correct an assumed window that the data itself contradicts.

    A prompt can never exceed its own context window, so an observed peak above
    the window we assumed means the assumption is wrong — a model we don't know
    (an agent's internal codename, or one released after this table was
    written). Rather than clamping every deep step to 100% fill and inventing a
    degradation threshold out of it, step up to the smallest real window that
    fits what we actually saw.
    """
    if observed_peak_tokens <= assumed_window:
        return assumed_window
    for tier in WINDOW_TIERS:
        if tier >= observed_peak_tokens:
            return tier
    return observed_peak_tokens


def step_cost_usd(
    input_tokens: int,
    cache_creation: int,
    cache_read: int,
    output_tokens: int,
    model: str,
) -> float:
    p = pricing_for(model)
    return (
        input_tokens * p.input
        + cache_creation * p.cache_write
        + cache_read * p.cache_read
        + output_tokens * p.output
    ) / 1_000_000
