# Phase 0 — Cleanup inventory and approval gate

**Status — Dry run complete. Awaiting explicit approval.** No deletion, move, rebuild, training, or Git mutation was performed. The only new project file is this inventory. All relative paths refer to the current `Academic_Advisor_Stable` checkout.

## A. Preservation inventory

| Classification | Preserve |
|---|---|
| Raw source data | The entire `data/raw/` tree, including the raw request export even though the production recommendation path does not use it. All six regular files are listed below. The raw tree currently contains no nested directories or reparse points. |
| Source code | All source files under `src/` and `tools/`, including existing untracked source. Only the exact bytecode files and their cache directories in section B are proposed for removal. |
| Tests | Test code, fixtures, utilities and test configuration under `tests/`, including empty `tests/e2e/`. Only the exact test bytecode and pytest cache paths in section B are proposed for removal. |
| Configuration | `pyproject.toml`, `requirements.lock`, `.env`, `.env.local`, `.env.example`, root `.gitignore`, `.gitattributes`, `AGENTS.md`, `config/`, and any other checked-in settings. No environment values are recorded in this report. |
| Installed environment | All of `.venv/`, including its configuration, interpreter, installed dependencies and their internal files. Its separately generated project-root `.egg-info/` is listed in section B. |
| Documentation and other work | Root `README.md`, all `docs/`, prior audit and stabilization reports, migration evidence, plans, and `.superpowers/` review records. Generated pytest copies of `README.md` and `.gitignore` are distinguished by their exact cache paths. |
| Git | Entire `.git/`, the index, branch history, and existing staged, unstaged and untracked work. |
| Ambiguous or outside scope | Empty legacy-looking paths and unchecked external locations listed in section D. |

### Raw file baseline

These SHA-256 hashes were computed directly from the file bytes without opening the Parquets as datasets. The modification times are reported in nanoseconds since the Unix epoch for the later preservation check.

| Exact relative path | Bytes | Modification time (ns) | SHA-256 |
|---|---:|---|---|
| `data/raw/v_acd_degree_course.parquet` | 97,968 | `1786270192418723400` | `13eafd910db4caead2132b17ce4a90d470dbaf691e488f14647e16a20efee848` |
| `data/raw/v_acs_grade.parquet` | 8,363 | `1786268672792741500` | `557e1cb7b03b09d690d639c8d61c50e5e537360d0dec0684e6a283047111aad2` |
| `data/raw/v_add_academic_info.parquet` | 304,641 | `1786266088705259000` | `bbaca16bd24c01602e02d35ee8be1068a33d6fa4ad6f1bb194a5caf7ad7cd3a3` |
| `data/raw/v_add_student_degree_status.parquet` | 6,935,286 | `1787487540249304100` | `8395641d4dfcfd4e731ead84a53d38b6593e7f5349abf75156f4a10a7a962371` |
| `data/raw/v_crg_std_cor_temp_request.parquet` | 4,473,901 | `1786271325592997100` | `1bd99cbb7abac635cbf9be6be7f2adb9718cfeb39fef0f9eca1f700262e10469` |
| `data/raw/v_crg_student_course_raw.parquet` | 15,288,890 | `1786268672536687100` | `bb25f5413d67cfb3fe41e24f4efee1b90330e4cbdd41a06dcddf91ea33081bba` |

### Git baseline

Branch `data_cleaning`. HEAD `d9c401920810d72050ced3af1df24551da54a928`. The index has 150 entries by path and no staged changes. SHA-256 of the `git ls-files --stage -z` byte stream: `b23f1042d2c582d1537e6bab7eef58af71c08275a53f3ddb9a76a6df0f75cc67`.

