# ctxprof

**Your coding agent gets worse as its context fills. ctxprof proves it on your own sessions — and tells you exactly what to change.**

[![CI](https://github.com/priyanshudoshi/ctxprof/actions/workflows/ci.yml/badge.svg)](https://github.com/priyanshudoshi/ctxprof/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/ctxprof)](https://pypi.org/project/ctxprof/)
[![Python](https://img.shields.io/pypi/pyversions/ctxprof)](https://pypi.org/project/ctxprof/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

```
uvx ctxprof
```

No config. No API keys. No uploads. ctxprof reads the agent transcripts already sitting on your disk and answers a question no other tool answers:

> **At what context fill does *my* agent start failing, what's causing it, and what is it costing me?**

```
╭──────────────── ctxprof — your context rot report ────────────────╮
│                                                                    │
│  Deep-context failure rate: 31.4% vs 14.9% in fresh context        │
│  (2.1×, statistically separated)                                   │
│  Your degradation threshold: ~60% context fill                     │
│  Est. spend on degraded steps: $23.40 of $148.02 total             │
│                                                                    │
╰────────────────────────────────────────────────────────────────────╯

           Failure-signal rate by context fill
   Fill    Rate                                            n   95% CI
  0–10%     9%  ████████                                 214   6%–13%
 10–20%    12%  ███████████                              308   9%–16%
 20–30%    14%  █████████████                            257  10%–18%
 ...
 60–70%    29%  ███████████████████████████              121  22%–37%
 70–80%    34%  ████████████████████████████████          87  25%–44%
```

## What "context rot" is — and why a benchmark can't tell you

Research ([Chroma's context-rot report](https://www.trychroma.com/research/context-rot), several 2026 papers) shows LLM output quality degrades as input context grows — even far below the window limit. But that research runs synthetic tasks in lab conditions. Your degradation point depends on *your* projects, *your* MCP setup, *your* model, *your* prompting style.

ctxprof measures it where it actually matters: in your own sessions.

## How it works

Agent CLIs like Claude Code log every session to local JSONL transcripts. Each step in those transcripts carries token accounting *and* behavioral evidence:

- **edit failures** — the agent tried to edit code and missed
- **retry loops** — the same tool call repeated after an error
- **re-reads** — the agent re-reading files it already read (it lost track)
- **self-corrections** — "I apologize, let me fix that"
- **tool errors** — any failed tool call

ctxprof extracts these signals per step, computes context fill at that moment, and correlates the two — with Wilson 95% confidence intervals, per-signal breakdowns, and honest n-counts. Then it estimates what degraded steps cost you and emits prescriptions quantified from your own data.

Full method: [docs/methodology.md](docs/methodology.md).

## What ctxprof is not

Be suspicious of any tool that won't tell you this, so:

- **Not a spend meter.** [ccusage](https://github.com/ryoppippi/ccusage) is excellent at "how much did I spend" — use it, it's complementary. ctxprof answers "where does my agent *degrade* and why."
- **Not Claude Code's `/context`.** That's a point-in-time composition snapshot. ctxprof correlates fill with *outcomes* across your whole history.
- **Not an observability platform.** Langfuse/Phoenix/MLflow instrument apps you build. ctxprof needs zero instrumentation and analyzes the agent you *use*.
- **Not a controlled experiment.** It's an observational diagnostic on your own data, with the statistical caveats printed right on the report.

## Install & use

```bash
uvx ctxprof            # zero-install run
# or
pip install ctxprof
```

```bash
ctxprof                        # full report, last 30 days
ctxprof --days 90              # widen the range
ctxprof -p myproject           # one project only
ctxprof --html report.html     # shareable single-file report (still local)
ctxprof --json                 # machine-readable
ctxprof sessions               # list what was parsed
```

Supported agents: **Claude Code** (today). Codex CLI, OpenCode, Gemini CLI, and OpenTelemetry GenAI spans are next — an adapter is one small file, and [writing one is the paved first-contribution path](CONTRIBUTING.md).

## Privacy

ctxprof makes **zero network calls**. It reads local transcript files, prints to your terminal, and optionally writes a local HTML file. Nothing leaves your machine. Grep the codebase for `http` — you won't find a client.

## Roadmap

- `ctxprof fix` — apply prescriptions interactively (disable unused MCP servers, trim CLAUDE.md) with before/after measurement
- More agent adapters + OTel ingestion
- Opt-in, anonymized aggregate stats → the **State of Context Rot** report: real-workload degradation curves across the community (off by default, documented schema, aggregate-only)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The most valuable first PR: an adapter for the agent CLI you use.

## License

[MIT](LICENSE)
