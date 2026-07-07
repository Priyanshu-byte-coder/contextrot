# Methodology

This page documents exactly how contextrot computes what it shows, including the limitations. If you're evaluating whether to trust the numbers, read this end to end — it's short.

## Data source

contextrot reads agent transcripts already on your disk (for Claude Code: `~/.claude/projects/<project>/<session>.jsonl`). Each transcript records every model API call with token accounting, every tool invocation, and every tool result. Nothing is instrumented and nothing is uploaded; analysis is a pure local read.

Sub-agent ("sidechain") traffic runs in its own context window, so it is excluded from the main analysis and counted separately. Sessions with fewer than 3 steps are skipped.

## Context fill

For each model call ("step"), context fill is the prompt-side token count — `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` — divided by the model's context window (200k default, `--window` to override). This is the exact size of what the model had to read at that moment, taken from the agent's own accounting, not an estimate.

## Reversal count

Context fill is not the only axis that can explain failures. contextrot also counts session-local reversals: correction/retry events that suggest the working state has become contradictory or has had to be revised.

The reversal proxy for a step is:

- `self_correction`
- `retry`
- `edit_failure` on a target that was edited earlier in the same session

Each step is bucketed by the number of reversals that happened **before** that step: 0, 1, 2, 3-4, or 5+. The y-axis is the current step's degraded rate with the same Wilson 95% intervals and low-confidence flag used for the fill curve. This avoids circularity: a same-step failure can increment the reversal count for later steps, but it does not explain itself in the current bucket.

## Outcome signals

Five per-step signals, each an independent heuristic, each reported separately as well as combined:

| Signal | Definition | Rationale |
|---|---|---|
| `tool_error` | any tool call in the step returned an error | direct failure evidence |
| `edit_failure` | an editing tool (Edit/Write/MultiEdit/...) returned an error | for coding agents, the clearest "model lost track of file state" event |
| `retry` | the step repeats a (tool, target) pair that errored within the previous 6 steps | rework: paying twice for the same action |
| `reread` | the step re-Reads a file already read earlier in the session | proxy for content scrolled out of effective attention |
| `self_correction` | assistant text matches apology/correction phrases ("I apologize", "my mistake", "let me fix that", ...) | linguistic marker of a recognized error |

A step is **degraded** if any signal fired. Signals are deliberately simple and inspectable — every one can be verified by grepping your own transcript. Known noise sources: `reread` can be legitimate (file changed on disk); `self_correction` matches politeness patterns imperfectly. This is why per-signal counts are always shown: a conclusion driven by one noisy signal is visible as such.

## The rot curve

Steps are bucketed by fill percentage (10-point buckets). Per bucket, contextrot reports the degraded-step rate with a **Wilson 95% score interval** (chosen over normal approximation because bucket counts can be small and rates sit near 0). Buckets with fewer than 15 steps are flagged low-confidence.

Two summary zones: **fresh** (< 40% fill) and **deep** (≥ 60%). The headline ratio is deep rate / fresh rate; it is labeled *statistically separated* only when the two zones' Wilson intervals don't overlap — a conservative test.

The **degradation threshold (knee)** is the start of the first non-low-confidence bucket at ≥ 40% fill whose rate reaches 1.5× the fresh-zone rate. If no bucket qualifies, no knee is reported — a flat curve is a valid result and contextrot will happily tell you your setup shows no measurable rot.

## Cost figures

Per-step cost uses published API list prices per model (input, output, cache read, cache write). For subscription users this is the *API-equivalent value*, not a bill. "Spend on degraded steps" sums the cost of steps where a failure signal fired — a lower bound on rework cost, since it excludes the follow-up work those failures caused. Unknown models fall back to conservative defaults and are marked estimated.

## Composition estimate

Startup overhead is the prompt size of each session's *first* API call (system prompt + tool schemas + project instructions — everything loaded before your first word), averaged per session and exact from token accounting. Tool-output and conversation figures use a 4-characters-per-token heuristic and are labeled estimates. With compaction, flow-through figures can exceed the window size; that flow is precisely what fills it.

## What this is not

- **Not causal.** contextrot measures association between context fill and failure signals in observational data. Deep-context steps also tend to be later in harder tasks; some of the association is task difficulty, not rot. The report never claims otherwise.
- **Not a benchmark.** Results describe *your* sessions with *your* configuration. They will differ from lab results ([Chroma's context-rot report](https://www.trychroma.com/research/context-rot)) and from other users — that's the point.
- **Not ground truth on quality.** Signals are proxies with false positives and negatives. They are useful because they are consistent proxies: the same heuristics applied at every fill level, so *differences across fill levels* are meaningful even when absolute rates are noisy.

## Reproducibility

`contextrot --json` emits every per-step signal record and per-bucket statistic, so any number in the report can be recomputed independently.
