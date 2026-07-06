"""Session-level --days filtering (issue #6).

The mtime pre-filter can't see inside files that hold many sessions (e.g.
OpenCode's single SQLite DB, whose mtime is always fresh). load_sessions must
also compare the parsed session's own timestamps against the cutoff.

The fixture transcript is dated 2026-06-01, but the file's mtime is whenever
git checked it out — exactly the mismatch that hid the bug.
"""

from pathlib import Path

from contextrot.analysis import load_sessions

FIXTURES = Path(__file__).parent / "fixtures"


def _touch_fresh(tmp_path: Path) -> Path:
    """Copy the fixture tree so the file mtime is *now* while the session's
    own timestamps stay old."""
    import shutil

    dest = tmp_path / "data"
    shutil.copytree(FIXTURES, dest)
    return dest


def test_old_session_in_fresh_file_is_excluded(tmp_path: Path):
    data = _touch_fresh(tmp_path)
    sessions, _ = load_sessions(data_dir=data, days=7)
    assert sessions == []  # fixture session ended long before the 7-day window


def test_old_session_included_with_wide_window(tmp_path: Path):
    data = _touch_fresh(tmp_path)
    sessions, _ = load_sessions(data_dir=data, days=365)
    assert len(sessions) == 1


def test_no_days_keeps_everything(tmp_path: Path):
    data = _touch_fresh(tmp_path)
    sessions, _ = load_sessions(data_dir=data, days=None)
    assert len(sessions) == 1
