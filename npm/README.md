# contextrot

Find out where **your** coding agent starts degrading — a personal context-rot
report from the transcripts your agent CLI already writes to your disk. Runs
fully local; nothing is uploaded.

```sh
npx contextrot
```

You get a short verdict: whether your agent degrades as context fills, what
that's costing you, and the one thing worth changing.

```
 ✓ NO MEASURABLE ROT

  Your agent slips 3.3% of the time when the context is nearly full, against
  4.0% when it's fresh. Filling the window is not what's hurting your output.

  Measured on 28,617 steps from the last 30 days.
  3.4% of your token spend went to steps that slipped — retries, failed edits
  and re-reads that produced nothing.
```

A tool that can say "you're fine" is one you can trust when it says you're not
— and about half of real reports come back clean.

## A few things to try

```sh
npx contextrot --full      # the curve, per-model comparison, context breakdown
npx contextrot waste       # the share of your spend that produced nothing
npx contextrot agents      # which of your CLIs holds up best on your work
npx contextrot status      # one live line for tmux, Starship or your shell prompt
npx contextrot doctor      # what it can see, and why you have no verdict yet
```

Reads Claude Code, Codex CLI, Gemini CLI, Qwen Code, OpenCode, and
Cline/Roo/Kilo Code.

## About this package

A thin launcher around the
[Python CLI](https://github.com/Priyanshu-byte-coder/contextrot): it runs
`uvx contextrot`, which fetches the latest release from PyPI in an isolated
environment. It needs [uv](https://docs.astral.sh/uv/) (or an existing
`pip install contextrot`) and prints one-line install instructions if neither
is found.

Because it always resolves the latest PyPI release, this package is
version-agnostic — you get current contextrot without updating anything here.

Full documentation, methodology, and reports:
**https://github.com/Priyanshu-byte-coder/contextrot**
