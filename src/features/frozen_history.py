"""Immutable serving-history bundles, independent of model training artifacts.

The caller attests which outcomes are finalized. Each base bundle contains
course history and a metadata completion marker. A failed build leaves an incomplete,
unloadable directory; neither complete nor incomplete versions are overwritten.
Experimental specialty history is optional: its implementation must be supplied
explicitly by the caller, never imported by the Features layer.
Only load locally trusted pickle artifacts.
"""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import pickle
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from src import paths
from src.features.feature_contract import FEATURE_ENGINEERING_VERSION, require_current_features
from src.paths import (
    academic_part, course_history_state_path, frozen_history_dir,
    history_metadata_path, specialty_history_state_path,
)
from src.features.temporal_features import CourseHistoryState, load_course_history_state, save_course_history_state

HISTORY_SOURCE_COLUMNS = [
    "student_course_id", "part_id", "degree_id", "course_id", "faculty_id",
    "plan_requirement_type_id", "course_credits", "attempt_number",
    "final_mark",
]


def file_sha256(path):
    digest = sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def previous_academic_part(target_part):
    target = academic_part(target_part)
    return target - 1 if target % 10 > 1 else (target // 10 - 1) * 10 + 3


def validate_history_selection(target_part, history_as_of_part, *, allow_older_history=False):
    target, cutoff = academic_part(target_part), academic_part(history_as_of_part)
    previous = previous_academic_part(target)
    if cutoff >= target:
        raise ValueError("Target semester must follow frozen history; target/future outcomes are forbidden.")
    if cutoff != previous and not allow_older_history:
        raise ValueError("History is older than the previous academic part; explicitly set allow_older_history for backtesting.")
    return {
        "target_part": target, "history_as_of_part": cutoff,
        "previous_academic_part": previous,
        "history_is_previous_part": cutoff == previous,
        "allow_older_history": bool(allow_older_history),
    }


def validate_history_pair(course, specialty, as_of_part):
    """Check the base cutoff and any explicitly supplied specialty history."""
    cutoff = academic_part(as_of_part)
    if course.as_of_part != cutoff or (specialty is not None and specialty.as_of_part != cutoff):
        raise ValueError("Course and specialty history cutoffs must match the requested as_of_part.")


def build_frozen_history(outcomes, as_of_part, *, finalized_through_part, specialty_history_type=None,
                         dataset_version=None):
    """Return (course, optional specialty, metadata) from one finalized prefix.

    Base history needs no experimental features or points/failure labels.
    Legacy experimental callers may supply their history type explicitly; it
    must implement from_training(source) and use the same finalized cutoff.
    V2 callers must attest versioned source provenance in outcomes.attrs; their
    bundles contain only base course history.
    """
    if dataset_version not in (None, "V2"):
        raise ValueError("Unsupported frozen history dataset_version; expected V2 or None.")
    if dataset_version == "V2":
        if outcomes.attrs.get("dataset_version") != "V2":
            raise ValueError("V2 history sources must attest dataset_version=V2.")
        if specialty_history_type is not None:
            raise ValueError("Official V2 history cannot contain specialty history.")
    cutoff, finalized = academic_part(as_of_part), academic_part(finalized_through_part)
    if cutoff > finalized:
        raise ValueError("History cutoff exceeds finalized_through_part.")
    require_current_features(outcomes.attrs)
    source_columns = list(HISTORY_SOURCE_COLUMNS)
    if specialty_history_type is not None:
        source_columns.extend(["is_fail", "points"])
    missing = set(source_columns) - set(outcomes.columns)
    if missing:
        raise ValueError(f"History source missing columns: {sorted(missing)}")
    parts = pd.to_numeric(outcomes.part_id, errors="raise")
    if parts.isna().any() or not parts.eq(parts.astype("int64")).all():
        raise ValueError("History source parts must be known integers.")
    for part in parts.unique():
        academic_part(int(part))
    source = outcomes.loc[parts.le(cutoff), source_columns].copy()
    if source.empty or int(source.part_id.max()) != cutoff:
        raise ValueError("Source must contain outcomes through the exact requested as_of_part.")
    if source.student_course_id.isna().any() or source.student_course_id.duplicated().any():
        raise ValueError("History source must have unique, non-null student_course_id values.")
    numeric_columns = [
        column for column in ("course_credits", "attempt_number", "final_mark", "is_fail", "points")
        if column in source.columns
    ]
    numbers = source[numeric_columns].apply(pd.to_numeric)
    if not np.isfinite(numbers.to_numpy(dtype=float)).all():
        raise ValueError("History outcomes must be finalized, finite values.")
    if (numbers.course_credits.lt(0).any() or numbers.attempt_number.lt(1).any()
            or not numbers.final_mark.between(0, 100).all()):
        raise ValueError("History outcomes violate the existing mark/points/failure contract.")
    if (("points" in numbers and not numbers.points.between(0, 4).all())
            or ("is_fail" in numbers and not numbers.is_fail.eq(numbers.final_mark.lt(50)).all())):
        raise ValueError("History outcomes violate the existing mark/points/failure contract.")
    source = source.sort_values(["part_id", "student_course_id"], kind="stable").reset_index(drop=True)
    course = CourseHistoryState()
    for _, semester in source.groupby("part_id", sort=True):
        course.update(semester)
    specialty = None
    if specialty_history_type is not None:
        specialty = specialty_history_type.from_training(source.copy())
    validate_history_pair(course, specialty, cutoff)
    # Future rows can promote a whole pandas column from integer to float.
    # Canonicalize the fingerprint so those rows cannot change prefix identity.
    fingerprint_source = source.copy()
    fingerprint_source["part_id"] = fingerprint_source.part_id.astype("int64")
    for column in numbers:
        fingerprint_source[column] = pd.to_numeric(fingerprint_source[column]).astype("float64")
    metadata = {
        "finalized_through_part": finalized,
        "source_min_part": int(source.part_id.min()), "source_max_part": int(source.part_id.max()),
        "source_row_count": len(source),
        "source_part_counts": {str(int(k)): int(v) for k, v in source.groupby("part_id").size().items()},
        "selected_source_sha256": sha256(pd.util.hash_pandas_object(fingerprint_source, index=False).values.tobytes()).hexdigest(),
    }
    if dataset_version is not None:
        metadata["dataset_version"] = dataset_version
    return course, specialty, metadata


def verify_legacy_course_history(legacy_path, rebuilt):
    """Verify migration equivalence without altering the original artifact."""
    legacy = load_course_history_state(Path(legacy_path))
    if (legacy.as_of_part != rebuilt.as_of_part or legacy.smoothing_k != rebuilt.smoothing_k
            or legacy.min_support != rebuilt.min_support or legacy.global_sums != rebuilt.global_sums):
        raise ValueError("Legacy course history does not match the rebuilt source prefix.")
    for level in rebuilt.tables:
        try:
            assert_frame_equal(legacy.tables[level].sort_index(), rebuilt.tables[level].sort_index(),
                               check_exact=False, atol=1e-9, rtol=1e-12)
        except AssertionError as exc:
            raise ValueError(f"Legacy course history differs at level {level}.") from exc
    return legacy


def save_frozen_history(course, specialty, metadata, *, root=None):
    if metadata.get("dataset_version") == "V2":
        if specialty is not None:
            raise ValueError("Official V2 history cannot contain specialty history.")
        if root is None:
            root = paths.FROZEN_HISTORY_DIR
    cutoff = academic_part(course.as_of_part)
    validate_history_pair(course, specialty, cutoff)
    if metadata.get("source_max_part") != cutoff:
        raise ValueError("Metadata source_max_part must match the history cutoff.")
    finalized = academic_part(metadata["finalized_through_part"])
    if finalized < cutoff:
        raise ValueError("History extends beyond finalized outcomes.")
    directory = frozen_history_dir(cutoff, root)
    directory.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive reservation prevents concurrent writers or accidental replacement.
    directory.mkdir(exist_ok=False)
    course_path = course_history_state_path(cutoff, root)
    specialty_path = specialty_history_state_path(cutoff, root)
    save_course_history_state(course, course_path)
    artifact_paths = [course_path]
    if specialty is not None:
        with specialty_path.open("xb") as stream:
            pickle.dump({
                "format_version": 1, "as_of_part": cutoff,
                "global_totals": specialty.global_totals, "degree_totals": specialty.degree_totals,
                "requirement_totals": specialty.requirement_totals,
            }, stream)
        artifact_paths.append(specialty_path)
    payload = {
        **metadata, "format_version": 2, "as_of_part": cutoff,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "feature_engineering_version": FEATURE_ENGINEERING_VERSION,
        "history_type": "frozen_serving_history",
        "artifact_sha256": {p.name: file_sha256(p) for p in artifact_paths},
    }
    with history_metadata_path(cutoff, root).open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False, allow_nan=False)
    return payload


