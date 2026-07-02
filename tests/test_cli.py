import json
from pathlib import Path

from typer.testing import CliRunner

from ctxprof.cli import app

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def test_default_report_runs():
    result = runner.invoke(
        app, ["--data-dir", str(FIXTURES), "--days", "0"], env={"NO_COLOR": "1"}
    )
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


def test_html_report_written(tmp_path: Path):
    out = tmp_path / "report.html"
    result = runner.invoke(
        app, ["--data-dir", str(FIXTURES), "--days", "0", "--html", str(out)]
    )
    assert result.exit_code == 0
    html = out.read_text(encoding="utf-8")
    assert "<svg" in html
    assert "ctxprof" in html
    # Self-contained: no external resources.
    assert "http://" not in html
    assert 'src="https' not in html and 'href="https' not in html


def test_sessions_subcommand():
    result = runner.invoke(app, ["sessions", "--data-dir", str(FIXTURES), "--days", "0"])
    assert result.exit_code == 0
    assert "demo-project" in result.output


def test_no_sessions_exit_code(tmp_path: Path):
    result = runner.invoke(app, ["--data-dir", str(tmp_path)])
    assert result.exit_code == 1
