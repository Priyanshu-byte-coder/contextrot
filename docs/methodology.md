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

Two caveats, same observational spirit as the fill axis. Reversal events autocorrelate: one retry loop both raises the counter and supplies several nearby failures, so a burst can manufacture its own slope. And the counter never resets within a session, so the 5+ bucket skews toward long sessions — steps there are also later-in-task steps, the same confounder the fill axis carries. Read the reversal curve as a complementary lens, not an independent experiment.

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

## Zone selection

The fresh/deep split above is the default. On a 1M-token window it can be unreachable — agents
compact long before 600k tokens, so the deep zone never fills and no verdict is possible. When
the absolute split cannot populate both zones, contextrot falls back to the **40th and 80th
percentiles of your own fill distribution**, provided the two zones stay at least 8 points apart
and each still clears the minimum sample size. Reports label which mode produced the verdict, so
an adaptive comparison is never presented as an absolute one.

## Scoped curves

A threshold measured on one agent does not describe another, and a 200k-window model and a
1M-window model have different curves *and* different denominators — averaging them describes
neither. So curves are computed and cached **per agent, per model family, and per agent+model
pair**, alongside the blended one.

Live surfaces resolve the narrowest scope that fits the session in front of them:

    agent+model  →  model  →  agent  →  global

Each level must clear the same minimum step count on its own before it is trusted, so a thin
scope falls through to a broader one rather than quoting a threshold built from noise. A scope
that blends over the other axis (one model across several agents, or one agent across several
models) is still quoted — it fixes at least one variable — but is labelled as blended rather
than presented as the session's own.

Model ids are canonicalised to a family key before grouping (`claude-opus-4-8` → `opus-4.8`,
`us.anthropic.claude-sonnet-4-6-v1:0` → `sonnet-4.6`). Non-Anthropic vendors get their own keys
derived from the id, so `gpt-5.6-terra` and `gpt-5.6-sol` group together rather than landing in
a single "unknown" bucket with every other vendor.

## Turn cost and headroom

A **turn** runs from one user prompt to the next. Its cost is the difference in prompt tokens
between the step that opens it and the step that opens the following one — everything the agent
read, ran and wrote in between. Negative differences are dropped rather than clamped: the context
shrank, which means a compaction or a fresh branch, not a turn that cost negative tokens.

Headroom is remaining tokens divided by the **median** turn cost, with the **90th percentile**
quoted beside it once headroom is tight. Both are needed: on real data the p90 turn is several
times the median, so a median-only estimate promises room that one expensive turn erases.

Turns rather than steps on purpose. Per-step growth is dominated by cache replay — a median step
adds on the order of a thousand tokens — so headroom expressed in steps runs to the hundreds and
reads as unlimited. Below 50 observed turns no headroom is reported at all; an estimate built on
noise reads as a promise.

## Cost figures

Per-step cost uses published API list prices per model (input, output, cache read, cache write). For subscription users this is the *API-equivalent value*, not a bill. "Spend on degraded steps" sums the cost of steps where a failure signal fired — a lower bound on rework cost, since it excludes the follow-up work those failures caused. `contextrot waste` breaks the same figure down by signal; because one step can trip several signals, those rows overlap and deliberately do not sum to the total. Unknown models fall back to conservative defaults and are marked estimated.

## Composition estimate

Startup overhead is the prompt size of each session's *first* API call (system prompt + tool schemas + project instructions — everything loaded before your first word), averaged per session and exact from token accounting. Tool-output and conversation figures use a 4-characters-per-token heuristic and are labeled estimates. With compaction, flow-through figures can exceed the window size; that flow is precisely what fills it.

## Water and energy (the one estimate)

Every other number in this document is measured from your transcripts. The water figure behind `contextrot water` and the `water` statusline segment is not, and it is labelled that way wherever it appears. The token counts feeding it are real; the constants that turn them into litres are published figures with real error bars.

### Tokens to energy

Three rates rather than one, because the three kinds of token cost wildly different amounts of compute:

| Token kind | Wh per 1k | Why |
|---|---|---|
| Output (decode) | 0.60 | One full forward pass per token |
| Fresh input and cache creation (prefill) | 0.12 | The whole prompt in parallel, so far cheaper per token |
| Cache read (replay) | 0.012 | Recomputes nothing; costs little more than moving the KV tensors |