def load_frozen_history(as_of_part, *, root=None, specialty_history_type=None, dataset_version=None):
    """Load base history without Experiments, including from legacy bundles.

    The optional specialty result is None unless its type is supplied. Legacy
    specialty files still undergo hash and cutoff checks when present; callers
    requesting specialty history must provide a type accepting its saved fields.
    Requesting dataset_version=V2 uses the canonical history root by default and
    validates the serialized contract, rejecting specialty artifacts before opening them.
    """
    if dataset_version not in (None, "V2"):
        raise ValueError("Unsupported frozen history dataset_version; expected V2 or None.")
    if dataset_version == "V2":
        if specialty_history_type is not None:
            raise ValueError("Official V2 history cannot load specialty history.")
        if root is None:
            root = paths.FROZEN_HISTORY_DIR
    cutoff = academic_part(as_of_part)
    meta_path = history_metadata_path(cutoff, root)
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    if dataset_version is not None and metadata.get("dataset_version") != dataset_version:
        raise ValueError(f"Frozen history dataset_version must be {dataset_version}.")
    require_current_features(metadata)
    if (metadata.get("format_version") not in (1, 2) or metadata.get("history_type") != "frozen_serving_history"
            or metadata.get("as_of_part") != cutoff or metadata.get("source_max_part") != cutoff
            or academic_part(metadata["finalized_through_part"]) < cutoff):
        raise ValueError("Frozen history metadata/cutoff mismatch.")
    course_path = course_history_state_path(cutoff, root)
    specialty_path = specialty_history_state_path(cutoff, root)
    if dataset_version == "V2" and (
            specialty_path.exists() or specialty_path.name in metadata["artifact_sha256"]
            or metadata["format_version"] == 1):
        raise ValueError("Official V2 history must be base-only; specialty artifacts are forbidden.")
    artifact_paths = [course_path]
    if metadata["format_version"] == 1 or specialty_path.name in metadata["artifact_sha256"]:
        artifact_paths.append(specialty_path)
    if specialty_history_type is not None and specialty_path not in artifact_paths:
        raise ValueError("This base history bundle contains no specialty history.")
    for path in artifact_paths:
        if file_sha256(path) != metadata["artifact_sha256"].get(path.name):
            raise ValueError(f"Frozen history hash mismatch: {path.name}")
    course = load_course_history_state(course_path)
    specialty = None
    if specialty_path in artifact_paths:
        with specialty_path.open("rb") as stream:
            payload = pickle.load(stream)
        if payload.get("format_version") != 1:
            raise ValueError("Unsupported specialty history format.")
        if payload.get("as_of_part") != cutoff:
            raise ValueError("Course and specialty history cutoffs must match the requested as_of_part.")
        if specialty_history_type is not None:
            specialty = specialty_history_type(**{k: payload[k] for k in (
                "as_of_part", "global_totals", "degree_totals", "requirement_totals",
            )})
    validate_history_pair(course, specialty, cutoff)
    provenance = {**metadata, "directory": str(meta_path.parent.resolve()), "metadata_sha256": file_sha256(meta_path)}
    return course, specialty, provenance


