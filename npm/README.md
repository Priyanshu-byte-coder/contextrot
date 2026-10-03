# contextrot

**Does your coding agent get worse as its context fills?** Find out on the sessions already
on your disk — and what actually moves its failure rate. Runs fully local; nothing is
uploaded.

```sh
npx contextrot
```

You get a short verdict: whether your agent degrades as context fills, the strongest other
thing moving its failure rate, what the slips are costing you, and the one thing worth
changing.

```
 ✓ NO MEASURABLE ROT

  Your agent slips 3.1% of the time when the context is nearly full, against 3.8% when
  it's fresh. Filling the window is not what's hurting your output.
  What does move it: it slips 1.7× as often at night (0–6h) as in the morning.
```

A tool that can say "you're fine" is one you can trust when it says you're not.

## Then

```sh
npx contextrot factors     # what actually moves your failure rate
npx contextrot --full      # the curve, comparisons, where your context goes
npx contextrot status      # one live line for tmux, Starship or your prompt
npx contextrot share       # your curve, anonymized, for the community dataset — sends nothing
npx contextrot doctor      # what it can see, and why you have no verdict yet
```

Reads Claude Code, Codex CLI, Gemini CLI, Qwen Code, OpenCode, and Cline/Roo/Kilo Code.

## About this package

A thin launcher around the
[Python CLI](https://github.com/Priyanshu-byte-coder/contextrot): it runs
`uvx contextrot`, which fetches the latest release from PyPI in an isolated
environment. It needs [uv](https://docs.astral.sh/uv/) (or an existing
`pip install contextrot`) and prints one-line install instructions if neither
is found.

Because it always resolves the latest PyPI release, this package is
version-agnostic — you get current contextrot without updating anything here.

Full documentation: **https://github.com/Priyanshu-byte-coder/contextrot**