`git status --short --untracked-files=all`, before creating this report:

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
?? docs/reports/PROJECT_BUILD_AUDIT.md
?? docs/reports/STABILIZATION_VERIFICATION_REPORT.md
?? docs/superpowers/plans/2026-11-16-remove-local-recommendation-pipeline.md
?? src/evaluation/local_course_inputs.py
```

All proposed files were checked against `git ls-files` and `git check-ignore`: **0 tracked files, 159 ignored files**. No proposed directory contains a tracked path. Git warned that it could not read the user-level ignore file. The repository ignore and cache-local ignore checks still identified every proposed file.

## B. Exact deletion inventory for approval

The directory rows authorize removal of those directories **only once empty** after deleting the specified files. They do not authorize deleting new, unlisted contents. Directory bytes below are totals of listed descendant files, repeated across parent and child rows. The total in section E counts each file once.

### Directories

| Exact relative path | Type | Generated reason (section C) | Git | Descendant files | Descendant logical bytes |
|---|---|---|---|---:|---:|
| `.pytest_cache/` | Directory | C1 | Untracked, no tracked descendants | 5 | 124,922 |
| `.pytest_cache/v/` | Directory | C1 | Untracked, no tracked descendants | 2 | 124,392 |
| `.pytest_cache/v/cache/` | Directory | C1 | Untracked, no tracked descendants | 2 | 124,392 |
| `academic_advisor_stable.egg-info/` | Directory | P1 | Untracked, no tracked descendants | 5 | 2,040 |
| `data/artifacts/` | Directory | F1/H1 | Untracked, no tracked descendants | 5 | 834,809 |
| `data/artifacts/history/` | Directory | H1 | Untracked, no tracked descendants | 4 | 562,957 |
| `data/artifacts/history/as_of_20243/` | Directory | H1 | Untracked, no tracked descendants | 2 | 272,875 |
| `data/artifacts/history/as_of_20251/` | Directory | H1 | Untracked, no tracked descendants | 2 | 290,082 |
| `data/clean/` | Directory | D | Untracked, no tracked descendants | 8 | 40,512,837 |
| `data/evaluation/` | Directory | E1 | Untracked, no tracked descendants | 3 | 2,757,930 |
| `data/features/` | Directory | F1 | Untracked, no tracked descendants | 2 | 39,018,733 |
| `data/merged/` | Directory | D | Untracked, no tracked descendants | 3 | 33,885,587 |
| `data/temporal/` | Directory | D | Untracked, no tracked descendants | 4 | 22,297,311 |
| `src/__pycache__/` | Directory | C2 | Untracked, no tracked descendants | 4 | 22,043 |
| `src/api/__pycache__/` | Directory | C2 | Untracked, no tracked descendants | 7 | 108,315 |
| `src/api/adapters/__pycache__/` | Directory | C2 | Untracked, no tracked descendants | 4 | 19,554 |
| `src/api/validators/__pycache__/` | Directory | C2 | Untracked, no tracked descendants | 5 | 50,180 |
| `src/data/__pycache__/` | Directory | C2 | Untracked, no tracked descendants | 2 | 2,687 |
| `src/data/building/__pycache__/` | Directory | C2 | Untracked, no tracked descendants | 5 | 16,551 |
| `src/data/cleaning/__pycache__/` | Directory | C2 | Untracked, no tracked descendants | 7 | 37,547 |
| `src/evaluation/__pycache__/` | Directory | C2 | Untracked, no tracked descendants | 4 | 33,406 |
| `src/features/__pycache__/` | Directory | C2 | Untracked, no tracked descendants | 5 | 58,198 |
| `src/modeling/__pycache__/` | Directory | C2 | Untracked, no tracked descendants | 6 | 54,335 |
| `src/recommendation/__pycache__/` | Directory | C2 | Untracked, no tracked descendants | 14 | 212,008 |
| `tests/__pycache__/` | Directory | C2 | Untracked, no tracked descendants | 2 | 5,352 |
| `tests/integration/__pycache__/` | Directory | C2 | Untracked, no tracked descendants | 4 | 50,507 |
| `tests/unit/__pycache__/` | Directory | C2 | Untracked, no tracked descendants | 48 | 1,396,676 |
| `tools/__pycache__/` | Directory | C2 | Untracked, no tracked descendants | 4 | 55,538 |
| `tools/academic_advisor_streamlit/__pycache__/` | Directory | C2 | Untracked, no tracked descendants | 3 | 46,784 |

### Dataset, feature, history and evaluation files

| Exact relative path | Type | Generated output and writer code | Git | Logical bytes |
|---|---|---|---|---:|
| `data/artifacts/course_history_state.pkl` | File | Feature export or training history (F1) | Ignored / untracked | 271,852 |
| `data/artifacts/history/as_of_20243/course_history_state.pkl` | File | Frozen history bundle (H1) | Ignored / untracked | 271,865 |
| `data/artifacts/history/as_of_20243/metadata.json` | File | Frozen history bundle (H1) | Ignored / untracked | 1,010 |
| `data/artifacts/history/as_of_20251/course_history_state.pkl` | File | Frozen history bundle (H1) | Ignored / untracked | 288,889 |
| `data/artifacts/history/as_of_20251/metadata.json` | File | Frozen history bundle (H1) | Ignored / untracked | 1,193 |
| `data/clean/degree_course.parquet` | File | Cleaned catalog (D1) | Ignored / untracked | 102,257 |
| `data/clean/registration_roster.parquet` | File | Registration roster (D2) | Ignored / untracked | 6,309,908 |
| `data/clean/student_course.parquet` | File | Common-student dataset (D3) | Ignored / untracked | 4,873,590 |
| `data/clean/student_course_enriched.parquet` | File | Enriched course dataset (D4) | Ignored / untracked | 17,561,262 |
| `data/clean/student_course_pre_common.parquet` | File | Pre-common course dataset (D5) | Ignored / untracked | 4,919,126 |
| `data/clean/student_diploma.parquet` | File | Diploma dataset (D6) | Ignored / untracked | 286,165 |
| `data/clean/student_status.parquet` | File | Common-student dataset (D3) | Ignored / untracked | 3,209,662 |
| `data/clean/student_status_pre_common.parquet` | File | Pre-common status dataset (D7) | Ignored / untracked | 3,250,867 |
| `data/evaluation/plan_gpa_course_predictions_2025.parquet` | File | Observed-plan evaluation output (E1) | Ignored / untracked | 2,474,851 |
| `data/evaluation/plan_gpa_evaluation_2025.parquet` | File | Observed-plan evaluation output (E1) | Ignored / untracked | 281,213 |
| `data/evaluation/plan_gpa_metrics_2025.json` | File | Observed-plan evaluation output (E1) | Ignored / untracked | 1,866 |
| `data/features/temporal_test_features.parquet` | File | Feature export or training history (F1) | Ignored / untracked | 6,525,068 |
| `data/features/temporal_train_features.parquet` | File | Feature export or training history (F1) | Ignored / untracked | 32,493,665 |
| `data/merged/outlier_students.parquet` | File | Outlier dataset or audit (D8) | Ignored / untracked | 15,297 |
| `data/merged/student_course_enriched_with_diploma.parquet` | File | Diploma dataset (D6) | Ignored / untracked | 17,631,223 |
| `data/merged/student_course_enriched_without_outliers.parquet` | File | Outlier dataset or audit (D8) | Ignored / untracked | 16,239,067 |
| `data/temporal/temporal_test.parquet` | File | Temporal outcome split (D9) | Ignored / untracked | 2,584,579 |
| `data/temporal/temporal_test_roster.parquet` | File | Registration roster (D2) | Ignored / untracked | 1,107,962 |
| `data/temporal/temporal_train.parquet` | File | Temporal outcome split (D9) | Ignored / untracked | 13,357,250 |
| `data/temporal/temporal_train_roster.parquet` | File | Registration roster (D2) | Ignored / untracked | 5,247,520 |

### Package metadata files

The metadata header identifies the project as `academic-advisor-stable`. These files are setuptools output. The installed distribution metadata and editable import hook in `.venv/` are outside this list.

| Exact relative path | Type | Generated output and writer code | Git | Logical bytes |
|---|---|---|---|---:|
| `academic_advisor_stable.egg-info/PKG-INFO` | File | Generated package metadata (P1) | Ignored / untracked | 766 |
| `academic_advisor_stable.egg-info/SOURCES.txt` | File | Generated package metadata (P1) | Ignored / untracked | 1,062 |
| `academic_advisor_stable.egg-info/dependency_links.txt` | File | Generated package metadata (P1) | Ignored / untracked | 1 |
| `academic_advisor_stable.egg-info/requires.txt` | File | Generated package metadata (P1) | Ignored / untracked | 207 |
| `academic_advisor_stable.egg-info/top_level.txt` | File | Generated package metadata (P1) | Ignored / untracked | 4 |

### Cache files

The cache headers identify `.pytest_cache/` as generated by pytest. Its nested metadata files are distinct from the repository's protected configuration and documentation.

<details>
<summary>Exact cache file list (129 files)</summary>

| Exact relative path | Type | Generated output and writer code | Git | Logical bytes |
|---|---|---|---|---:|
| `.pytest_cache/.gitignore` | File | Pytest cache (C1) | Ignored / untracked | 37 |
| `.pytest_cache/CACHEDIR.TAG` | File | Pytest cache (C1) | Ignored / untracked | 191 |
| `.pytest_cache/README.md` | File | Pytest cache (C1) | Ignored / untracked | 302 |
| `.pytest_cache/v/cache/lastfailed` | File | Pytest cache (C1) | Ignored / untracked | 13,777 |
| `.pytest_cache/v/cache/nodeids` | File | Pytest cache (C1) | Ignored / untracked | 110,615 |
| `src/__pycache__/__init__.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 168 |
| `src/__pycache__/grade_scale.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 4,496 |
| `src/__pycache__/main.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 11,828 |
| `src/__pycache__/paths.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 5,551 |
| `src/api/__pycache__/__init__.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 172 |
| `src/api/__pycache__/app.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 19,385 |
| `src/api/__pycache__/catalog.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 850 |
| `src/api/__pycache__/request_store.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 27,411 |
| `src/api/__pycache__/schemas.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 9,639 |
| `src/api/__pycache__/service.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 34,086 |
| `src/api/__pycache__/settings.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 16,772 |
| `src/api/adapters/__pycache__/__init__.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 256 |
| `src/api/adapters/__pycache__/courses.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 5,013 |
| `src/api/adapters/__pycache__/history.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 2,251 |
| `src/api/adapters/__pycache__/student.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 12,034 |
| `src/api/validators/__pycache__/__init__.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 258 |
| `src/api/validators/__pycache__/common.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 11,144 |
| `src/api/validators/__pycache__/courses.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 18,208 |
| `src/api/validators/__pycache__/history.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 3,095 |
| `src/api/validators/__pycache__/student.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 17,475 |
| `src/data/__pycache__/__init__.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 173 |
| `src/data/__pycache__/academic_calendar.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 2,514 |
| `src/data/building/__pycache__/__init__.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 182 |
| `src/data/building/__pycache__/build_registration_roster.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 5,609 |
| `src/data/building/__pycache__/build_student_course_enriched.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 2,551 |
| `src/data/building/__pycache__/build_temporal_split.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 4,140 |
| `src/data/building/__pycache__/filter_common_students.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 4,069 |
| `src/data/cleaning/__pycache__/__init__.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 182 |
| `src/data/cleaning/__pycache__/clean_degree_course.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 2,787 |
| `src/data/cleaning/__pycache__/clean_outliers.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 10,190 |
| `src/data/cleaning/__pycache__/clean_student_course.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 6,488 |
| `src/data/cleaning/__pycache__/clean_student_diploma.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 5,954 |
| `src/data/cleaning/__pycache__/clean_student_status.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 9,384 |
| `src/data/cleaning/__pycache__/cleaning_utils.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 2,562 |
| `src/evaluation/__pycache__/__init__.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 179 |
| `src/evaluation/__pycache__/evaluate_plan_gpa.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 10,872 |
| `src/evaluation/__pycache__/local_course_inputs.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 11,190 |
| `src/evaluation/__pycache__/observed_plan.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 11,165 |
| `src/features/__pycache__/__init__.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 177 |
| `src/features/__pycache__/build_frozen_history.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 5,461 |
| `src/features/__pycache__/feature_contract.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 5,383 |
| `src/features/__pycache__/frozen_history.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 22,842 |
| `src/features/__pycache__/temporal_features.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 24,335 |
| `src/modeling/__pycache__/__init__.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 177 |
| `src/modeling/__pycache__/build_artifact_manifest.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 17,778 |
| `src/modeling/__pycache__/shortlist_features.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 1,945 |
| `src/modeling/__pycache__/train_models.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 20,243 |
| `src/modeling/__pycache__/train_shortlist_models.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 13,276 |
| `src/modeling/__pycache__/training_config.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 916 |
| `src/recommendation/__pycache__/__init__.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 183 |
| `src/recommendation/__pycache__/balance_policy.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 10,109 |
| `src/recommendation/__pycache__/constraints.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 13,076 |
| `src/recommendation/__pycache__/course_status.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 2,638 |
| `src/recommendation/__pycache__/cumulative_history.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 41,124 |
| `src/recommendation/__pycache__/history_update.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 31,819 |
| `src/recommendation/__pycache__/inputs.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 15,820 |
| `src/recommendation/__pycache__/plan_generation.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 7,851 |
| `src/recommendation/__pycache__/plan_scoring.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 7,226 |
| `src/recommendation/__pycache__/ranking.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 20,457 |
| `src/recommendation/__pycache__/ranking_policy.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 8,288 |
| `src/recommendation/__pycache__/shortlist.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 5,228 |
| `src/recommendation/__pycache__/two_stage_artifacts.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 25,416 |
| `src/recommendation/__pycache__/two_stage_engine.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 22,773 |
| `tests/__pycache__/__init__.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 170 |
| `tests/__pycache__/synthetic_api.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 5,182 |
| `tests/integration/__pycache__/__init__.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 182 |
| `tests/integration/__pycache__/test_api_stable.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 28,697 |
| `tests/integration/__pycache__/test_api_stable.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 9,812 |
| `tests/integration/__pycache__/test_streamlit_stable.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 11,816 |
| `tests/unit/__pycache__/__init__.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 175 |
| `tests/unit/__pycache__/recommendation_fixtures.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 5,953 |
| `tests/unit/__pycache__/test_academic_calendar.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 6,201 |
| `tests/unit/__pycache__/test_api_portable_settings.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 4,743 |
| `tests/unit/__pycache__/test_api_request_store.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 75,501 |
| `tests/unit/__pycache__/test_balance_policy.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 38,899 |
| `tests/unit/__pycache__/test_build_registration_roster.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 17,475 |
| `tests/unit/__pycache__/test_build_student_course_enriched.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 9,840 |
| `tests/unit/__pycache__/test_build_temporal_split.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 8,649 |
| `tests/unit/__pycache__/test_candidate_input_contract.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 2,520 |
| `tests/unit/__pycache__/test_clean_degree_course.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 9,670 |
| `tests/unit/__pycache__/test_clean_outliers.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 26,549 |
| `tests/unit/__pycache__/test_clean_student_course.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 53,946 |
| `tests/unit/__pycache__/test_clean_student_diploma.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 15,079 |
| `tests/unit/__pycache__/test_clean_student_status.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 53,027 |
| `tests/unit/__pycache__/test_clean_utils.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 13,162 |
| `tests/unit/__pycache__/test_cumulative_history.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 127,251 |
| `tests/unit/__pycache__/test_evaluate_plan_gpa.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 34,531 |
| `tests/unit/__pycache__/test_feature_contract_responsibilities.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 9,016 |
| `tests/unit/__pycache__/test_filter_common_students.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 14,054 |
| `tests/unit/__pycache__/test_fresh_artifact_metadata.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 3,035 |
| `tests/unit/__pycache__/test_frozen_history.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 26,768 |
| `tests/unit/__pycache__/test_grade_scale.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 11,078 |
| `tests/unit/__pycache__/test_history_update.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 112,009 |
| `tests/unit/__pycache__/test_main_runner.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 17,083 |
| `tests/unit/__pycache__/test_migration_ranking_provenance.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 3,233 |
| `tests/unit/__pycache__/test_observed_plan.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 18,334 |
| `tests/unit/__pycache__/test_ranking_strategies.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 63,376 |
| `tests/unit/__pycache__/test_release_example.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 6,107 |
| `tests/unit/__pycache__/test_release_packages.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 8,936 |
| `tests/unit/__pycache__/test_runtime_catalog.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 6,240 |
| `tests/unit/__pycache__/test_stable_ui_views.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 12,147 |
| `tests/unit/__pycache__/test_standalone_staging.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 5,878 |
| `tests/unit/__pycache__/test_standalone_timeout.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 2,457 |
| `tests/unit/__pycache__/test_temporal_features.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 26,611 |
| `tests/unit/__pycache__/test_train_models.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 64,998 |
| `tests/unit/__pycache__/test_training_config.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 5,460 |
| `tests/unit/__pycache__/test_two_stage_activation.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 44,710 |
| `tests/unit/__pycache__/test_two_stage_activation.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 23,461 |
| `tests/unit/__pycache__/test_two_stage_artifacts.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 82,113 |
| `tests/unit/__pycache__/test_two_stage_artifacts.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 47,557 |
| `tests/unit/__pycache__/test_two_stage_constraints.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 36,454 |
| `tests/unit/__pycache__/test_two_stage_engine.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 114,353 |
| `tests/unit/__pycache__/test_two_stage_matrix.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 12,406 |
| `tests/unit/__pycache__/test_two_stage_payloads.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 34,194 |
| `tests/unit/__pycache__/test_two_stage_shortlist.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 26,600 |
| `tests/unit/__pycache__/test_ui_client.cpython-311-pytest-9.1.1.pyc` | File | Python bytecode (C2) | Ignored / untracked | 46,680 |
| `tests/unit/__pycache__/two_stage_fixtures.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 8,157 |
| `tools/__pycache__/__init__.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 170 |
| `tools/__pycache__/prepare_release.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 18,448 |
| `tools/__pycache__/verify_release.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 25,046 |
| `tools/__pycache__/verify_standalone.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 11,874 |
| `tools/academic_advisor_streamlit/__pycache__/__init__.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 197 |
| `tools/academic_advisor_streamlit/__pycache__/ui_client.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 38,668 |
| `tools/academic_advisor_streamlit/__pycache__/views.cpython-311.pyc` | File | Python bytecode (C2) | Ignored / untracked | 7,919 |

</details>

## C. Build and runtime writers

| Code | Writer or source of output | What it generates |
|---|---|---|
| D and D1 | `src/paths.py` supplies the canonical paths. `src/data/cleaning/clean_degree_course.py` | Data output directories and cleaned degree catalog |
| D2 | `src/data/building/build_registration_roster.py` | Full roster and both temporal rosters |
| D3 | `src/data/building/filter_common_students.py` | Clean course and status Parquets for the common-student population |
| D4 | `src/data/building/build_student_course_enriched.py` | Student-course enrichment |
| D5 | `src/data/cleaning/clean_student_course.py` | Pre-common course outcomes |
| D6 | `src/data/cleaning/clean_student_diploma.py` | Diploma table and diploma-enriched course data |
| D7 | `src/data/cleaning/clean_student_status.py` | Pre-common degree and student status |
| D8 | `src/data/cleaning/clean_outliers.py` | Outlier-filtered outcomes and the outlier audit |
| D9 | `src/data/building/build_temporal_split.py` | Train and test outcome splits |
| F1 | `src/features/build_temporal_features.py` and `src/features/temporal_features.py` | Train and test Parquets and the standalone training history pickle |
| H1 | `src/features/build_frozen_history.py` and `src/features/frozen_history.py` | Frozen course-history state and matching metadata for each cutoff |
| E1 | `src/evaluation/evaluate_plan_gpa.py` | Course predictions, plan evaluation and metrics. Reports under `docs/` are separate and protected |
| C1 | pytest cache provider | Repository test cache and generated cache markers |
| C2 | Python import/pytest bytecode cache | Regenerable `.pyc` under the listed project cache directories |
| P1 | setuptools packaging backend declared in `pyproject.toml` | Project-root `.egg-info` metadata from the editable install/build |

Other audited writers and locations:

- **Model training and publication.** `src/modeling/train_models.py`, `train_shortlist_models.py`, and `build_artifact_manifest.py` write model pairs, metadata, category levels, shortlist evaluation files, temporary publication staging, and the serving manifest. The artifact loader in `src/recommendation/two_stage_artifacts.py` confirms canonical paths. No model files, shortlist evaluation output, category files, publication staging or serving manifest exist here. The historical build manifest in `data/artifacts/build_manifest.json` is also already absent.
- **Runtime state.** `src/api/settings.py`, `request_store.py`, `src/recommendation/cumulative_history.py`, and `src/features/frozen_history.py` define the SQLite store, incremental history control/lock/bundles, and temporary staging. Both the default `.api-state/` and `data/artifacts/history_incremental/` output locations are absent. Checked the relevant override names in the current environment and environment files without disclosing secret values. The default history baseline location is the existing canonical frozen history in this inventory. Streamlit's resource cache is in memory.
- **Packaging and temporary builds.** `tools/prepare_release.py` writes release ZIP files. `tools/verify_release.py` and `tools/verify_standalone.py` use system temporary locations and private build trees. No matching project-owned staging, export archives, `release/`, `build/`, `dist/`, `results/`, or `data/processed/` was found within this checkout. External temp/cache paths are excluded.
- **Experiment outputs.** No `src/experiment_io.py` or equivalent standalone experiment writer was found in this checkout. Stage 1 training is the experiment-named writer within the canonical modeling flow. The scan also checked Parquet, pickle/joblib, model-save, packaging, JSON/text, directory creation and runtime file-writing references. Test fixture writers use their test directories or temporary paths and are preserved as code. Only observed outputs appear in B.

## D. Ambiguous items and exclusions

| Item | Observed state and disposition |
|---|---|
| `artifacts/`, `artifacts/history/` | Empty historical location with no files and no verified active writer here. Preserve both directories pending separate review. |
| `models/`, `models/active/` | The model root is canonical, but its only child is an empty `active/` with no confirmed producer in this checkout. Preserve the empty directories. There are no model bytes to delete. |
| `.superpowers/sdd/` | Contains planning and review evidence from earlier work. Preserve it as project documentation rather than treating it as a cache. |
| `.venv/` | Preserve the installed environment as a unit. Its internal vendor and environment files were not included in the deletion scan. |
| External directories, temp files and caches | Outside this inventory's repository scope. No proposed action. |

## E. Summary and post-approval verification plan

| Proposed group | Files | Logical bytes |
|---|---:|---:|
| Generated datasets, features, history and evaluation | 25 | 139,307,207 |
| Editable-install metadata | 5 | 2,040 |
| Pytest and Python bytecode caches | 129 | 2,294,603 |
| **Total proposed** | **159** | **141,603,850 (135.04 MiB)** |

- **Proposed directories** — 29, including nested directories. **Preserved raw files** — 6, totaling 27,109,049 bytes.
- **Selection fingerprint (SHA-256)** — `fd093fcacc9fe7e34ef134cef185b4cd7ffac42f9da414bd8fac8bb7929f78fc`. Computed from the sorted directory records `[path,"d"]` followed by sorted file records `[path,"f",size,sha256]` in compact ASCII JSON. This detects changes to the selected paths and file contents before any deletion.
- **Preserved-tree fingerprint (SHA-256)** — `9ef5d8d3a5ecb6ede91442ee951a2e2344e4c4767ac987611e9258d1c39b470f` over 211 entries. Compact ASCII JSON of path-sorted `[path,"d",null]` or `[path,"f",sha256]` records, excluding `.git/`, `.venv/`, and the two Phase 0 reports. Environment file values and individual secrets are never printed. The Git index and HEAD have separate baselines.
- **Risks** — Deleting generated history and evaluation files removes prior local evidence and stops artifact-dependent API readiness until the later rebuild. Cache removal clears local pytest run history. Source packaging metadata may be recreated by a future install. No listed file is a production model or live request store.
- **After approval only** — Recheck the exact paths, fingerprints, Git state, raw hash baseline and file types. Check resolved Windows paths remain inside this checkout, avoid following reparse points, and stop on changes to the approved selection. The audit found no reparse points in the inspected tree and all listed files had one link. Delete only listed files, then remove approved directories bottom-up only when empty. Compare all six raw SHA-256 hashes, original sizes and modification times. Recheck the protected tree, Git state and remaining output paths. Write `docs/reports/PHASE_0_CLEANUP_REPORT.md`.
- **Approval required** — Approve the exact section B inventory before cleanup. Review the cleanup report separately before any build starts.
