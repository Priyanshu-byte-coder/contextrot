<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Priyanshu-byte-coder/contextrot/main/assets/logo_dark.png">
    <img src="https://raw.githubusercontent.com/Priyanshu-byte-coder/contextrot/main/assets/logo_white.png" alt="contextrot logo" width="200" height="200">
  </picture>
  <h1>contextrot</h1>
  <p><strong>Your coding agent gets worse as its context fills.<br>contextrot proves it on your own sessions — and tells you exactly what to change.</strong></p>
</div>

<p align="center">
  <a href="https://pypi.org/project/contextrot/"><img src="https://img.shields.io/pypi/v/contextrot?color=2a78d6" alt="PyPI version"></a>
  <a href="https://pepy.tech/projects/contextrot"><img src="https://static.pepy.tech/personalized-badge/contextrot?period=total&units=INTERNATIONAL_SYSTEM&left_color=BLACK&right_color=GREEN&left_text=downloads" alt="PyPI Downloads"></a>
  <a href="https://pypi.org/project/contextrot/"><img src="https://img.shields.io/pypi/pyversions/contextrot?color=2a78d6" alt="Python versions"></a>
  <a href="https://github.com/Priyanshu-byte-coder/contextrot/actions/workflows/ci.yml"><img src="https://github.com/Priyanshu-byte-coder/contextrot/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2a78d6" alt="License: MIT"></a>
</p>

## Quick start

```bash
uvx contextrot
```

or, with plain pip (Python 3.9+ — including the stock python3 on macOS):

```bash
pip3 install contextrot
contextrot
```

> **`contextrot: command not found` after pip install?** Your Python scripts
> directory isn't on `PATH` (common with the stock macOS `python3`). Either use
> `uvx contextrot` above, or run it PATH-free with `python3 -m contextrot`.

That's it. No config, no API keys, no uploads. contextrot reads the session transcripts your agent CLI already keeps on disk and answers a question no other tool answers:

> **At what context fill does *my* agent start failing, what's causing it, and what is it costing me?**

<div align="center">
  <img src="https://raw.githubusercontent.com/Priyanshu-byte-coder/contextrot/main/assets/screenshot.png" alt="contextrot terminal report: verdict, rot curve by context fill with confidence intervals, context composition, and prescriptions" width="900">
  <p><strong><a href="SHOWCASE.md">📸 See every feature in action →</a></strong></p>
</div>

Every report leads with a plain verdict — one of four honest answers:

| Verdict | Meaning |
|---|---|
| ✗ **Context rot detected** | your failure rate climbs significantly as context fills |
| ! **Edge rot** | flat until near the window limit, then it climbs — compact before you get there |
| ✓ **No measurable rot** | your failure rate stays flat; your setup is working |
| ? **Not enough data** | keep using your agent and re-run |

A tool that can say "you're fine" is a tool you can trust when it says you're not.

## What it does, in plain words

One command reads the session logs your coding agent already saved and tells you where it starts getting worse. Everything runs on your machine. Here's the whole tool, by what you might want:

| You want to… | Run | What you get back |
|---|---|---|
| See if your agent degrades — and where | `contextrot` | a plain verdict + the context-fill % where *you* start failing |
| Look further back for tighter numbers | `contextrot --days 90` | the same report over more history |
| Check just one repo | `contextrot -p myproject` | that project's own curve and verdict |
| Get a report you can share | `contextrot --html report.html` | one local HTML file + a ready-to-post image card |
| Find which of your repos rots first | `contextrot projects` | your projects ranked, worst-degrading first |
| Find which agent rots first | `contextrot agents` | Claude Code vs Codex vs Gemini vs Cline, ranked on *your* work |
| Know what to actually change | `contextrot fix` | plain fixes + a list of MCP servers you set up but never use (preview only, changes nothing) |
| Check whether you're improving | `contextrot trends` | week-over-week failure rate and startup-bloat trend |
| Put a status badge in your README | `contextrot badge` | a local SVG verdict badge — no badge service sees your data |

Use more than one model? A head-to-head model comparison (Opus vs Sonnet vs Haiku, on your workload) shows up in the main report automatically.

