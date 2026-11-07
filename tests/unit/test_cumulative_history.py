"""Synthetic cumulative history administration; never touch serving data."""
from copy import deepcopy
import json
import importlib
import importlib.util
from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys
from threading import Event

import pandas as pd
from pandas.testing import assert_frame_equal
import pytest

from src.features.frozen_history import file_sha256, save_frozen_history, load_frozen_history
from src.features.temporal_features import CourseHistoryState


def module():
    assert importlib.util.find_spec("src.recommendation.cumulative_history") is not None
    return importlib.import_module("src.recommendation.cumulative_history")


def source(root, *, cutoff=20251, cumulative=True):
    state = CourseHistoryState()
    outcomes = [(20211, 1, 80), (20243, 2, 40), (cutoff, 1, 70)] if cumulative else [(cutoff, 1, 70)]
    state.update(pd.DataFrame([
        {"part_id": part, "degree_id": "D", "course_id": "C", "faculty_id": "F",
         "plan_requirement_type_id": "R", "course_credits": 3,
         "attempt_number": attempt, "final_mark": mark}
        for part, attempt, mark in outcomes
    ]))
    counts = {str(part): sum(p == part for p, _, _ in outcomes) for part, _, _ in outcomes}
    save_frozen_history(state, None, {
        "dataset_version": "V2", "source_min_part": min(p for p, _, _ in outcomes), "source_max_part": cutoff,
        "source_row_count": len(outcomes), "source_part_counts": counts,
        "finalized_through_part": cutoff,
    }, root=root)
    return state, file_sha256(root / f"as_of_{cutoff}/metadata.json")


def payload(part=20252):
    return {"delta_part": part, "finalized": True, "aggregates": [
        {"part_id": part, "degree_id": "D", "course_id": "C", "faculty_id": "F",
         "plan_requirement_type_id": "R", "course_credits": 3, "count": 2,
         "mark_sum": 120, "fail_count": 1, "attempt_sum": 3, "retake_count": 1},
    ]}


def initialize(tmp_path, **kwargs):
    old = tmp_path / "old"
    baseline, digest = source(old)
    kwargs.setdefault("compatibility_check", lambda state, metadata: True)
    store = module().CumulativeHistoryStore(tmp_path / "incremental", **kwargs)
    store.initialize(source_root=old, expected_source_hash=digest,
                     approval_reference="synthetic-approved-prefix",
                     cumulative_history_confirmed=True, confirmation=True)
    return store, baseline, old


def commit(store, data):
    preview = store.preview(history_payload=data)
    result = store.commit(history_payload=data, preview_sha256=preview["preview_sha256"],
                          confirmation=True, approval_reference="synthetic-admin-approval")
    return result


def activate(store, result):
    return store.activate(cutoff=result["history_as_of_part"],
                          expected_history_sha256=result["new_history_sha256"], confirmation=True)


def test_lazy_defaults_and_persistent_modes(tmp_path):
    root = tmp_path / "missing"
    store = module().CumulativeHistoryStore(root)
    assert not root.exists()
    assert store.status()["update_mode"] == "manual"
    assert not root.exists()
    store.set_mode("disabled")
    assert module().CumulativeHistoryStore(root).status()["update_mode"] == "disabled"
    with pytest.raises(ValueError, match="mode"):
        store.set_mode("sometimes")


def test_approved_initialization_preserves_full_weighted_history_and_source(tmp_path):
    store, baseline, old = initialize(tmp_path)
    loaded, _, metadata = load_frozen_history(20251, root=store.root, dataset_version="V2")
    assert loaded.global_sums == baseline.global_sums
    assert loaded.global_sums["raw_count"] == 3
    assert loaded.global_sums["effective_support"] == 2.25
    assert metadata["baseline_completeness"] == "admin_attested"
    assert "baseline_approval_reference" not in metadata
    assert metadata["baseline_source_metadata_sha256"] == file_sha256(old / "as_of_20251/metadata.json")
    assert metadata["artifact_sha256"]["course_history_state.pkl"] == file_sha256(old / "as_of_20251/course_history_state.pkl")
    assert store.status()["active_historical_cutoff"] == 20251
    for level in baseline.tables:
        assert_frame_equal(loaded.tables[level], baseline.tables[level])


