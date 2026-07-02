# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versioning follows
[SemVer](https://semver.org/).

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
- `ctxprof sessions` listing command
