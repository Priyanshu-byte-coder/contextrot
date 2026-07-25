"""Context-window resolution — the denominator of every fill percentage.

A stale window silently distorts the entire analysis: fill percentages inflate,
deep-context steps get misclassified, and a degradation threshold can be
invented out of clamping. These tests pin the current generation's windows and
the data-driven rescue for models the table doesn't know.
"""

from __future__ import annotations

from contextrot.pricing import (
    DEFAULT_CONTEXT_WINDOW,
    context_window_for,
    infer_window,
    pricing_for,
)

_MILLION = 1_000_000


def test_current_anthropic_models_have_million_token_windows():
    for model in (
        "claude-opus-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-5",
        "claude-sonnet-4-6",
        "claude-fable-5",
    ):
        assert context_window_for(model) == _MILLION, model


def test_two_hundred_k_generation():
    for model in ("claude-haiku-4-5", "claude-opus-4-5", "claude-sonnet-4-5"):
        assert context_window_for(model) == 200_000, model


def test_separator_and_case_insensitive():
    # Adapters hand us whatever the transcript recorded.
    assert context_window_for("Opus-4.8") == _MILLION
    assert context_window_for("claude-opus-4-8") == _MILLION


def test_specific_families_win_over_generic_prefix():
    # "opus-4-8" must not be swallowed by the older, pricier "opus-4" entry.
    assert pricing_for("claude-opus-4-8").input == 5.0
    assert pricing_for("claude-opus-4-5").input == 15.0


def test_unknown_model_falls_back_to_default():
    assert context_window_for("big-pickle") == DEFAULT_CONTEXT_WINDOW


def test_infer_window_rescues_an_impossible_fill():
    # A prompt can't exceed its own window, so 364k observed under a 200k guess
    # means the guess was wrong — step up to the smallest window that fits.
    assert infer_window(364_193, 200_000) == _MILLION


def test_infer_window_leaves_a_consistent_guess_alone():
    assert infer_window(150_000, 200_000) == 200_000
    assert infer_window(200_000, 200_000) == 200_000


def test_infer_window_handles_beyond_known_tiers():
    huge = 5 * _MILLION
    assert infer_window(huge, 200_000) == huge