**And you can run it live inside Claude Code** — a context-health meter in your status bar, an in-session warning when you cross your own threshold, and a way for Claude Code to check its own rot mid-task. [See below.](#use-it-live-inside-claude-code)

## Why a benchmark can't tell you this

Research ([Chroma's context-rot report](https://www.trychroma.com/research/context-rot), several 2026 papers) shows LLM output quality degrades as input context grows — even far below the window limit. But that research runs synthetic tasks in lab conditions. Your degradation point depends on *your* projects, *your* MCP setup, *your* model, *your* prompting style.

contextrot measures it where it actually matters: in your own sessions.

## How it works

Agent CLIs like Claude Code log every session to local JSONL transcripts. Each step carries token accounting *and* behavioral evidence. contextrot extracts five independent failure signals per step and correlates them with context fill at that moment:

| Signal | What it catches |
|---|---|
| **Edit failures** | the agent tried to edit code and missed — the clearest "lost track of file state" event |
| **Retry loops** | the same tool call repeated after an error: paying twice for one action |
| **Re-reads** | re-reading files it already read — content scrolled out of effective attention |
| **Self-corrections** | "I apologize, let me fix that" |
| **Tool errors** | any failed tool call |

Statistics are kept honest: Wilson 95% confidence intervals, per-signal breakdowns, visible n-counts, and a degradation threshold that only gets declared when a bucket's confidence floor clears the baseline — one noisy bucket can't scare you. Full method: [docs/methodology.md](docs/methodology.md).

Use more than one model? The report also compares them head-to-head — an independent rot curve and verdict per model family (Opus vs Sonnet vs Haiku), on a shared scale, so you can see which model degrades first *for your workload*.

Work across several repos? `contextrot projects` does the same head-to-head by **project** — an independent rot curve and verdict per working directory, ranked by size, so the specific repo whose CLAUDE.md or MCP setup is dragging you down stops hiding inside your all-projects average.

Use more than one coding agent? `contextrot agents` compares them too — Claude Code vs Codex CLI vs Gemini CLI vs Cline, each with its own curve and verdict on a shared scale, measured on your workload rather than a benchmark's.

## Command reference

The [table above](#what-it-does-in-plain-words) explains each of these in plain words; this is the quick lookup.

```bash
contextrot                      # full report, last 30 days
contextrot --days 90            # more history = tighter statistics
contextrot -p myproject         # one project only
contextrot --html report.html   # shareable single-file report + share card (100% local)
contextrot --json               # every number, machine-readable
contextrot projects             # rank your projects — which repo rots first
contextrot agents               # rank your coding agents — which CLI rots first
contextrot fix                  # what to change (dry-run; --apply to act, backs up first)
contextrot trends               # week-over-week: are you improving?
contextrot badge                # local SVG verdict badge for your README
contextrot sessions             # list what was parsed

# Live inside Claude Code (see next section):
contextrot install statusline   # context-health meter in your status bar
contextrot install hook         # one in-session warning when you cross your threshold
contextrot mcp                  # let Claude Code query your rot report mid-session
```

## Use it live inside Claude Code

The report tells you where you degrade *after the fact*. These three put it **in front of you while you're working** — and they're the reason a Claude Code user gets the most out of contextrot. All three are dry-run by default, write only with `--apply`, back up your settings first, and undo cleanly with `contextrot uninstall`.

### 1. A live context-health meter in your status bar

```bash
contextrot install statusline --apply
```

Claude Code's status bar shows your current context fill, colored against your *own* measured curve — not a generic "yellow at 70%":

```
ctx 72% ███████░░░ · ▲ past your knee (~70%) · fail here 4.8% (1.5× fresh)
```

Other statusline tools show cost and a hardcoded threshold; this one knows where *you* start failing, and every plain `contextrot` run recalibrates it from your latest sessions.

### 2. A one-time warning the moment you cross your threshold

```bash
contextrot install hook --apply
```

Prefer an active nudge over a passive bar? This registers a hook that warns **once** — the instant a session crosses *your* measured failure threshold — then stays quiet until the next crossing. If your curve has no threshold, it says nothing at all: no generic scare popups.

### 3. Let Claude Code check its own rot, mid-task

```bash
claude mcp add contextrot -- contextrot mcp
```

This runs contextrot as an MCP server, so Claude Code itself can pull your rot report during a session — and decide to compact, warn you, or switch models based on your real numbers. It exposes three tools to the agent: `rot_report`, `agents_ranking`, and `prescriptions`. Still zero network — it's a local pipe, not a socket.

## How is this different from…

| Tool | Question it answers | What it can't tell you |
|---|---|---|
| [ccusage](https://github.com/ryoppippi/ccusage) | "How much did I spend?" | anything about output *quality* — use both, they're complementary |
| Claude Code `/context` | "What's in my window right now?" | no outcomes, no history, no correlation |
| Langfuse / Phoenix / MLflow | "How is the app I *built* behaving?" | require instrumentation; contextrot analyzes the agent you *use*, zero setup |
| Chroma's research | "Do models degrade on benchmarks?" | nothing about your workload — contextrot is the personal-data counterpart |

## FAQ

**The report says $2,000+ but I'm on a $20/month subscription. Is it broken?**
No — that figure is the *token value* of your usage priced at API list rates, labeled as such in the report. It exists because tokens are the resource that fills your context window and burns your rate limits, and dollars are the only unit everyone reads instantly. Two honest readings: it's what your usage *would* cost pay-per-token (enjoy your subscription), and the "burned in degraded steps" share is the fraction of that resource going to rework. It is not, and never claims to be, your bill.

**Why is the token flow so large?**
Agents re-send the entire conversation to the model on *every* step. A 100-step session at 100k context ≈ 10M tokens flowing through — mostly cache reads. That's normal; it's also exactly why context bloat matters.

**Correlation isn't causation, right?**
Right, and the report says so on its face. Deep-context steps are also later-in-task steps. contextrot is an observational diagnostic with conservative statistics, not a lab experiment — see [methodology](docs/methodology.md).

**What about my privacy?**
contextrot makes **zero network calls**. Local files in, terminal/local HTML out. Grep the codebase for an HTTP client — there isn't one.

## Supported agents

| Agent | Status |
|---|---|
| Claude Code | ✅ today |
| OpenCode | ✅ today — both the current file storage and legacy `opencode.db` |
| Codex CLI | ✅ today |
| Gemini CLI | ✅ today |
| Qwen Code | ✅ today — same recording format as Gemini CLI |
| Cline (VS Code) | ✅ today |
| Roo Code (VS Code) | ✅ today |
| Kilo Code (VS Code) | ✅ today |
| Google Antigravity | 🔬 investigating — it does keep local session/token files, so it's the most promising IDE to add next |
| Cursor / Windsurf | ⚠️ blocked for now — their local stores rarely record per-message token counts, so context fill can't be computed reliably |
| Kiro CLI | ❌ blocked upstream — its transcripts record no token counts, so context fill can't be computed |
| OpenTelemetry GenAI spans | planned |

An adapter is one small file with a fixture and a test — [it's the paved first-contribution path](CONTRIBUTING.md).

## Roadmap

- ✅ `contextrot fix` (0.6.0) — dry-run prescriptions + unused-MCP-server detection, reversible `--apply`
- ✅ Adapter wave (0.6.1–0.7.0) — Codex CLI, Gemini CLI, Qwen Code, Cline, Roo Code, Kilo Code + per-agent comparison
- ✅ Live surfaces (0.8.0–0.10.0) — calibrated Claude Code statusline, knee-crossing warning hook, MCP server for any agent
- ✅ `contextrot trends` (0.11.0) — week-over-week before/after measurement for `fix`
- OpenTelemetry GenAI span ingestion
- Opt-in, anonymized aggregate stats → the **State of Context Rot** report: real-workload degradation curves across the community (off by default, aggregate-only, documented schema)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Most valuable first PR: an adapter for the agent CLI you use — there are [spec'd, ready-to-pick-up adapter issues](https://github.com/Priyanshu-byte-coder/contextrot/contribute) waiting.

Ran the tool? [Share your rot curve](https://github.com/Priyanshu-byte-coder/contextrot/discussions/8) — flat curves count too.

<a href="https://github.com/Priyanshu-byte-coder/contextrot/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=Priyanshu-byte-coder/contextrot" alt="Contributors" />
</a>

## Stats

<p>
  <a href="https://pypistats.org/packages/contextrot"><img src="https://img.shields.io/pypi/dm/contextrot?label=downloads%2Fmonth&color=2a78d6" alt="Downloads per month"></a>
  <a href="https://pypistats.org/packages/contextrot"><img src="https://img.shields.io/pypi/dw/contextrot?label=downloads%2Fweek&color=2a78d6" alt="Downloads per week"></a>
  <a href="https://pypistats.org/packages/contextrot"><img src="https://img.shields.io/pypi/dd/contextrot?label=downloads%2Fday&color=2a78d6" alt="Downloads per day"></a>
  <a href="https://github.com/Priyanshu-byte-coder/contextrot"><img src="https://komarev.com/ghpvc/?username=Priyanshu-byte-coder&label=Views&color=blueviolet" alt="Views"></a>
</p>

Live dashboards: [pypistats](https://pypistats.org/packages/contextrot) ·
[clickpy (ClickHouse)](https://clickpy.clickhouse.com/dashboard/contextrot)

If contextrot told you something useful about your setup, a ⭐ helps other agent users find it.

<a href="https://www.star-history.com/#Priyanshu-byte-coder/contextrot&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=Priyanshu-byte-coder/contextrot&type=Date&theme=dark" />
    <img src="https://api.star-history.com/svg?repos=Priyanshu-byte-coder/contextrot&type=Date" alt="Star History Chart" width="600" />
  </picture>
</a>

## License

[MIT](LICENSE)
