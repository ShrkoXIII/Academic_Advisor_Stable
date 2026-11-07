"""Finalized-semester aggregate updates, separate from recommendation scoring.

The local Core envelope is ``{delta_part, finalized: True, aggregates: [...]}``.
Each row has degree/course/faculty/requirement IDs, full course_credits, count,
fail_count, retake_count, mark_sum and attempt_sum. Counts describe finalized
outcomes using the training definitions (mark < 50, attempt > 1), not roster
statuses. An optional row part_id must equal delta_part. This is not an HTTP
contract. No raw rows, training tables or experimental history are read here.
"""
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from hashlib import sha256
import json
import pickle
from pathlib import Path
from threading import Lock

import numpy as np
import pandas as pd

from src import paths
from src.data.cleaning.cleaning_utils import clean_id
from src.features.feature_contract import FEATURE_ENGINEERING_VERSION
from src.features.frozen_history import (
    load_frozen_history, save_frozen_history_atomic, validate_history_selection,
)
from src.features.temporal_features import (
    HISTORY_SUM_COLUMNS, CourseHistoryState, build_history_keys,
)


DELTA_ID_COLUMNS = ("degree_id", "course_id", "faculty_id", "plan_requirement_type_id")
DELTA_NUMERIC_COLUMNS = ("course_credits", "count", "fail_count", "retake_count", "mark_sum", "attempt_sum")
DELTA_COLUMNS = (*DELTA_ID_COLUMNS, *DELTA_NUMERIC_COLUMNS)
_MAX_EXACT_INTEGER = 2**53
_EXACT_SUM_SOURCES = {"effective_support": "count", "raw_count": "count", "fail_sum": "fail_count",
                      "attempt_sum": "attempt_sum", "retake_sum": "retake_count"}


def _number(value, name, *, integer=False):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"Invalid {name}: boolean is not a number.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid {name}.") from exc
    if (not result.is_finite() or result < 0 or not np.isfinite(float(result))
            or (integer and result != result.to_integral_value())):
        raise ValueError(f"Invalid finite nonnegative {name}.")
    if integer and result > _MAX_EXACT_INTEGER:
        raise ValueError(f"{name} exceeds the exact float64 integer range.")
    return result


def _part(value):
    number = _number(value, "delta_part", integer=True)
    if not 10000 <= number <= 99999:
        raise ValueError("Invalid five-digit academic part.")
    return paths.academic_part(int(number))


def _canonical_number(number):
    text = format(number, "f")
    return (text.rstrip("0").rstrip(".") if "." in text else text) if number else "0"


@dataclass(frozen=True)
class HistoryDelta:
    """Normalized immutable rows with a canonical, versioned content identity."""

    delta_part: int
    rows: tuple
    delta_sha256: str

    def to_frame(self):
        frame = pd.DataFrame(self.rows, columns=DELTA_COLUMNS)
        for column in DELTA_ID_COLUMNS:
            frame[column] = frame[column].astype("string")
        for column in DELTA_NUMERIC_COLUMNS:
            frame[column] = frame[column].astype("float64")
        return frame


