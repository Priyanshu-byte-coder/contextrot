import json
from pathlib import Path

from contextrot.analysis.fixes import (
    claude_md_report,
    configured_mcp_servers,
    disable_global_servers,
    unused_mcp_servers,
    used_mcp_servers,
)
from contextrot.models import Session, Step, ToolCall


def _session(tool_names: list[str]) -> Session:
    step = Step(
        timestamp=None,
        model="claude-opus-4-8",
        tool_calls=[ToolCall(name=n, tool_use_id=str(i)) for i, n in enumerate(tool_names)],
    )
    return Session(session_id="s", source="claude-code", project="/p", steps=[step])


def test_used_mcp_servers_extracts_prefix():
    sessions = [_session(["mcp__figma__get_file", "Read", "mcp__github__search"])]
    assert used_mcp_servers(sessions) == {"figma", "github"}


def test_used_mcp_servers_ignores_non_mcp():
    sessions = [_session(["Read", "Edit", "Bash"])]
    assert used_mcp_servers(sessions) == set()


def _write_config(path: Path, global_servers, project_servers) -> None:
    data = {
        "mcpServers": {n: {"command": n} for n in global_servers},
        "projects": {
            proj: {"mcpServers": {n: {"command": n} for n in servers}}
            for proj, servers in project_servers.items()
        },
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def test_configured_mcp_servers_global_and_project(tmp_path: Path):
    cfg = tmp_path / "claude.json"
    _write_config(cfg, ["stitch"], {"/home/me/api": ["github", "figma"]})
    servers = configured_mcp_servers(cfg)
    by_name = {s.name: s.scope for s in servers}
    assert by_name == {"stitch": "global", "github": "project", "figma": "project"}


def test_configured_missing_file_is_empty(tmp_path: Path):
    assert configured_mcp_servers(tmp_path / "nope.json") == []


def test_configured_malformed_is_empty(tmp_path: Path):
    cfg = tmp_path / "claude.json"
    cfg.write_text("{not json", encoding="utf-8")
    assert configured_mcp_servers(cfg) == []


def test_unused_splits_global_and_project(tmp_path: Path):
    cfg = tmp_path / "claude.json"
    _write_config(cfg, ["stitch", "used_global"], {"/home/me/api": ["github", "figma"]})
    # Only used_global and figma were actually called.
    sessions = [_session(["mcp__used_global__x", "mcp__figma__y"])]
    unused = unused_mcp_servers(sessions, cfg)
    assert [s.name for s in unused.global_unused] == ["stitch"]
    assert [s.name for s in unused.project_unused] == ["github"]
    assert unused.any


def test_unused_none_when_all_used(tmp_path: Path):
    cfg = tmp_path / "claude.json"
    _write_config(cfg, ["stitch"], {})
    sessions = [_session(["mcp__stitch__x"])]
    unused = unused_mcp_servers(sessions, cfg)
    assert not unused.any


def test_claude_md_report(tmp_path: Path):
    md = tmp_path / "CLAUDE.md"
    md.write_text("x" * 400, encoding="utf-8")
    r = claude_md_report(md)
    assert r is not None
    assert r.chars == 400
    assert r.token_estimate == 100  # chars // 4


def test_claude_md_report_missing(tmp_path: Path):
    assert claude_md_report(tmp_path / "nope.md") is None


def test_disable_global_servers_moves_and_backs_up(tmp_path: Path):
    cfg = tmp_path / "claude.json"
    _write_config(cfg, ["stitch", "keepme"], {"/home/me/api": ["github"]})
    original = cfg.read_text(encoding="utf-8")

    backup, moved = disable_global_servers(cfg, ["stitch"])

    assert moved == ["stitch"]
    # Backup preserves the pre-edit file byte-for-byte.
    assert backup.read_text(encoding="utf-8") == original
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert "stitch" not in data["mcpServers"]
    assert "keepme" in data["mcpServers"]  # untouched
    assert "stitch" in data["contextrotDisabledMcpServers"]
    # Reversible: the full definition is preserved in the stash.
    assert data["contextrotDisabledMcpServers"]["stitch"] == {"command": "stitch"}
    # Project tree is left entirely alone.
    assert data["projects"]["/home/me/api"]["mcpServers"] == {"github": {"command": "github"}}


def test_disable_global_servers_noop_when_absent(tmp_path: Path):
    cfg = tmp_path / "claude.json"
    _write_config(cfg, ["stitch"], {})
    before = cfg.read_text(encoding="utf-8")
    _, moved = disable_global_servers(cfg, ["not_configured"])
    assert moved == []
    # No write, no backup file, when nothing matched.
    assert cfg.read_text(encoding="utf-8") == before
    assert not (tmp_path / "claude.json.contextrot.bak").exists()