Collapsing these into one per-token rate is the single biggest way to get this wrong. A coding agent's token total is dominated by cache reads — typically over 90% of it — so pricing them like fresh input overstates the result several times over, and pricing them like nothing understates it.

**The output rate is the well-anchored one.** On these constants a 1,000-token prompt with a 300-token answer comes to 0.24 Wh, which is exactly [Google's published median for a text prompt](https://cloud.google.com/blog/products/infrastructure/measuring-the-environmental-impact-of-ai-inference). Independently, Epoch AI put a typical GPT-4o query at about 0.3 Wh for roughly 500 output tokens — the same 0.6 per 1k. Two different sources, same number.

**Prefill and cache replay are anchored to price**, which is the only external signal available for them: providers charge 20% of the output rate for fresh input and 2% for a cache read (Opus 5: $5.00 / $0.50 / $25.00 per MTok). Price is not cost, but it is a market signal that cost at least loosely tracks. Version 1.8.0 used 10% and 1% — half of each — which put the whole estimate about 2x low, and worst for exactly the long-context agent sessions this tool exists to study.

### Model size

A coarse three-tier multiplier on those rates: frontier (Opus / Fable / GPT-5 / Gemini 3 class) at 1.0, mid at 0.5, small (Haiku / Flash / mini / nano class) at 0.15. Three tiers rather than a curve because "small / mid / frontier" is the honest resolution available from outside a provider; anything finer would be invented. An unrecognised model is assumed mid-sized, not frontier — guessing high would quietly inflate the figure for every model the table does not know.

### Energy to water, in two parts

Water is consumed twice over, and only reporting the first part is how an estimate ends up several times too small:

| Where | mL per Wh | What it is |
|---|---|---|
| Datacenter cooling | 1.08 | Evaporated in cooling towers and evaporative loops |
| Electricity generation | 1.80 | Consumed at the power station that supplied the datacenter |
| **Total (reported)** | **2.88** | |

The cooling figure is not a free parameter: it is Google's own published pair for a median text prompt — 0.26 mL of water against 0.24 Wh of energy — divided. The same ratio matches their reported fleet water-usage effectiveness of about 1.1 L/kWh, so two independently published numbers agree.

The generation figure is the consumptive water intensity of US grid electricity. Thermoelectric plants evaporate cooling water of their own, and hydro reservoirs evaporate from their surface; wind and solar consume almost none. So this term swings enormously with grid mix — a datacenter on a clean grid sits far below it, one on a hydro-heavy grid far above. It is nonetheless the *larger* of the two terms, which is why quoting cooling alone understates the footprint by nearly 3x.

`contextrot water` prints the total and then the split, so either convention is readable off the same output.

### What biases it low

**Long-context attention is not priced separately.** Generating one output token requires attending over the entire prefix, so decode gets more expensive as context grows — and a single flat per-output-token rate cannot express that. Modelling it properly needs an attention-cost constant that is not published anywhere, so rather than invent one, this is recorded as a known floor: **the figure is biased low, and increasingly so on deep-context sessions.** That is the opposite of the bias you would want from a tool arguing that long contexts are costly, which is why it is stated here rather than buried.

### Uncertainty

Plus or minus 2x, quoted with the number every time. The constants are public medians across whole fleets; a specific datacenter on a specific day, with a specific cooling design and a specific grid mix, sits well either side of them. The figure is useful for *relative* comparison — which agent, which model, which bucket — and for order of magnitude. It is not a utility bill.

The derivation is reproducible: `contextrot water --json` emits the raw token counts, the energy total, the cooling and generation halves, and the split by bucket, agent and model family, so any of it can be recomputed against different constants.

## What this is not

- **Not causal.** contextrot measures association between context fill and failure signals in observational data. Deep-context steps also tend to be later in harder tasks; some of the association is task difficulty, not rot. The report never claims otherwise.
- **Not a benchmark.** Results describe *your* sessions with *your* configuration. They will differ from lab results ([Chroma's context-rot report](https://www.trychroma.com/research/context-rot)) and from other users — that's the point.
- **Not ground truth on quality.** Signals are proxies with false positives and negatives. They are useful because they are consistent proxies: the same heuristics applied at every fill level, so *differences across fill levels* are meaningful even when absolute rates are noisy.

## Reproducibility

`contextrot --json` emits every per-step signal record and per-bucket statistic, so any number in the report can be recomputed independently. `contextrot waste --json` and `contextrot status --format json` do the same for the cost breakdown and the live reading, the latter naming which scope answered.
