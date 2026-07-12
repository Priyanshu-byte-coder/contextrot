# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versioning follows
[SemVer](https://semver.org/).

## [0.10.0] - 2026-07-12

### Added

- **MCP server** — `contextrot mcp` serves contextrot to *any* MCP-capable
  agent over stdio (`claude mcp add contextrot -- contextrot mcp`). Three
  tools: `rot_report` (verdict, knee, fresh/deep failure rates, cost of
  degraded steps, prescriptions), `agents_ranking` (which of the user's CLIs
  degrades first), and `prescriptions`. The agent itself can now ask "how
  rotted is my human's setup?" mid-session and act on the answer — compact,
  warn, or switch models.
- Zero new dependencies: the JSON-RPC 2.0 / MCP stdio transport
  (newline-delimited, spec 2025-06-18, with version negotiation, ping, and
  in-band tool errors) is implemented in the standard library. Still zero
  network calls — stdio is a pipe to the parent process, not a socket.

## [0.9.0] - 2026-07-12

### Added

- **Knee-crossing warning hook for Claude Code** — `contextrot install hook`
  registers a PostToolUse hook that watches the live session and warns **once**
  the moment context fill crosses your measured degradation threshold:
  *"contextrot: context 75% — past your measured degradation threshold (~70%).
  Your failure rate here is 2.0× fresh-context. Consider /compact or a fresh
  session."* The fill comes from a tail read of the live transcript (cheap even
  on multi-megabyte sessions); the threshold and rates come from your
  calibration cache. A marker keeps it from nagging on every tool call, and it
  re-arms after fill drops back below the knee (e.g. post-/compact).
- Honest by design: with no calibration, too little data, or no knee in your
  curve, the hook says nothing — no generic scare thresholds.
- Installer safety as always: dry-run by default, `--apply` + confirm,
  `.contextrot.bak` backup. The hook entry is appended without touching your
  existing hooks, and `contextrot uninstall hook` removes only contextrot's
  entry.

## [0.8.0] - 2026-07-12

### Added

- **Live statusline for Claude Code** — the report's knowledge, in the session
  where it matters. `contextrot statusline` renders a context-health segment
  from the JSON Claude Code pipes to statusline commands: current fill with a
  bar, colored against **your measured degradation curve** (green below your
  knee, yellow approaching it, red past it) instead of a generic hardcoded
  threshold, plus your historical failure rate at the current fill
  ("fail here 4.8% (1.5× fresh)"). Uncalibrated setups fall back to generic
  70/90 thresholds and say so.
- `contextrot install statusline` / `contextrot uninstall statusline` — wires
  the statusline into `~/.claude/settings.json` with the same safety contract
  as `contextrot fix`: **dry-run by default**, `--apply` + confirmation to
  write, a `.contextrot.bak` backup beside the file, and an existing
  non-contextrot statusLine is never replaced without `--force`.
- **Calibration cache** (`~/.contextrot/calibration.json`) — every full report
  run over your real data dirs snapshots your curve (knee, verdict, per-bucket
  rates) so live surfaces can compare in milliseconds. It's a cache, not
  state: delete it freely, the next report rewrites it. Runs with `--data-dir`
  never write it, so fixtures can't poison your calibration.

## [0.7.0] - 2026-07-10

### Added

- **Per-agent comparison** — the capstone of the 0.6.x adapter wave. With
  eight agents supported (Claude Code, Codex CLI, Gemini CLI, Qwen Code,
  OpenCode, Cline, Roo Code, Kilo Code), contextrot now builds an independent
  rot curve + verdict *per coding agent* on a shared scale: which CLI
  degrades first, measured on your workload rather than a benchmark's. New
  `contextrot agents` subcommand prints the ranked breakdown; the same table
  and small-multiple charts appear in the default terminal report and the
  HTML report when at least two agents clear the 150-step floor (smaller
  agents fold into "Other").
- Additive `agents` key in `--json` (mirrors `models`/`projects`) and a
  per-step `source` field.
- `contextrot sessions` shows an Agent column when sessions span more than
  one agent.

### Changed

- The no-sessions message and `--data-dir` help now describe the full set of
  supported agents instead of Claude Code only.

