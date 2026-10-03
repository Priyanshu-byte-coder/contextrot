# Contributing to contextrot

Thanks for considering a contribution. This project is deliberately structured so the highest-impact contribution is also the easiest one.

## The paved path: write an adapter

contextrot supports any agent CLI whose transcripts can be parsed into the normalized session model. Each adapter is **one self-contained file** — no changes to analysis or reporting code needed.

1. Copy `src/contextrot/adapters/claude_code.py` as a starting point.
2. Implement the two methods of `SessionAdapter`:
   - `discover()` — find transcript files on disk
   - `parse(path)` — convert one file into a `Session` of `Step`s and `ToolCall`s
3. Register it in `src/contextrot/adapters/__init__.py`.
4. Add a small sanitized fixture transcript under `tests/fixtures/` and a test file modeled on `tests/test_adapter_claude_code.py`.

Adapter ground rules:

- **Get token accounting right.** `prompt_tokens` must equal the true context size: fresh input **plus** cache creation **plus** cache reads. Anthropic reports those separately; OpenAI-style APIs already fold cache into `input_tokens`, so adding it again double-counts. Nothing crashes when this is wrong — every fill percentage is just quietly incorrect, which is worse.
- **Append with `session.add_step(step)`, not `session.steps.append(step)`**, and call `session.mark_turn_start()` when you see a real user prompt (not a tool result). That one call is what gives the user headroom — "~45 turns left" — and adapters that skip it simply contribute nothing to that figure rather than producing a wrong one.
- **Set `ToolCall.target`.** Retry and re-read detection compare targets across steps; without it two of the five signals go silent for your agent.
- **Tolerant parsing.** Skip malformed lines, ignore unknown fields, never crash on a weird file. A partial session beats an exception.
- **No network calls.** contextrot is local-only; adapters read files, period.
- **Sanitize fixtures.** Strip real file paths, code, and personal data from any transcript you commit.

Already shipped: Claude Code, Codex CLI, Gemini CLI, Qwen Code, OpenCode, Cline/Roo/Kilo Code.

Wanted: OpenClaw, Cursor CLI, Antigravity, Amp, OpenTelemetry GenAI spans.

## Other contributions

- **New outcome signals** (`src/contextrot/signals/`): each signal must be independently testable, documented in `docs/methodology.md`, and reported separately in output. Adding a name to `SIGNAL_NAMES` wires it through buckets, JSON and the waste breakdown automatically — but it also changes the composite `degraded` flag, so every historical verdict shifts. Open an issue first to discuss the heuristic.
- **Prescription rules** (`src/contextrot/analysis/prescriptions.py`): must be quantified from the user's own data, with an explicit evidence threshold.
- **Bug reports**: include your contextrot version, agent CLI version, OS, and — if it's a parsing bug — a *sanitized* snippet of the offending transcript line.

## Development setup

```bash
git clone https://github.com/Priyanshu-byte-coder/contextrot
cd contextrot
pip install -e ".[dev]"
pytest
ruff check src tests scripts
mypy src
```

All three must pass in CI. Python 3.9–3.13 supported (CI tests the full matrix
across Linux/macOS/Windows).

## Style

- Match the existing code: type hints everywhere, docstrings explain *why* and document format assumptions.
- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
- Keep dependencies minimal — new runtime deps need a strong justification (install speed is a feature).

## Statistical honesty

This tool's credibility rests on not overclaiming. Reports must always carry n-counts, confidence intervals, and the observational-diagnostic caveat. PRs that trade rigor for a scarier headline will be declined.

## Regenerating the showcase media

Every terminal screen in `README.md` and `SHOWCASE.md` is generated, not photographed:

```bash
python scripts/make_showcase_data.py --out .showcase-data
python scripts/capture_showcase.py --data-dir .showcase-data
```

The first writes a deterministic synthetic corpus — fixed seed, three made-up projects, two
agents, four models — shaped so each screen has something true to show: Opus degrading while
the others stay flat, a late-night effect for `factors`, a four-week improvement for `trends`.
The second runs each command against it and exports SVG through rich, so no browser is needed.

Run both from the repo root, with the relative `--data-dir` above. The capture runs every
command inside a **sandboxed home directory** with a synthetic `~/.claude.json` and
CLAUDE.md, because several commands read your home regardless of `--data-dir` — `fix` lists
your MCP servers and project paths, `doctor` your calibration. An early version leaked a
username and three real server names exactly that way; `tests/test_repo_hygiene.py` now scans
every committed image for home-directory paths.

Two images are still hand-captured: `report-html.png` (it needs a browser) and `hook.png`
(Claude Code's own UI). If you change what one of those shows, retake it or say in your PR
that it's stale — and **never** capture media from your own sessions.

## Adding an animated renderer

Do not write an animated version of a renderer beside the static one — they drift.
Instead take a `Reveal` and let `t = 1.0` be the finished frame:

```python
from contextrot.anim import STATIC, Reveal, bar, play

def _my_table(data, rv: Reveal = STATIC) -> Table:
    table = Table()
    for i, row in enumerate(data):
        table.add_row(row.label, bar(row.value, peak, 14, rv.stagger(i, len(data))))
    return table

play(console, lambda rv: _my_table(data, rv), animate=animate)
```

`play` prints `build(STATIC)` and returns immediately when animation is off, so
there is exactly one code path and disabling animation is provably a no-op. There
is a test per command asserting the piped output is unchanged; add yours to
`ANIMATED_COMMANDS` in `tests/test_cli.py`.

The rules an effect has to clear:

- **It interpolates a real value.** Bars grow to their height, counters count to
  their total, rows arrive in rank order. No spinners next to numbers, nothing
  pulsing or bouncing.
- **It never delays the answer.** Verdicts and headlines print instantly.
- **It leaves prose alone.** A figure that changes width mid-count re-wraps the
  paragraph around it.
- **It animates per section, not per screen.** `rich.Live` crops anything taller
  than the terminal, so a whole report in one `Live` loses its bottom half on a
  short window.

Use `rv.stagger(i, n)` when every row is present from the first frame and their
bars should cascade; use `anim.rows` when the rows themselves should arrive.
