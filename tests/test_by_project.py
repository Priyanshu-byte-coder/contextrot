from contextrot.analysis.by_project import (
    build_project_comparison,
    project_label,
)
from contextrot.analysis.rot import build_rot_curve, verdict
from contextrot.signals import StepSignals


def test_project_label_basename():
    assert project_label("/home/me/code/webapp") == "webapp"
    assert project_label("C:\\Users\\me\\code\\webapp") == "webapp"
    assert project_label("C:/Users/me/code/webapp/") == "webapp"
    assert project_label("webapp") == "webapp"
    assert project_label("") == "unknown"


def _step(fill: float, degraded: bool, project: str) -> StepSignals:
    return StepSignals(
        step_index=0,
        prompt_tokens=int(fill * 2000),
        fill_pct=fill,
        model="claude-opus-4-8",
        project=project,
        tool_error=degraded,
    )


def _steps_for(project: str, n: int, deep_fail: bool) -> list[StepSignals]:
    """Half fresh (2% fail), half deep (30% fail if deep_fail else 2%)."""
    steps = [_step(15.0, i % 50 == 0, project) for i in range(n // 2)]
    deep_rate = 3 if deep_fail else 50  # every 3rd vs every 50th step fails
    steps += [_step(75.0, i % deep_rate == 0, project) for i in range(n // 2)]
    return steps


def test_comparison_two_projects_plus_other():
    steps = (
        _steps_for("/home/me/proj-a", 400, deep_fail=True)
        + _steps_for("/home/me/proj-b", 400, deep_fail=False)
        + _steps_for("/home/me/proj-c", 10, deep_fail=False)
    )
    projects = build_project_comparison(steps)

    assert [p.label for p in projects] == ["proj-a", "proj-b", "Other"]
    a, b, other = projects
    assert a.steps == 400 and not a.is_other
    assert a.key == "/home/me/proj-a"
    assert other.is_other and other.steps == 10 and other.verdict_kind == "insufficient"
    # The rotting project shows a higher ratio than the clean one.
    assert (a.curve.degradation_ratio or 0) > (b.curve.degradation_ratio or 0)


def test_comparison_reuses_verdict_logic():
    group = _steps_for("/home/me/proj-a", 400, deep_fail=True)
    steps = group + _steps_for("/home/me/proj-b", 400, deep_fail=False)
    projects = build_project_comparison(steps)
    expected_kind, expected_text = verdict(build_rot_curve(group))
    assert projects[0].verdict_kind == expected_kind
    assert projects[0].verdict_text == expected_text


def test_single_project_returns_empty_by_default():
    steps = _steps_for("/home/me/proj-a", 400, deep_fail=True)
    assert build_project_comparison(steps) == []


def test_single_project_shown_when_require_two_false():
    steps = _steps_for("/home/me/proj-a", 400, deep_fail=True)
    projects = build_project_comparison(steps, require_two=False)
    assert len(projects) == 1
    assert projects[0].label == "proj-a" and not projects[0].is_other


def test_two_tiny_projects_return_empty():
    steps = _steps_for("/home/me/proj-a", 20, deep_fail=True) + _steps_for(
        "/home/me/proj-b", 20, deep_fail=False
    )
    assert build_project_comparison(steps) == []


def test_distinct_paths_same_basename_stay_separate():
    # Two different working dirs that share a leaf name are distinct projects.
    steps = _steps_for("/home/me/work/api", 400, deep_fail=True) + _steps_for(
        "/home/me/play/api", 400, deep_fail=False
    )
    projects = build_project_comparison(steps)
    keys = {p.key for p in projects}
    assert keys == {"/home/me/work/api", "/home/me/play/api"}
    assert all(p.label == "api" for p in projects)
