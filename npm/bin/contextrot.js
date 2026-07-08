#!/usr/bin/env node
// npm wrapper for the contextrot Python CLI.
// Delegates to `uvx contextrot`, which fetches and runs the latest release
// from PyPI in an isolated environment. This wrapper stays version-agnostic
// on purpose: publishing it once is enough, npm users always get the
// current PyPI version.
"use strict";

const { spawnSync } = require("child_process");

const args = process.argv.slice(2);

function run(cmd, cmdArgs) {
  return spawnSync(cmd, cmdArgs, { stdio: "inherit" });
}

// Preferred: uvx (ships with uv, bootstraps Python itself if needed).
let result = run("uvx", ["contextrot"].concat(args));

// Fallback: an already-installed contextrot (pip install contextrot).
if (result.error && result.error.code === "ENOENT") {
  result = run("contextrot", args);
}

if (result.error && result.error.code === "ENOENT") {
  console.error(
    [
      "contextrot needs `uv` (recommended) or a Python install of contextrot.",
      "",
      "Install uv (one time):",
      "  Windows:     powershell -ExecutionPolicy ByPass -c \"irm https://astral.sh/uv/install.ps1 | iex\"",
      "  macOS/Linux: curl -LsSf https://astral.sh/uv/install.sh | sh",
      "",
      "…or use pip directly:",
      "  pip install contextrot",
      "",
      "Then re-run: npx contextrot",
    ].join("\n")
  );
  process.exit(1);
}

if (result.error) {
  console.error("contextrot: failed to launch:", result.error.message);
  process.exit(1);
}

process.exit(result.status === null ? 1 : result.status);