@pytest.mark.parametrize("change", ["hash", "approval", "cumulative", "cutoff"])
def test_initialization_requires_exact_approved_cumulative_prefix(tmp_path, change):
    old = tmp_path / "old"
    _, digest = source(old, cutoff=20243 if change == "cutoff" else 20251)
    store = module().CumulativeHistoryStore(tmp_path / "new", compatibility_check=lambda state, metadata: True)
    with pytest.raises((ValueError, FileNotFoundError)):
        store.initialize(source_root=old, expected_source_hash="0" * 64 if change == "hash" else digest,
                         approval_reference="" if change == "approval" else "approved",
                         cumulative_history_confirmed=change != "cumulative", confirmation=True)
    assert store.status()["active_historical_cutoff"] is None


def test_preview_commit_activation_separate_and_sequential_raw_equivalence(tmp_path):
    store, oracle, _ = initialize(tmp_path)
    for part in (20252, 20253, 20261):
        data = payload(part)
        preview = store.preview(history_payload=data)
        assert not (store.root / f"as_of_{part}").exists()
        prior = store.status()["active_historical_cutoff"]
        result = store.commit(history_payload=data, preview_sha256=preview["preview_sha256"],
                              confirmation=True, approval_reference="approval")
        assert store.status()["active_historical_cutoff"] == prior
        oracle.update(pd.DataFrame([
            {"part_id": part, "degree_id": "D", "course_id": "C", "faculty_id": "F",
             "plan_requirement_type_id": "R", "course_credits": 3,
             "attempt_number": attempt, "final_mark": mark}
            for attempt, mark in [(1, 40), (2, 80)]
        ]))
        saved, _, _ = load_frozen_history(part, root=store.root, dataset_version="V2")
        assert saved.global_sums == oracle.global_sums
        for level in oracle.tables:
            assert_frame_equal(saved.tables[level].sort_index(), oracle.tables[level].sort_index())
        activate(store, result)
        assert store.status()["active_historical_cutoff"] == part
    assert store.status()["available_historical_versions"] == [20251, 20252, 20253, 20261]
    with pytest.raises(ValueError, match="target|Target"):
        store.capture(target_part=20261)
    assert store.capture(target_part=20262).as_of_part == 20261


def test_confirmation_binds_hash_and_base_and_prevents_conflicting_replay(tmp_path):
    store, _, _ = initialize(tmp_path)
    data = payload()
    preview = store.preview(history_payload=data)
    with pytest.raises(ValueError, match="confirmation"):
        store.commit(history_payload=data, preview_sha256=preview["preview_sha256"], confirmation=False,
                     approval_reference="approved")
    changed = deepcopy(data)
    changed["aggregates"][0]["mark_sum"] = 121
    with pytest.raises(ValueError, match="preview|Preview"):
        store.commit(history_payload=changed, preview_sha256=preview["preview_sha256"], confirmation=True,
                     approval_reference="approved")
    first = commit(store, data)
    activate(store, first)
    replay = commit(store, data)
    assert replay["status"] == "already_applied"
    with pytest.raises(module().HistoryUpdateError) as conflict:
        store.preview(history_payload=changed)
    assert conflict.value.code == "HISTORY_CONFLICT"
    with pytest.raises(ValueError, match="chronological|next|order"):
        store.preview(history_payload=payload(20261))


