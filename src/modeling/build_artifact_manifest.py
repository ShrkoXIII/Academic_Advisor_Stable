"""Publish existing 33-feature assets byte-for-byte; never train or regenerate.

Run once from the repository root with:
    ./.venv/Scripts/python.exe -m src.modeling.build_artifact_manifest
"""
import ast
import argparse
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import shutil
import tempfile

from src import paths
from src.features.frozen_history import file_sha256
from src.recommendation.ranking_policy import (
    APPROVED_RANKING, UNRESOLVED_OPERATIONAL_CONTRACTS,
    balance_policy_contract, validate_ranking_policy,
)
from src.recommendation.two_stage_artifacts import (
    MANIFEST_VERSION, PREDICTION_CONTRACT, UNAPPROVED_RANKING,
    artifact_relative_paths, load_manifest_assets, project_file, read_artifact_json,
    stage_feature_contract, validate_stage_metadata, verify_artifact_hash,
)


def verify_training_sources(root, metadata):
    """Verify recorded fitting inputs before archiving their original signature."""
    relative = lambda path: path.relative_to(paths.PROJECT_ROOT).as_posix()
    required = {
        relative(path) for path in (
            paths.TEMPORAL_TRAIN_FEATURES_PATH, paths.TEMPORAL_TEST_FEATURES_PATH,
            paths.GRADE_MODEL_PATH, paths.FAIL_MODEL_PATH,
            paths.CATEGORY_LEVELS_PATH, paths.MODEL_METADATA_PATH,
        )
    } | {
        "src/modeling/train_models.py", "src/modeling/training_config.py",
        "src/features/feature_contract.py", "src/modeling/train_shortlist_models.py",
        "src/modeling/shortlist_features.py",
    }
    if set(metadata["input_sha256"]) != required:
        raise ValueError("Original course-only training signature is incomplete or unexpected.")
    for name, expected in metadata["input_sha256"].items():
        verify_artifact_hash(project_file(root, name), expected)
    config_path = project_file(root, "src/modeling/training_config.py")
    definitions = {
        target.id: node.value.value
        for node in ast.walk(ast.parse(config_path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
        for target in node.targets if isinstance(target, ast.Name)
    }
    if definitions.get("TARGET_GRADE") != "final_mark" or definitions.get("TARGET_FAIL") != "is_fail":
        raise ValueError("Verified training sources must use final_mark and is_fail targets.")
    builder_path = project_file(root, "src/features/build_temporal_features.py")
    builder = ast.parse(builder_path.read_text(encoding="utf-8"))
    fail_assignments = [
        node for node in ast.walk(builder) if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant)
                and target.slice.value == "is_fail" for target in node.targets)
    ]
    if not fail_assignments or any(
        "['final_mark'].lt(50).astype(" not in ast.unparse(node.value) for node in fail_assignments
    ):
        raise ValueError("Fail target source must define is_fail from final_mark < 50.")
    return {
        name: file_sha256(project_file(root, name)) for name in (
            "src/modeling/training_config.py", "src/features/build_temporal_features.py", "src/grade_scale.py",
        )
    }


def build_promotion_manifest(project_root):
    """Audit sources and pin both stages, preserving full original metadata."""
    root = Path(project_root).resolve()
    source_dir = project_file(root, paths.COURSE_ONLY_MODEL_DIR.relative_to(paths.PROJECT_ROOT).as_posix())
    source_metadata_path = source_dir / "model_metadata.json"
    source = read_artifact_json(source_metadata_path)
    source_evidence = verify_training_sources(root, source)
    for name in ("grade_regressor.txt", "fail_risk_classifier.txt", "category_levels.json"):
        verify_artifact_hash(source_dir / name, source["artifact_sha256"][name])
    official_relative = paths.MODEL_METADATA_PATH.relative_to(paths.PROJECT_ROOT).as_posix()
    official_path = project_file(root, official_relative)
    official = read_artifact_json(official_path)
    stages = {}
    for stage, metadata, metadata_path in (
        ("stage1", source, source_metadata_path), ("stage2", official, official_path),
    ):
        cutoff, basis = validate_stage_metadata(stage, metadata)
        relative = artifact_relative_paths(stage)
        originals = {
            "grade": source_dir / "grade_regressor.txt", "fail": source_dir / "fail_risk_classifier.txt",
            "category_levels": source_dir / "category_levels.json",
        } if stage == "stage1" else {key: project_file(root, name) for key, name in relative.items()}
        models = {
            role: {"path": relative[role], "sha256": file_sha256(originals[role]),
                   "target": target, "objective": objective}
            for role, target, objective in (("grade", "final_mark", "regression"), ("fail", "is_fail", "binary"))
        }
        models["fail"]["target_definition"] = "final_mark < 50"
        provenance = {
            "metadata_path": metadata_path.relative_to(root).as_posix(),
            "metadata_sha256": file_sha256(metadata_path), "metadata": deepcopy(metadata),
            "dataset_version_basis": "original_metadata.dataset_version" if stage == "stage1" else "official_V2_paths_and_verified_training_source",
            "target_basis": "verified_training_config_and_fail_definition_source_and_binary_objectives",
            "source_evidence_sha256_at_promotion": source_evidence.copy(),
        }
        if stage == "stage1":
            provenance["input_sha256_at_promotion"] = deepcopy(source["input_sha256"])
            provenance["source_artifact_sha256_at_promotion"] = {
                path.relative_to(root).as_posix(): file_sha256(path) for path in originals.values()
            }
        stages[stage] = {
            "feature_contract": stage_feature_contract(stage), "training_as_of_part": cutoff,
            "training_cutoff_basis": basis, "models": models,
            "category_levels": {"path": relative["category_levels"],
                                "sha256": file_sha256(originals["category_levels"]),
                                "levels": read_artifact_json(originals["category_levels"])},
            "provenance": provenance,
        }
    scale_relative = paths.GRADE_SCALE_PATH.relative_to(paths.PROJECT_ROOT).as_posix()
    scale_hash = file_sha256(project_file(root, scale_relative))
    return {
        "manifest_version": MANIFEST_VERSION, "dataset_version": "V2",
        "feature_engineering_version": source["feature_engineering_version"], "stages": stages,
        "grade_scale": {"path": scale_relative, "grade_scale_version": f"sha256:{scale_hash}",
                        "grade_scale_sha256": scale_hash},
        "prediction_contract": deepcopy(PREDICTION_CONTRACT), "ranking_approval": UNAPPROVED_RANKING.copy(),
    }


