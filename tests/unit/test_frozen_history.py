"""Canonical serving history uses an isolated immutable finalized prefix."""
import json
from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from src import paths
from src.features import build_frozen_history as cli
from src.features.frozen_history import (
    build_frozen_history, file_sha256, load_frozen_history, save_frozen_history,
    validate_history_selection,
)


def outcomes():
    frame = pd.DataFrame({
        "student_course_id": ["past", "last", "first_test", "future"],
        "part_id": [20242, 20243, 20251, 20252],
        "degree_id": ["D"] * 4, "course_id": ["C"] * 4,
        "faculty_id": ["F"] * 4, "plan_requirement_type_id": ["R"] * 4,
        "course_credits": [3.0] * 4, "attempt_number": [1] * 4,
        "final_mark": [40.0, 60.0, 80.0, 100.0],
        "end_agpa_points": [1.0, 2.0, 3.0, 4.0],
    })
    return frame


def save_history(root, part=20243, frame=None):
    bundle = build_frozen_history(
        outcomes() if frame is None else frame, part,
        finalized_through_part=part,
    )
    save_frozen_history(*bundle, root=root)
    return bundle


def test_default_root_never_falls_back_to_another_history_directory(tmp_path, monkeypatch):
    legacy, canonical = tmp_path / "other_history", tmp_path / "history"
    monkeypatch.setattr(paths, "FROZEN_HISTORY_DIR", canonical)
    old = outcomes().assign(final_mark=10.0)
    save_frozen_history(*build_frozen_history(old, 20243, finalized_through_part=20243), root=legacy)
    with pytest.raises(FileNotFoundError):
        load_frozen_history(20243)
    save_history(canonical)
    loaded, specialty, provenance = load_frozen_history(20243)
    assert loaded.global_sums["raw_count"] == 2
    assert loaded.global_sums["mark_sum"] == 100.0
    assert specialty is None
    assert provenance["directory"] == str((canonical / "as_of_20243").resolve())


def test_history_hash_corruption_is_rejected(tmp_path):
    save_history(tmp_path)
    state = tmp_path / "as_of_20243" / "course_history_state.pkl"
    state.write_bytes(state.read_bytes() + b"corruption")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_frozen_history(20243, root=tmp_path)


def test_new_cutoff_has_only_finalized_prefix_and_cannot_overwrite(tmp_path):
    save_history(tmp_path)
    directory = tmp_path / "as_of_20243"
    before = {p.name: file_sha256(p) for p in directory.iterdir()}
    save_history(tmp_path, part=20251)
    for cutoff, count, part_counts in [(20243, 2, {"20242": 1, "20243": 1}), (20251, 3, {"20242": 1, "20243": 1, "20251": 1})]:
        state, specialty, meta = load_frozen_history(cutoff, root=tmp_path)
        assert state.global_sums["raw_count"] == count
        assert meta["source_row_count"] == count
        assert meta["source_part_counts"] == part_counts
        assert meta["source_max_part"] == cutoff
        assert specialty is None
    with pytest.raises(FileExistsError):
        save_history(tmp_path)
    assert before == {p.name: file_sha256(p) for p in directory.iterdir()}


def test_target_outcomes_and_end_gpa_do_not_change_history():
    first = build_frozen_history(outcomes(), 20243, finalized_through_part=20243)
    poisoned = outcomes()
    poisoned.loc[poisoned.part_id.ge(20251), "final_mark"] = float("nan")
    poisoned["end_agpa_points"] = -999.0
    second = build_frozen_history(poisoned, 20243, finalized_through_part=20243)
    assert first[0].global_sums == second[0].global_sums
    assert first[2] == second[2]
    for name in first[0].tables:
        assert_frame_equal(first[0].tables[name], second[0].tables[name])


@pytest.mark.parametrize("target,cutoff,allowed", [(20251, 20243, True), (20252, 20251, True), (20251, 20251, False), (20252, 20252, False)])
def test_required_cutoff_contract(target, cutoff, allowed):
    if allowed:
        assert validate_history_selection(target, cutoff)["history_is_previous_part"]
    else:
        with pytest.raises(ValueError, match="forbidden"):
            validate_history_selection(target, cutoff)


@pytest.mark.parametrize("cutoff,expected_count,source_count", [(20243, 2, 1), (20251, 3, 2)])
def test_cli_defaults_to_canonical_sources_and_saves_source_hashes(tmp_path, monkeypatch, cutoff, expected_count, source_count):
    train = tmp_path / "temporal_train_features.parquet"
    test = tmp_path / "temporal_test_features.parquet"
    source = outcomes()
    # Canonical sources attest the feature contract.
    source.loc[source.part_id.le(20243)].to_parquet(train)
    source.loc[source.part_id.ge(20251)].to_parquet(test)
    monkeypatch.setattr(cli, "TEMPORAL_TRAIN_FEATURES_PATH", train, raising=False)
    monkeypatch.setattr(cli, "TEMPORAL_TEST_FEATURES_PATH", test, raising=False)
    root = tmp_path / "history"
    monkeypatch.setattr(cli, "FROZEN_HISTORY_DIR", root, raising=False)
    cli.main(["--as-of-part", str(cutoff), "--finalized-through-part", str(cutoff)])
    _, _, meta = load_frozen_history(cutoff, root=root)
    assert meta["source_row_count"] == expected_count
    assert len(meta["sources"]) == source_count
    for signature in meta["sources"]:
        assert not Path(signature["path"]).is_absolute()
        assert signature["sha256"] == file_sha256(tmp_path / signature["path"])
    assert not (root / f"as_of_{cutoff}" / "specialty_history_state.pkl").exists()


@pytest.mark.parametrize("filename", ["finalized_outcomes.parquet", "export.parquet"])
def test_cli_accepts_custom_source_by_contract_without_filename_label(tmp_path, filename):
    source_path = tmp_path / "outcomes.parquet"
    outcomes().to_parquet(source_path)
    root = tmp_path / "history"
    cli.main(["--as-of-part", "20243", "--finalized-through-part", "20243",
              "--sources", str(source_path), "--history-root", str(root)])
    state, specialty, meta = load_frozen_history(20243, root=root)
    assert state.global_sums["raw_count"] == 2
    assert specialty is None
    assert meta["sources"] == [{"path": filename, "sha256": file_sha256(source_path)}]


def test_cli_rejects_custom_source_missing_required_history_columns(tmp_path):
    source = outcomes().drop(columns="student_course_id")
    source_path = tmp_path / "outcomes.parquet"
    source.to_parquet(source_path)
    root = tmp_path / "history"
    with pytest.raises(SystemExit) as error:
        cli.main(["--as-of-part", "20243", "--finalized-through-part", "20243", "--sources", str(source_path), "--history-root", str(root)])
    assert error.value.code == 2
    assert not root.exists()
