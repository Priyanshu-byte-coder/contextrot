# Sharing your curve

Every claim about context rot so far comes from lab benchmarks — needle-in-a-haystack,
synthetic retrieval, controlled prompts. Nobody knows what the curve looks like on real
coding work across many people, because nobody has had the data. contextrot produces it,
one machine at a time. `contextrot share` is how those curves get pooled.

```bash
contextrot share --copy
```

Then paste it into a
**[Share your curve](https://github.com/Priyanshu-byte-coder/contextrot/issues/new?template=share_your_curve.yml)**
issue. Clean curves count exactly as much as rotten ones — how often rot *doesn't* show up
is half of what nobody knows.

## No telemetry. Ever.

`share` prints a JSON block, optionally copies it to your clipboard, and stops. **It sends
nothing anywhere** — contextrot has no HTTP client and makes zero network calls. You read
the block, decide, and paste it yourself.

That's deliberate. A pooled dataset doesn't need a network call in the tool; it needs a
step people can trust, and "you can read every byte before it leaves" is that step. The
submit link carries no data either — a query string is logged by every server it passes
through, so only the template name is in it.

`--copy` uses your operating system's own clipboard program (`clip`, `pbcopy`, `wl-copy`,
`xclip` or `xsel`). If none is available it says so and you copy the printed block by hand.

The JSON goes to stdout and the instructions to stderr, so this saves just the data:

```bash
contextrot share > my-curve.json
```

## What's in it

Aggregate statistics only.

| Key | What it is |
|---|---|
| `schema`, `tool`, `version` | format version (currently `1`) and the contextrot version |
| `days` | the window analyzed; `null` means all history |
| `sessions`, `steps` | how much data the curve is built on |
| `agents` | which agent CLIs contributed (e.g. `claude-code`, `codex`) |
| `max_window` | the largest context window seen, in tokens |
| `verdict` | kind, threshold, fresh and deep rates and counts, ratio, significance, zone bounds |
| `curve` | per 10%-fill bucket: steps `n` and `failures` |
| `snowball` | per "mistakes so far" bucket: `n` and `failures` |
| `signals` | the rate of each of the five failure signals |
| `factors` | for each factor: strength, ratio, and every group's `n` and `failures` |
| `by_agent`, `by_model` | each one's verdict, fresh and deep rates, ratio and threshold |
| `waste_share` | the share of token value spent on steps that slipped |
| `startup_share_of_window` | average startup overhead as a share of the window |

Counts are integers, not just rates, so curves from different people can be pooled
exactly — summing steps and failures per bucket — rather than averaged.

## What's never in it

- project names or repository names
- file paths, of any kind
- session ids or timestamps
- prompts, code, or anything the model wrote
- dollar figures
- model names from unknown vendors

That last one needs a word. Model *families* come from the raw model id, so a private
fine-tune named after a company would surface under the company's name. Only families from
known public vendors (Anthropic, OpenAI, Google, Qwen, DeepSeek, Mistral, Meta and so on)
appear by name; everything else is pooled as `other`, or left out of `by_model`.

These guarantees are enforced by a test, not a promise: `tests/test_share.py` builds a
corpus whose project name and paths contain a secret, checks the secret really reached the
analysis, and then walks every string in the shared payload to confirm it didn't leak.

## For anyone pooling curves

- A change in a field's meaning, or its removal, bumps `schema`. Adding a field does not —
  ignore keys you don't recognise.
- Pool `curve` and `snowball` by summing `n` and `failures` per bucket; the bucket bounds are
  fixed (`lo`/`hi` in 10% steps; `reversals` labels match across versions).
- `verdict` is a finished judgement on one machine's data. Don't average verdicts; recompute
  one from the pooled buckets.
- Treat it as observational data from self-selected volunteers. A pooled curve describes the
  people who shared, not developers in general.
