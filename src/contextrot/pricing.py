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


# Matched by substring against the model id, first hit wins.
_PRICING: list[tuple[str, ModelPricing]] = [
    ("opus-4", ModelPricing(15.0, 75.0, 18.75, 1.50)),
    ("sonnet-4", ModelPricing(3.0, 15.0, 3.75, 0.30)),
    ("sonnet-3", ModelPricing(3.0, 15.0, 3.75, 0.30)),
    ("haiku-4", ModelPricing(1.0, 5.0, 1.25, 0.10)),
    ("haiku-3", ModelPricing(0.80, 4.0, 1.0, 0.08)),
    ("fable", ModelPricing(15.0, 75.0, 18.75, 1.50, estimated=True)),
    ("gpt-5", ModelPricing(1.25, 10.0, 1.25, 0.125, context_window=272_000, estimated=True)),
    ("gpt-4", ModelPricing(2.50, 10.0, 2.50, 1.25, context_window=128_000, estimated=True)),
    ("gemini-2.5-flash", ModelPricing(0.30, 2.50, 0.30, 0.075, 1_048_576, estimated=True)),
    ("gemini-3", ModelPricing(2.0, 12.0, 2.0, 0.20, 1_048_576, estimated=True)),
    ("gemini", ModelPricing(1.25, 10.0, 1.625, 0.31, 1_048_576, estimated=True)),
    ("qwen", ModelPricing(1.0, 5.0, 1.0, 0.10, 262_144, estimated=True)),
]

_FALLBACK = ModelPricing(3.0, 15.0, 3.75, 0.30, estimated=True)


def pricing_for(model: str) -> ModelPricing:
    m = (model or "").lower()
    for needle, p in _PRICING:
        if needle in m:
            return p
    return _FALLBACK


def context_window_for(model: str, override: int | None = None) -> int:
    if override:
        return override
    return pricing_for(model).context_window


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
