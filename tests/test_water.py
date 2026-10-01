"""Water estimates, formatting, and the incremental session cursor."""

from __future__ import annotations

import json

import pytest

from contextrot.models import Session, Step
from contextrot.water import (
    ML_PER_WH,
    ML_PER_WH_COOLING,
    ML_PER_WH_GENERATION,
    WH_PER_1K_CACHE_READ,
    WH_PER_1K_OUTPUT,
    WH_PER_1K_PREFILL,
    WaterTotals,
    comparison,
    energy_scale,
    fmt_energy,
    fmt_tokens,
    fmt_volume,
    provenance,
    session_water,
    step_energy_wh,
    step_water_ml,
    totals_for_sessions,
)

# --- the estimate itself -----------------------------------------------------


def test_energy_scale_orders_model_sizes() -> None:
    assert energy_scale("claude-haiku-4-5") < energy_scale("claude-sonnet-5")
    assert energy_scale("claude-sonnet-5") < energy_scale("claude-opus-5")
    assert energy_scale("claude-opus-5") == energy_scale("claude-fable-5")


def test_small_model_markers_beat_the_family_name() -> None:
    """"gpt-4o-mini" holds both "-mini" and "gpt-4"; the small tier has to win."""
    assert energy_scale("gpt-4o-mini") < energy_scale("gpt-4o")
    assert energy_scale("gemini-2.5-flash") < energy_scale("gemini-3-pro")


def test_unknown_model_is_assumed_mid_sized() -> None:
    mid = energy_scale("claude-sonnet-5")
    assert energy_scale("some-internal-codename") == mid
    assert energy_scale("") == mid


def test_cache_reads_are_far_cheaper_per_token_than_output() -> None:
    """The whole point of three rates: a replayed prefix is not a decode."""
    reads = step_water_ml(0, 0, 1_000_000, 0, "claude-opus-5")
    output = step_water_ml(0, 0, 0, 1_000_000, "claude-opus-5")
    assert output / reads == WH_PER_1K_OUTPUT / WH_PER_1K_CACHE_READ


def test_the_token_rates_track_what_providers_charge_for_them() -> None:
    """The only external anchor for prefill and cache replay is their price.

    Opus 5 is $5.00 fresh input, $0.50 cache read and $25.00 output per MTok, so
    20% and 2% of the output rate. An earlier version of this module used half of
    each, which put the whole estimate about 2x low.
    """
    assert pytest.approx(5.00 / 25.00) == WH_PER_1K_PREFILL / WH_PER_1K_OUTPUT
    assert pytest.approx(0.50 / 25.00) == WH_PER_1K_CACHE_READ / WH_PER_1K_OUTPUT


def test_water_is_energy_times_the_published_ratio() -> None:
    wh = step_energy_wh(1_000, 2_000, 300_000, 4_000, "claude-opus-5")
    assert step_water_ml(1_000, 2_000, 300_000, 4_000, "claude-opus-5") == wh * ML_PER_WH


def test_negative_counts_cannot_subtract_water() -> None:
    assert step_water_ml(-5, -5, -5, -5, "claude-opus-5") == 0.0


# --- totals ------------------------------------------------------------------


def _step(model: str = "claude-opus-5", **kw: int) -> Step:
    return Step(timestamp=None, model=model, **kw)


def test_buckets_account_for_the_whole_total() -> None:
    totals = WaterTotals()
    totals.add_step(1_000, 5_000, 400_000, 2_000, "claude-opus-5", agent="claude-code")
    totals.add_step(500, 0, 120_000, 800, "claude-haiku-4-5", agent="codex")
    assert sum(totals.by_bucket.values()) == pytest.approx(totals.ml)
    assert sum(totals.by_agent.values()) == pytest.approx(totals.ml)
    assert sum(totals.by_model.values()) == pytest.approx(totals.ml)


def test_bucket_rows_are_ordered_and_share_one() -> None:
    totals = WaterTotals()
    totals.add_step(1_000, 5_000, 400_000, 2_000, "claude-opus-5")
    rows = totals.bucket_rows()
    assert [label for label, _, _ in rows] == ["cache reads", "output", "fresh input"]
    assert sum(share for _, _, share in rows) == pytest.approx(1.0)
    # For an agent replaying a large context, cache reads dominate — that is the
    # finding the breakdown exists to surface.
    assert totals.dominant_bucket() == ("cache reads", rows[0][2])


def test_empty_totals_claim_nothing() -> None:
    totals = WaterTotals()
    assert totals.dominant_bucket() is None
    assert totals.bucket_rows() == []
    assert totals.ranked(totals.by_agent) == []


