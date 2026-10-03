<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Priyanshu-byte-coder/contextrot/main/assets/logo_dark.png">
    <img src="https://raw.githubusercontent.com/Priyanshu-byte-coder/contextrot/main/assets/logo_white.png" alt="contextrot logo" width="180" height="180">
  </picture>
  <h1>contextrot</h1>
  <p><strong>Does your coding agent get worse as its context fills?</strong><br>
  Find out on the sessions already on your disk — and what actually moves its failure rate.</p>

  <p><a href="https://priyanshu-byte-coder.github.io/contextrot/"><strong>See the story →</strong> priyanshu-byte-coder.github.io/contextrot</a></p>

  <a href="https://pypi.org/project/contextrot/"><img src="https://img.shields.io/pypi/v/contextrot?color=2a78d6" alt="PyPI version"></a>
  <a href="https://pepy.tech/projects/contextrot"><img src="https://static.pepy.tech/personalized-badge/contextrot?period=total&units=INTERNATIONAL_SYSTEM&left_color=BLACK&right_color=GREEN&left_text=downloads" alt="Downloads"></a>
  <a href="https://pypi.org/project/contextrot/"><img src="https://img.shields.io/pypi/pyversions/contextrot?color=2a78d6" alt="Python versions"></a>
  <a href="https://github.com/Priyanshu-byte-coder/contextrot/actions/workflows/ci.yml"><img src="https://github.com/Priyanshu-byte-coder/contextrot/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/Priyanshu-byte-coder/contextrot/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-2a78d6" alt="License: MIT"></a>
</div>

---

Everyone says coding agents get worse as their context fills — `/clear` often, keep it
small, use subagents. That advice comes from lab benchmarks. **contextrot checks it against
your own real sessions.** Sometimes it's true. Often it isn't, and something else is what's
hurting you.

No setup, no API keys. It reads the transcripts your agent CLI already keeps, runs entirely
on your machine, and makes zero network calls.

## Quick start

```bash
uvx contextrot
```

or `pip install contextrot` then `contextrot` (Python 3.9+).

<details>
<summary><code>contextrot: command not found</code> after pip install?</summary>

Your Python scripts folder isn't on `PATH` — common with the stock macOS `python3`. Use
`uvx contextrot`, or run it as `python3 -m contextrot`.
</details>

<div align="center">
  <img src="https://raw.githubusercontent.com/Priyanshu-byte-coder/contextrot/main/assets/showcase/hero.svg" alt="contextrot's short report: a context-rot verdict, the slip rate at a fresh versus a full context, the strongest other factor, and what to do" width="860">
</div>

You get one of four honest answers:

| | Verdict | Meaning |
|---|---|---|
| ✗ | **Context rot detected** | your failure rate climbs as context fills — and here's where |
| ! | **Edge rot** | flat until near the limit, then it climbs |
| ✓ | **No measurable rot** | filling the window isn't what's hurting you |
| ? | **Not enough data** | keep using your agent, or look further back with `--days 0` |

A tool that can say "you're fine" is a tool you can trust when it says you're not.

## Then, three things worth doing

### 1. Find what actually moves your failure rate

```bash
contextrot factors
```

Context fill is one suspect. This checks the others with the same statistics — time of
day, how long the agent runs without you, mistakes piling up, which model, which agent —
and ranks what genuinely separates your good steps from your bad ones.

<div align="center">
  <img src="https://raw.githubusercontent.com/Priyanshu-byte-coder/contextrot/main/assets/showcase/factors.svg" alt="contextrot factors: a ranked table of factors with the worst and best group for each, the size of the gap, and whether the effect is clear" width="860">
</div>

### 2. Keep it watching

```bash
contextrot install statusline --apply    # Claude Code: a live meter in your status bar
contextrot status --setup tmux           # any agent: one line for tmux, Starship, your prompt
```

A report you run once is forgotten. A meter you see every turn isn't — it shows how full
the window is, how many turns are left, and goes red where *your* curve says it should,
not at a generic 70%.