def test_manual_automatic_and_disabled_workflows(tmp_path):
    store, _, _ = initialize(tmp_path)
    with pytest.raises(ValueError, match="auto_on_finalization"):
        store.finalize(history_payload=payload(), approval_reference="official", trusted_event=True)
    store.set_mode("auto_on_finalization")
    with pytest.raises(ValueError, match="trusted|approval"):
        store.finalize(history_payload=payload(), approval_reference="official", trusted_event=False)
    with pytest.raises(ValueError, match="approval"):
        store.finalize(history_payload=payload(), approval_reference="", trusted_event=True)
    result = store.finalize(history_payload=payload(), approval_reference="official-finalization", trusted_event=True)
    assert result["status"] == "activated"
    assert store.finalize(history_payload=payload(), approval_reference="official-finalization", trusted_event=True)["status"] == "already_applied"
    store.set_mode("disabled")
    for action in (
        lambda: store.preview(history_payload=payload(20253)),
        lambda: store.commit(history_payload=payload(20253), preview_sha256="0" * 64, confirmation=True, approval_reference="approval"),
        lambda: store.activate(cutoff=20251, expected_history_sha256="0" * 64, confirmation=True),
    ):
        with pytest.raises(ValueError, match="disabled"):
            action()


def test_failed_publication_and_compatibility_preserve_active_history(tmp_path, monkeypatch):
    store, _, _ = initialize(tmp_path)
    import src.recommendation.history_update as updates
    def fail(*args, **kwargs):
        raise OSError("private /credentials/raw source must never reach status")
    monkeypatch.setattr(updates, "save_frozen_history_atomic", fail)
    with pytest.raises(OSError):
        commit(store, payload())
    status = store.status()
    assert status["active_historical_cutoff"] == 20251
    assert status["previous_update_failures"][-1]["code"] == "history_io_failed"
    assert "credentials" not in str(status)
    incompatible = module().CumulativeHistoryStore(store.root, compatibility_check=lambda state, metadata: False)
    assert incompatible.status()["serving_artifacts_compatible"] is False
    with pytest.raises(ValueError, match="compatib"):
        incompatible.preview(history_payload=payload())


def test_rollback_exact_selection_and_reload_do_not_delete_later_versions(tmp_path):
    store, _, _ = initialize(tmp_path)
    result = commit(store, payload())
    activate(store, result)
    baseline_hash = file_sha256(store.root / "as_of_20251/course_history_state.pkl")
    store.activate(cutoff=20251, expected_history_sha256=baseline_hash, confirmation=True, rollback=True)
    reloaded = module().CumulativeHistoryStore(store.root)
    assert reloaded.capture(target_part=20252).as_of_part == 20251
    assert reloaded.capture(target_part=20253, history_as_of_part=20252, allow_older_history=True).as_of_part == 20252
    assert (store.root / "as_of_20252").exists()
    with pytest.raises(FileNotFoundError):
        store.capture(target_part=20262, history_as_of_part=20261)


def test_concurrent_preview_confirmations_do_not_duplicate_version(tmp_path):
    store, _, _ = initialize(tmp_path)
    data = payload()
    preview = store.preview(history_payload=data)
    def worker():
        try:
            other = module().CumulativeHistoryStore(store.root, compatibility_check=lambda state, metadata: True)
            return other.commit(history_payload=data, preview_sha256=preview["preview_sha256"],
                                confirmation=True, approval_reference="approval")["status"]
        except ValueError:
            return "rejected"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert "committed" in results
    assert len(list(store.root.glob("as_of_20252"))) == 1
    assert store.status()["active_historical_cutoff"] == 20251


def test_serving_proxy_pins_requests_and_readonly_validation_preserves_pending(tmp_path):
    store, _, _ = initialize(tmp_path)
    proxy = store.serving_manager()
    from src.recommendation.history_update import FrozenHistoryManager
    assert isinstance(proxy, FrozenHistoryManager)
    pinned = proxy.capture(target_part=20252)
    before = (store.root / "control.json").read_bytes()
    proxy.preview_delta(history_payload=payload())
    assert (store.root / "control.json").read_bytes() == before
    with pytest.raises(module().HistoryUpdateError) as rejected:
        proxy.update_history_from_payload(history_payload=payload())
    assert rejected.value.code == "ADMIN_WORKFLOW_REQUIRED"
    result = commit(store, payload())
    activate(store, result)
    assert pinned.as_of_part == 20251
    assert proxy.capture(target_part=20253).as_of_part == 20252


