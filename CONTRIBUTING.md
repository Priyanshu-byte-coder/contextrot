# Contributing to ctxprof

Thanks for considering a contribution. This project is deliberately structured so the highest-impact contribution is also the easiest one.

## The paved path: write an adapter

ctxprof supports any agent CLI whose transcripts can be parsed into the normalized session model. Each adapter is **one self-contained file** — no changes to analysis or reporting code needed.

1. Copy `src/ctxprof/adapters/claude_code.py` as a starting point.
2. Implement the two methods of `SessionAdapter`:
   - `discover()` — find transcript files on disk
   - `parse(path)` — convert one file into a `Session` of `Step`s and `ToolCall`s
3. Register it in `src/ctxprof/adapters/__init__.py`.
4. Add a small sanitized fixture transcript under `tests/fixtures/` and a test file modeled on `tests/test_adapter_claude_code.py`.

Adapter ground rules:

- **Tolerant parsing.** Skip malformed lines, ignore unknown fields, never crash on a weird file. A partial session beats an exception.
- **No network calls.** ctxprof is local-only; adapters read files, period.
- **Sanitize fixtures.** Strip real file paths, code, and personal data from any transcript you commit.

Wanted adapters: Codex CLI, OpenCode, Gemini CLI, OpenClaw, Cursor CLI, OpenTelemetry GenAI spans.

## Other contributions

- **New outcome signals** (`src/ctxprof/signals/`): each signal must be independently testable, documented in `docs/methodology.md`, and reported separately in output. Open an issue first to discuss the heuristic.
- **Prescription rules** (`src/ctxprof/analysis/prescriptions.py`): must be quantified from the user's own data, with an explicit evidence threshold.
- **Bug reports**: include your ctxprof version, agent CLI version, OS, and — if it's a parsing bug — a *sanitized* snippet of the offending transcript line.

## Development setup

```bash
git clone https://github.com/priyanshudoshi/ctxprof
cd ctxprof
pip install -e ".[dev]"
pytest
ruff check src tests
mypy src
```

All three must pass in CI. Python 3.11+ supported.

## Style

- Match the existing code: type hints everywhere, docstrings explain *why* and document format assumptions.
- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
- Keep dependencies minimal — new runtime deps need a strong justification (install speed is a feature).

## Statistical honesty

This tool's credibility rests on not overclaiming. Reports must always carry n-counts, confidence intervals, and the observational-diagnostic caveat. PRs that trade rigor for a scarier headline will be declined.
