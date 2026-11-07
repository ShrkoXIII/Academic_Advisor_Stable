"""The canonical runner invokes only migrated stages and honors dry-run."""
import sys
from types import SimpleNamespace

import src.main as runner


def test_data_order_and_dry_run_never_execute(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run executed a stage")
    monkeypatch.setattr(runner.subprocess, "run", forbidden)
    assert [s.name for s in runner.PIPELINE["data"]] == [
        "clean_degree_course", "clean_student_course", "clean_student_status",
        "filter_common_students", "build_student_course_enriched",
        "clean_student_diploma", "clean_outliers", "build_temporal_split",
        "build_registration_roster",
    ]
    assert runner.main(["--all", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "src.data.building.build_registration_roster" in output
    assert "src.experiments" not in output
    assert "build_frozen_history" not in output
    assert "publish_artifacts" not in output
    assert "V1" not in output and "V2" not in output


def test_failure_stops_the_pipeline(monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=7 if len(calls) == 2 else 0)
    monkeypatch.setattr(runner.subprocess, "run", run)
    assert runner.main(["--section", "data"]) == 7
    assert len(calls) == 2
    assert calls[0][0][:2] == [sys.executable, "-m"]
    assert calls[0][1]["cwd"] == runner.PROJECT_ROOT