def test_exact_older_legacy_backtesting_version_remains_accessible(tmp_path):
    legacy = tmp_path / "legacy"
    source(legacy)
    source(legacy, cutoff=20243)
    digest = file_sha256(legacy / "as_of_20251/metadata.json")
    store = module().CumulativeHistoryStore(tmp_path / "new", legacy_root=legacy,
                                           compatibility_check=lambda state, metadata: True)
    store.initialize(source_root=legacy, expected_source_hash=digest, approval_reference="approved",
                     confirmation=True, cumulative_history_confirmed=True)
    with pytest.raises(ValueError, match="older"):
        store.capture(target_part=20253, history_as_of_part=20243, allow_older_history=False)
    snapshot = store.capture(target_part=20253, history_as_of_part=20243, allow_older_history=True)
    assert snapshot.as_of_part == 20243
    assert not (store.root / "as_of_20243").exists()


def test_missing_serving_compatibility_allows_partial_preview_but_blocks_publication(tmp_path):
    store, _, _ = initialize(tmp_path)
    unavailable = module().CumulativeHistoryStore(store.root)
    assert unavailable.status()["serving_compatibility"] == "unavailable"
    preview = unavailable.preview(history_payload=payload())
    assert preview["status"] == "partial"
    with pytest.raises(module().HistoryUpdateError) as error:
        unavailable.commit(history_payload=payload(), preview_token=preview["preview_token"],
                           confirmation=True, approval_reference="approved")
    assert error.value.code == "SERVING_ARTIFACTS_UNAVAILABLE"
    assert not (store.root / "as_of_20252").exists()


def test_activation_hash_and_rollback_confirmation_are_checked(tmp_path):
    store, _, _ = initialize(tmp_path)
    result = commit(store, payload())
    with pytest.raises(module().HistoryUpdateError) as error:
        store.activate(cutoff=20252, expected_history_sha256="0" * 64, confirmation=True)
    assert error.value.code == "HISTORY_CONFLICT"
    assert store.status()["active_as_of_part"] == 20251
    activate(store, result)
    baseline_hash = file_sha256(store.root / "as_of_20251/course_history_state.pkl")
    with pytest.raises(module().HistoryUpdateError) as error:
        store.activate(cutoff=20251, expected_history_sha256=baseline_hash, confirmation=True)
    assert error.value.code == "ROLLBACK_CONFIRMATION_REQUIRED"
    assert store.status()["active_as_of_part"] == 20252


def test_disabled_blocks_initialization_and_overlapping_roots_are_rejected(tmp_path):
    old = tmp_path / "source"
    _, digest = source(old)
    store = module().CumulativeHistoryStore(tmp_path / "new", default_mode="disabled")
    with pytest.raises(module().HistoryUpdateError) as error:
        store.initialize(source_root=old, expected_source_hash=digest, approval_reference="approved",
                         confirmation=True, cumulative_history_confirmed=True)
    assert error.value.code == "HISTORY_DISABLED"
    with pytest.raises(module().HistoryUpdateError) as error:
        module().CumulativeHistoryStore(old / "incremental", legacy_root=old)
    assert error.value.code == "HISTORY_ROOT_OVERLAP"


