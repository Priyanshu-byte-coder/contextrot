<div align="center">
  <h1>contextrot — every feature, in pictures</h1>
  <p><strong>A quick visual tour of what the tool shows you.</strong><br>
  One command reads the session logs your coding agent already saved and tells you
  where it starts getting worse. Everything runs on your machine — no API keys, no uploads.</p>
  <p><em>All screenshots below are from a synthetic demo dataset, so no real project
  names appear. Your own report uses your real sessions.</em></p>
  <p><a href="README.md">← back to the README</a> · <a href="#install">install</a></p>
</div>

---

## The answer, in fifteen seconds

`contextrot`

The default report answers three questions and stops: **am I degrading, what is it costing me,
and what should I change.** Everything else is one flag away.

```
 ✓ NO MEASURABLE ROT

  Your agent slips 3.3% of the time when the context is nearly full, against
  4.0% when it's fresh. Filling the window is not what's hurting your output.

  Measured on 28,617 steps from the last 30 days.
  3.4% of your token spend went to steps that slipped — retries, failed edits
  and re-reads that produced nothing.

  What to do
  → Nothing about context fill — your setup is holding up.

  Run contextrot --full for the curve behind this, the comparisons, and where
  your context goes.
```

The rule behind every line: if it wouldn't change what you do next, it lives in `--full`.

---

## The full analysis — where exactly does it start failing?

`contextrot --full`

The headline is a plain verdict — **rot**, **edge rot**, **clean**, or **not enough data** —
followed by the exact context-fill % where you start failing, a failure-rate curve with
confidence intervals, where your context is being spent, and concrete fixes. Use more than
one model and it compares them head-to-head automatically (here Opus rots 3.8× while Sonnet
stays flat on the same work).

<div align="center">
  <img src="assets/showcase/report.png" alt="contextrot terminal report: rot verdict, failure-rate curve by context fill, reversal table, per-model comparison, composition, and prescriptions" width="900">
</div>

### The same report as a shareable HTML page

`contextrot --html report.html`

One self-contained local file (still zero network) with a built-in 1200×630 share card you
can save as a PNG and post.

<div align="center">
  <img src="assets/showcase/report-html.png" alt="contextrot HTML report with verdict hero, charts, per-model and per-project breakdowns, and a share card" width="720">
</div>

---

## Which of your repos rots first?

`contextrot projects`

An independent curve and verdict per project, ranked worst-first — so the specific repo whose
`CLAUDE.md` or MCP setup is dragging you down stops hiding inside your all-projects average.

<div align="center">
  <img src="assets/showcase/projects.png" alt="Per-project context-rot comparison table: auth-service rot, web-dashboard edge, cli-tools clean" width="820">
</div>

## Which coding agent rots first?

`contextrot agents`

Claude Code vs Codex CLI vs Gemini CLI vs Cline — each with its own curve and verdict on a
shared scale, measured on *your* workload rather than a benchmark's.

<div align="center">
  <img src="assets/showcase/agents.png" alt="Per-agent context-rot comparison: Claude Code vs Codex CLI" width="820">
</div>

---

## Are you actually improving?

`contextrot trends`

Week-over-week failure rate and startup-overhead bloat, with an honest verdict on whether the
change cleared statistical noise. This is the before/after check for `contextrot fix`.

<div align="center">
  <img src="assets/showcase/trends.png" alt="Week-over-week trend table showing failure rate improving from 9.9% to 6.1% and startup tokens shrinking" width="820">
</div>

## What is the rot actually costing you?

`contextrot waste`

Usage trackers can tell you what you spent. None of them can tell you which part was **wasted**,
because that needs the failure signals: a retry of a call that already errored, an edit that
missed, a re-read of a file still sitting in context. Those tokens were paid for and bought
nothing.

```
  3.4% of your token spend went to steps that slipped
  1,082 of 28,701 steps over the last 30 days · $248.91 of $7,342.39 at API list prices

  What went wrong                              Steps     Cost
  Tool calls that errored                        581  $137.99
  Files re-read that were already in context     337   $71.74
  Same call repeated after an error              161   $36.04
  Edits that missed their target                  44    $8.48
  “actually, let me fix that”                     27    $8.49
```

