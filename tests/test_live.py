"""Agent-agnostic live-session detection (the engine behind `contextrot status`).

Fixtures are built in tmp_path, so nothing real or private is read.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from contextrot.live import detect_live_session, tail_fill
from contextrot.pricing import context_window_for


def _claude_transcript(root: Path, fill_pct: float, model="claude-opus-4-8") -> Path:
    d = root / "-home-dev-demo"
    d.mkdir(parents=True, exist_ok=True)
    prompt = int(fill_pct / 100.0 * context_window_for(model))
    path = d / "session.jsonl"
    path.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "model": model,
                    "usage": {
                        "input_tokens": 500,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": prompt - 500,
                        "output_tokens": 20,
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _codex_rollout(root: Path, fill_pct: float, window=272_000) -> Path:
    d = root / "codex-sessions" / "2026" / "07" / "21"
    d.mkdir(parents=True, exist_ok=True)
    prompt = int(fill_pct / 100.0 * window)
    path = d / "rollout-2026-07-21-abc.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"type": "session_meta", "payload": {"id": "s1", "cwd": "/w"}}),
                json.dumps({"type": "turn_context", "payload": {"model": "gpt-5-codex"}}),
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {
                                # OpenAI style: input_tokens already includes cache.
                                "last_token_usage": {
                                    "input_tokens": prompt,
                                    "cached_input_tokens": prompt - 200,
                                    "output_tokens": 30,
                                },
                                "model_context_window": window,
                            },
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_tail_fill_claude_shape(tmp_path: Path):
    p = _claude_transcript(tmp_path, 42)
    assert tail_fill(p) is not None
    assert abs(tail_fill(p) - 42.0) < 0.5


def test_tail_fill_codex_shape(tmp_path: Path):
    p = _codex_rollout(tmp_path, 70)
    fill = tail_fill(p)
    assert fill is not None and abs(fill - 70.0) < 0.5


def test_tail_fill_unreadable_or_empty(tmp_path: Path):
    assert tail_fill(tmp_path / "nope.jsonl") is None
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert tail_fill(empty) is None
    junk = tmp_path / "junk.jsonl"
    junk.write_text("not json\n{}\n", encoding="utf-8")
    assert tail_fill(junk) is None


def test_detect_prefers_the_newest_transcript(tmp_path: Path):
    _claude_transcript(tmp_path, 30)
    codex = _codex_rollout(tmp_path, 80)
    # Make the codex rollout unambiguously newer.
    future = time.time() + 60
    os.utime(codex, (future, future))

    live = detect_live_session(data_dir=tmp_path)
    assert live is not None
    assert live.source == "codex"
    assert abs(live.fill_pct - 80.0) < 0.5


def test_detect_respects_within_minutes(tmp_path: Path):
    p = _claude_transcript(tmp_path, 50)
    old = time.time() - 3 * 3600
    os.utime(p, (old, old))
    assert detect_live_session(data_dir=tmp_path, within_minutes=30) is None
    # No recency requirement → still found.
    assert detect_live_session(data_dir=tmp_path) is not None


def test_detect_nothing_when_no_transcripts(tmp_path: Path):
    assert detect_live_session(data_dir=tmp_path) is None


def test_detect_falls_back_to_adapter_parse(tmp_path: Path):
    """OpenCode's JSON storage can't be tail-read — the adapter path must cover it."""
    storage = tmp_path / "storage"

    def write(*key: str, data: dict) -> None:
        path = storage.joinpath(*key).with_suffix(".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    write("project", "p1", data={"id": "p1", "worktree": "/home/dev/app"})
    write("session", "p1", "s1", data={"id": "s1", "projectID": "p1", "time": {"created": 1}})
    write(
        "message",
        "s1",
        "m1",
        data={
            "id": "m1",
            "role": "assistant",
            "modelID": "claude-sonnet-4-6",
            "time": {"created": 2},
            "tokens": {"input": 100, "output": 10, "cache": {"read": 99_900, "write": 0}},
        },
    )

    live = detect_live_session(data_dir=tmp_path)
    assert live is not None
    assert live.source == "opencode"
    # 100k of sonnet-4.6's 1M window.
    assert abs(live.fill_pct - 10.0) < 0.5
    assert live.project == "/home/dev/app"