def test_cross_process_lock_is_exclusive_and_released_on_process_exit(tmp_path):
    root = tmp_path / "workflow"
    child_script = (
        "import sys,time; from src.recommendation.cumulative_history import CumulativeHistoryStore; "
        "store=CumulativeHistoryStore(sys.argv[1]); "
        "guard=store._locked(); guard.__enter__(); print('locked',flush=True); time.sleep(2)"
    )
    process = subprocess.Popen([sys.executable, "-c", child_script, str(root)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "locked"
        store = module().CumulativeHistoryStore(root)
        with pytest.raises(module().HistoryUpdateError) as error:
            store.set_mode("disabled")
        assert error.value.code == "HISTORY_LOCK_BUSY"
        process.wait(timeout=10)
        assert process.returncode == 0
        assert store.set_mode("disabled")["mode"] == "disabled"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def test_single_semester_baseline_cannot_be_misrepresented_as_cumulative(tmp_path):
    old = tmp_path / "source"
    _, digest = source(old, cumulative=False)
    store = module().CumulativeHistoryStore(tmp_path / "new", compatibility_check=lambda state, metadata: True)
    with pytest.raises(module().HistoryUpdateError) as error:
        store.initialize(source_root=old, expected_source_hash=digest, approval_reference="approved",
                         confirmation=True, cumulative_history_confirmed=True)
    assert error.value.code == "BASELINE_NOT_CUMULATIVE"
    assert not (store.root / "as_of_20251").exists()


def test_specialty_requirement_and_missing_points_are_not_fabricated(tmp_path):
    def specialty_required(state, metadata):
        raise ValueError("SPECIALTY_HISTORY_AGGREGATES_UNAVAILABLE")
    old = tmp_path / "source"
    _, digest = source(old)
    before = {p.name: file_sha256(p) for p in (old / "as_of_20251").iterdir()}
    store = module().CumulativeHistoryStore(tmp_path / "new", compatibility_check=specialty_required)
    with pytest.raises(module().HistoryUpdateError) as error:
        store.initialize(source_root=old, expected_source_hash=digest, approval_reference="approved",
                         confirmation=True, cumulative_history_confirmed=True)
    assert error.value.code == "SPECIALTY_HISTORY_AGGREGATES_UNAVAILABLE"
    assert not (store.root / "as_of_20251").exists()
    assert before == {p.name: file_sha256(p) for p in (old / "as_of_20251").iterdir()}


def test_corrupted_control_or_active_hash_never_selects_a_different_version(tmp_path):
    store, _, _ = initialize(tmp_path)
    result = commit(store, payload())
    activate(store, result)
    control_path = store.root / "control.json"
    saved = json.loads(control_path.read_text(encoding="utf-8"))
    saved["active"]["history_sha256"] = "0" * 64
    control_path.write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(module().HistoryUpdateError) as error:
        store.capture(target_part=20253)
    assert error.value.code == "HISTORY_CONFLICT"
    with pytest.raises(module().HistoryUpdateError) as error:
        store.serving_manager()
    assert error.value.code == "HISTORY_CONFLICT"
    assert store.status()["active_as_of_part"] == 20252
    assert store.status()["serving_artifacts_compatible"] is False
    control_path.write_text('{"format_version": 999, "mode": "manual"}', encoding="utf-8")
    with pytest.raises(module().HistoryUpdateError) as error:
        store.capture(target_part=20253)
    assert error.value.code == "HISTORY_CONTROL_INVALID"


def test_failed_atomic_pointer_replace_preserves_previous_active_version(tmp_path, monkeypatch):
    store, _, _ = initialize(tmp_path)
    result = commit(store, payload())
    previous = (store.root / "control.json").read_bytes()
    def fail_replace(*args):
        raise OSError("synthetic pointer write failure")
    with monkeypatch.context() as scoped:
        scoped.setattr(module().os, "replace", fail_replace)
        with pytest.raises(OSError):
            activate(store, result)
    assert (store.root / "control.json").read_bytes() == previous
    assert store.status()["active_as_of_part"] == 20251
    assert (store.root / "as_of_20252/metadata.json").exists()
    activate(store, result)
    assert store.status()["active_as_of_part"] == 20252


def test_unactivated_committed_history_cannot_be_selected_explicitly(tmp_path):
    store, _, _ = initialize(tmp_path)
    result = commit(store, payload())
    for backtesting in (False, True):
        with pytest.raises(module().HistoryUpdateError) as error:
            store.capture(target_part=20253, history_as_of_part=20252, allow_older_history=backtesting)
        assert error.value.code == "HISTORY_VERSION_NOT_ACTIVATED"
    assert store.status()["activated_versions"] == {"20251": file_sha256(store.root / "as_of_20251/course_history_state.pkl")}
    activate(store, result)
    assert store.capture(target_part=20253, history_as_of_part=20252, allow_older_history=False).as_of_part == 20252


def test_normal_capture_after_rollback_cannot_bypass_active_pointer(tmp_path):
    store, _, _ = initialize(tmp_path)
    result = commit(store, payload())
    activate(store, result)
    baseline_hash = file_sha256(store.root / "as_of_20251/course_history_state.pkl")
    store.activate(cutoff=20251, expected_history_sha256=baseline_hash, confirmation=True, rollback=True)
    with pytest.raises(module().HistoryUpdateError) as error:
        store.capture(target_part=20253, history_as_of_part=20252, allow_older_history=False)
    assert error.value.code == "HISTORY_CUTOFF_AFTER_ACTIVE"
    assert store.capture(target_part=20253, history_as_of_part=20252, allow_older_history=True).as_of_part == 20252


def test_preexisting_bundle_without_activation_record_cannot_be_served(tmp_path):
    store, _, _ = initialize(tmp_path)
    from src.recommendation.history_update import apply_history_delta
    baseline, _, _ = load_frozen_history(20251, root=store.root, dataset_version="V2")
    state = apply_history_delta(baseline, payload())
    save_frozen_history(state, None, {
        "dataset_version": "V2", "source_min_part": 20211, "source_max_part": 20252,
        "source_row_count": 5, "source_part_counts": {"20211": 1, "20243": 1, "20251": 1, "20252": 2},
        "finalized_through_part": 20252,
    }, root=store.root)
    with pytest.raises(module().HistoryUpdateError) as error:
        store.capture(target_part=20253, history_as_of_part=20252, allow_older_history=True)
    assert error.value.code == "HISTORY_VERSION_NOT_ACTIVATED"


def test_readonly_proxy_rejects_skipped_semester_without_changing_control(tmp_path):
    store, _, _ = initialize(tmp_path)
    proxy = store.serving_manager()
    before = (store.root / "control.json").read_bytes()
    with pytest.raises(module().HistoryUpdateError) as error:
        proxy.preview_delta(history_payload=payload(20261))
    assert error.value.code == "OUT_OF_ORDER_DELTA"
    assert (store.root / "control.json").read_bytes() == before
    assert proxy.preview_delta(history_payload=payload(20252))["status"] == "new_delta"
    assert (store.root / "control.json").read_bytes() == before
    # Existing core callers keep their earlier permissive order contract.
    from src.recommendation.history_update import FrozenHistoryManager
    snapshot = proxy.capture(target_part=20252)
    assert FrozenHistoryManager(snapshot, root=store.root).preview_delta(history_payload=payload(20261))["status"] == "new_delta"


def test_baseline_retry_adopts_exact_verified_bundle_after_pointer_failure(tmp_path, monkeypatch):
    old = tmp_path / "source"
    _, digest = source(old)
    store = module().CumulativeHistoryStore(tmp_path / "new", compatibility_check=lambda state, metadata: True)
    request = dict(source_root=old, expected_source_hash=digest, approval_reference="approved",
                   confirmation=True, cumulative_history_confirmed=True)
    def fail_replace(*args):
        raise OSError("synthetic first pointer failure")
    with monkeypatch.context() as scoped:
        scoped.setattr(module().os, "replace", fail_replace)
        with pytest.raises(OSError):
            store.initialize(**request)
    baseline = store.root / "as_of_20251"
    before = {p.name: file_sha256(p) for p in baseline.iterdir()}
    assert store.status()["active_as_of_part"] is None
    result = store.initialize(**request)
    assert result["status"] == "initialized"
    assert result["baseline_recovered"] is True
    assert store.capture(target_part=20252).as_of_part == 20251
    assert before == {p.name: file_sha256(p) for p in baseline.iterdir()}


@pytest.mark.parametrize("conflict", ["approval", "source"])
def test_baseline_retry_rejects_conflicting_approval_or_source_without_overwrite(tmp_path, monkeypatch, conflict):
    old = tmp_path / "source"
    _, digest = source(old)
    store = module().CumulativeHistoryStore(tmp_path / "new", compatibility_check=lambda state, metadata: True)
    request = dict(source_root=old, expected_source_hash=digest, approval_reference="approved",
                   confirmation=True, cumulative_history_confirmed=True)
    def fail_replace(*args):
        raise OSError("synthetic first pointer failure")
    with monkeypatch.context() as scoped:
        scoped.setattr(module().os, "replace", fail_replace)
        with pytest.raises(OSError):
            store.initialize(**request)
    before = {p.name: file_sha256(p) for p in (store.root / "as_of_20251").iterdir()}
    if conflict == "approval":
        request["approval_reference"] = "different-approval"
    else:
        metadata_path = old / "as_of_20251/metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["additional_source_approval"] = "different-source"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        request["expected_source_hash"] = file_sha256(metadata_path)
    with pytest.raises(module().HistoryUpdateError) as error:
        store.initialize(**request)
    assert error.value.code == "HISTORY_CONFLICT"
    assert store.status()["active_as_of_part"] is None
    assert before == {p.name: file_sha256(p) for p in (store.root / "as_of_20251").iterdir()}


def test_cross_worker_capture_pins_history_during_atomic_activation(tmp_path, monkeypatch):
    store, _, _ = initialize(tmp_path)
    committed = commit(store, payload())
    reader = module().CumulativeHistoryStore(store.root, compatibility_check=lambda state, metadata: True)
    pinned = reader.capture(target_part=20252, history_as_of_part=20251, allow_older_history=False)
    old_sums = deepcopy(pinned._state.global_sums)
    bundles_before = {p.relative_to(store.root).as_posix(): file_sha256(p)
                      for directory in store.root.glob("as_of_*") for p in directory.iterdir() if p.is_file()}
    ready, resume = Event(), Event()
    original_write = store._write

    def paused_write(control):
        ready.set()
        assert resume.wait(10)
        original_write(control)

    monkeypatch.setattr(store, "_write", paused_write)
    with ThreadPoolExecutor(max_workers=1) as pool:
        job = pool.submit(activate, store, committed)
        try:
            assert ready.wait(10)
            during = reader.capture(target_part=20252, history_as_of_part=20251, allow_older_history=False)
            assert during.as_of_part == during.metadata["as_of_part"] == 20251
            assert during._state.global_sums == old_sums
            assert reader.status()["active_as_of_part"] == 20251
        finally:
            resume.set()
        assert job.result(timeout=10)["status"] == "activated"
    after = reader.capture(target_part=20253, history_as_of_part=20252, allow_older_history=False)
    assert after.as_of_part == after.metadata["as_of_part"] == 20252
    assert after._state.global_sums["raw_count"] == old_sums["raw_count"] + 2
    assert pinned.as_of_part == pinned.metadata["as_of_part"] == 20251
    assert pinned._state.global_sums == old_sums
    assert bundles_before == {p.relative_to(store.root).as_posix(): file_sha256(p)
                              for directory in store.root.glob("as_of_*") for p in directory.iterdir() if p.is_file()}


@pytest.mark.parametrize("count", [2**53 - 2, 2**51])
def test_inexact_cumulative_statistics_reject_commit_without_publication(tmp_path, count):
    store, baseline, _ = initialize(tmp_path)
    data = payload()
    data["aggregates"][0].update(count=count, mark_sum=50 * count,
                                 fail_count=0, retake_count=0, attempt_sum=count)
    before = {p.name: file_sha256(p) for p in (store.root / "as_of_20251").iterdir()}
    with pytest.raises(ValueError, match="exact"):
        commit(store, data)
    snapshot = store.capture(target_part=20252, history_as_of_part=20251, allow_older_history=False)
    assert snapshot._state.global_sums == baseline.global_sums
    assert store.status()["active_as_of_part"] == 20251
    assert not (store.root / "as_of_20252").exists()
    assert before == {p.name: file_sha256(p) for p in (store.root / "as_of_20251").iterdir()}