## [0.6.3] - 2026-07-10

### Added

- **Cline, Roo Code, and Kilo Code adapter** — one adapter for the Cline
  family of VS Code extensions. Task directories are discovered in the
  global storage of every common host editor (VS Code, VS Code Insiders,
  VSCodium, Cursor, Windsurf); sessions are labeled `cline`, `roo-code`, or
  `kilo-code` by publisher. Token accounting comes from each task's
  `api_req_started` UI entries (Anthropic-style `tokensIn`/`tokensOut`/
  `cacheWrites`/`cacheReads`, mapped straight through); tool calls are
  parsed from the XML-style tags these extensions embed in assistant text,
  with outcomes judged from the `[tool ...] Result:` blocks in the following
  user message (documented as heuristic — the format records no status
  flag). Project identity comes from the announced workspace directory,
  falling back to Roo's `history_item.json`.

### Changed

- Edit/read tool-name coverage in signal extraction now includes every
  supported agent's native names (`replace`, `write_file`, `write_to_file`,
  `replace_in_file`, `apply_diff`, `insert_content`, `search_and_replace`,
  `edit_file`, `read_file`, `read_many_files`) — Gemini CLI and Cline-family
  edit failures now register as edit failures, not just generic tool errors.

## [0.6.2] - 2026-07-10

### Added

