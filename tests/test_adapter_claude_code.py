from pathlib import Path

from contextrot.adapters.claude_code import ClaudeCodeAdapter

FIXTURES = Path(__file__).parent / "fixtures"
SESSION_FILE = FIXTURES / "demo-project" / "11111111-2222-3333-4444-555555555555.jsonl"


def test_discover_finds_fixture():
    paths = ClaudeCodeAdapter().discover(FIXTURES)
    assert SESSION_FILE in paths


def test_parse_basic_structure():
    session = ClaudeCodeAdapter().parse(SESSION_FILE)
    assert session is not None
    assert session.source == "claude-code"
    assert len(session.steps) == 5  # sidechain step excluded
    assert session.sidechain_steps == 1
    assert session.project == "C:\\work\\demo-project"
    assert session.started_at is not None and session.ended_at is not None
    assert session.started_at < session.ended_at


def test_token_accounting():
    session = ClaudeCodeAdapter().parse(SESSION_FILE)
    assert session is not None
    first, *_, last = session.steps
    assert first.prompt_tokens == 12 + 19988 + 0
    assert last.prompt_tokens == 22 + 9978 + 140000
    assert first.model == "claude-sonnet-4-6"


def test_tool_results_attached():
    session = ClaudeCodeAdapter().parse(SESSION_FILE)
    assert session is not None
    edit_fail_step = session.steps[1]
    assert edit_fail_step.tool_calls[0].name == "Edit"
    assert edit_fail_step.tool_calls[0].is_error
    assert "not found" in edit_fail_step.tool_calls[0].error_text

    ok_read = session.steps[0].tool_calls[0]
    assert ok_read.name == "Read"
    assert not ok_read.is_error
    assert ok_read.result_chars > 0


def test_malformed_lines_are_skipped(tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    f = project / "broken.jsonl"
    f.write_text(
        'not json at all\n{"type":"assistant","message":{"role":"assistant",'
        '"model":"claude-sonnet-4-6","content":[],"usage":{"input_tokens":5,'
        '"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":1}}}\n',
        encoding="utf-8",
    )
    session = ClaudeCodeAdapter().parse(f)
    assert session is not None
    assert len(session.steps) == 1


def test_empty_file_returns_none(tmp_path: Path):
    f = tmp_path / "empty.jsonl"
    f.write_text("", encoding="utf-8")
    assert ClaudeCodeAdapter().parse(f) is None
