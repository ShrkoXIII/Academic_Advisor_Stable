"""Durable administration over the existing base-only immutable V2 history.

The small control file is the active pointer and administrative configuration.
Immutable bundle publication remains owned by FrozenHistoryManager. This module
does not reconstruct rows, supply points, load models, or authorize HTTP users.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import Lock
from uuid import uuid4

from pandas.testing import assert_frame_equal

from src import paths
from src.features.frozen_history import (
    file_sha256, load_frozen_history, previous_academic_part,
    save_frozen_history_atomic, validate_history_selection,
)
from src.recommendation.history_update import (
    FrozenHistoryManager, HistorySnapshot, normalize_history_delta,
    validate_history_state, _validate_update_metadata,
)


BASELINE_PART = 20251
UPDATE_MODES = frozenset({"disabled", "manual", "auto_on_finalization"})
_LOCKS = {}
_LOCKS_GUARD = Lock()


class HistoryUpdateError(ValueError):
    """Public fixed-code history failure without private filesystem details."""

    def __init__(self, code, message, *, status_code=409):
        super().__init__(message)
        self.code, self.status_code = code, status_code


def _now():
    return datetime.now(timezone.utc).isoformat()


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _approval(value):
    if not isinstance(value, str) or not value.strip():
        raise HistoryUpdateError("BASELINE_APPROVAL_REQUIRED", "An authoritative approval reference is required.", status_code=422)
    return sha256(value.encode("utf-8")).hexdigest()


def _confirmation(value):
    if value is not True:
        raise HistoryUpdateError("CONFIRMATION_REQUIRED", "Explicit administrator confirmation is required.", status_code=422)


def _overlap(a, b):
    return a == b or a in b.parents or b in a.parents


class CumulativeHistoryStore:
    """Separate cumulative versions, serialized publication and atomic activation.

    ``compatibility_check(state, metadata)`` verifies selected serving artifacts;
    it may raise a fixed error, return False, or return None/True on success.
    Without a checker readiness is unavailable and publishing/activation fails.
    Construction and status on an absent store perform no filesystem writes.
    """

    def __init__(self, root, *, default_mode="manual", compatibility_check=None, legacy_root=None):
        if default_mode not in UPDATE_MODES:
            raise ValueError("Invalid history update mode.")
        self.root = Path(root).resolve()
        self.legacy_root = Path(legacy_root).resolve() if legacy_root is not None else None
        protected = [Path(paths.FROZEN_HISTORY_DIR).resolve(), Path(paths.FROZEN_HISTORY_DIR).resolve()]
        if self.legacy_root is not None:
            protected.append(self.legacy_root)
        if any(_overlap(self.root, old) for old in protected):
            raise HistoryUpdateError("HISTORY_ROOT_OVERLAP", "Cumulative storage must be separate from existing frozen history.", status_code=422)
        self.default_mode = default_mode
        self.compatibility_check = compatibility_check
        self._control_path = self.root / "control.json"
        with _LOCKS_GUARD:
            self._thread_lock = _LOCKS.setdefault(str(self.root), Lock())

    def _read(self):
        if not self._control_path.exists():
            return {"format_version": 1, "mode": self.default_mode, "active": None,
                    "pending_delta": None, "last_successful_update": None,
                    "failures": [], "approvals": {}, "activated_versions": {}}
        control = json.loads(self._control_path.read_text(encoding="utf-8"))
        if control.get("format_version") != 1 or control.get("mode") not in UPDATE_MODES:
            raise HistoryUpdateError("HISTORY_CONTROL_INVALID", "Durable history configuration is invalid.", status_code=503)
        activated = control.get("activated_versions", {})
        if not isinstance(activated, dict):
            raise HistoryUpdateError("HISTORY_CONTROL_INVALID", "History activation evidence is invalid.", status_code=503)
        control["activated_versions"] = activated
        return control

    def _write(self, control):
        temporary = self.root / f".control-{uuid4().hex}.tmp"
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(control, stream, sort_keys=True, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._control_path)
        finally:
            temporary.unlink(missing_ok=True)

    @contextmanager
    def _locked(self):
        if not self._thread_lock.acquire(blocking=False):
            raise HistoryUpdateError("HISTORY_LOCK_BUSY", "A history operation is already in progress.", status_code=503)
        stream = None
        acquired = False
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            stream = (self.root / ".workflow.lock").open("a+b")
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                raise HistoryUpdateError("HISTORY_LOCK_BUSY", "A history operation is already in progress.", status_code=503) from None
            control = self._read()
            try:
                yield control
            except Exception as error:
                code = error.code if isinstance(error, HistoryUpdateError) else (
                    "history_io_failed" if isinstance(error, OSError) else "history_validation_failed")
                control.setdefault("failures", []).append({"code": code, "at_utc": _now()})
                control["failures"] = control["failures"][-20:]
                self._write(control)
                raise
            else:
                self._write(control)
        finally:
            if stream is not None:
                if acquired:
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                stream.close()
            self._thread_lock.release()

    @staticmethod
    def _enabled(control, required_mode=None):
        if control["mode"] == "disabled":
            raise HistoryUpdateError("HISTORY_DISABLED", "History updates and activation are disabled.")
        if required_mode is not None and control["mode"] != required_mode:
            code = "MANUAL_MODE_REQUIRED" if required_mode == "manual" else "AUTO_MODE_REQUIRED"
            raise HistoryUpdateError(code, f"History operation requires {required_mode} mode.")

    def _load(self, cutoff, *, legacy=False):
        root = self.legacy_root if legacy else self.root
        if root is None:
            raise FileNotFoundError("Requested exact history version is unavailable.")
        state, _, metadata = load_frozen_history(cutoff, root=root, dataset_version="V2")
        validate_history_state(state)
        _validate_update_metadata(metadata)
        return HistorySnapshot(state, metadata)

    def _active(self, control):
        active = control.get("active")
        if active is None:
            raise HistoryUpdateError("HISTORY_UNINITIALIZED", "Initialize the approved cumulative 20251 baseline first.", status_code=503)
        snapshot = self._load(active["as_of_part"])
        if snapshot.metadata["artifact_sha256"]["course_history_state.pkl"] != active["history_sha256"]:
            raise HistoryUpdateError("HISTORY_CONFLICT", "Active history pointer does not match its immutable bundle.")
        if control.get("activated_versions", {}).get(str(snapshot.as_of_part)) != active["history_sha256"]:
            raise HistoryUpdateError("HISTORY_VERSION_NOT_ACTIVATED", "Active history lacks durable activation evidence.", status_code=503)
        return snapshot

    def _compatible(self, snapshot, *, required=True):
        if self.compatibility_check is None:
            if required:
                raise HistoryUpdateError("SERVING_ARTIFACTS_UNAVAILABLE", "Selected serving artifact compatibility is unavailable.", status_code=503)
            return None
        try:
            result = self.compatibility_check(snapshot._state, snapshot.metadata)
        except HistoryUpdateError:
            raise
        except ValueError as error:
            allowed = {"SPECIALTY_HISTORY_AGGREGATES_UNAVAILABLE", "SERVING_ARTIFACTS_UNAVAILABLE", "SERVING_POLICY_INCOMPATIBLE", "SERVING_HISTORY_INCOMPATIBLE"}
            code = str(error) if str(error) in allowed else "HISTORY_INCOMPATIBLE"
            if code == "SERVING_ARTIFACTS_UNAVAILABLE" and not required:
                return None
            raise HistoryUpdateError(code, "Selected serving artifacts are incompatible with this base history.", status_code=503) from None
        if result is False:
            raise HistoryUpdateError("HISTORY_INCOMPATIBLE", "Selected serving artifact compatibility failed.", status_code=503)
        return True

    def status(self):
        control = self._read()
        available, invalid = [], []
        for directory in self.root.glob("as_of_*"):
            try:
                cutoff = paths.academic_part(directory.name[6:])
            except ValueError:
                continue
            try:
                self._load(cutoff)
            except Exception:
                invalid.append(cutoff)
            else:
                available.append(cutoff)
        active = control.get("active")
        compatible = None
        if active is not None:
            try:
                compatible = self._compatible(self._active(control), required=False)
            except Exception:
                compatible = False
        cutoff = active["as_of_part"] if active else None
        return {"mode": control["mode"], "update_mode": control["mode"],
                "active_as_of_part": cutoff, "active_historical_cutoff": cutoff,
                "active_history_sha256": active["history_sha256"] if active else None,
                "activated_versions": deepcopy(control.get("activated_versions", {})),
                "available_versions": sorted(available), "available_historical_versions": sorted(available),
                "invalid_versions": sorted(invalid), "pending_delta": deepcopy(control.get("pending_delta")),
                "last_successful_update": deepcopy(control.get("last_successful_update")),
                "failures": deepcopy(control.get("failures", [])), "previous_update_failures": deepcopy(control.get("failures", [])),
                "serving_artifacts_compatible": compatible,
                "serving_compatibility": "unavailable" if compatible is None else ("compatible" if compatible else "incompatible")}

    def set_mode(self, mode):
        if mode not in UPDATE_MODES:
            raise ValueError("Invalid history update mode.")
        with self._locked() as control:
            control["mode"] = mode
            control["pending_delta"] = None
        return self.status()

    def initialize(self, *, source_root, expected_source_hash, approval_reference, confirmation=False,
                   cumulative_history_confirmed=False):
        with self._locked() as control:
            self._enabled(control, "manual")
            _confirmation(confirmation)
            approval_hash = _approval(approval_reference)
            if cumulative_history_confirmed is not True:
                raise HistoryUpdateError("BASELINE_NOT_CUMULATIVE", "Administrator must explicitly attest the full approved cumulative prefix.", status_code=422)
            source_root = Path(source_root).resolve()
            if _overlap(self.root, source_root):
                raise HistoryUpdateError("HISTORY_ROOT_OVERLAP", "Source and cumulative storage must be separate.", status_code=422)
            if control.get("active") is not None:
                raise HistoryUpdateError("HISTORY_CONFLICT", "Cumulative history has already been initialized.")
            source_metadata_path = source_root / f"as_of_{BASELINE_PART}" / "metadata.json"
            if file_sha256(source_metadata_path) != expected_source_hash:
                raise HistoryUpdateError("SOURCE_HASH_MISMATCH", "Approved baseline metadata hash differs from source.")
            state, _, metadata = load_frozen_history(BASELINE_PART, root=source_root, dataset_version="V2")
            validate_history_state(state)
            _validate_update_metadata(metadata)
            counts = metadata.get("source_part_counts", {})
            earlier = [paths.academic_part(p) for p, n in counts.items() if n > 0 and paths.academic_part(p) < BASELINE_PART]
            if (not earlier or metadata.get("source_min_part") != min(earlier)
                    or counts.get(str(BASELINE_PART), 0) <= 0
                    or any(paths.academic_part(p) > BASELINE_PART or isinstance(n, bool) or not isinstance(n, int) or n < 0 for p, n in counts.items())
                    or sum(counts.values()) != metadata.get("source_row_count")
                    or sum(counts.values()) != state.global_sums["raw_count"]):
                raise HistoryUpdateError("BASELINE_NOT_CUMULATIVE", "Approved baseline must include consistent earlier and 20251 source provenance.", status_code=422)
            self._compatible(HistorySnapshot(state, metadata))
            original_hash = metadata["artifact_sha256"]["course_history_state.pkl"]
            exported = {key: value for key, value in metadata.items() if key not in {
                "directory", "metadata_sha256", "cleanup_warnings", "created_at", "created_at_utc"}}
            exported.update({"baseline_as_of_part": BASELINE_PART,
                "baseline_source_metadata_sha256": expected_source_hash,
                "baseline_source_history_sha256": original_hash,
                "baseline_approval_sha256": approval_hash, "baseline_completeness": "admin_attested"})
            recovered = (self.root / f"as_of_{BASELINE_PART}").exists()
            if recovered:
                # A crash between immutable publication and pointer replacement
                # may leave a complete baseline. Adopt only the identical approved
                # migration; neither complete nor incomplete bundles are replaced.
                try:
                    existing = self._load(BASELINE_PART)
                    actual = existing.metadata
                    generated = {"created_at", "created_at_utc", "new_history_sha256", "directory", "metadata_sha256", "cleanup_warnings"}
                    expected = {key: value for key, value in exported.items() if key not in generated}
                    if {key: value for key, value in actual.items() if key not in generated} != expected:
                        raise ValueError("Baseline approval or source provenance differs.")
                    if (actual["artifact_sha256"]["course_history_state.pkl"] != original_hash
                            or actual.get("new_history_sha256") != original_hash
                            or existing._state.global_sums != state.global_sums):
                        raise ValueError("Baseline history differs.")
                    for level in state.tables:
                        assert_frame_equal(existing._state.tables[level], state.tables[level], check_exact=True)
                except (OSError, ValueError, KeyError, TypeError, AssertionError):
                    raise HistoryUpdateError("HISTORY_CONFLICT", "Published baseline does not match the exact approved cumulative migration.") from None
                loaded, provenance = existing._state, actual
            else:
                loaded, provenance = save_frozen_history_atomic(state, exported, root=self.root)
            if provenance["artifact_sha256"]["course_history_state.pkl"] != original_hash:
                raise HistoryUpdateError("HISTORY_CONFLICT", "Migrated baseline bytes differ from approved source.")
            self._compatible(HistorySnapshot(loaded, provenance))
            control["active"] = {"as_of_part": BASELINE_PART, "history_sha256": original_hash}
            control.setdefault("activated_versions", {})[str(BASELINE_PART)] = original_hash
            control["last_successful_update"] = {"operation": "initialize", "as_of_part": BASELINE_PART,
                "history_sha256": original_hash, "source_metadata_sha256": expected_source_hash,
                "approval_sha256": approval_hash, "at_utc": _now(), "completeness": "admin_attested"}
        return {"status": "initialized", "active_as_of_part": BASELINE_PART,
                "history_as_of_part": BASELINE_PART, "new_history_sha256": original_hash,
                "source_metadata_sha256": expected_source_hash, "source_history_sha256": original_hash,
                "baseline_completeness": "admin_attested", "baseline_recovered": recovered}

    def _preview(self, control, history_payload):
        snapshot = self._active(control)
        compatibility = self._compatible(snapshot, required=False)
        delta = normalize_history_delta(history_payload, require_finalized=False)
        manager = FrozenHistoryManager(snapshot, root=self.root)
        result = manager.preview_delta(history_payload=history_payload)
        if result["status"] != "already_applied" and previous_academic_part(delta.delta_part) != snapshot.as_of_part:
            raise HistoryUpdateError("OUT_OF_ORDER_DELTA", "Delta must be the next chronological academic semester.")
        token = _digest({"delta_sha256": delta.delta_sha256, "base_as_of_part": snapshot.as_of_part,
                         "base_history_sha256": result["base_history_sha256"], "mode": control["mode"]})
        pending = {**result, "preview_token": token, "preview_sha256": token,
                   "proposed_as_of_part": delta.delta_part, "compatibility": compatibility}
        control["pending_delta"] = pending
        return {**pending, "status": "previewed" if compatibility else "partial"}

    def preview(self, *, history_payload):
        with self._locked() as control:
            self._enabled(control)
            try:
                return self._preview(control, history_payload)
            except ValueError as error:
                if isinstance(error, HistoryUpdateError):
                    raise
                code = ("HISTORY_CONFLICT" if "CONFLICT" in str(error) else
                        "OUT_OF_ORDER_DELTA" if "out-of-order" in str(error) else "INVALID_DELTA")
                raise HistoryUpdateError(code, "History delta conflicts with lineage or aggregate rules.", status_code=409 if code == "HISTORY_CONFLICT" else 422) from None

    def _commit(self, control, history_payload, token, approval_reference):
        delta = normalize_history_delta(history_payload)
        snapshot = self._active(control)
        self._compatible(snapshot)
        pending = control.get("pending_delta") or {}
        if (pending.get("preview_token") != token or pending.get("delta_sha256") != delta.delta_sha256
                or pending.get("history_as_of_part") != snapshot.as_of_part
                or pending.get("base_history_sha256") != snapshot.metadata["artifact_sha256"]["course_history_state.pkl"]):
            raise HistoryUpdateError("STALE_PREVIEW", "Commit requires confirmation of the matching preview and active baseline.")
        approval_hash = _approval(approval_reference)
        manager = FrozenHistoryManager(snapshot, root=self.root)
        if pending["status"] == "already_applied":
            return {"status": "already_applied", "history_as_of_part": snapshot.as_of_part,
                    "delta_part": delta.delta_part, "delta_sha256": delta.delta_sha256, "activated": False}
        destination = self.root / f"as_of_{delta.delta_part}"
        if destination.exists():
            committed = self._load(delta.delta_part)
            metadata = committed.metadata
            if (metadata.get("delta_sha256") != delta.delta_sha256
                    or metadata.get("previous_history_sha256") != pending["base_history_sha256"]):
                raise HistoryUpdateError("HISTORY_CONFLICT", "An immutable version already exists with different lineage.")
            self._compatible(committed)
            new_hash = metadata["artifact_sha256"]["course_history_state.pkl"]
        else:
            # The temporary manager publishes using Phase 3's clone/save/reload
            # verification; its local reference swap never activates this store.
            result = manager.update_history_from_payload(history_payload=history_payload)
            new_hash = result["new_history_sha256"]
            self._compatible(self._load(delta.delta_part))
        control.setdefault("approvals", {})[str(delta.delta_part)] = approval_hash
        pending.update({"committed": True, "new_history_sha256": new_hash, "approval_sha256": approval_hash})
        control["pending_delta"] = pending
        control["last_successful_update"] = {"operation": "commit", "as_of_part": delta.delta_part,
            "delta_sha256": delta.delta_sha256, "history_sha256": new_hash,
            "approval_sha256": approval_hash, "at_utc": _now()}
        return {"status": "committed", "history_as_of_part": delta.delta_part,
                "delta_part": delta.delta_part, "delta_sha256": delta.delta_sha256,
                "new_history_sha256": new_hash, "activated": False}

    def commit(self, *, history_payload, confirmation, approval_reference, preview_token=None, preview_sha256=None):
        with self._locked() as control:
            self._enabled(control, "manual")
            _confirmation(confirmation)
            return self._commit(control, history_payload, preview_token or preview_sha256, approval_reference)

    def _activate(self, control, cutoff, expected_history_sha256, *, rollback):
        snapshot = self._load(cutoff)
        self._compatible(snapshot)
        new_hash = snapshot.metadata["artifact_sha256"]["course_history_state.pkl"]
        if new_hash != expected_history_sha256:
            raise HistoryUpdateError("HISTORY_CONFLICT", "Activation hash differs from the exact immutable version.")
        current = self._active(control)
        if cutoff < current.as_of_part and rollback is not True:
            raise HistoryUpdateError("ROLLBACK_CONFIRMATION_REQUIRED", "An older version requires explicit rollback confirmation.")
        if cutoff > current.as_of_part and (snapshot.metadata.get("previous_as_of_part") != current.as_of_part
                or snapshot.metadata.get("previous_history_sha256") != current.metadata["artifact_sha256"]["course_history_state.pkl"]):
            raise HistoryUpdateError("HISTORY_CONFLICT", "Activation lineage must follow the current active version.")
        control["active"] = {"as_of_part": cutoff, "history_sha256": new_hash}
        control.setdefault("activated_versions", {})[str(cutoff)] = new_hash
        control["pending_delta"] = None
        control["last_successful_update"] = {"operation": "rollback" if cutoff < current.as_of_part else "activate",
            "as_of_part": cutoff, "history_sha256": new_hash, "at_utc": _now()}
        return {"status": "activated", "active_as_of_part": cutoff, "history_as_of_part": cutoff,
                "new_history_sha256": new_hash, "activated": True}

    def activate(self, *, cutoff, expected_history_sha256, confirmation, rollback=False):
        cutoff = paths.academic_part(cutoff)
        with self._locked() as control:
            self._enabled(control, "manual")
            _confirmation(confirmation)
            return self._activate(control, cutoff, expected_history_sha256, rollback=rollback)

    def finalize(self, *, history_payload, approval_reference, trusted_event=False):
        with self._locked() as control:
            self._enabled(control, "auto_on_finalization")
            if trusted_event is not True:
                raise HistoryUpdateError("FINALIZATION_REQUIRED", "A trusted authenticated finalization event is required.", status_code=422)
            _approval(approval_reference)
            normalize_history_delta(history_payload)
            preview = self._preview(control, history_payload)
            result = self._commit(control, history_payload, preview["preview_token"], approval_reference)
            if result["status"] == "already_applied":
                control["pending_delta"] = None
                return result
            return self._activate(control, result["history_as_of_part"], result["new_history_sha256"], rollback=False)

    def capture(self, *, target_part, history_as_of_part=None, allow_older_history=None):
        control = self._read()
        active = self._active(control)
        older = history_as_of_part is None if allow_older_history is None else allow_older_history
        if not isinstance(older, bool):
            raise ValueError("allow_older_history must be a boolean.")
        if history_as_of_part is None:
            snapshot = active
        else:
            cutoff = paths.academic_part(history_as_of_part)
            legacy = cutoff < BASELINE_PART and not (self.root / f"as_of_{cutoff}").exists()
            snapshot = self._load(cutoff, legacy=legacy)
            if cutoff >= BASELINE_PART:
                history_hash = snapshot.metadata["artifact_sha256"]["course_history_state.pkl"]
                if control.get("activated_versions", {}).get(str(cutoff)) != history_hash:
                    raise HistoryUpdateError("HISTORY_VERSION_NOT_ACTIVATED", "Requested history version has never been activated.")
                if cutoff > active.as_of_part and not older:
                    raise HistoryUpdateError("HISTORY_CUTOFF_AFTER_ACTIVE", "Normal serving cannot select history newer than the active pointer.")
        validate_history_selection(target_part, snapshot.as_of_part, allow_older_history=older)
        return snapshot

    def serving_manager(self):
        control = self._read()
        if control.get("active") is None:
            return None
        self._active(control)
        return _ServingHistoryManager(self)


class _ServingHistoryManager(FrozenHistoryManager):
    """Engine-compatible read-only proxy; refresh durable pointer each capture."""

    def __init__(self, store):
        self.store = store
        self.root = store.root
        self.skipped_bundles = ()

    def capture(self, **kwargs):
        return self.store.capture(**kwargs)

    def preview_delta(self, *, history_payload):
        snapshot = self.store._active(self.store._read())
        result = FrozenHistoryManager(snapshot, root=self.root).preview_delta(history_payload=history_payload)
        if result["status"] != "already_applied" and previous_academic_part(result["delta_part"]) != snapshot.as_of_part:
            raise HistoryUpdateError("OUT_OF_ORDER_DELTA", "Delta must be the next chronological academic semester.")
        return result

    def update_history_from_payload(self, *, history_payload):
        raise HistoryUpdateError("ADMIN_WORKFLOW_REQUIRED", "Use authenticated administrative preview, commit and activation.")