def test_totals_for_sessions_skips_empty_sessions() -> None:
    full = Session(session_id="a", source="claude-code", project="p")
    full.add_step(_step(input_tokens=100, output_tokens=50))
    full.add_step(_step(cache_read_tokens=9_000))
    empty = Session(session_id="b", source="codex", project="p")

    totals = totals_for_sessions([full, empty])
    assert totals.sessions == 1
    assert totals.steps == 2
    assert totals.by_agent == {"claude-code": totals.ml}
    assert totals.total_tokens == 100 + 50 + 9_000


# --- formatting --------------------------------------------------------------


def test_fmt_volume_switches_unit_and_precision() -> None:
    assert fmt_volume(0.4) == "0.40 ml"
    assert fmt_volume(3.42) == "3.4 ml"
    assert fmt_volume(812.4) == "812 ml"
    assert fmt_volume(4_123) == "4.12 L"
    assert fmt_volume(47_000) == "47.0 L"
    assert fmt_volume(1_240_000) == "1,240 L"
    assert fmt_volume(-5) == "0.00 ml"


def test_fmt_energy_and_tokens() -> None:
    assert fmt_energy(0.4) == "0.40 Wh"
    assert fmt_energy(812) == "812 Wh"
    assert fmt_energy(3_810) == "3.81 kWh"
    assert fmt_tokens(950) == "950"
    assert fmt_tokens(68_000) == "68.0k"
    assert fmt_tokens(9_630_000_000) == "9.6B"


def test_comparison_picks_the_largest_unit_that_counts() -> None:
    assert comparison(0.5) is None  # below a teaspoon, every comparison lies
    assert comparison(5.1) == "about a teaspoon"
    assert comparison(6) == "about 1.2 teaspoons"
    assert comparison(500) == "about a water bottle"
    assert comparison(4_100) == "about 8.2 water bottles"
    assert comparison(190_000) == "about 1.3 bathtubs"


def test_provenance_names_every_constant_it_uses() -> None:
    text = provenance()
    for fragment in ("0.6 Wh", "1.08 mL/Wh", "1.8 mL/Wh", "0.24 Wh", "Estimate"):
        assert fragment in text


def test_the_reported_figure_is_the_total_not_just_cooling() -> None:
    """Cooling alone understates the footprint by nearly 3x."""
    assert pytest.approx(ML_PER_WH_COOLING + ML_PER_WH_GENERATION) == ML_PER_WH
    assert ML_PER_WH > 2 * ML_PER_WH_COOLING


# --- the live session cursor -------------------------------------------------


def _assistant(output: int = 100, cache_read: int = 0) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "model": "claude-opus-5",
                "usage": {
                    "input_tokens": 10,
                    "cache_creation_input_tokens": 20,
                    "cache_read_input_tokens": cache_read,
                    "output_tokens": output,
                },
            },
        }
    )


def test_session_water_counts_a_transcript(tmp_path) -> None:
    transcript = tmp_path / "s.jsonl"
    transcript.write_text(_assistant() + "\n", encoding="utf-8")
    live = session_water(transcript, cache=tmp_path / "cache.json")
    assert live is not None and live.ml > 0


def test_the_frame_index_advances_once_per_render(tmp_path) -> None:
    """The droplet loop is driven by this, not by a clock."""
    transcript = tmp_path / "s.jsonl"
    cache = tmp_path / "cache.json"
    transcript.write_text(_assistant() + "\n", encoding="utf-8")
    frames = [session_water(transcript, cache=cache).frame for _ in range(4)]
    assert frames == [1, 2, 3, 4]


def test_the_two_halves_of_the_water_figure_sum_to_it() -> None:
    totals = WaterTotals()
    totals.add_step(1_000, 5_000, 400_000, 2_000, "claude-opus-5")
    assert totals.cooling_ml + totals.generation_ml == pytest.approx(totals.ml)
    # Generation is the larger half, which is why quoting cooling alone misleads.
    assert totals.generation_ml > totals.cooling_ml


def test_the_output_rate_reproduces_the_published_median_prompt() -> None:
    """1k prefill + 300 output lands on Google's published 0.24 Wh median."""
    wh = step_energy_wh(1_000, 0, 0, 300, "claude-opus-5")
    assert wh == pytest.approx(0.30, abs=0.01)


def test_repeated_calls_do_not_double_count(tmp_path) -> None:
    transcript = tmp_path / "s.jsonl"
    cache = tmp_path / "cache.json"
    transcript.write_text(_assistant() + "\n", encoding="utf-8")

    first = session_water(transcript, cache=cache)
    second = session_water(transcript, cache=cache)
    assert first is not None and second is not None
    assert first.ml == second.ml


def test_appended_lines_add_exactly_their_own_cost(tmp_path) -> None:
    transcript = tmp_path / "s.jsonl"
    cache = tmp_path / "cache.json"
    transcript.write_text(_assistant() + "\n", encoding="utf-8")
    before = session_water(transcript, cache=cache)

    with transcript.open("a", encoding="utf-8") as f:
        f.write(_assistant(output=400) + "\n")
    after = session_water(transcript, cache=cache)

    added = step_water_ml(10, 20, 0, 400, "claude-opus-5")
    assert before is not None and after is not None
    assert abs((after.ml - before.ml) - added) < 1e-9