def normalize_history_delta(payload, *, require_finalized=True):
    """Validate one finalized semester and hash normalized rows in stable order."""
    if not isinstance(payload, Mapping) or (require_finalized and payload.get("finalized") is not True):
        raise ValueError("History Delta must explicitly attest finalized=True.")
    part = _part(payload.get("delta_part"))
    if part < 20221:
        raise ValueError("Aggregate Delta supports only new semesters with temporal weight 1.")
    records = payload.get("aggregates")
    if not isinstance(records, (list, tuple)):
        raise ValueError("History aggregates must be a list of records.")
    rows, seen = [], set()
    for record in records:
        if not isinstance(record, Mapping) or not set(DELTA_COLUMNS).issubset(record):
            raise ValueError("History aggregate is missing required keys or sums.")
        if "part_id" in record and _part(record["part_id"]) != part:
            raise ValueError("Aggregate part_id must match delta_part.")
        ids = []
        for column in DELTA_ID_COLUMNS:
            value = record[column]
            if not isinstance(value, (str, int, float, Decimal)) or isinstance(value, bool):
                raise ValueError(f"Invalid {column}.")
            normalized = clean_id(pd.Series([value])).iloc[0]
            if pd.isna(normalized) or "||" in normalized or normalized == "__MISSING__":
                raise ValueError(f"Invalid history key {column}.")
            ids.append(str(normalized))
        numbers = {column: _number(record[column], column, integer=column != "course_credits" and column != "mark_sum")
                   for column in DELTA_NUMERIC_COLUMNS}
        count, failed, retakes = (numbers[c] for c in ("count", "fail_count", "retake_count"))
        marks, attempts = numbers["mark_sum"], numbers["attempt_sum"]
        if (count <= 0 or failed > count or retakes > count or marks > 100 * count
                or marks < 50 * (count - failed)
                or (failed > 0 and marks >= 50 * failed + 100 * (count - failed))
                or attempts < count + retakes or (retakes == 0 and attempts != count)):
            raise ValueError("Aggregate sums violate finalized mark/failure/attempt definitions.")
        if numbers["course_credits"] >= 2**63 - 1:
            raise ValueError("course_credits exceeds the history-key numeric range.")
        values = tuple(_canonical_number(numbers[c]) for c in DELTA_NUMERIC_COLUMNS)
        grain = (*ids, values[0])
        if grain in seen:
            raise ValueError("Duplicate normalized aggregate grain.")
        seen.add(grain)
        rows.append((*ids, *values))
    rows = tuple(sorted(rows))
    canonical = json.dumps({"format_version": 1, "delta_part": part, "columns": DELTA_COLUMNS,
                            "rows": rows}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return HistoryDelta(part, rows, sha256(canonical.encode("utf-8")).hexdigest())


def validate_history_state(state):
    """Check the official aggregate shape and consistency without rebuilding it."""
    if (not isinstance(state, CourseHistoryState) or state.smoothing_k != 20
            or state.min_support != 20 or set(state.tables) != set(range(1, 6))
            or set(state.global_sums) != set(HISTORY_SUM_COLUMNS)):
        raise ValueError("Invalid official CourseHistoryState contract/configuration.")
    paths.academic_part(state.as_of_part)

    def check_sums(values):
        if not np.isfinite(values).all() or (values < 0).any():
            raise ValueError("History sums must be finite and nonnegative.")
        support, count, mark, fail, attempt, retake = values.T
        tolerance = 1e-8
        if (np.any(support > count + tolerance) or np.any(count != np.floor(count))
                or np.any(fail > support + tolerance) or np.any(retake > support + tolerance)
                or np.any(mark / np.maximum(support, 1e-300) > 100 + tolerance)
                or np.any(attempt + tolerance < support)
                or np.any((support == 0) & (np.sum(values, axis=1) != 0))):
            raise ValueError("Inconsistent history aggregates.")

    global_values = np.array([[state.global_sums[c] for c in HISTORY_SUM_COLUMNS]], dtype=float)
    check_sums(global_values)
    for table in state.tables.values():
        if (list(table.columns) != HISTORY_SUM_COLUMNS or table.index.has_duplicates
                or table.index.isna().any() or not all(isinstance(k, str) for k in table.index)):
            raise ValueError("Invalid history table schema/keys.")
        values = table.to_numpy(dtype=float)
        check_sums(values)
        if not np.allclose(values.sum(axis=0), global_values[0], rtol=1e-10, atol=1e-7):
            raise ValueError("History table totals disagree with global sums.")


def apply_history_delta(state, history_payload):
    """Return a validated clone; never route aggregates through raw update()."""
    return _apply_normalized_delta(state, normalize_history_delta(history_payload))


def _validate_exact_addition(previous, addition, name):
    """Reject count overflow or loss of an existing weighted fraction."""
    if addition == 0:
        return
    exact = Fraction(float(previous)) + addition
    if exact > _MAX_EXACT_INTEGER or Fraction(float(exact)) != exact:
        raise ValueError(f"Cumulative {name} exceeds the exact float64 statistic range.")


def _apply_normalized_delta(state, delta):
    # Keep the exact immutable rows whose identity was checked by the manager.
    validate_history_state(state)
    if delta.delta_part <= state.as_of_part:
        raise ValueError("History Delta is out-of-order relative to the saved cutoff.")
    # Sum immutable integer strings before any float64 conversion can round
    # large inputs. The existing mark and credit numeric policies are unchanged.
    for column, source in _EXACT_SUM_SOURCES.items():
        position = DELTA_COLUMNS.index(source)
        addition = sum(int(row[position]) for row in delta.rows)
        _validate_exact_addition(state.global_sums[column], addition, column)
    cloned = deepcopy(state)
    frame = delta.to_frame()
    if not frame.empty:
        additions = pd.DataFrame({
            "effective_support": frame["count"], "raw_count": frame["count"],
            "mark_sum": frame["mark_sum"], "fail_sum": frame["fail_count"],
            "attempt_sum": frame["attempt_sum"], "retake_sum": frame["retake_count"],
        })
        for level, key in build_history_keys(frame).items():
            grouped = additions.assign(key=key).groupby("key", sort=True)[HISTORY_SUM_COLUMNS].sum()
            table = cloned.tables[level]
            for group, values in grouped.iterrows():
                for column in _EXACT_SUM_SOURCES:
                    previous = table.at[group, column] if group in table.index else 0
                    _validate_exact_addition(previous, int(values[column]), column)
            cloned.tables[level] = (pd.concat([cloned.tables[level], grouped])
                                    .groupby(level=0, sort=True)[HISTORY_SUM_COLUMNS].sum().astype("float64"))
        for column in HISTORY_SUM_COLUMNS:
            cloned.global_sums[column] += float(additions[column].sum())
    cloned.as_of_part = delta.delta_part
    validate_history_state(cloned)
    return cloned


@dataclass(frozen=True)
class HistorySnapshot:
    """One owned state/provenance pair retained throughout a future request.

    State has no public mutation API. Metadata is returned as a detached copy.
    Internal state ownership stays with the manager; consumers call apply().
    """

    _state: CourseHistoryState = field(repr=False)
    _metadata: dict = field(repr=False)

    @property
    def as_of_part(self):
        return self._state.as_of_part

    @property
    def metadata(self):
        return deepcopy(self._metadata)

    def apply(self, frame):
        return self._state.apply(frame)

    def metadata_for_target(self, target_part):
        """Return detached provenance and explicit history age for this request."""
        selection = validate_history_selection(_part(target_part), self.as_of_part, allow_older_history=True)
        return {**self.metadata, **selection, "history_is_stale": not selection["history_is_previous_part"]}


def _validate_update_metadata(metadata):
    if metadata.get("update_method") != "aggregate_delta_v1":
        return
    cutoff = metadata["as_of_part"]
    previous = paths.academic_part(metadata.get("previous_as_of_part"))
    applied = metadata.get("applied_deltas", {})
    if (previous >= cutoff or metadata.get("delta_part") != cutoff
            or metadata.get("new_history_sha256") != metadata["artifact_sha256"]["course_history_state.pkl"]
            or not isinstance(applied, dict) or applied.get(str(cutoff)) != metadata.get("delta_sha256")
            or not metadata.get("created_at")):
        raise ValueError("Invalid aggregate Delta lineage metadata.")
    for part, digest in applied.items():
        if (_part(part) > cutoff or not isinstance(digest, str) or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)):
            raise ValueError("Invalid applied Delta identity.")
    digest = metadata.get("previous_history_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("Invalid previous history hash.")


class FrozenHistoryManager:
    """Serialize local updates and swap a single verified snapshot reference.

    Writers are serialized per manager. Publication is exclusive across local
    managers/processes; a destination collision fails without replacing data.
    Readers capture a reference under a short lock, never held during I/O.
    The future two-stage engine delegates here; no engine/ranking is activated.
    """

    def __init__(self, snapshot, *, root, skipped_bundles=()):
        self.root = Path(root)
        self.skipped_bundles = tuple(skipped_bundles)
        self._active = snapshot
        self._update_lock, self._active_lock = Lock(), Lock()
        self._snapshots = {snapshot.as_of_part: snapshot}

    @classmethod
    def load(cls, *, root=None):
        """Load the newest valid, complete, base-only V2 bundle without rebuild."""
        root = Path(paths.FROZEN_HISTORY_DIR if root is None else root)
        candidates = []
        for directory in root.glob("as_of_*"):
            if directory.is_dir():
                try:
                    candidates.append((paths.academic_part(directory.name[6:]), directory))
                except ValueError:
                    continue
        skipped = []
        for cutoff, directory in sorted(candidates, reverse=True):
            try:
                state, _, metadata = load_frozen_history(cutoff, root=root, dataset_version="V2")
                validate_history_state(state)
                _validate_update_metadata(metadata)
            except (OSError, ValueError, KeyError, TypeError, AttributeError, EOFError, pickle.UnpicklingError) as exc:
                skipped.append({"as_of_part": cutoff, "reason": str(exc)})
                continue
            return cls(HistorySnapshot(state, metadata), root=root, skipped_bundles=skipped)
        raise FileNotFoundError(f"No complete valid V2 Frozen History found in {root}.")

    def capture(self, *, target_part, history_as_of_part=None, allow_older_history=None):
        """Pin one snapshot, accepting stale finalized history and forbidding overlap."""
        target = _part(target_part)
        with self._active_lock:
            snapshot = self._active
        if history_as_of_part is not None:
            cutoff = _part(history_as_of_part)
            with self._active_lock:
                snapshot = self._snapshots.get(cutoff)
            if snapshot is None:
                state, _, metadata = load_frozen_history(cutoff, root=self.root, dataset_version="V2")
                validate_history_state(state)
                _validate_update_metadata(metadata)
                snapshot = HistorySnapshot(state, metadata)
                with self._active_lock:
                    snapshot = self._snapshots.setdefault(cutoff, snapshot)
        older = history_as_of_part is None if allow_older_history is None else allow_older_history
        if not isinstance(older, bool):
            raise ValueError("allow_older_history must be a boolean.")
        validate_history_selection(target, snapshot.as_of_part, allow_older_history=older)
        return snapshot

    def preview_delta(self, *, history_payload):
        """Inspect normalized aggregates and lineage without writing or activating."""
        delta = normalize_history_delta(history_payload, require_finalized=False)
        with self._active_lock:
            snapshot = self._active
        metadata = snapshot.metadata
        existing = metadata.get("applied_deltas", {}).get(str(delta.delta_part))
        if existing is not None:
            if existing != delta.delta_sha256:
                raise ValueError("CONFLICT: same semester has a different Delta hash.")
            status = "already_applied"
        elif delta.delta_part <= snapshot.as_of_part:
            raise ValueError("History Delta is out-of-order and not previously recorded.")
        else:
            status = "new_delta"
        return {"status": status, "delta_part": delta.delta_part, "delta_sha256": delta.delta_sha256,
                "history_as_of_part": snapshot.as_of_part, "row_count": len(delta.rows),
                "finalization_verified": history_payload.get("finalized") is True,
                "base_history_sha256": metadata["artifact_sha256"]["course_history_state.pkl"]}

    def update_history_from_payload(self, *, history_payload):
        """Validate → clone → add → stage → verify → publish → atomic swap."""
        delta = normalize_history_delta(history_payload)
        with self._update_lock:
            with self._active_lock:
                previous = self._active
            old_meta = previous.metadata
            applied = dict(old_meta.get("applied_deltas", {}))
            existing = applied.get(str(delta.delta_part))
            if existing is not None:
                if existing != delta.delta_sha256:
                    raise ValueError("CONFLICT: same semester has a different Delta hash.")
                return {"status": "already_applied", "delta_part": delta.delta_part,
                        "delta_sha256": delta.delta_sha256, "history_as_of_part": previous.as_of_part}
            if delta.delta_part <= previous.as_of_part:
                raise ValueError("History Delta is out-of-order and not previously recorded.")
            state = _apply_normalized_delta(previous._state, delta)
            applied[str(delta.delta_part)] = delta.delta_sha256
            part_counts = dict(old_meta.get("source_part_counts", {}))
            part_counts[str(delta.delta_part)] = sum(int(row[5]) for row in delta.rows)
            metadata = {
                "dataset_version": "V2", "feature_engineering_version": FEATURE_ENGINEERING_VERSION,
                "source_min_part": old_meta.get("source_min_part", previous.as_of_part),
                "source_max_part": delta.delta_part, "finalized_through_part": delta.delta_part,
                "source_row_count": int(state.global_sums["raw_count"]), "source_part_counts": part_counts,
                "update_method": "aggregate_delta_v1", "previous_as_of_part": previous.as_of_part,
                "previous_history_sha256": old_meta["artifact_sha256"]["course_history_state.pkl"],
                "delta_part": delta.delta_part, "delta_sha256": delta.delta_sha256,
                "applied_deltas": applied,
            }
            loaded, provenance = save_frozen_history_atomic(state, metadata, root=self.root)
            snapshot = HistorySnapshot(loaded, provenance)
            with self._active_lock:
                self._active = snapshot
            return {"status": "applied", "delta_part": delta.delta_part,
                    "delta_sha256": delta.delta_sha256, "history_as_of_part": snapshot.as_of_part,
                    "new_history_sha256": provenance["new_history_sha256"],
                    "cleanup_warnings": provenance["cleanup_warnings"]}
