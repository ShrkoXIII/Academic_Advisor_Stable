# Phase 0 — Cleanup verification report

**Status — Complete. Awaiting review before Phase 1.** Cleanup followed the [reviewed inventory](PHASE_0_CLEANUP_INVENTORY.md) and the explicit exclusion of the entire `academic_advisor_stable.egg-info/` directory. No build, training, application run, or data tests were performed.

## Approved selection and outcome

- Deleted **154 files and 28 empty directories**, totaling 141,601,810 logical bytes (135.04 MiB).
- Before deletion, the original inventory fingerprint, all candidate file bytes, protected-tree fingerprint, raw file baselines, and Git index and HEAD matched the dry run.
- Excluding the five package metadata files and their directory produced the revised selection SHA-256 `9225b7d0d5219051c2e48a85b3d054743cac7803c6a6e728ff64a6907ddbdaeb`.
- Each file was rechecked before unlinking. Directories were removed deepest first and only when empty. No unlisted file or directory disappeared from the inspected tree.
- Failures: none. Remaining approved paths: none.

## Preserved paths

The complete trees `data/raw/`, `.venv/`, `academic_advisor_stable.egg-info/`, `.git/`, `config/`, `docs/`, and `.superpowers/` were preserved. The report is the sole addition to documentation. `src/`, `tools/`, and `tests/` retain every source, test, fixture and configuration file. Only their explicitly approved cache entries were removed.

Preserved root files are `.env`, `.env.example`, `.env.local`, `.gitattributes`, `.gitignore`, `AGENTS.md`, `README.md`, `pyproject.toml`, and `requirements.lock`. The checked protected files matched their pre-cleanup content hashes. Git HEAD and index were checked separately, and the installed environment was excluded from deletion and aggregate hashing.

The following intentionally preserved generated files matched their pre-cleanup SHA-256 hashes:

- `academic_advisor_stable.egg-info/PKG-INFO`
- `academic_advisor_stable.egg-info/SOURCES.txt`
- `academic_advisor_stable.egg-info/dependency_links.txt`
- `academic_advisor_stable.egg-info/requires.txt`
- `academic_advisor_stable.egg-info/top_level.txt`

The empty `artifacts/`, `artifacts/history/`, `models/`, and `models/active/` directories were intentionally preserved. External temporary paths were outside the scope.

## Raw data verification

All six raw files matched their original paths, SHA-256 hashes, sizes, and modification times from the dry run. No additional raw file appeared.

| Exact path | Bytes | Modification time (Unix ns) | SHA-256 verified after cleanup |
|---|---:|---|---|
| `data/raw/v_acd_degree_course.parquet` | 97968 | `1786270192418723400` | `13eafd910db4caead2132b17ce4a90d470dbaf691e488f14647e16a20efee848` |
| `data/raw/v_acs_grade.parquet` | 8363 | `1786268672792741500` | `557e1cb7b03b09d690d639c8d61c50e5e537360d0dec0684e6a283047111aad2` |
| `data/raw/v_add_academic_info.parquet` | 304641 | `1786266088705259000` | `bbaca16bd24c01602e02d35ee8be1068a33d6fa4ad6f1bb194a5caf7ad7cd3a3` |
| `data/raw/v_add_student_degree_status.parquet` | 6935286 | `1787487540249304100` | `8395641d4dfcfd4e731ead84a53d38b6593e7f5349abf75156f4a10a7a962371` |
| `data/raw/v_crg_std_cor_temp_request.parquet` | 4473901 | `1786271325592997100` | `1bd99cbb7abac635cbf9be6be7f2adb9718cfeb39fef0f9eca1f700262e10469` |
| `data/raw/v_crg_student_course_raw.parquet` | 15288890 | `1786268672536687100` | `bb25f5413d67cfb3fe41e24f4efee1b90330e4cbdd41a06dcddf91ea33081bba` |

## Git status

Before cleanup, `git status --short --untracked-files=all` listed:

```text
 M README.md
 M docs/CHANGELOG.md
 M docs/PIPELINE_AND_LOGIC_MAP.md
 M docs/architecture.md
 M src/api/service.py
 M src/main.py
 M src/recommendation/inputs.py
 M src/recommendation/two_stage_artifacts.py
 M tests/unit/test_main_runner.py
 M tests/unit/test_stable_ui_views.py
 M tests/unit/test_two_stage_payloads.py
 M tools/academic_advisor_streamlit/streamlit_app.py
 M tools/academic_advisor_streamlit/views.py
?? docs/reports/PHASE_0_CLEANUP_INVENTORY.md
?? docs/reports/PROJECT_BUILD_AUDIT.md
?? docs/reports/STABILIZATION_VERIFICATION_REPORT.md
?? docs/superpowers/plans/2026-11-16-remove-local-recommendation-pipeline.md
?? src/evaluation/local_course_inputs.py
```

After cleanup, `git status --short` returned the following. The untracked `docs/reports/` entry groups the existing reports and this report. HEAD and index are unchanged. The detailed status before writing this report matched the pre-cleanup status.

```text
 M README.md
 M docs/CHANGELOG.md
 M docs/PIPELINE_AND_LOGIC_MAP.md
 M docs/architecture.md
 M src/api/service.py
 M src/main.py
 M src/recommendation/inputs.py
 M src/recommendation/two_stage_artifacts.py
 M tests/unit/test_main_runner.py
 M tests/unit/test_stable_ui_views.py
 M tests/unit/test_two_stage_payloads.py
 M tools/academic_advisor_streamlit/streamlit_app.py
 M tools/academic_advisor_streamlit/views.py
?? docs/reports/
?? docs/superpowers/plans/2026-11-16-remove-local-recommendation-pipeline.md
?? src/evaluation/local_course_inputs.py
```

## Exact deleted paths

<details>
<summary>154 files</summary>