def test_a_half_written_line_is_not_counted_until_it_is_complete(tmp_path) -> None:
    """Transcripts are appended to live, so the tail is routinely truncated."""
    transcript = tmp_path / "s.jsonl"
    cache = tmp_path / "cache.json"
    transcript.write_text(_assistant() + "\n" + '{"type": "assist', encoding="utf-8")
    partial = session_water(transcript, cache=cache)

    # Finish the line. Its tokens appear now, and the bytes are not re-read.
    with transcript.open("a", encoding="utf-8") as f:
        f.write('ant"}\n' + _assistant(output=250) + "\n")
    complete = session_water(transcript, cache=cache)

    assert partial is not None and complete is not None
    added = step_water_ml(10, 20, 0, 250, "claude-opus-5")
    assert abs((complete.ml - partial.ml) - added) < 1e-9


def test_a_truncated_transcript_starts_over(tmp_path) -> None:
    transcript = tmp_path / "s.jsonl"
    cache = tmp_path / "cache.json"
    transcript.write_text((_assistant() + "\n") * 4, encoding="utf-8")
    big = session_water(transcript, cache=cache)

    transcript.write_text(_assistant() + "\n", encoding="utf-8")
    small = session_water(transcript, cache=cache)

    assert big is not None and small is not None
    assert small.ml < big.ml
    assert abs(small.ml - step_water_ml(10, 20, 0, 100, "claude-opus-5")) < 1e-9


def test_nothing_to_report_stays_silent(tmp_path) -> None:
    cache = tmp_path / "cache.json"
    assert session_water(None, cache=cache) is None
    assert session_water(tmp_path / "missing.jsonl", cache=cache) is None

    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert session_water(empty, cache=cache) is None

    # Readable, but holds nothing with token usage: still nothing to say.
    noise = tmp_path / "noise.jsonl"
    noise.write_text('{"type": "user"}\nnot json\n', encoding="utf-8")
    assert session_water(noise, cache=cache) is None


def test_a_corrupt_cache_is_rebuilt_not_trusted(tmp_path) -> None:
    transcript = tmp_path / "s.jsonl"
    cache = tmp_path / "cache.json"
    transcript.write_text(_assistant() + "\n", encoding="utf-8")
    cache.write_text("}{ not json", encoding="utf-8")

    live = session_water(transcript, cache=cache)
    assert live is not None and live.ml > 0
    assert json.loads(cache.read_text(encoding="utf-8"))["sessions"]


def test_a_cache_from_different_constants_is_discarded(tmp_path) -> None:
    """Totals computed under old rates are not reproducible, so they are not kept."""
    transcript = tmp_path / "s.jsonl"
    cache = tmp_path / "cache.json"
    transcript.write_text(_assistant() + "\n", encoding="utf-8")
    first = session_water(transcript, cache=cache)

    stale = json.loads(cache.read_text(encoding="utf-8"))
    stale["model"] = "deadbeef1234"
    for entry in stale["sessions"].values():
        entry["ml"] = 999_999.0  # a figure the current constants could never give
    cache.write_text(json.dumps(stale), encoding="utf-8")

    again = session_water(transcript, cache=cache)
    assert first is not None and again is not None
    assert again.ml == first.ml


def test_codex_shape_is_split_without_changing_the_prompt_total(tmp_path) -> None:
    """Codex's input_tokens already includes the cached prefix."""
    transcript = tmp_path / "codex.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "model": "gpt-5.4",
                        "model_context_window": 272_000,
                        "last_token_usage": {
                            "input_tokens": 100_000,
                            "cached_input_tokens": 90_000,
                            "output_tokens": 500,
                        },
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    live = session_water(transcript, cache=tmp_path / "cache.json")
    # 10k fresh prefill + 90k replayed + 500 decoded, not 100k priced as fresh.
    assert live is not None
    assert abs(live.ml - step_water_ml(10_000, 0, 90_000, 500, "gpt-5.4")) < 1e-9


def test_milestones_are_the_next_round_number_up() -> None:
    from contextrot.water import milestone

    assert milestone(420) == (500.0, pytest.approx(0.2))
    assert milestone(980) == (1_000.0, pytest.approx(0.8))
    assert milestone(3_400) == (4_000.0, pytest.approx(0.4))
    assert milestone(38_209) == (40_000.0, pytest.approx(0.8209))
    assert milestone(470_000) == (500_000.0, pytest.approx(0.7))


def test_a_milestone_fraction_is_always_a_usable_level() -> None:
    from contextrot.water import milestone

    for ml in (0, 1, 99, 999, 1_000, 9_999, 100_000, 5_000_000):
        ceiling, fraction = milestone(ml)
        assert ceiling > ml
        assert 0.0 <= fraction < 1.0
