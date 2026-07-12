"""Minimal MCP server over stdio — contextrot for any MCP-capable agent.

Implements just enough of the Model Context Protocol (JSON-RPC 2.0,
newline-delimited over stdin/stdout) to serve tools, with zero new
dependencies: agents can ask "how rotted is my human's setup?" mid-session
and decide to compact, warn, or switch models on the answer.

Register it like any stdio MCP server, e.g. for Claude Code:

    claude mcp add contextrot -- contextrot mcp

Transport rules honored (spec 2025-06-18): one JSON-RPC message per line,
nothing but MCP messages on stdout, logging (if any) to stderr only.
Still zero network — stdio is a pipe to the parent process, not a socket.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable

from contextrot import __version__

_SUPPORTED_PROTOCOLS = {"2024-11-05", "2025-03-26", "2025-06-18"}
_DEFAULT_PROTOCOL = "2025-06-18"

_DAYS_PROP = {
    "type": "integer",
    "description": "Analysis window in days (0 = all history).",
    "default": 30,
}
_DATA_DIR_PROP = {
    "type": "string",
    "description": "Optional transcript-directory override (default: every agent's own dir).",
}

TOOLS: list[dict] = [
    {
        "name": "rot_report",
        "description": (
            "Analyze the user's local coding-agent transcripts and summarize where "
            "output quality degrades: verdict (rot/edge/clean/insufficient), degradation "
            "threshold (context-fill knee), fresh-vs-deep failure rates, and top "
            "prescriptions. Reads local files only; nothing is uploaded."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": _DAYS_PROP,
                "project": {
                    "type": "string",
                    "description": "Only sessions whose project path matches this substring.",
                },
                "data_dir": _DATA_DIR_PROP,
            },
        },
    },
    {
        "name": "agents_ranking",
        "description": (
            "Rank the user's coding agents (Claude Code, Codex CLI, Gemini CLI, Cline, …) "
            "by measured context rot on their own workload: per-agent failure rates, "
            "degradation ratio, threshold, and verdict."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"days": _DAYS_PROP, "data_dir": _DATA_DIR_PROP},
        },
    },
    {
        "name": "prescriptions",
        "description": (
            "Quantified, data-derived recommendations for the user's setup: when to "
            "compact, startup-overhead findings, re-read patterns — each with its "
            "measured impact."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"days": _DAYS_PROP, "data_dir": _DATA_DIR_PROP},
        },
    },
]


def _analysis(args: dict):
    from pathlib import Path

    from contextrot.analysis import analyze

    days = args.get("days", 30)
    data_dir = args.get("data_dir")
    return analyze(
        data_dir=Path(data_dir) if data_dir else None,
        project_filter=args.get("project"),
        days=int(days) if days else 0,
    )


def _finite(value: float | None) -> float | None:
    if value is None or value == float("inf"):
        return None
    return round(value, 3)


def _tool_rot_report(args: dict) -> dict:
    r = _analysis(args)
    return {
        "verdict": {"kind": r.verdict_kind, "text": r.verdict_text},
        "sessions": len(r.sessions),
        "steps": len(r.steps),
        "knee_pct": r.curve.knee_pct,
        "fresh_failure_rate": round(r.curve.low_fill_rate, 4),
        "deep_failure_rate": round(r.curve.high_fill_rate, 4),
        "degradation_ratio": _finite(r.curve.degradation_ratio),
        "ratio_significant": r.curve.ratio_significant,
        "cost_of_degraded_steps_usd": round(r.rework_cost_usd, 2),
        "prescriptions": [{"title": p.title, "detail": p.detail} for p in r.prescriptions],
    }


def _tool_agents_ranking(args: dict) -> dict:
    from contextrot.analysis.by_source import build_agent_comparison

    r = _analysis(args)
    stats = build_agent_comparison(r.steps, require_two=False)
    return {
        "agents": [
            {
                "agent": a.label,
                "steps": a.steps,
                "fresh_failure_rate": round(a.curve.low_fill_rate, 4),
                "deep_failure_rate": round(a.curve.high_fill_rate, 4),
                "degradation_ratio": _finite(a.curve.degradation_ratio),
                "knee_pct": a.curve.knee_pct,
                "verdict": a.verdict_kind,
                "other": a.is_other,
            }
            for a in stats
        ]
    }


def _tool_prescriptions(args: dict) -> dict:
    r = _analysis(args)
    return {
        "verdict": r.verdict_kind,
        "prescriptions": [
            {"title": p.title, "detail": p.detail, "impact": p.impact}
            for p in r.prescriptions
        ],
    }


_TOOL_IMPLS: dict[str, Callable[[dict], dict]] = {
    "rot_report": _tool_rot_report,
    "agents_ranking": _tool_agents_ranking,
    "prescriptions": _tool_prescriptions,
}


def _result(req_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle_message(msg: dict) -> dict | None:
    """One JSON-RPC message in, one response out (None for notifications)."""
    method = msg.get("method")
    req_id = msg.get("id")
    is_notification = "id" not in msg

    if not isinstance(method, str):
        return None if is_notification else _error(req_id, -32600, "invalid request")

    if method.startswith("notifications/"):
        return None

    if method == "initialize":
        params = msg.get("params") or {}
        requested = params.get("protocolVersion")
        version = requested if requested in _SUPPORTED_PROTOCOLS else _DEFAULT_PROTOCOL
        return _result(
            req_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "contextrot", "version": __version__},
            },
        )

    if method == "ping":
        return _result(req_id, {})

    if method == "tools/list":
        return _result(req_id, {"tools": TOOLS})

    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        impl = _TOOL_IMPLS.get(name or "")
        if impl is None:
            return _result(
                req_id,
                {
                    "content": [{"type": "text", "text": f"unknown tool: {name}"}],
                    "isError": True,
                },
            )
        try:
            payload = impl(args if isinstance(args, dict) else {})
        except Exception as e:  # noqa: BLE001 — tool errors go in-band per MCP
            text = f"{type(e).__name__}: {e}"
            return _result(
                req_id,
                {"content": [{"type": "text", "text": text}], "isError": True},
            )
        return _result(
            req_id,
            {
                "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
                "isError": False,
            },
        )

    if is_notification:
        return None
    return _error(req_id, -32601, f"method not found: {method}")


def serve(stdin=None, stdout=None) -> None:
    """Blocking stdio loop: one JSON-RPC message per line, responses flushed."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            stdout.write(json.dumps(_error(None, -32700, "parse error")) + "\n")
            stdout.flush()
            continue
        if not isinstance(msg, dict):
            stdout.write(json.dumps(_error(None, -32600, "invalid request")) + "\n")
            stdout.flush()
            continue
        response = handle_message(msg)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