- `.pytest_cache/.gitignore`
- `.pytest_cache/CACHEDIR.TAG`
- `.pytest_cache/README.md`
- `.pytest_cache/v/cache/lastfailed`
- `.pytest_cache/v/cache/nodeids`
- `data/artifacts/course_history_state.pkl`
- `data/artifacts/history/as_of_20243/course_history_state.pkl`
- `data/artifacts/history/as_of_20243/metadata.json`
- `data/artifacts/history/as_of_20251/course_history_state.pkl`
- `data/artifacts/history/as_of_20251/metadata.json`
- `data/clean/degree_course.parquet`
- `data/clean/registration_roster.parquet`
- `data/clean/student_course.parquet`
- `data/clean/student_course_enriched.parquet`
- `data/clean/student_course_pre_common.parquet`
- `data/clean/student_diploma.parquet`
- `data/clean/student_status.parquet`
- `data/clean/student_status_pre_common.parquet`
- `data/evaluation/plan_gpa_course_predictions_2025.parquet`
- `data/evaluation/plan_gpa_evaluation_2025.parquet`
- `data/evaluation/plan_gpa_metrics_2025.json`
- `data/features/temporal_test_features.parquet`
- `data/features/temporal_train_features.parquet`
- `data/merged/outlier_students.parquet`
- `data/merged/student_course_enriched_with_diploma.parquet`
- `data/merged/student_course_enriched_without_outliers.parquet`
- `data/temporal/temporal_test.parquet`
- `data/temporal/temporal_test_roster.parquet`
- `data/temporal/temporal_train.parquet`
- `data/temporal/temporal_train_roster.parquet`
- `src/__pycache__/__init__.cpython-311.pyc`
- `src/__pycache__/grade_scale.cpython-311.pyc`
- `src/__pycache__/main.cpython-311.pyc`
- `src/__pycache__/paths.cpython-311.pyc`
- `src/api/__pycache__/__init__.cpython-311.pyc`
- `src/api/__pycache__/app.cpython-311.pyc`
- `src/api/__pycache__/catalog.cpython-311.pyc`
- `src/api/__pycache__/request_store.cpython-311.pyc`
- `src/api/__pycache__/schemas.cpython-311.pyc`
- `src/api/__pycache__/service.cpython-311.pyc`
- `src/api/__pycache__/settings.cpython-311.pyc`
- `src/api/adapters/__pycache__/__init__.cpython-311.pyc`
- `src/api/adapters/__pycache__/courses.cpython-311.pyc`
- `src/api/adapters/__pycache__/history.cpython-311.pyc`
- `src/api/adapters/__pycache__/student.cpython-311.pyc`
- `src/api/validators/__pycache__/__init__.cpython-311.pyc`
- `src/api/validators/__pycache__/common.cpython-311.pyc`
- `src/api/validators/__pycache__/courses.cpython-311.pyc`
- `src/api/validators/__pycache__/history.cpython-311.pyc`
- `src/api/validators/__pycache__/student.cpython-311.pyc`
- `src/data/__pycache__/__init__.cpython-311.pyc`
- `src/data/__pycache__/academic_calendar.cpython-311.pyc`
- `src/data/building/__pycache__/__init__.cpython-311.pyc`
- `src/data/building/__pycache__/build_registration_roster.cpython-311.pyc`
- `src/data/building/__pycache__/build_student_course_enriched.cpython-311.pyc`
- `src/data/building/__pycache__/build_temporal_split.cpython-311.pyc`
- `src/data/building/__pycache__/filter_common_students.cpython-311.pyc`
- `src/data/cleaning/__pycache__/__init__.cpython-311.pyc`
- `src/data/cleaning/__pycache__/clean_degree_course.cpython-311.pyc`
- `src/data/cleaning/__pycache__/clean_outliers.cpython-311.pyc`
- `src/data/cleaning/__pycache__/clean_student_course.cpython-311.pyc`
- `src/data/cleaning/__pycache__/clean_student_diploma.cpython-311.pyc`
- `src/data/cleaning/__pycache__/clean_student_status.cpython-311.pyc`
- `src/data/cleaning/__pycache__/cleaning_utils.cpython-311.pyc`
- `src/evaluation/__pycache__/__init__.cpython-311.pyc`
- `src/evaluation/__pycache__/evaluate_plan_gpa.cpython-311.pyc`
- `src/evaluation/__pycache__/local_course_inputs.cpython-311.pyc`
- `src/evaluation/__pycache__/observed_plan.cpython-311.pyc`
- `src/features/__pycache__/__init__.cpython-311.pyc`
- `src/features/__pycache__/build_frozen_history.cpython-311.pyc`
- `src/features/__pycache__/feature_contract.cpython-311.pyc`
- `src/features/__pycache__/frozen_history.cpython-311.pyc`
- `src/features/__pycache__/temporal_features.cpython-311.pyc`
- `src/modeling/__pycache__/__init__.cpython-311.pyc`
- `src/modeling/__pycache__/build_artifact_manifest.cpython-311.pyc`
- `src/modeling/__pycache__/shortlist_features.cpython-311.pyc`
- `src/modeling/__pycache__/train_models.cpython-311.pyc`
- `src/modeling/__pycache__/train_shortlist_models.cpython-311.pyc`
- `src/modeling/__pycache__/training_config.cpython-311.pyc`
- `src/recommendation/__pycache__/__init__.cpython-311.pyc`
- `src/recommendation/__pycache__/balance_policy.cpython-311.pyc`
- `src/recommendation/__pycache__/constraints.cpython-311.pyc`
- `src/recommendation/__pycache__/course_status.cpython-311.pyc`
- `src/recommendation/__pycache__/cumulative_history.cpython-311.pyc`
- `src/recommendation/__pycache__/history_update.cpython-311.pyc`
- `src/recommendation/__pycache__/inputs.cpython-311.pyc`
- `src/recommendation/__pycache__/plan_generation.cpython-311.pyc`
- `src/recommendation/__pycache__/plan_scoring.cpython-311.pyc`
- `src/recommendation/__pycache__/ranking.cpython-311.pyc`
- `src/recommendation/__pycache__/ranking_policy.cpython-311.pyc`
- `src/recommendation/__pycache__/shortlist.cpython-311.pyc`
- `src/recommendation/__pycache__/two_stage_artifacts.cpython-311.pyc`
- `src/recommendation/__pycache__/two_stage_engine.cpython-311.pyc`
- `tests/__pycache__/__init__.cpython-311.pyc`
- `tests/__pycache__/synthetic_api.cpython-311.pyc`
- `tests/integration/__pycache__/__init__.cpython-311.pyc`
- `tests/integration/__pycache__/test_api_stable.cpython-311-pytest-9.1.1.pyc`
- `tests/integration/__pycache__/test_api_stable.cpython-311.pyc`
- `tests/integration/__pycache__/test_streamlit_stable.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/__init__.cpython-311.pyc`
- `tests/unit/__pycache__/recommendation_fixtures.cpython-311.pyc`
- `tests/unit/__pycache__/test_academic_calendar.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_api_portable_settings.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_api_request_store.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_balance_policy.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_build_registration_roster.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_build_student_course_enriched.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_build_temporal_split.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_candidate_input_contract.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_clean_degree_course.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_clean_outliers.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_clean_student_course.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_clean_student_diploma.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_clean_student_status.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_clean_utils.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_cumulative_history.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_evaluate_plan_gpa.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_feature_contract_responsibilities.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_filter_common_students.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_fresh_artifact_metadata.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_frozen_history.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_grade_scale.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_history_update.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_main_runner.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_migration_ranking_provenance.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_observed_plan.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_ranking_strategies.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_release_example.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_release_packages.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_runtime_catalog.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_stable_ui_views.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_standalone_staging.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_standalone_timeout.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_temporal_features.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_train_models.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_training_config.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_two_stage_activation.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_two_stage_activation.cpython-311.pyc`
- `tests/unit/__pycache__/test_two_stage_artifacts.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_two_stage_artifacts.cpython-311.pyc`
- `tests/unit/__pycache__/test_two_stage_constraints.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_two_stage_engine.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_two_stage_matrix.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_two_stage_payloads.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_two_stage_shortlist.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/test_ui_client.cpython-311-pytest-9.1.1.pyc`
- `tests/unit/__pycache__/two_stage_fixtures.cpython-311.pyc`
- `tools/__pycache__/__init__.cpython-311.pyc`
- `tools/__pycache__/prepare_release.cpython-311.pyc`
- `tools/__pycache__/verify_release.cpython-311.pyc`
- `tools/__pycache__/verify_standalone.cpython-311.pyc`
- `tools/academic_advisor_streamlit/__pycache__/__init__.cpython-311.pyc`
- `tools/academic_advisor_streamlit/__pycache__/ui_client.cpython-311.pyc`
- `tools/academic_advisor_streamlit/__pycache__/views.cpython-311.pyc`

</details>

<details>
<summary>28 directories, in deletion order</summary>

- `src/data/cleaning/__pycache__/`
- `src/data/building/__pycache__/`
- `src/api/validators/__pycache__/`
- `src/api/adapters/__pycache__/`
- `data/artifacts/history/as_of_20251/`
- `data/artifacts/history/as_of_20243/`
- `tools/academic_advisor_streamlit/__pycache__/`
- `tests/unit/__pycache__/`
- `tests/integration/__pycache__/`
- `src/recommendation/__pycache__/`
- `src/modeling/__pycache__/`
- `src/features/__pycache__/`
- `src/evaluation/__pycache__/`
- `src/data/__pycache__/`
- `src/api/__pycache__/`
- `data/artifacts/history/`
- `.pytest_cache/v/cache/`
- `tools/__pycache__/`
- `tests/__pycache__/`
- `src/__pycache__/`
- `data/temporal/`
- `data/merged/`
- `data/features/`
- `data/evaluation/`
- `data/clean/`
- `data/artifacts/`
- `.pytest_cache/v/`
- `.pytest_cache/`

</details>

The workspace is ready for review of Phase 0. Generated datasets, features, frozen serving history, and evaluation outputs covered by the approval are absent.