def promote_shortlist_artifacts(*, project_root=paths.PROJECT_ROOT,
                                approval_reference=None, approval_date=None):
    """Validate in staging, then publish a new directory without overwriting.

Failure before publication leaves no partial deployment. The source metadata,
experimental model bytes, official assets, datasets and history are read-only.
"""
    root = Path(project_root).resolve()
    destination = project_file(root, paths.SHORTLIST_MODEL_DIR.relative_to(paths.PROJECT_ROOT).as_posix())
    if destination.exists():
        raise FileExistsError(f"Shortlist promotion already exists; refuse overwrite: {destination}")
    manifest = build_promotion_manifest(root)
    if approval_reference is not None:
        if not isinstance(approval_reference, str) or not approval_reference.strip():
            raise ValueError("Preserved-policy approval requires an explicit user reference.")
        approved_on = date.fromisoformat(approval_date) if approval_date else date.today()
        identity = {"name": "pareto", "version": "v1"}
        evidence = "docs/api_contract.md"
        manifest["ranking_approval"] = APPROVED_RANKING.copy()
        manifest["ranking_policy"] = {
            "schema_version": 1,
            "stage1_shortlist_strategy": identity.copy(),
            "final_ranking_strategy": identity.copy(),
            "approved_combination": {
                "stage1_shortlist_strategy": identity.copy(),
                "final_ranking_strategy": identity.copy(),
            },
            "balance_policy": balance_policy_contract(),
            "operational_contracts": UNRESOLVED_OPERATIONAL_CONTRACTS.copy(),
            "human_approval": {
                "authority": "human_user", "basis": "stable_migration",
                "source": approval_reference, "date": approved_on.isoformat(),
                "rationale": ["Preserve the existing two-stage Pareto v1 and Balance business logic."],
                "limitations": ["Migration authorization is not independent academic approval of new model quality.",
                                "Operational limits remain unresolved."],
                "evidence": {"migration_contract": {
                    "path": evidence, "sha256": file_sha256(project_file(root, evidence)),
                }},
            },
        }
        validate_ranking_policy(manifest, require_approved=True)
    source_dir = project_file(root, paths.COURSE_ONLY_MODEL_DIR.relative_to(paths.PROJECT_ROOT).as_posix())
    with tempfile.TemporaryDirectory(prefix=".shortlist-", dir=destination.parent) as temporary:
        bundle = Path(temporary) / "bundle"
        bundle.mkdir()
        for original, copied in (("grade_regressor.txt", "grade_model.txt"),
                                 ("fail_risk_classifier.txt", "fail_model.txt"),
                                 ("category_levels.json", "category_levels.json")):
            shutil.copyfile(source_dir / original, bundle / copied)
        manifest_path = bundle / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8", newline="\n",
        )
        # Reload serialized evidence and validate all four binary headers before publish.
        load_manifest_assets(read_artifact_json(manifest_path), project_root=root, shortlist_directory=bundle)
        for name, expected in manifest["stages"]["stage1"]["provenance"]["input_sha256_at_promotion"].items():
            verify_artifact_hash(project_file(root, name), expected)
        verify_artifact_hash(source_dir / "model_metadata.json",
                             manifest["stages"]["stage1"]["provenance"]["metadata_sha256"])
        for role, name in (("grade", "grade_regressor.txt"), ("fail", "fail_risk_classifier.txt")):
            verify_artifact_hash(source_dir / name, manifest["stages"]["stage1"]["models"][role]["sha256"])
        verify_artifact_hash(source_dir / "category_levels.json", manifest["stages"]["stage1"]["category_levels"]["sha256"])
        if destination.exists():
            raise FileExistsError(f"Shortlist promotion appeared during validation: {destination}")
        bundle.rename(destination)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approval-reference")
    parser.add_argument("--approval-date")
    args = parser.parse_args()
    published = promote_shortlist_artifacts(approval_reference=args.approval_reference,
                                           approval_date=args.approval_date)
    print(f"Published byte-identical shortlist assets: {paths.SHORTLIST_MODEL_DIR}")
    print(f"Features: {published['stages']['stage1']['feature_contract']['feature_count']}; ranking: {published['ranking_approval']}")
