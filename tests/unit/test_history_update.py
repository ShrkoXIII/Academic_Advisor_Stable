"""Synthetic aggregate updates over weighted history; no real serving runs."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib
import importlib.util
import json
from threading import Event

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from src.features import frozen_history as frozen
from src.features.temporal_features import CourseHistoryState, HISTORY_SUM_COLUMNS


def api():
    assert importlib.util.find_spec("src.recommendation.history_update") is not None, "Phase 3 aggregate history API is missing"
    return importlib.import_module("src.recommendation.history_update")


def delta(part=20251):
    return {"delta_part": part, "finalized": True, "aggregates": [
        {"degree_id": "D", "course_id": "A", "faculty_id": "F",
         "plan_requirement_type_id": "R", "course_credits": 2.5,
         "count": 2, "fail_count": 1, "retake_count": 1,
         "mark_sum": 120, "attempt_sum": 3},
        {"degree_id": "E", "course_id": "B", "faculty_id": "G",
         "plan_requirement_type_id": "S", "course_credits": 0,
         "count": 1, "fail_count": 0, "retake_count": 0,
         "mark_sum": 80, "attempt_sum": 1},
    ]}


def weighted_state():
    state = CourseHistoryState()
    state.update(pd.DataFrame({
        "part_id": [20211, 20243], "degree_id": ["D", "D"],
        "course_id": ["A", "A"], "faculty_id": ["F", "F"],
        "plan_requirement_type_id": ["R", "R"], "course_credits": [2.5, 2.5],
        "attempt_number": [2, 1], "final_mark": [40, 60],
    }))
    return state


def save_initial(root, part=20243):
    state = weighted_state()
    state.as_of_part = part
    frozen.save_frozen_history(state, None, {
        "dataset_version": "V2", "source_min_part": 20211,
        "source_max_part": part, "source_row_count": 2,
        "source_part_counts": {"20211": 1, str(part): 1},
        "finalized_through_part": part,
    }, root=root)
    return state


def hashes(root):
    return {p.relative_to(root).as_posix(): frozen.file_sha256(p) for p in root.rglob("*") if p.is_file()}


def targets(part=20252):
    return pd.DataFrame({
        "part_id": [part] * 6, "degree_id": ["D", "X", "D", "X", "X", "X"],
        "course_id": ["A", "A", "C", "C", "C", "C"],
        "faculty_id": ["F", "F", "X", "F", "X", "X"],
        "plan_requirement_type_id": ["R", "R", "R", "R", "R", "X"],
        "course_credits": [2.5, 2.5, 2.5, 2.5, 2.5, 7],
    })


def test_aggregate_addition_preserves_weighted_prefix_and_matches_raw_oracle():
    module = api()
    old = weighted_state()
    before = deepcopy(old)
    updated = module.apply_history_delta(old, delta())
    assert updated.global_sums == {
        "effective_support": 4.25, "raw_count": 5.0, "mark_sum": 270.0,
        "fail_sum": 1.25, "attempt_sum": 5.5, "retake_sum": 1.25,
    }
    assert old.global_sums == before.global_sums
    assert (old.as_of_part, updated.as_of_part) == (20243, 20251)
    assert updated.smoothing_k == updated.min_support == 20
    for level in old.tables:
        assert_frame_equal(old.tables[level], before.tables[level])
    # Independent raw-outcome oracle for the same three new attempts.
    oracle = deepcopy(old)
    oracle.update(pd.DataFrame({
        "part_id": [20251] * 3, "degree_id": ["D", "D", "E"],
        "course_id": ["A", "A", "B"], "faculty_id": ["F", "F", "G"],
        "plan_requirement_type_id": ["R", "R", "S"], "course_credits": [2.5, 2.5, 0],
        "attempt_number": [1, 2, 1], "final_mark": [40, 80, 80],
    }))
    assert_frame_equal(updated.apply(targets()), oracle.apply(targets()))
    assert updated.apply(targets()).course_history_fallback_level.tolist() == [1, 2, 3, 4, 5, 6]
    assert updated.tables[3].loc["D||R||2", "effective_support"] == 3.25


def test_delta_identity_is_canonical_and_state_bytes_are_deterministic(tmp_path):
    module = api()
    first = delta()
    second = deepcopy(first)
    second["delta_part"] = "20251.0"
    second["aggregates"].reverse()
    for row in second["aggregates"]:
        for key in ("count", "fail_count", "retake_count", "mark_sum", "attempt_sum", "course_credits"):
            row[key] = str(float(row[key]))
        row["course_id"] = " " + row["course_id"] + " "
    a, b = module.normalize_history_delta(first), module.normalize_history_delta(second)
    assert a.delta_sha256 == b.delta_sha256
    assert first == delta()
    for label, payload in [("a", first), ("b", second)]:
        state = module.apply_history_delta(weighted_state(), payload)
        frozen.save_frozen_history(state, None, {
            "source_max_part": 20251, "finalized_through_part": 20251,
            "dataset_version": "V2",
        }, root=tmp_path / label)
    assert frozen.file_sha256(tmp_path / "a/as_of_20251/course_history_state.pkl") == frozen.file_sha256(tmp_path / "b/as_of_20251/course_history_state.pkl")
    changed = deepcopy(first)
    changed["aggregates"][0]["mark_sum"] = 121
    assert module.normalize_history_delta(changed).delta_sha256 != a.delta_sha256


@pytest.mark.parametrize("field,value", [
    ("count", 0), ("count", 1.5), ("count", True), ("count", "1e400"),
    ("fail_count", -1), ("fail_count", 3), ("fail_count", 0.5),
    ("retake_count", 3), ("retake_count", -1),
    ("mark_sum", -1), ("mark_sum", 201), ("mark_sum", float("nan")),
    ("attempt_sum", 1), ("attempt_sum", 2.5), ("attempt_sum", float("inf")),
    ("attempt_sum", 2), ("course_credits", -1), ("course_credits", "1e400"),
    ("degree_id", None), ("course_id", ""), ("faculty_id", "X||Y"),
])
def test_invalid_aggregate_is_rejected_without_mutating_prefix(field, value):
    module = api()
    payload = delta()
    payload["aggregates"][0][field] = value
    state = weighted_state()
    before = deepcopy(state)
    with pytest.raises(ValueError):
        module.apply_history_delta(state, payload)
    assert state.global_sums == before.global_sums
    for level in state.tables:
        assert_frame_equal(state.tables[level], before.tables[level])


@pytest.mark.parametrize("change", ["not_finalized", "wrong_part", "missing_sum", "duplicate", "old_weight", "not_rows"])
def test_delta_contract_validation(change):
    module = api()
    payload = delta()
    if change == "not_finalized":
        payload["finalized"] = False
    elif change == "wrong_part":
        payload["aggregates"][0]["part_id"] = 20252
    elif change == "missing_sum":
        del payload["aggregates"][0]["mark_sum"]
    elif change == "duplicate":
        payload["aggregates"].append(deepcopy(payload["aggregates"][0]))
    elif change == "old_weight":
        payload["delta_part"] = 20211
    else:
        payload["aggregates"] = {}
    with pytest.raises(ValueError):
        module.normalize_history_delta(payload)


def test_numeric_ids_normalize_to_existing_history_keys():
    module = api()
    payload = delta()
    payload["aggregates"][0].update(degree_id="123.00", course_id=456.0)
    state = module.apply_history_delta(weighted_state(), payload)
    assert state.tables[1].loc["123||456", "raw_count"] == 2


def test_empty_finalized_semester_advances_without_changing_sums():
    module = api()
    old = weighted_state()
    new = module.apply_history_delta(old, {"delta_part": 20251, "finalized": True, "aggregates": []})
    assert new.as_of_part == 20251
    assert new.global_sums == old.global_sums
    assert_frame_equal(new.apply(targets()), old.apply(targets()))


def test_update_publishes_verified_immutable_bundle_and_lineage(tmp_path):
    module = api()
    save_initial(tmp_path)
    before = hashes(tmp_path)
    manager = module.FrozenHistoryManager.load(root=tmp_path)
    old = manager.capture(target_part=20252)
    old_features = old.apply(targets())
    result = manager.update_history_from_payload(history_payload=delta())
    assert result["status"] == "applied"
    current = manager.capture(target_part=20252)
    assert old.as_of_part == 20243 and current.as_of_part == 20251
    assert_frame_equal(old.apply(targets()), old_features)
    loaded, _, meta = frozen.load_frozen_history(20251, root=tmp_path, dataset_version="V2")
    assert loaded.global_sums["raw_count"] == 5
    assert meta["previous_as_of_part"] == 20243
    assert meta["previous_history_sha256"] == before["as_of_20243/course_history_state.pkl"]
    assert meta["new_history_sha256"] == frozen.file_sha256(tmp_path / "as_of_20251/course_history_state.pkl")
    assert meta["delta_sha256"] == result["delta_sha256"]
    assert meta["created_at"] and meta["feature_engineering_version"] == 2
    assert meta["source_row_count"] == 5 and meta["source_part_counts"]["20251"] == 3
    assert current.metadata["directory"] == str((tmp_path / "as_of_20251").resolve())
    assert all(hashes(tmp_path)[name] == digest for name, digest in before.items())
    assert not list(tmp_path.glob(".history-staging-*"))


def test_same_delta_after_newer_update_and_restart_never_rolls_back(tmp_path):
    module = api()
    save_initial(tmp_path)
    manager = module.FrozenHistoryManager.load(root=tmp_path)
    manager.update_history_from_payload(history_payload=delta())
    manager.update_history_from_payload(history_payload=delta(20252))
    before = hashes(tmp_path)
    restarted = module.FrozenHistoryManager.load(root=tmp_path)
    active = restarted.capture(target_part=20253)
    for part in [20251, 20252]:
        assert restarted.update_history_from_payload(history_payload=delta(part))["status"] == "already_applied"
        assert restarted.capture(target_part=20253) is active
    assert hashes(tmp_path) == before
    conflicting = delta()
    conflicting["aggregates"][0]["mark_sum"] = 121
    with pytest.raises(ValueError, match="CONFLICT"):
        restarted.update_history_from_payload(history_payload=conflicting)
    assert restarted.capture(target_part=20253) is active


def test_older_unrecorded_delta_is_rejected(tmp_path):
    module = api()
    save_initial(tmp_path, part=20252)
    manager = module.FrozenHistoryManager.load(root=tmp_path)
    before = hashes(tmp_path)
    with pytest.raises(ValueError, match="out.of.order"):
        manager.update_history_from_payload(history_payload=delta())
    assert hashes(tmp_path) == before


@pytest.mark.parametrize("target", [20251, 20252, 20253, 20262])
def test_serving_accepts_older_history_without_changing_backtesting_rule(tmp_path, target):
    module = api()
    save_initial(tmp_path)
    manager = module.FrozenHistoryManager.load(root=tmp_path)
    snapshot = manager.capture(target_part=target)
    assert snapshot.as_of_part == 20243
    provenance = snapshot.metadata_for_target(target)
    assert provenance["history_as_of_part"] == 20243
    assert provenance["target_part"] == target
    assert provenance["history_is_stale"] is (target != 20251)
    assert provenance["artifact_sha256"] == snapshot.metadata["artifact_sha256"]
    if target != 20251:
        with pytest.raises(ValueError, match="older"):
            frozen.validate_history_selection(target, 20243)


@pytest.mark.parametrize("target", [20243, 20242, 20211])
def test_serving_forbids_current_or_future_history(tmp_path, target):
    module = api()
    save_initial(tmp_path)
    with pytest.raises(ValueError, match="forbidden"):
        module.FrozenHistoryManager.load(root=tmp_path).capture(target_part=target)


def test_snapshot_metadata_is_not_shared_mutable_state(tmp_path):
    module = api()
    save_initial(tmp_path)
    manager = module.FrozenHistoryManager.load(root=tmp_path)
    snapshot = manager.capture(target_part=20252)
    meta = snapshot.metadata
    meta["as_of_part"] = 99999
    meta["artifact_sha256"]["course_history_state.pkl"] = "poison"
    assert snapshot.metadata["as_of_part"] == 20243
    assert snapshot.metadata["artifact_sha256"]["course_history_state.pkl"] != "poison"


@pytest.mark.parametrize("failure", ["save", "reload", "corrupt", "publish"])
def test_failed_update_keeps_active_snapshot_and_old_bundle(tmp_path, monkeypatch, failure):
    module = api()
    save_initial(tmp_path)
    manager = module.FrozenHistoryManager.load(root=tmp_path)
    snapshot = manager.capture(target_part=20252)
    before = hashes(tmp_path)
    original_save = frozen.save_frozen_history
    original_load = frozen.load_frozen_history

    def broken_save(*args, **kwargs):
        if failure == "save":
            raise OSError("synthetic failed save")
        result = original_save(*args, **kwargs)
        if failure == "corrupt":
            path = kwargs["root"] / "as_of_20251/course_history_state.pkl"
            path.write_bytes(path.read_bytes() + b"corrupt")
        return result

    def broken_load(*args, **kwargs):
        if failure == "reload" and args[0] == 20251:
            raise OSError("synthetic failed reload")
        return original_load(*args, **kwargs)

    monkeypatch.setattr(frozen, "save_frozen_history", broken_save)
    monkeypatch.setattr(frozen, "load_frozen_history", broken_load)
    if failure == "publish":
        def broken_rename(*args, **kwargs):
            raise OSError("synthetic failed publish")
        monkeypatch.setattr(type(tmp_path), "rename", broken_rename)
    with pytest.raises((OSError, ValueError)):
        manager.update_history_from_payload(history_payload=delta())
    assert manager.capture(target_part=20252) is snapshot
    assert hashes(tmp_path) == before
    assert not (tmp_path / "as_of_20251").exists()
    assert not list(tmp_path.glob(".history-staging-*"))


def test_existing_destination_is_never_overwritten_even_if_incomplete(tmp_path):
    module = api()
    save_initial(tmp_path)
    manager = module.FrozenHistoryManager.load(root=tmp_path)
    (tmp_path / "as_of_20251").mkdir()
    before = hashes(tmp_path)
    with pytest.raises(FileExistsError):
        manager.update_history_from_payload(history_payload=delta())
    assert manager.capture(target_part=20252).as_of_part == 20243
    assert hashes(tmp_path) == before


def test_latest_valid_load_skips_incomplete_corrupt_and_wrong_version(tmp_path):
    module = api()
    save_initial(tmp_path)
    save_initial(tmp_path, part=20251)
    (tmp_path / "as_of_20252").mkdir()
    save_initial(tmp_path, part=20253)
    (tmp_path / "as_of_20253/course_history_state.pkl").write_bytes(b"bad pickle bytes")
    save_initial(tmp_path, part=20261)
    path = tmp_path / "as_of_20261/metadata.json"
    metadata = json.loads(path.read_text())
    metadata["dataset_version"] = "V1"
    path.write_text(json.dumps(metadata))
    manager = module.FrozenHistoryManager.load(root=tmp_path)
    assert manager.capture(target_part=20262).as_of_part == 20251
    assert len(manager.skipped_bundles) == 3


def test_missing_history_never_rebuilds_or_falls_back(tmp_path):
    module = api()
    with pytest.raises(FileNotFoundError):
        module.FrozenHistoryManager.load(root=tmp_path)
    assert not list(tmp_path.iterdir())


def test_concurrent_reader_keeps_one_snapshot_while_update_publishes(tmp_path, monkeypatch):
    module = api()
    save_initial(tmp_path)
    manager = module.FrozenHistoryManager.load(root=tmp_path)
    old = manager.capture(target_part=20252)
    before = old.apply(targets())
    ready, resume = Event(), Event()
    original = frozen.save_frozen_history

    def paused_save(*args, **kwargs):
        result = original(*args, **kwargs)
        ready.set()
        assert resume.wait(10)
        return result

    monkeypatch.setattr(frozen, "save_frozen_history", paused_save)
    with ThreadPoolExecutor(max_workers=1) as pool:
        job = pool.submit(manager.update_history_from_payload, history_payload=delta())
        try:
            assert ready.wait(10)
            assert manager.capture(target_part=20252) is old
            assert not (tmp_path / "as_of_20251").exists()
            assert_frame_equal(old.apply(targets()), before)
        finally:
            resume.set()
        assert job.result(timeout=10)["status"] == "applied"
    assert manager.capture(target_part=20252).as_of_part == 20251
    assert_frame_equal(old.apply(targets()), before)
    assert not manager.capture(target_part=20252).apply(targets()).equals(before)


def test_concurrent_same_delta_adds_only_once(tmp_path):
    module = api()
    save_initial(tmp_path)
    manager = module.FrozenHistoryManager.load(root=tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: manager.update_history_from_payload(history_payload=delta()), range(2)))
    assert sorted(r["status"] for r in results) == ["already_applied", "applied"]
    loaded, _, _ = frozen.load_frozen_history(20251, root=tmp_path, dataset_version="V2")
    assert loaded.global_sums["raw_count"] == 5


@pytest.mark.parametrize("corruption", ["global", "table", "config", "cutoff"])
def test_structurally_invalid_state_is_rejected(corruption):
    module = api()
    state = weighted_state()
    if corruption == "global":
        state.global_sums["mark_sum"] = float("inf")
    elif corruption == "table":
        state.tables[1].loc["D||A", "raw_count"] += 1
    elif corruption == "config":
        state.smoothing_k = 1
    else:
        state.as_of_part = None
    with pytest.raises(ValueError):
        module.apply_history_delta(state, delta())


def test_unreadable_pickle_with_matching_hash_is_skipped(tmp_path):
    module = api()
    save_initial(tmp_path)
    save_initial(tmp_path, part=20251)
    state = tmp_path / "as_of_20251/course_history_state.pkl"
    state.write_bytes(b"not a valid pickle")
    path = tmp_path / "as_of_20251/metadata.json"
    metadata = json.loads(path.read_text())
    metadata["artifact_sha256"][state.name] = frozen.file_sha256(state)
    path.write_text(json.dumps(metadata))
    manager = module.FrozenHistoryManager.load(root=tmp_path)
    assert manager.capture(target_part=20252).as_of_part == 20243
    assert len(manager.skipped_bundles) == 1


@pytest.mark.parametrize("cleanup", ["guard", "staging"])
def test_cleanup_failure_after_publication_does_not_report_failed_update(tmp_path, monkeypatch, cleanup):
    module = api()
    save_initial(tmp_path)
    manager = module.FrozenHistoryManager.load(root=tmp_path)
    original_unlink = type(tmp_path).unlink

    def failing_unlink(path, *args, **kwargs):
        if path.name == ".publish_as_of_20251.lock":
            raise OSError("synthetic cleanup failure")
        return original_unlink(path, *args, **kwargs)

    if cleanup == "guard":
        monkeypatch.setattr(type(tmp_path), "unlink", failing_unlink)
    else:
        def failing_cleanup(self):
            raise OSError("synthetic staging cleanup failure")
        monkeypatch.setattr(frozen.TemporaryDirectory, "cleanup", failing_cleanup)
    result = manager.update_history_from_payload(history_payload=delta())
    assert result["status"] == "applied"
    assert manager.capture(target_part=20252).as_of_part == 20251
    assert result["cleanup_warnings"]
    loaded, _, _ = frozen.load_frozen_history(20251, root=tmp_path, dataset_version="V2")
    assert loaded.global_sums["raw_count"] == 5


def test_update_uses_normalized_delta_even_if_callers_payload_changes(tmp_path, monkeypatch):
    module = api()
    save_initial(tmp_path)
    manager = module.FrozenHistoryManager.load(root=tmp_path)
    payload = delta()
    original_normalize = module.normalize_history_delta

    def normalize_then_mutate(value):
        normalized = original_normalize(value)
        payload["aggregates"][0]["mark_sum"] = 121
        return normalized

    monkeypatch.setattr(module, "normalize_history_delta", normalize_then_mutate)
    result = manager.update_history_from_payload(history_payload=payload)
    loaded, _, meta = frozen.load_frozen_history(20251, root=tmp_path, dataset_version="V2")
    assert loaded.global_sums["mark_sum"] == 270
    assert meta["delta_sha256"] == original_normalize(delta()).delta_sha256 == result["delta_sha256"]


def test_two_managers_cannot_replace_a_published_version(tmp_path):
    module = api()
    save_initial(tmp_path)
    first = module.FrozenHistoryManager.load(root=tmp_path)
    second = module.FrozenHistoryManager.load(root=tmp_path)
    first.update_history_from_payload(history_payload=delta())
    before = hashes(tmp_path)
    with pytest.raises(FileExistsError):
        second.update_history_from_payload(history_payload=delta())
    assert second.capture(target_part=20252).as_of_part == 20243
    assert hashes(tmp_path) == before


def test_bad_lineage_is_not_selected_on_restart(tmp_path):
    module = api()
    save_initial(tmp_path)
    module.FrozenHistoryManager.load(root=tmp_path).update_history_from_payload(history_payload=delta())
    path = tmp_path / "as_of_20251/metadata.json"
    metadata = json.loads(path.read_text())
    metadata["applied_deltas"]["20251"] = "a" * 64
    path.write_text(json.dumps(metadata))
    manager = module.FrozenHistoryManager.load(root=tmp_path)
    assert manager.capture(target_part=20252).as_of_part == 20243
    assert len(manager.skipped_bundles) == 1


def test_distinct_full_credit_grains_reuse_existing_rounded_history_groups():
    module = api()
    payload = delta()
    row = dict(payload["aggregates"][0], count=1, fail_count=0, retake_count=0,
               mark_sum=60, attempt_sum=1)
    payload["aggregates"] = [
        dict(row, course_credits=credits) for credits in ("2.4", "2.5", "3")
    ] + [dict(row, course_credits="3", plan_requirement_type_id="S")]
    normalized = module.normalize_history_delta(payload)
    assert len(normalized.rows) == 4
    updated = module.apply_history_delta(weighted_state(), payload)
    # Full credits distinguish incoming grains; the established feature keys
    # pool 2.4 and 2.5 through pandas rounding, while retaining requirement IDs.
    assert updated.tables[1].loc["D||A", "raw_count"] == 6
    assert updated.tables[2].loc["A", "raw_count"] == 6
    for level, prefix in ((3, "D||"), (4, "F||"), (5, "")):
        table = updated.tables[level]
        assert table.loc[prefix + "R||2", "raw_count"] == 4
        assert table.loc[prefix + "R||3", "raw_count"] == 1
        assert table.loc[prefix + "S||3", "raw_count"] == 1
    assert updated.global_sums["raw_count"] == 6


def test_equivalent_credit_representations_are_duplicate_delta_grains():
    payload = delta()
    payload["aggregates"].append(dict(payload["aggregates"][0], course_credits="2.500"))
    with pytest.raises(ValueError, match="Duplicate normalized aggregate grain"):
        api().normalize_history_delta(payload)


@pytest.mark.parametrize("statistic", ["count", "attempt_sum"])
def test_integer_statistics_above_float64_exact_range_are_rejected(statistic):
    payload = delta()
    row = dict(payload["aggregates"][0], count=1, mark_sum=60,
               fail_count=0, retake_count=1, attempt_sum=2)
    if statistic == "count":
        row.update(count=2**53 + 1, mark_sum=50 * (2**53 + 1),
                   retake_count=0, attempt_sum=2**53 + 1)
    else:
        row["attempt_sum"] = 2**53 + 1
    payload["aggregates"] = [row]
    with pytest.raises(ValueError, match="exact"):
        api().normalize_history_delta(payload)


def test_float64_exact_integer_boundary_is_preserved_in_normalized_frame():
    payload = delta()
    payload["aggregates"] = [dict(payload["aggregates"][0], count=2**53,
                                  mark_sum=50 * 2**53, fail_count=0,
                                  retake_count=0, attempt_sum=2**53)]
    normalized = api().normalize_history_delta(payload)
    frame = normalized.to_frame()
    assert normalized.rows[0][5] == str(2**53)
    assert int(frame.iloc[0]["count"]) == int(frame.iloc[0]["attempt_sum"]) == 2**53


def test_aggregate_addition_rejects_weight_loss_in_affected_table_group():
    state = CourseHistoryState()
    state.update(pd.DataFrame([
        {"part_id": 20211, "degree_id": "D", "course_id": course, "faculty_id": "F",
         "plan_requirement_type_id": "R", "course_credits": 3,
         "attempt_number": 1, "final_mark": 80} for course in ("A", "B", "C", "D")
    ]))
    state.as_of_part = 20243
    before = deepcopy(state)
    payload = delta()
    payload["aggregates"] = [dict(payload["aggregates"][0], course_credits=3,
                                  count=2**51, mark_sum=50 * 2**51,
                                  fail_count=0, retake_count=0, attempt_sum=2**51)]
    # Global support is an exact integer; the affected course still has its
    # quarter-weight prefix, which float64 would lose when adding this delta.
    assert state.global_sums["effective_support"] == 1
    assert state.tables[1].loc["D||A", "effective_support"] == .25
    with pytest.raises(ValueError, match="exact"):
        api().apply_history_delta(state, payload)
    assert state.global_sums == before.global_sums
    for level in state.tables:
        assert_frame_equal(state.tables[level], before.tables[level])
