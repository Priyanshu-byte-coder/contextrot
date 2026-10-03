"""``contextrot share``: what it carries, what it must never carry, and its format.

The privacy test walks every string in the payload. It is the contract the
whole sharing mechanism rests on — "you can read every byte, and none of it is
yours to worry about" — so it is enforced here, not promised in a docstring.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from contextrot.analysis import analyze
from contextrot.cli import app
from contextrot.share import (
    SCHEMA,
    SUBMIT_URL,
    _public_model,
    build_share,
    copy_to_clipboard,
    to_json,
)

FIXTURES = Path(__file__).parent / "fixtures"
SECRET = "acme-secret-billing-service"
runner = CliRunner()


@pytest.fixture()
def private_corpus(tmp_path: Path) -> Path:
    """The demo fixture, moved under a project name and path that must not leak."""
    project = tmp_path / f"-home-alice-{SECRET}"
    project.mkdir()
    for src in (FIXTURES / "demo-project").glob("*.jsonl"):
        text = src.read_text(encoding="utf-8")
        text = text.replace("C:\\\\work\\\\demo-project", f"/home/alice/{SECRET}")
        text = text.replace("demo-project", SECRET)
        (project / src.name).write_text(text, encoding="utf-8")
    return tmp_path


def _strings(value) -> list[str]:
    """Every string anywhere in a JSON-shaped value, keys included."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (k, *_strings(v))]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


# --- privacy -------------------------------------------------------------------


def test_no_project_name_or_path_anywhere(private_corpus: Path) -> None:
    result = analyze(data_dir=private_corpus, days=0)
    # Guard against a vacuous pass: the secret must actually be in what was
    # analyzed, or "it didn't leak" proves nothing.
    assert any(SECRET in s.project for s in result.sessions), "fixture did not carry the secret"
    payload = build_share(result, version="test")
    for text in _strings(payload):
        assert SECRET not in text, text
        assert "alice" not in text, text
        assert "/" not in text and "\\" not in text, f"path-like string: {text!r}"


def test_no_dollar_figures_or_timestamps(private_corpus: Path) -> None:
    payload = build_share(analyze(data_dir=private_corpus, days=0), version="test")
    blob = json.dumps(payload)
    assert "cost" not in blob and "usd" not in blob
    assert "2026-" not in blob, "a timestamp leaked into the share"


def test_private_model_names_are_pooled_as_other() -> None:
    """A fine-tune named after an employer must never surface by name."""
    assert _public_model("Opus 5") == "Opus 5"
    assert _public_model("gpt-5.4") == "gpt-5.4"
    assert _public_model("Acme 7") == "other"
    assert _public_model("abliterated") == "other"


# --- shape -----------------------------------------------------------------------


def test_payload_has_the_documented_top_level_keys() -> None:
    payload = build_share(analyze(data_dir=FIXTURES, days=0), version="9.9.9")
    assert payload["schema"] == SCHEMA
    assert payload["tool"] == "contextrot"
    assert payload["version"] == "9.9.9"
    for key in ("verdict", "curve", "snowball", "signals", "factors", "by_agent", "by_model"):
        assert key in payload


def test_counts_are_integers_so_curves_can_be_pooled() -> None:
    """Rates alone can only be averaged; counts can be summed exactly."""
    payload = build_share(analyze(data_dir=FIXTURES, days=0), version="t")
    for bucket in payload["curve"]:
        assert isinstance(bucket["n"], int) and isinstance(bucket["failures"], int)
        assert 0 <= bucket["failures"] <= bucket["n"]


def test_all_history_is_recorded_as_null_not_zero() -> None:
    payload = build_share(analyze(data_dir=FIXTURES, days=0), version="t")
    assert payload["days"] is None


# --- serialisation ---------------------------------------------------------------


def test_serialised_block_round_trips() -> None:
    payload = build_share(analyze(data_dir=FIXTURES, days=0), version="t")
    assert json.loads(to_json(payload)) == payload


def test_serialised_block_is_ascii_for_every_clipboard() -> None:
    payload = build_share(analyze(data_dir=FIXTURES, days=0), version="t")
    to_json(payload).encode("ascii")  # must not raise


def test_flat_objects_stay_on_one_line() -> None:
    """Readability is the trust mechanism: a bucket is one row, not six."""
    text = to_json({"curve": [{"lo": 0, "hi": 10, "n": 5, "failures": 1}]})
    assert '{"lo": 0, "hi": 10, "n": 5, "failures": 1}' in text


def test_submit_url_carries_no_data() -> None:
    """A query string is logged by every server it passes; only the template rides."""
    assert SUBMIT_URL.endswith("?template=share_your_curve.yml")


# --- the command -------------------------------------------------------------------


def test_share_prints_json_on_stdout_and_guidance_elsewhere() -> None:
    result = runner.invoke(app, ["share", "--data-dir", str(FIXTURES), "--days", "0"])
    assert result.exit_code == 0
    # CliRunner mixes stderr into output by default; the JSON must still parse
    # from the start of stdout.
    start = result.stdout.index("{")
    end = result.stdout.rindex("}") + 1
    payload = json.loads(result.stdout[start:end])
    assert payload["tool"] == "contextrot"


def test_share_with_no_sessions_exits_nonzero(tmp_path: Path) -> None:
    result = runner.invoke(app, ["share", "--data-dir", str(tmp_path)])
    assert result.exit_code == 1


def test_copy_reports_failure_rather_than_raising(monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _cmd: None)
    assert copy_to_clipboard('{"a": 1}') is False