### 3. Add your curve to the dataset

```bash
contextrot share --copy
```

Nobody knows what context rot looks like on real work across many people, because nobody
has had the data. This prints your curve as anonymized numbers — no project names, paths,
prompts or code — **and sends nothing.** You read it, then paste it into a
[Share your curve](https://github.com/Priyanshu-byte-coder/contextrot/issues/new?template=share_your_curve.yml)
issue. Clean curves count as much as rotten ones.
[What's in it, exactly →](https://github.com/Priyanshu-byte-coder/contextrot/blob/main/docs/sharing.md)

## Everything else

| You want to… | Run |
|---|---|
| See the full analysis behind the verdict | `contextrot --full` |
| Know which kinds of slip cost the most | `contextrot waste` |
| Compare your coding agents on your own work | `contextrot agents` |
| Find which repo degrades first | `contextrot projects` |
| See whether it's getting better week by week | `contextrot trends` |
| Get concrete fixes, including unused MCP servers | `contextrot fix` |
| Share a report as a single HTML file | `contextrot --html report.html` |
| Work out why you have no verdict | `contextrot doctor` |
| See how much water your agents' inference used | `contextrot water` |

Every command animates when you're watching and prints plain output when you're not. The
[guide](https://github.com/Priyanshu-byte-coder/contextrot/blob/main/docs/guide.md) covers
every command, the status line segment by segment, troubleshooting and the FAQ. The
[showcase](https://github.com/Priyanshu-byte-coder/contextrot/blob/main/SHOWCASE.md) shows
each screen.

## Supported agents

| Agent | |
|---|---|
| Claude Code · Codex CLI · Gemini CLI · Qwen Code · OpenCode | ✅ |
| Cline · Roo Code · Kilo Code (VS Code) | ✅ |
| Google Antigravity | 🔬 investigating |
| Cursor · Windsurf · Kiro | ⚠️ their local files don't record per-message token counts |

Adding an agent is one small file with a fixture and a test —
[the paved first contribution](https://github.com/Priyanshu-byte-coder/contextrot/blob/main/CONTRIBUTING.md).

## How it works

Agent CLIs log every step to local transcripts, with token counts and what happened. For
each step, contextrot records how full the context window was and whether one of five
failure signals fired — a failed edit, a retried call, a re-read of a file already read, a
tool error, or an "I apologize, let me fix that". Then it measures how the rate of those
changes as context fills.

The statistics are conservative on purpose: Wilson 95% confidence intervals, visible
sample sizes, and a threshold declared only when the evidence clears the baseline — one
noisy bucket can't scare you. It's observational, and it says so: deeper context also
means later in the task. The full method is in
[methodology.md](https://github.com/Priyanshu-byte-coder/contextrot/blob/main/docs/methodology.md).

## Privacy

Local files in; terminal, or a local HTML file, out. **Zero network calls** — there's no
HTTP client in the codebase. `share` prints and copies to your clipboard; whether anything
leaves your machine is entirely your decision.

## Contributing

The most valuable first PR is an adapter for the agent CLI you use — see
[CONTRIBUTING.md](https://github.com/Priyanshu-byte-coder/contextrot/blob/main/CONTRIBUTING.md).
Bugs and ideas are welcome in
[issues](https://github.com/Priyanshu-byte-coder/contextrot/issues) and
[discussions](https://github.com/Priyanshu-byte-coder/contextrot/discussions). If it told
you something useful about your setup, a ⭐ helps other people find it.

<a href="https://github.com/Priyanshu-byte-coder/contextrot/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=Priyanshu-byte-coder/contextrot" alt="Contributors">
</a>

## License

MIT — see [LICENSE](https://github.com/Priyanshu-byte-coder/contextrot/blob/main/LICENSE).
Release notes are in the
[changelog](https://github.com/Priyanshu-byte-coder/contextrot/blob/main/CHANGELOG.md).
