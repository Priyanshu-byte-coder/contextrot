import json
from pathlib import Path

from typer.testing import CliRunner

from contextrot.cli import app

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def test_default_report_runs():
    result = runner.invoke(app, ["--data-dir", str(FIXTURES), "--days", "0"], env={"NO_COLOR": "1"})
    assert result.exit_code == 0
    assert "context rot report" in result.output


def test_json_output_shape():
    result = runner.invoke(app, ["--data-dir", str(FIXTURES), "--days", "0", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["sessions"] == 1
    assert len(payload["steps"]) == 5
    assert payload["cost"]["total_usd"] >= 0
    assert any(b["n"] for b in payload["curve"]["buckets"])
    assert any(b["n"] for b in payload["reversal_curve"]["buckets"])
    assert payload["reversal_curve"]["total_reversal_events"] >= 0
    # Additive per-model key: always present, empty for the single-model fixture.
    assert payload["models"] == []
    # Additive per-project key: always present, empty for the tiny fixture.
    assert payload["projects"] == []
    # Additive per-agent key: always present, empty for the single-agent fixture.
    assert payload["agents"] == []
    # Per-step project and source are threaded through.
    assert all("project" in s for s in payload["steps"])
    assert all(s["source"] == "claude-code" for s in payload["steps"])


def test_html_report_written(tmp_path: Path):
    out = tmp_path / "report.html"
    result = runner.invoke(app, ["--data-dir", str(FIXTURES), "--days", "0", "--html", str(out)])
    assert result.exit_code == 0
    html = out.read_text(encoding="utf-8")
    assert "<svg" in html
    assert "contextrot" in html
    # Self-contained: no external resources.
    assert "http://" not in html
    assert 'src="https' not in html and 'href="https' not in html


def test_html_report_written_to_directory(tmp_path: Path):
    result = runner.invoke(
        app, ["--data-dir", str(FIXTURES), "--days", "0", "--html", str(tmp_path)]
    )
    assert result.exit_code == 0
    out = tmp_path / "contextrot-report.html"
    assert out.exists()
    assert "<svg" in out.read_text(encoding="utf-8")


def test_sessions_subcommand():
    result = runner.invoke(app, ["sessions", "--data-dir", str(FIXTURES), "--days", "0"])
    assert result.exit_code == 0
    assert "demo-project" in result.output


def test_projects_subcommand_insufficient(tmp_path: Path):
    # The 5-step demo fixture is well under the 150-step-per-project floor, so
    # the projects command exits 1 with a "keep using" message rather than a table.
    result = runner.invoke(app, ["projects", "--data-dir", str(FIXTURES), "--days", "0"])
    assert result.exit_code == 1
    assert "Not enough steps" in result.output


def test_agents_subcommand_insufficient(tmp_path: Path):
    # The 5-step demo fixture is well under the 150-step-per-agent floor, so
    # the agents command exits 1 with a "keep using" message rather than a table.
    result = runner.invoke(app, ["agents", "--data-dir", str(FIXTURES), "--days", "0"])
    assert result.exit_code == 1
    assert "Not enough steps" in result.output


def test_no_sessions_exit_code(tmp_path: Path):
    result = runner.invoke(app, ["--data-dir", str(tmp_path)])
    assert result.exit_code == 1


def _fix_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "claude.json"
    cfg.write_text(
        json.dumps({"mcpServers": {"unused_server": {"command": "x"}}, "projects": {}}),
        encoding="utf-8",
    )
    return cfg


def test_fix_dry_run_writes_nothing(tmp_path: Path):
    cfg = _fix_config(tmp_path)
    before = cfg.read_text(encoding="utf-8")
    result = runner.invoke(
        app,
        ["fix", "--data-dir", str(FIXTURES), "--days", "0", "--config", str(cfg)],
    )
    assert result.exit_code == 0
    assert "unused_server" in result.output
    assert "--apply" in result.output
    # The demo fixture never calls unused_server, so it is flagged — but dry run
    # must not touch the config, and must not leave a backup behind.
    assert cfg.read_text(encoding="utf-8") == before
    assert not (tmp_path / "claude.json.contextrot.bak").exists()


def test_fix_apply_disables_with_backup(tmp_path: Path):
    cfg = _fix_config(tmp_path)
    result = runner.invoke(
        app,
        ["fix", "--data-dir", str(FIXTURES), "--days", "0", "--config", str(cfg), "--apply"],
        input="y\n",
    )
    assert result.exit_code == 0
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert "unused_server" not in data["mcpServers"]
    assert "unused_server" in data["contextrotDisabledMcpServers"]
    assert (tmp_path / "claude.json.contextrot.bak").exists()


def test_statusline_command(tmp_path: Path):
    payload = json.dumps({"context_window": {"used_percentage": 42}})
    result = runner.invoke(
        app,
        ["statusline"],
        input=payload,
        env={"CONTEXTROT_CALIBRATION": str(tmp_path / "none.json")},
    )
    assert result.exit_code == 0
    assert "42%" in result.output


def test_statusline_survives_garbage_stdin(tmp_path: Path):
    result = runner.invoke(
        app,
        ["statusline"],
        input="{not json",
        env={"CONTEXTROT_CALIBRATION": str(tmp_path / "none.json")},
    )
    assert result.exit_code == 0
    assert "ctx" in result.output


def test_install_statusline_dry_run_writes_nothing(tmp_path: Path):
    settings = tmp_path / "settings.json"
    result = runner.invoke(app, ["install", "statusline", "--settings", str(settings)])
    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert not settings.exists()


def test_install_statusline_apply(tmp_path: Path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"model": "opus"}), encoding="utf-8")
    result = runner.invoke(
        app, ["install", "statusline", "--settings", str(settings), "--apply"], input="y\n"
    )
    assert result.exit_code == 0
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["model"] == "opus"  # untouched
    assert data["statusLine"]["type"] == "command"
    assert "contextrot" in data["statusLine"]["command"]
    backup = Path(str(settings) + ".contextrot.bak")
    assert backup.exists()
    assert json.loads(backup.read_text(encoding="utf-8")) == {"model": "opus"}


def test_install_statusline_refuses_foreign_entry(tmp_path: Path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps({"statusLine": {"type": "command", "command": "my-own-script.sh"}}),
        encoding="utf-8",
    )
    result = runner.invoke(
        app, ["install", "statusline", "--settings", str(settings), "--apply"], input="y\n"
    )
    assert result.exit_code == 1
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["command"] == "my-own-script.sh"


def test_uninstall_statusline_roundtrip(tmp_path: Path):
    settings = tmp_path / "settings.json"
    runner.invoke(
        app, ["install", "statusline", "--settings", str(settings), "--apply"], input="y\n"
    )
    # Dry run first: key stays.
    result = runner.invoke(app, ["uninstall", "statusline", "--settings", str(settings)])
    assert result.exit_code == 0
    assert "statusLine" in json.loads(settings.read_text(encoding="utf-8"))
    # Apply: key removed.
    result = runner.invoke(
        app, ["uninstall", "statusline", "--settings", str(settings), "--apply"], input="y\n"
    )
    assert result.exit_code == 0
    assert "statusLine" not in json.loads(settings.read_text(encoding="utf-8"))


def test_report_with_data_dir_does_not_write_calibration(tmp_path: Path):
    cal = tmp_path / "calibration.json"
    result = runner.invoke(
        app,
        ["--data-dir", str(FIXTURES), "--days", "0"],
        env={"CONTEXTROT_CALIBRATION": str(cal), "NO_COLOR": "1"},
    )
    assert result.exit_code == 0
    assert not cal.exists()
