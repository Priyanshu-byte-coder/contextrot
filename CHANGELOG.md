# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versioning follows
[SemVer](https://semver.org/).

## [0.1.6] - 2026-07-03

### Fixed

- `--html <directory>` crashed with `PermissionError`/`IsADirectoryError` on
  Windows/POSIX because it tried to open the directory itself as a file.
  Now writes `contextrot-report.html` inside the given directory.
- HTML-write failures now print a plain error and exit(1) instead of a raw
  traceback.

## [0.1.5] - 2026-07-03

### Fixed

- `--version` reported a stale hardcoded number; `__version__` now reads the
  installed package metadata (single source of truth: pyproject.toml)

## [0.1.4] - 2026-07-03

### Fixed

- Python 3.9 and 3.10 compatibility: `pip3 install contextrot` now works on the
  stock macOS python3 (3.9.6) — runtime pipe-unions in the CLI replaced with
  `Optional[...]`, `datetime.UTC` replaced with `timezone.utc`
- CI now tests 3.9–3.13 across Linux/macOS/Windows

### Changed

- Downloads badge switched to pepy.tech total-downloads badge
- README: pip install path documented alongside `uvx`

## [0.1.3] - 2026-07-03

### Changed

- Downloads badge in README (stats providers now index the package)
- Republished so PyPI renders the rebuilt README from 0.1.2

## [0.1.2] - 2026-07-03

### Changed

- Cost figures relabeled as "token value at API list rates" with an inline explainer — an efficiency yardstick, not a bill (clears up confusion for subscription users); `--json` now carries `pricing_basis`
- README rebuilt: logo, verdict table, signal table, comparison table, FAQ (including the subscription-cost question)

### Added

- Project logo (light/dark variants)

## [0.1.1] - 2026-07-03

### Added

- Plain-language verdict line ("rot detected" / "no measurable rot" / "not enough data") leading every report — terminal, HTML, and JSON
- Explicit "degradation threshold: none found" reporting for flat curves

### Fixed

- `sessions` table now shows the project basename on Linux/macOS for transcripts recorded on Windows
- Statistical wording made readable ("within statistical noise" instead of "CIs overlap")

## [0.1.0] - 2026-07-02

### Added

- Claude Code transcript adapter (`~/.claude/projects/**/*.jsonl`), tolerant parsing, sidechain exclusion
- Outcome-signal extraction: tool errors, edit failures, retry loops, file re-reads, self-corrections
- Rot curve: failure-signal rate by context-fill bucket with Wilson 95% confidence intervals
- Degradation threshold (knee) detection and fresh-vs-deep context ratio with significance check
- Context composition estimate (startup overhead, tool outputs, conversation)
- Cost accounting per step with per-model pricing; cost-of-degraded-steps estimate
- Quantified prescriptions engine
- Terminal report (Rich), self-contained HTML report (inline SVG, dark mode, tooltips, data table), `--json` output
- `contextrot sessions` listing command
