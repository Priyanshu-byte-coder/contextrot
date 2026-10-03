# The contextrot guide

Everything the [README](../README.md) leaves out: every command, the live status line in
depth, troubleshooting, and the questions people actually ask.

**Contents**

- [The report](#the-report)
- [What actually moves your failure rate](#what-actually-moves-your-failure-rate)
- [Comparing models, agents and projects](#comparing-models-agents-and-projects)
- [Watching it live](#watching-it-live)
  - [The Claude Code status line](#the-claude-code-status-line)
  - [Any terminal, any agent](#any-terminal-any-agent)
  - [The threshold warning hook](#the-threshold-warning-hook)
  - [Letting your agent ask](#letting-your-agent-ask-mcp)
- [Acting on it](#acting-on-it)
- [Sharing](#sharing)
- [Water](#water)
- [Animation](#animation)
- [Command reference](#command-reference)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [How is this different from…](#how-is-this-different-from)

---

## The report

```bash
contextrot              # the short answer, last 30 days
contextrot --full       # the analysis behind it
contextrot --days 90    # more history, tighter statistics (0 = everything)
contextrot -p myrepo    # one project only
contextrot --html r.html  # a single-file report you can share, plus an image card
contextrot --json       # every number, machine-readable
```

Every report leads with one of four verdicts:

| Verdict | Meaning |
|---|---|
| ✗ **Context rot detected** | your failure rate climbs significantly as context fills |
| ! **Edge rot** | flat until near the limit, then it climbs — compact before you get there |
| ✓ **No measurable rot** | your failure rate stays flat as context fills |
| ? **Not enough data** | keep using your agent and re-run |

The short report then names the strongest *other* thing that moves your rate (if one is
clear), the share of your spend that went to steps that slipped, the one or two changes
worth making, and three next steps.

`--full` adds the failure-rate curve by context fill with confidence intervals, the
"do mistakes snowball?" table, side-by-side model / project / agent comparisons, and where
your context window actually goes (startup overhead, tool output, conversation).

**What counts as a slip.** Every step is checked for five failure signals, each of which
is something you'd rather your agent hadn't done:

| Signal | What it catches |
|---|---|
| **Edit failures** | tried to edit code and missed — the clearest "lost track of the file" event |
| **Retries** | the same tool call repeated after an error |
| **Re-reads** | reading a file it already read in this session |
| **Self-corrections** | "I apologize, let me fix that" |
| **Tool errors** | any failed tool call |

How the statistics work — Wilson intervals, how a threshold is declared, how fresh and
deep zones are chosen on a 1M-token window — is in [methodology.md](methodology.md).

## What actually moves your failure rate

```bash
contextrot factors
```

The report asks one question: does a fuller context make your agent worse? On a lot of
real work the honest answer is no — which leaves you with nothing to act on. `factors`
asks the broader one with the same statistics:

| Factor | The question |
|---|---|
| Context fill | Does a fuller window make it slip more? |
| Mistakes so far | Once a session has gone wrong a few times, does it keep going wrong? |
| Time of day | Do sessions at some hours go worse than others? |
| Steps since you last spoke | Does it slip more the longer it runs without you? |
| Model | Which model holds up best on *your* work? |
| Coding agent | Which agent CLI holds up best on *your* work? |

Each comes back **clear** (the two groups' confidence ranges don't overlap), **maybe**
(they overlap), or **no effect** — and the ones that cleared the bar come with one thing to
do about them. "No effect" rows stay in the table on purpose: *"time of day doesn't matter
for you"* is an answer too.

Read it as association, not causation. Sessions that have made more mistakes tend to be
deeper into their context, for example, so the two factors can echo each other. Two axes
that look tempting were deliberately left out because they'd teach the wrong lesson — see
[methodology.md](methodology.md#factors).

## Comparing models, agents and projects

```bash
contextrot agents     # Claude Code vs Codex vs Gemini CLI vs Cline… on your work
contextrot projects   # which of your repos degrades first
```

Each gets its own curve and verdict on a shared scale, ranked worst first. Model
comparisons appear automatically in `contextrot --full` once you use more than one model.
`projects` is how the one repo whose CLAUDE.md or MCP setup is dragging you down stops
hiding inside your all-projects average.

```bash
contextrot trends     # week by week: is it getting better?
contextrot sessions   # what was parsed, and how full each session got
contextrot waste      # which kinds of slip cost the most
```

## Watching it live

The report tells you what happened. These put it in front of you while you work.

### The Claude Code status line

```bash
contextrot install statusline --apply
```

```
ctx 72% ███████▊░░ · 144k/200k · ~4 turns left · ▲ past threshold ~70% · slip 4.8% — 1.5× fresh · 5h █▏░░░ 24%
```

Left to right: how full the window is, the raw token counts, **how much more work fits**,
and then what *your* history says about being here — colored against your own measured
curve, not a generic "yellow at 70%".

- **`~4 turns left`** is headroom in the unit you plan in. The median turn in your own
  sessions adds a certain number of tokens; what's left divides into roughly that many more.
  Under 12 it goes yellow and adds the heavy case (`~4 turns left, ~1 heavy`), because one
  wide search can cost several typical turns. Until enough turns are measured it says
  `56k left`.
- **`slip 4.8%`** — 4.8% of your past steps at this fill level hit a failure signal, against
  3.2% on a fresh context. A historical rate, not a prediction.
- **`5h █▏░░░ 24%`** and **`wk ██░░░ 41%`** — your Claude.ai rate limits, with time-to-reset
  once either passes 70%. Pro/Max only, and only after the session's first response.

**When nothing is wrong, it says nothing about it.** A clean curve adds no words — the green
bar is the message:

```
ctx 34% ███▍░░░░░░ · 340k/1M · ~45 turns left
```

Words appear only when they'd change what you do: `nearing threshold ~70%`, `▲ past
threshold ~70%`, `deep runs hotter`, `rot measured`, or `need deeper sessions`.

**The threshold is the one for what you're running right now.** Curves are stored per
agent, per model family, and per agent+model pair, because they genuinely differ — a 200k
model and a 1M one don't even share a denominator. The line uses the narrowest curve with
enough data of its own (`agent+model → model → agent → all`), and says so when it had to
fall back: `▲ past threshold ~70% (all agents)`. `contextrot doctor` lists every curve it
stored.

**Segments.** Pick what fits:

```bash
contextrot install statusline --segments ctx,tokens,health,plan,water --apply
contextrot statusline --legend     # what every segment means
```

`cost` and `water` are off by default — cost because Claude Code already shows it, water
because it's the one estimate in a line of measurements. Unknown segment names are refused
at install time rather than silently dropped.

Every plain `contextrot` run recalibrates the line from your latest sessions. Undo with
`contextrot uninstall statusline --apply`; your settings are backed up first either way.

### Any terminal, any agent

Claude Code is the only agent that pushes live session data to a command. For everyone
else, `contextrot status` pulls: it finds whichever session is active right now — Claude
Code, Codex, Gemini CLI, OpenCode, Cline and the rest — and prints one line.

```bash
contextrot status                    # one line, now
contextrot status --setup tmux       # a copy-paste snippet; also starship, bash, zsh, fish
contextrot status --format tmux      # also: plain, json (for Waybar/polybar/scripts)
contextrot status --segments ctx,tokens
```

In tmux, for example:

```tmux
set -g status-interval 5
set -ag status-right ' #(contextrot status --format tmux) '
```

It stays silent when no session was touched recently (`--within`, default 30 minutes), so
a bar never shows a stale number.

### The threshold warning hook

```bash
contextrot install hook --apply
```

Warns **once**, inside Claude Code, the moment a session crosses your measured threshold,
then stays quiet until the next crossing. If your curve has no threshold it says nothing at
all — no generic scare popups.

### Letting your agent ask (MCP)

```bash
claude mcp add contextrot -- contextrot mcp
```

Runs contextrot as a local MCP server, so your agent can pull your report mid-session and
decide to compact, warn you, or switch models. Three tools: `rot_report`,
`agents_ranking`, `prescriptions`. Still no network — it's a pipe to the parent process.

## Acting on it

```bash
contextrot fix          # what to change, as checkable actions — changes nothing
contextrot fix --apply  # disable global MCP servers you never use (backed up, reversible)
contextrot badge        # a local SVG badge of your verdict for your README
```

`fix` lists the report's prescriptions, the size of your global CLAUDE.md, and MCP servers
you configured but never call — each one is startup overhead on every single session.
Per-project servers and CLAUDE.md are reported, never edited.

## Sharing

```bash
contextrot share --copy
```

Prints your curve as anonymized JSON — verdict, rates and step counts per fill bucket,
which factors moved your rate, per-agent and per-model summaries — and copies it to your
clipboard. **It sends nothing.** You read it, then paste it into a
[Share your curve](https://github.com/Priyanshu-byte-coder/contextrot/issues/new?template=share_your_curve.yml)
issue. Exactly what's in it and what's never in it: [sharing.md](sharing.md).

## Water

```bash
contextrot water         # how much water your agents' inference used, filling up on screen
contextrot water --live  # the same, animating continuously — put it in a split pane
```

The one figure contextrot *estimates* rather than measures, and it says so wherever it
appears, with its derivation and a plain ±2×. The chain — and what biases it low — is in
[methodology.md](methodology.md#water-and-energy-the-one-estimate). A `water` status line
segment shows the running total for the current session; it advances a frame per redraw
rather than animating, because Claude Code redraws the line on events, not on a timer.

## Animation

Bars grow to their height, the curve draws along its own axis, tables arrive in rank order,
`doctor` resolves its checks as it runs them, and parsing shows a progress bar. It switches
itself off when nobody's watching — a pipe, CI, Jupyter, `--json` — and the output is then
byte-for-byte what it would have been without it.

```bash
contextrot --no-animate          # just print it
export CONTEXTROT_NO_ANIM=1      # always
```

The HTML report animates too, and honours `prefers-reduced-motion`.

## Command reference

| Command | What you get |
|---|---|
| `contextrot` | the short verdict |
| `contextrot --full` | the complete analysis |
| `contextrot factors` | what actually moves your failure rate |
| `contextrot waste` | the share of your spend that produced nothing, by cause |
| `contextrot agents` | your coding agents compared on your work |
| `contextrot projects` | your repos compared — which degrades first |
| `contextrot trends` | week by week: improving or not |
| `contextrot sessions` | what was parsed |
| `contextrot water` | the water your agents' inference used |
| `contextrot status` | one live line for any terminal, any agent |
| `contextrot share` | your curve, anonymized, to add to the dataset |
| `contextrot badge` | an SVG verdict badge, rendered locally |
| `contextrot fix` | what to change; `--apply` disables unused MCP servers |
| `contextrot install statusline` / `hook` | Claude Code live surfaces (dry-run unless `--apply`) |
| `contextrot uninstall statusline` / `hook` | remove them again |
| `contextrot doctor` | what it can see, where it looked, and why you have no verdict |

`statusline`, `hook` and `mcp` exist too, but Claude Code runs those for you.

Common options on most commands: `--days N` (default 30; `0` = all history), `--project` /
`-p`, `--data-dir`, `--window` (override the context-window size), `--json`.

## Troubleshooting

**`contextrot: command not found` after `pip install`.** Your Python scripts folder isn't on
`PATH` — common with the stock macOS `python3`. Use `uvx contextrot`, or run it as
`python3 -m contextrot`.

**"Not enough data", or it can't see the agent you use.** Run `contextrot doctor`. It shows
your version, every agent it looked for, the exact folders it searched, how many steps each
contributed, and how many more fresh or deep steps a verdict needs. The usual cause is a
short window: try `contextrot --days 0`.

**Your transcripts live somewhere unusual.** Point at them with `--data-dir`.

**The numbers look wrong.** Please [open a bug](https://github.com/Priyanshu-byte-coder/contextrot/issues/new?template=bug_report.yml)
with the output of `contextrot doctor` — it answers most questions on its own.

## FAQ

**The report says $2,000 but I'm on a $20 subscription. Is it broken?**
No — that's the *token value* of your usage at API list prices, labelled as such. Tokens are
what fill your window and burn your rate limits, and dollars are the unit everyone reads
instantly. It's what your usage would cost pay-per-token, not your bill.

**Why is the token flow so large?**
Agents re-send the whole conversation on every step. A 100-step session at 100k context is
about 10M tokens flowing through, mostly cache reads. That's normal — and it's exactly why
context bloat matters.

**Correlation isn't causation, right?**
Right, and the report says so on its face. Deep-context steps are also later-in-task
steps. contextrot is an observational diagnostic with conservative statistics, not a lab
experiment.

**My report says no rot. Is the tool broken?**
No. Clean results are common: lab benchmarks find rot under conditions real work may never
reach, and on a 1M-token window most sessions never get deep enough to find out. A tool
that can say "you're fine" is one you can trust when it says you're not. Run
`contextrot factors` to see what *is* moving your rate — and consider
[sharing your curve](sharing.md), because how common clean really is, nobody yet knows.

**What about privacy?**
contextrot makes **zero network calls**: local files in, terminal or local HTML out. There's
no HTTP client in the codebase. `share` prints and copies; you decide whether to paste.

## How is this different from…

| Tool | Question it answers | What it can't tell you |
|---|---|---|
| [ccusage](https://github.com/ryoppippi/ccusage) | How much did I spend? | anything about output *quality* — use both |
| Claude Code `/context` | What's in my window right now? | outcomes, history, correlation |
| Langfuse / Phoenix / MLflow | How is the app I *built* behaving? | they need instrumentation; contextrot reads the agent you *use*, zero setup |
| [Chroma's context-rot research](https://www.trychroma.com/research/context-rot) | Do models degrade on benchmarks? | anything about *your* workload |