- **Gemini CLI adapter** (closes
  [#4](https://github.com/Priyanshu-byte-coder/contextrot/issues/4)) — reads
  session recordings under `~/.gemini/tmp/<project-hash>/chats/`, supporting
  both the current JSONL stream (including `$set` metadata patches and
  `$rewindTo` rollbacks) and the legacy single-JSON `ConversationRecord`.
  Per-call token accounting comes from each gemini message's `tokens` summary
  (cached prefix split out of `input` so context fill is never double
  counted; `thoughts` tokens counted as output), tool calls from `toolCalls`
  records with `status: "error"` detection, and the project from the
  session's recorded `directories`. Sub-agent recordings (`kind: "subagent"`)
  are excluded, mirroring sidechain handling elsewhere.
- **Qwen Code support** — Qwen Code is a Gemini CLI fork with the same
  recording format; `~/.qwen/tmp/` is scanned automatically and its sessions
  are labeled `qwen-code` so the two CLIs stay distinguishable.

## [0.6.1] - 2026-07-10

### Added

- **Codex CLI adapter** (closes
  [#3](https://github.com/Priyanshu-byte-coder/contextrot/issues/3)) — reads
  Codex's per-session rollout files
  (`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`) with real per-call token
  accounting from `token_count` events, `function_call`/`custom_tool_call`
  tool calls (including `apply_patch`, whose first touched file becomes the
  retry/re-read target), and error detection from `Exit code:` prefixes and
  embedded `metadata.exit_code`. Cached input tokens are split out so context
  fill is never double counted.
- Transcripts that state their own context window (Codex's
  `model_context_window`) now feed it to the analysis as a per-session hint —
  more accurate fill % than the model-name lookup, still overridable with
  `--window`.
- Context-window and list-price entries for GPT-5/GPT-4, Gemini, and Qwen
  model families (flagged as estimated), so mixed-agent reports price and
  bucket sensibly.

## [0.6.0] - 2026-07-09

### Added

- **`contextrot fix`** — turns the report's prescriptions into concrete,
  checkable actions. **Dry run by default**: it lists your prescriptions, the
  size of the global CLAUDE.md loaded before your first word, and any MCP
  servers configured but never actually called in the analyzed window (their
  tool schemas sit in every session's startup overhead for nothing) — and
  writes nothing.
- **`contextrot fix --apply`** disables *unused global* MCP servers, with a
  y/N prompt per server. It writes a full `.contextrot.bak` backup first, then
  moves each server from `mcpServers` into a reversible
  `contextrotDisabledMcpServers` stash — nothing is deleted and the rest of the
  config (per-project tree, all other keys) is left byte-untouched. Undo by
  restoring the backup or moving the entries back.
- Unused **project-scoped** MCP servers and CLAUDE.md are **reported only**,
  never auto-edited — the former with the exact `claude mcp remove` command to
  run yourself, the latter because contextrot never rewrites your prose.
- Detection is derived entirely from local data: used servers come from
  `mcp__<server>__` tool-call prefixes in your transcripts, configured servers
  from `~/.claude.json`. A server is judged unused only if *no* analyzed session
  used it, so a server you rely on anywhere is never flagged.

## [0.5.0] - 2026-07-09

### Added

- **Per-project comparison** — a new grouping axis alongside the per-model one.
  contextrot now builds an independent rot curve + verdict for each project
  (working directory) it finds, so you can see *which repo degrades first*
  instead of only an all-projects average. New `contextrot projects` subcommand
  prints the ranked breakdown (Project · Steps · Fresh · Deep · Ratio ·
  Threshold · Verdict); the same table and small-multiple charts appear in the
  default terminal report and the HTML report when at least two projects clear
  the 150-step floor. Projects under that floor fold into a single "Other" row.
- Additive `projects` key in `--json` (mirrors `models`) and a per-step
  `project` field. Projects are grouped by full working-directory path, so two
  different directories that share a leaf name stay separate; the display label
  is the basename.

## [0.4.0] - 2026-07-07

### Added

- **Reversal-count axis** — community contribution by
  [@Muhtasim-Munif-Fahim](https://github.com/Muhtasim-Munif-Fahim)
  ([#7](https://github.com/Priyanshu-byte-coder/contextrot/pull/7), closes
  [#5](https://github.com/Priyanshu-byte-coder/contextrot/issues/5)).
  Failure rate is now also correlated against how many session-local
  reversals (self-corrections, retries, repeated edit failures on an
  already-edited file) happened *before* each step — the "rot is what's in
  the context, not how full it is" hypothesis, measurable on your own data.
  New table in terminal and HTML reports, additive `reversal_curve` key in
  `--json`, and per-step `reversals_so_far`/`reversal` fields. Buckets use
  prior-step counts only, so a failure never explains itself.
- Methodology notes for the reversal axis, including its confounders
  (reversal bursts autocorrelate; the 5+ bucket skews toward long sessions)

## [0.3.0] - 2026-07-06

### Added

- **OpenCode adapter** — the first community-contributed adapter, by
  [@BYK](https://github.com/BYK) ([#2](https://github.com/Priyanshu-byte-coder/contextrot/pull/2)).
  Reads OpenCode's single SQLite database (`opencode.db`) with real per-step
  token accounting, embedded tool outcomes, and sub-agent sessions surfaced as
  sidechain steps. `contextrot` now analyzes Claude Code and OpenCode sessions
  side by side.

### Fixed

- Tool-name matching in signal extraction is now case-insensitive — OpenCode's
  lowercase tool names (`edit`, `read`) previously never registered as edit
  failures or re-reads (part of #2)
- `--days` now also filters by the parsed session's own timestamps, not just
  file mtime — with single-database adapters the file is always fresh, so old
  sessions were never excluded
  ([#6](https://github.com/Priyanshu-byte-coder/contextrot/issues/6))

## [0.2.0] - 2026-07-04

### Added

- Hero verdict banner leading both reports: verdict word + one big memorable
  number (ratio / threshold / steps), color-blocked in HTML, color-boxed with a
  unicode sparkline of the rot curve in the terminal
- **Share card**: 1200×630 social-ready card in the HTML report with
  Save-as-PNG and Download-SVG buttons — pure inline SVG, still zero network
- **Per-model comparison**: independent rot curve + verdict per model family
  (Opus vs Sonnet vs …), comparison table in both reports, small-multiple
  charts on a shared scale in HTML, additive `models` key in `--json`;
  models under 150 steps fold into "Other"

### Fixed

- HTML chart y-axis was squashed when a tiny bucket's wide confidence interval
  set the scale (seen in real user reports) — low-confidence buckets no longer
  drive the axis, in HTML or terminal
- "CIs overlap" jargon in the HTML tile now reads "within statistical noise",
  matching the terminal

## [0.1.7] - 2026-07-04

### Added

- `python -m contextrot` entry point — runs the tool without needing the pip
  scripts directory on `PATH` (common friction with the stock macOS `python3`
  and `pip install --user`). README documents it as the fallback.

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
