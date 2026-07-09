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
    # Per-step project is threaded through.
    assert all("project" in s for s in payload["steps"])


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


def test_no_sessions_exit_code(tmp_path: Path):
    result = runner.invoke(app, ["--data-dir", str(tmp_path)])
    assert result.exit_code == 1
