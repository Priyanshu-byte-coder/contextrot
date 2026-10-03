"""Build the synthetic dataset the SHOWCASE media is captured from.

SHOWCASE.md promises that every figure in it comes from a synthetic dataset and
that no real project names appear. This script is that dataset, written down, so
every screenshot can be regenerated and checked rather than re-photographed:

    python scripts/make_showcase_data.py --out .showcase-data
    python scripts/capture_showcase.py --data-dir .showcase-data

Three fake projects, two agents, four models, and a deliberate shape — chosen so
each screen has something true to show, not so the tool looks good:

* **Opus degrades with context fill; Sonnet and Haiku stay flat** on the same
  work, so the rot curve has a real threshold and the model comparison a real gap.
* **Late-night sessions slip more**, so ``contextrot factors`` has a genuine
  time-of-day effect to find. Hours are laid out on *this machine's* local clock,
  because that is the clock ``factors`` reads — capture on the machine you
  generate on, or the night sessions land in a different bucket.
* **Failures are independent of earlier failures** — and ``factors`` still
  reports a snowball. That is not a bug in either: sessions that have made more
  mistakes are, on average, deeper into their context, where Opus degrades. It is
  confounding, it happens on real data too, and it is the clearest demonstration
  of why the report says "association, not causation".
* **Things get better over four weeks**, about a third as many slips by the last
  week than the first — for both agents — so ``contextrot trends`` has a direction
  to draw.
* **Realistic rates**: about 4% of steps slip at a fresh context, as on real
  workloads, rather than the 15–20% a naive generator produces when every read
  hits the same five files and counts as a re-read.

Failures are placed per fill bucket rather than by a modulus over step number: a
modulus correlates with the fill sweep and manufactures a threshold.

Fixed seed, so the same numbers come out every run. Writes nothing outside
``--out``. Nothing here touches a real transcript.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Local wall-clock start, converted to UTC for the files. See the module docstring.
START_LOCAL = datetime(2026, 8, 3, 9, 0)

# project slug -> (sessions, model, turns per session)
PROJECTS = (
    ("auth-service", "claude-opus-5", 30, 22),
    ("web-dashboard", "claude-sonnet-5", 20, 12),
    ("cli-tools", "claude-haiku-4-5", 14, 5),
)

# Probability a step slips, per fill decile. Opus degrades past ~60%; the others
# hold flat at roughly what real sessions show.
ROTTING = (0.035, 0.035, 0.04, 0.04, 0.045, 0.05, 0.11, 0.17, 0.22, 0.26)
FLAT = (0.04,) * 10

# Per-week multiplier on every slip probability: the "you changed something and it
# helped" story that `contextrot trends` exists to show.
WEEKLY = (1.7, 1.3, 0.9, 0.6)

# Sessions starting in this local-hour window slip this much more often.
NIGHT_HOURS = range(0, 5)
NIGHT_MULTIPLIER = 1.9

# Enough distinct files that ordinary reads are not mostly re-reads.
FILES = tuple(f"src/{area}/{name}.py" for area in ("auth", "api", "db", "ui") for name in
              ("models", "routes", "views", "utils", "config", "schema", "tests", "client"))
TOOLS = ("Read", "Edit", "Bash", "Grep", "Write", "Bash", "Edit")


def _iso(local: datetime) -> str:
    """A local wall-clock time as the UTC ISO string transcripts carry."""
    return local.astimezone().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _usage(prompt: int, output: int, fresh: int = 0) -> dict:
    """Claude Code's usage block, split the way a long session really splits.

    By the second step of a turn almost all of the prompt is a cache read, which
    is why water and cost totals are dominated by replay rather than output.
    """
    fresh = min(fresh or 0, prompt)
    return {
        "input_tokens": 24,
        "cache_creation_input_tokens": fresh,
        "cache_read_input_tokens": max(0, prompt - fresh - 24),
        "output_tokens": output,
    }


def _session_start(index: int, count: int) -> datetime:
    """Spread sessions over four weeks; roughly one in six runs past midnight."""
    day = START_LOCAL + timedelta(days=(index * 28) // max(count, 1))
    if index % 6 == 5:
        return day.replace(hour=1, minute=(index * 7) % 50)
    return day.replace(hour=9 + (index % 10), minute=(index * 13) % 50)


def _claude_session(
    rng: random.Random, project: str, model: str, index: int, count: int, turns: int, rates
) -> list[dict]:
    """One Claude Code transcript as a list of JSONL entries."""
    window = 1_000_000 if ("opus" in model or "sonnet-5" in model) else 200_000
    cwd = f"/home/dev/{project}"
    started = _session_start(index, count)
    night = started.hour in NIGHT_HOURS
    week = min(len(WEEKLY) - 1, (started - START_LOCAL).days // 7)
    sid = f"demo-{project}-{index}"
    lines: list[dict] = []
    uid = 0
    prompt = 18_000  # startup overhead: system prompt, tool schemas, instructions
    read_so_far: set[str] = set()

    for turn in range(turns):
        uid += 1
        when = started + timedelta(minutes=turn * 4)
        lines.append({
            "parentUuid": None if turn == 0 else f"a{uid - 1}",
            "isSidechain": False, "type": "user",
            "message": {"role": "user", "content": f"task {turn}: tidy {rng.choice(FILES)}"},
            "timestamp": _iso(when), "uuid": f"u{uid}", "cwd": cwd, "sessionId": sid,
        })

        for step in range(rng.randint(3, 7)):
            uid += 1
            fill = min(0.99, prompt / window)
            p = rates[min(9, int(fill * 10))] * WEEKLY[week]
            p *= NIGHT_MULTIPLIER if night else 1.0
            failed = rng.random() < p

            # Reads go to fresh files unless this step is meant to slip, so the
            # re-read signal fires about as often as the rate says and no more.
            tool = rng.choice(TOOLS)
            if tool == "Read" and not failed:
                fresh_files = [f for f in FILES if f not in read_so_far] or list(FILES)
                target_rel = rng.choice(fresh_files)
            elif tool == "Read":
                target_rel = rng.choice(sorted(read_so_far)) if read_so_far else FILES[0]
            else:
                target_rel = rng.choice(FILES)
            if tool == "Read":
                read_so_far.add(target_rel)
            target = f"{cwd}/{target_rel}"
            is_error = failed and tool != "Read"

            stamp = _iso(started + timedelta(minutes=turn * 4, seconds=step * 25 + 5))
            output = rng.randint(180, 900)
            fresh = rng.randint(1_200, 4_500) if step == 0 else 0
            lines.append({
                "parentUuid": f"u{uid - 1}", "isSidechain": False, "type": "assistant",
                "message": {
                    "role": "assistant", "model": model,
                    "content": [
                        {"type": "text", "text": "Working on it."},
                        {"type": "tool_use", "id": f"t{uid}", "name": tool,
                         "input": {"file_path": target}},
                    ],
                    "usage": _usage(prompt, output, fresh),
                },
                "timestamp": stamp, "uuid": f"a{uid}", "cwd": cwd, "sessionId": sid,
            })
            lines.append({
                "parentUuid": f"a{uid}", "isSidechain": False, "type": "user",
                "message": {"role": "user", "content": [{
                    "type": "tool_result", "tool_use_id": f"t{uid}", "is_error": is_error,
                    "content": "String to replace not found in file." if is_error else "ok\n",
                }]},
                "timestamp": stamp, "uuid": f"r{uid}", "cwd": cwd, "sessionId": sid,
            })
            prompt += output + rng.randint(2_500, 9_000)
            if prompt > window * 0.97:
                prompt = int(window * 0.35)  # a compaction
    return lines


def _codex_session(rng: random.Random, index: int, turns: int) -> list[dict]:
    """One Codex CLI rollout with real tool calls, so its rate is a measurement."""
    lines: list[dict] = []
    started = START_LOCAL + timedelta(days=(index * 28) // 20, hours=4, minutes=index * 7)
    week = min(len(WEEKLY) - 1, (started - START_LOCAL).days // 7)
    total_in = 9_000
    lines.append({
        "type": "turn_context", "timestamp": _iso(started),
        "payload": {"model": "gpt-5.4-codex", "cwd": "/home/dev/cli-tools"},
    })
    call = 0
    for turn in range(turns):
        when = started + timedelta(minutes=turn * 5)
        lines.append({"type": "event_msg", "timestamp": _iso(when),
                      "payload": {"type": "user_message", "message": f"fix bug {turn}"}})
        for step in range(rng.randint(2, 5)):
            call += 1
            stamp = _iso(when + timedelta(seconds=step * 20 + 3))
            failed = rng.random() < 0.06 * WEEKLY[week]
            lines.append({"type": "response_item", "timestamp": stamp, "payload": {
                "type": "function_call", "name": "shell", "call_id": f"c{call}",
                "arguments": json.dumps({"command": ["pytest", f"tests/test_{call % 9}.py"]}),
            }})
            lines.append({"type": "response_item", "timestamp": stamp, "payload": {
                "type": "function_call_output", "call_id": f"c{call}",
                "output": f"Exit code: {1 if failed else 0}\nOutput:\n...",
            }})
            output = rng.randint(150, 700)
            lines.append({"type": "event_msg", "timestamp": stamp, "payload": {
                "type": "token_count", "info": {
                    "model_context_window": 272_000,
                    "last_token_usage": {
                        "input_tokens": total_in,
                        # Codex reports the cached prefix inside input_tokens.
                        "cached_input_tokens": max(0, total_in - 2_400),
                        "output_tokens": output,
                    },
                },
            }})
            total_in += output + rng.randint(1_800, 6_000)
            if total_in > 260_000:
                total_in = 60_000
    return lines


def build(out: Path) -> dict:
    """Write the corpus. Returns a small summary for the caller to print."""
    if out.exists():
        shutil.rmtree(out)
    # Both adapters read the same --data-dir, so the layout has to satisfy both
    # without either picking up the other's files. Claude Code globs "*/*.jsonl"
    # from the root; Codex rglobs "rollout-*.jsonl", so putting the rollouts two
    # levels down keeps them out of Claude's glob.
    out.mkdir(parents=True)
    codex_root = out / "codex" / "sessions"
    codex_root.mkdir(parents=True)

    rng = random.Random(20260803)
    sessions = 0
    for project, model, count, turns in PROJECTS:
        rates = ROTTING if "opus" in model else FLAT
        d = out / f"-home-dev-{project}"
        d.mkdir()
        for index in range(count):
            lines = _claude_session(rng, project, model, index, count, turns, rates)
            (d / f"demo-{project}-{index:03d}.jsonl").write_text(
                "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
            )
            sessions += 1

    # Enough Codex work, and long enough sessions, for it to earn a verdict of its
    # own rather than "not enough data" — otherwise the agent comparison has one row.
    for index in range(20):
        lines = _codex_session(rng, index, 14)
        (codex_root / f"rollout-demo-{index:03d}.jsonl").write_text(
            "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
        )
        sessions += 1

    return {"sessions": sessions, "out": str(out)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out",
        type=Path,
        default=Path(".showcase-data"),
        help="Directory to write the synthetic corpus into (recreated each run).",
    )
    args = ap.parse_args()
    summary = build(args.out)
    print(f"wrote {summary['sessions']} synthetic sessions to {summary['out']}")
    print("capture with: python scripts/capture_showcase.py --data-dir", summary["out"])


if __name__ == "__main__":
    main()