def save_frozen_history_atomic(course, metadata, *, root=None):
    """Stage/verify/publish a new base-only V2 bundle without replacing a version.

    Existing save/load behavior stays unchanged. A same-filesystem staging
    directory keeps partial files invisible to latest-bundle discovery. The
    exclusive publication guard serializes cooperating local writers. All
    verification and provenance construction finish before directory rename;
    the caller can then swap its active state without further filesystem I/O.
    """
    if metadata.get("dataset_version") != "V2":
        raise ValueError("Atomic history publication requires base-only V2 metadata.")
    root = Path(paths.FROZEN_HISTORY_DIR if root is None else root)
    destination = frozen_history_dir(course.as_of_part, root)
    root.mkdir(parents=True, exist_ok=True)
    temporary = TemporaryDirectory(prefix=".history-staging-", dir=root)
    cleanup_warnings = []
    try:
        staging = Path(temporary.name)
        saved = save_frozen_history(course, None, metadata, root=staging)
        # These fields identify the serialized state bytes, not a reweighted source.
        saved["new_history_sha256"] = saved["artifact_sha256"]["course_history_state.pkl"]
        saved["created_at"] = saved["created_at_utc"]
        meta_path = history_metadata_path(course.as_of_part, staging)
        meta_path.write_text(json.dumps(saved, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        loaded, _, provenance = load_frozen_history(course.as_of_part, root=staging, dataset_version="V2")
        if (loaded.global_sums != course.global_sums or loaded.smoothing_k != course.smoothing_k
                or loaded.min_support != course.min_support):
            raise ValueError("Reloaded history differs from the staged state.")
        for level in course.tables:
            assert_frame_equal(loaded.tables[level], course.tables[level], check_exact=True)
        provenance["directory"] = str(destination.resolve())
        provenance["cleanup_warnings"] = cleanup_warnings
        guard = root / f".publish_{destination.name}.lock"
        # An exclusive marker and destination check protect even an empty/incomplete
        # directory. Never use replace(), which can overwrite on some platforms.
        with guard.open("x", encoding="utf-8"):
            pass  # Close the handle before unlinking the exclusive marker on Windows.
        try:
            if destination.exists():
                raise FileExistsError(f"Frozen History destination already exists: {destination}")
            frozen_history_dir(course.as_of_part, staging).rename(destination)
        finally:
            try:
                guard.unlink()
            except OSError as exc:
                cleanup_warnings.append(f"Publication guard cleanup: {exc}")
    finally:
        try:
            temporary.cleanup()
        except OSError as exc:
            # Cleanup cannot turn a successful publish into a failed update.
            # A leftover hidden staging directory is never a loadable bundle.
            cleanup_warnings.append(f"Staging cleanup: {exc}")
    return loaded, provenance