One step can trip several of these, so the rows overlap and the output says so rather than
apportioning a precision that isn't there. `--json` included, labelled with its pricing basis
(API list prices — on a subscription that's "what this would have cost", not a bill you got).

---

## And how much water did that drink?

`contextrot water`

Inference runs in datacenters that evaporate water to stay cool, and the power stations feeding them
consume more. The token counts contextrot already parses convert into litres. The tank fills on
screen while the number counts up, then the breakdown says where the water went.

<div align="center">
  <img src="assets/showcase/water.svg" alt="contextrot water: a filled tank with a rippling surface, the total in large block digits, a where-it-went breakdown dominated by cache reads, per-agent and per-model splits, the cooling and generation halves, and the estimate's full derivation" width="900">
</div>

The breakdown is the interesting part: **cache reads, not output, are where the water goes** — 84%
of it here, against 12% for everything the models actually wrote. Most people assume the answers
dominate. For an agent replaying a large context on every step, they are a small fraction.

A still frame can't show the part worth showing. The water surface is tracked in eighths of a row,
so it moves eight times per row rather than jumping whole cells; its height per column is two sine
waves at incommensurate frequencies travelling in opposite directions, so the crests never realign
and the surface never visibly loops; and every landing droplet adds a decaying ripple, which is what
makes a splash read as a splash. Level and number share one ease-out curve, so they decelerate into
the final value together instead of stopping dead.

This is the **one figure contextrot estimates rather than measures**, and it never appears without
its derivation attached — the 0.6 Wh per 1k output tokens, the price-anchored prefill and replay
rates, the two separate water terms for datacenter cooling and electricity generation, and a plain
plus-or-minus-2x. It even says what biases it **low**: long-context attention is not priced
separately, and correcting that needs a constant nobody publishes.

Which is why it is a separate command rather than a line in the report, and off by default in the
status line. `--no-animate` skips to the numbers, `--json` emits the whole derivation including the
cooling and generation halves. The full chain is in [docs/methodology.md](docs/methodology.md).

### Watch it fill while you work

```bash
contextrot water --live
```

The same scene, animating continuously at 20 fps with its own clock, tracking whichever agent's
session is live. The pool fills toward the next round volume and splashes over it, and the level
eases toward real data rather than snapping, so a jump in the number still looks like water
arriving. Put it in a split pane and leave it running; Ctrl-C to stop.

---

## What should you actually change?

`contextrot fix`

Turns the report's findings into concrete actions, and points out MCP servers you configured
but never actually use. **Dry-run by default — it writes nothing** unless you add `--apply`
(which backs up first and is reversible).

<div align="center">
  <img src="assets/showcase/fix.png" alt="contextrot fix: prescriptions plus a list of unused MCP servers, dry-run by default" width="820">
</div>

## What sessions were parsed?

`contextrot sessions`

A plain list of everything that was read, with each session's peak context fill.

<div align="center">
  <img src="assets/showcase/sessions.png" alt="contextrot sessions: list of parsed sessions with project, steps, peak prompt tokens, and model" width="820">
</div>

---

## Use it live, inside Claude Code

The report tells you where you degrade *after the fact*. These put it in front of you **while
you're working** — and they're the reason a Claude Code user gets the most out of contextrot.
All three are dry-run by default, write only with `--apply`, back up your settings first, and
undo cleanly with `contextrot uninstall`.

### A live context-health meter in your status bar

`contextrot install statusline --apply`

Your current context fill, colored against your *own* measured curve — not a generic
"yellow at 70%." It knows where *you* start failing, and recalibrates on every run.

```
ctx 34% ███▍░░░░░░ · 340k/1M · ~45 turns left
ctx 85% ████████▌░ · 850k/1M · ~10 turns left, ~2 heavy · ▲ past threshold ~70% · slip 9.2% — 1.9× fresh
ctx 99% █████████▉ · 198k/200k · no room for another turn
```

**Headroom in the unit you plan in.** `660k left` is precise and abstract; `~45 turns left` is
the thing you decide with. It's measured from your own history — the median turn adds a certain
number of tokens, so what remains divides into roughly that many more turns. Under 12 it goes
yellow and adds the heavy case, because one wide grep can cost several times a typical turn.

**The threshold is the one for what you're running right now.** Curves are stored per agent, per
model and per pair, and the line resolves the narrowest that fits your session. When it has to
borrow from a broader slice it says so — `(all agents)` — rather than passing it off as yours.

**When nothing is wrong, it says nothing.** A clean curve renders no health text at all; the
green bar is the message.

<div align="center">
  <img src="assets/showcase/statusline.png" alt="Claude Code statusline showing context fill colored green/yellow/red against the user's measured threshold, with headroom in turns and the failure ratio" width="900">
</div>

### A live water meter, if you want one

```bash
contextrot install statusline --segments ctx,tokens,health,plan,water --apply
```

<div align="center">
  <img src="assets/showcase/statusline-water.svg" alt="Claude Code statusline with the water segment on: context fill and bar, absolute tokens, rate-limit meters, and this session's estimated water use with a droplet beside it" width="900">
</div>

This session's running total, read incrementally — only the transcript bytes appended since the last
render are parsed, so a warm render costs about a millisecond.

The five cells beside it are a droplet falling into a pool, advancing one frame per redraw:

```
▁▁▁▁▁   ▁▁'▁▁   ▁▁·▁▁   ▁▁.▁▁   ▁▂█▂▁   ▂▅▆▅▂   ▃▄▂▄▃   ▂▁▂▁▂
calm    drop    falling  lands   impact  crown   collapse ripples
```

**It will not look animated, and it can't.** Claude Code re-runs a status command when the
conversation changes rather than on a timer, which in practice is a couple of times a minute, so the
droplet advances a frame at a time. Nothing rendered into a status line can do better, because the
host decides when to redraw it — which is what `contextrot water --live` is for.

---

### A one-time warning the moment you cross your threshold

`contextrot install hook --apply`

One nudge, the instant a session crosses *your* measured failure threshold — then silence
until the next crossing. It uses the threshold for the model actually running, not a blend.
No threshold in your data? It says nothing at all.

<div align="center">
  <img src="assets/showcase/hook.png" alt="Claude Code hook warning that fires once when context crosses the measured degradation threshold" width="820">
</div>

### Let Claude Code check its own rot, mid-task

`claude mcp add contextrot -- contextrot mcp`

Runs contextrot as an MCP server so Claude Code itself can pull your rot report during a
session and decide to compact, warn you, or switch models. Still zero network — a local pipe,
not a socket.

---

## Which curve is the statusline quoting?

`contextrot doctor`

Thresholds differ by agent and by model, so `doctor` tables every curve that was measured and
stored — and flags the ones that blend across slices you're not currently using.

```
  Measured curve           Steps  Threshold  Measured to
  Claude Code + Opus 5    21,367  none                 —
  Claude Code + Opus 4.8   3,619  none          60% full
  Claude Code + Fable 5    2,484  none          40% full
  Opus 5                  21,378  none                 —  blends all agents
  Claude Code             28,269  none                 —  blends all models
  all agents and models   28,448  none                 —  blends all agents
  Live surfaces use the narrowest of these that fits your current session.
```

It also explains which agents were found, where it looked, and what's still missing when you
have no verdict yet.

---

## Install

```bash
uvx contextrot
# or
pip install contextrot
contextrot
```

No config, no API keys, no uploads. contextrot makes **zero network calls** — local files in,
terminal or local HTML out.

<div align="center">
  <strong>Ran it on your own sessions?</strong>
  <a href="https://github.com/Priyanshu-byte-coder/contextrot/discussions/8">Share your rot curve</a>
  — flat curves count too. If it told you something useful, a ⭐ helps other agent users find it.
</div>
