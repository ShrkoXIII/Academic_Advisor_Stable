# Phase 8A · Pipeline reference

**Stable · 2026-11-19 · `data_cleaning` at `2eb30c7bbb765c9cb8c0a5e75c87ff4d5054fac4`.** Only `data/raw/` contained datasets at inspection. Counts below are expected from read-only raw projections. Use the [main audit](PHASE_8A_PIPELINE_AUDIT.md) for the derivations, feature definitions, gaps and issue IDs.

## Execution map

`src/main.py::PIPELINE` owns the order. The first nine rows run serially under `--section data`. Catalog, outcome cleaning and status cleaning have independent raw inputs. The roster branch depends on the **outlier audit and common status**, and imports the outcome split's term lists. It rereads raw registrations. Output stems in the table are Parquet files under `data/` unless an extension or a different root is shown.

| Runner step / entry point | Inputs → outputs | Critical invariant |
|---|---|---|
| 1 `clean_degree_course` · `src.data.cleaning.clean_degree_course.clean_degree_course` | `raw/v_acd_degree_course` → `clean/degree_course` | Unique degree/course curriculum key when consumed (4,006 rows) |
| 2 `clean_student_course` · `src.data.cleaning.clean_student_course.clean_student_course` | `raw/v_crg_student_course_raw` → `clean/student_course_pre_common` | R/E after 20193, attempts assigned before finish/GPA flags. Registration ID and student/course/part unique after key cleaning (459,620 outcomes) |
| 3 `clean_student_status` · `src.data.cleaning.clean_student_status.clean_student_status` | `raw/v_add_student_degree_status` → `clean/student_status_pre_common` | Degree-scoped enrollment lag calculated before business filters. Status and student/degree/part unique in extract (108,974 rows) |
| 4 `filter_common_students` · `src.data.building.filter_common_students.filter_common_students` | Both pre-common files → `clean/student_course`, `clean/student_status` | Same 12,792 student IDs, 456,595 / 107,939 rows. Term match still required |
| 5 `build_student_course_enriched` · `src.data.building.build_student_course_enriched.main` | Common course/status + clean catalog → `clean/student_course_enriched` | Inner status on student/degree/part, left plan on degree/course, both `m:1`. 456,453 retained, 142 status misses, 67 plan misses |
| 6 `clean_student_diploma` · `src.data.cleaning.clean_student_diploma.{clean_student_diploma,merge_student_course_with_diploma}` | `raw/v_add_academic_info` → `clean/student_diploma`; join with enriched → `merged/student_course_enriched_with_diploma` | One diploma per student; left join preserves 456,453. Full-file top four, global forward fill |
| 7 `clean_outliers` · `src.data.cleaning.clean_outliers.{build_outlier_audit,remove_outlier_students}` | Diploma-enriched rows → `merged/student_course_enriched_without_outliers`, `merged/outlier_students` | Rule evidence is student/scope/rule; exclusion by student across all terms. 424,435 retained; future dependence A01 |
| 8 `build_temporal_split` · `src.data.building.build_temporal_split.build_temporal_split` | Filtered outcomes → `temporal/temporal_train`, `temporal/temporal_test` | Train 20201–20243, test 20251–20252, incomplete 20253. 356,882 / 67,548 outcomes |
| 9 `build_registration_roster` · `src.data.building.build_registration_roster.build_registration_roster` | Raw course + common status + clean catalog + outlier IDs → `clean/registration_roster`, `temporal/temporal_train_roster`, `temporal/temporal_test_roster` | Full 474,264, split 389,062 / 74,827. W and unfinished rows can provide plan context; only finalized supervised rows update course history |
| 10 `build_temporal_features` · `src.features.build_temporal_features.build_feature_tables` | Two outcome splits + both split rosters + common status → `features/temporal_train_features`, `features/temporal_test_features`, `artifacts/course_history_state.pkl` | Apply before update each term, clone train state for rolling holdout; plan context grouped by student/degree/part, joined on registration ID. **Model training can start here** |
| 11 `train_models` · `src.modeling.train_models.main` | Feature Parquets → `models/{grade_regressor.txt,fail_risk_classifier.txt,model_metadata.json}` and `data/artifacts/category_levels.json` | Stage **2** trains first; 43 features, 2 temporal validation folds, fit-only categories/weights |
| 12 `train_shortlist_models` · `src.modeling.train_shortlist_models.train_experiment` | Same feature files + fitted baseline/levels/metadata + fitting sources → `models/shortlist_training/{grade_regressor.txt,fail_risk_classifier.txt,category_levels.json,model_metadata.json}`, `data/evaluation/shortlist/{grade_validation.json,fail_validation.json,holdout_predictions.parquet,model_comparison.json}` | Stage **1** retains 31 columns. Requires baseline assets for signature and holdout comparison |
| 13 `evaluate_plan_gpa` · `src.evaluation.evaluate_plan_gpa.main` | Test features + full grade model/levels + `raw/v_acs_grade` → `evaluation/{plan_gpa_course_predictions_2025.parquet,plan_gpa_evaluation_2025.parquet,plan_gpa_metrics_2025.json}` | Uses the observed supervised subset. Standard runner schedules after shortlist, although evaluator has no shortlist dependency |
| Separate `build_frozen_history` · `src.features.build_frozen_history.main` | Canonical train features (+ test for cutoff >20243) and explicit finalization → `artifacts/history/as_of_<part>/{course_history_state.pkl,metadata.json}` | Prefix inclusive through exactly as-of; optional legacy state only for equivalence. CLI publishes base-only. `FrozenHistoryManager`/`CumulativeHistoryStore` load it; request capture pins a cutoff preceding target |
| Separate `publish_artifacts` · `src.modeling.build_artifact_manifest.promote_shortlist_artifacts` | Both stage outputs, signed inputs, grade scale; optional approval evidence → `models/shortlist/{grade_model.txt,fail_model.txt,category_levels.json,manifest.json}` | Stages and validates new directory; Stage 2 model/level files stay at their original paths and are referenced by hash |

The additional `raw/v_crg_std_cor_temp_request.parquet` has no edge to standard training. Specialty history is available only through an injected type in `src.features.frozen_history`; no standard step supplies one.

## Commands and prerequisites

Run from the repository root using the project interpreter (`python` below). `pyproject.toml` defines dependencies, `requirements.lock` pins versions. Windows README setup uses `py -3.11 -m venv .venv`, `.venv\Scripts\python.exe -m pip install -r requirements.lock`, then `.venv\Scripts\python.exe -m pip install -e ".[api,ui,dev]"`. Core build steps need local source files and writable output roots. No environment variables are required by the offline standard build. `src/paths.py` resolves paths relative to the project. No source exporter or external database client occurs in the standard graph.

**Inspection commands**

```powershell
python -m src.main --list
python -m src.main --all --dry-run
```

**Build commands for a separately authorized run.** These commands describe actual entry points and write canonical outputs. Only the dry-run was executed for this audit. Replace `<step-name>` with a runner step in the table.

```powershell
python -m src.main --section data
python -m src.main --section features
python -m src.main --section modeling
python -m src.main --section evaluation
```

`python -m src.main --all` runs these four sections, excluding cutoff-specific history and manifest publication. `python -m src.main --step <step-name>` runs only the named stage; dependencies must already exist. `python -m src.main --from data --to features` runs an inclusive section range. Each stage also has a direct `python -m <module>` invocation (use the file's dotted module name without its function). The shortlist guard calls `train_experiment()` directly. It has no implemented `--skip-training` CLI.

**Cutoff-specific history.** The following are the canonical previous-part examples for 20251 and 20252. The operator supplies the finalized-through argument only when source finalization is established.

```powershell
python -m src.features.build_frozen_history --as-of-part 20243 --finalized-through-part 20243
python -m src.features.build_frozen_history --as-of-part 20251 --finalized-through-part 20251
```

Equivalent single-step forwarding uses `python -m src.main --step build_frozen_history -- --as-of-part 20243 --finalized-through-part 20243`. `--sources`, `--history-root` and `--verify-legacy-course-state` are optional CLI arguments. Building a cutoff writes an immutable bundle. Durable administration uses baseline 20251, a separate storage root, a verified hash and explicit activation. A normal API request selects the immediately preceding part. Source and incremental root overrides, update mode and backtesting configuration are owned by `src/api/settings.py::ApiSettings.from_env`.

**Model publication.** The manifest CLI accepts `python -m src.modeling.build_artifact_manifest` and optional `--approval-reference "<actual approval reference>" --approval-date YYYY-MM-DD`. Without approval evidence the manifest records unapproved ranking. The current raw grade scale is a required input to promotion and GPA evaluation.

## Checkpoints for operating the build

- Scope the student, degree, course, registration and term independently. Join status on student/degree/part and plan on degree/course. Count input misses as well as output rows.
- Preserve distinct outcome and roster denominators and evaluate credit and course coverage by plan. Verify non-null finite supervised targets, uniqueness of roster registration IDs and one feature row per retained target.
- Measure prefix membership before accepting strictly chronological history. Cutoff fields alone cannot detect retroactive removal of students. Training feature X excludes current labels even though the wider Parquet carries them.
- Verify an entire output generation together. Most data/feature writers overwrite single files, and a section failure can leave products from different runs. Existing frozen cutoff and promoted shortlist directories refuse replacement. An existing shortlist training metadata file stops its fit after the baseline stage may already have overwritten assets.
- Check the 31/43 ordered lists, both vocabulary orders, real booster headers, raw and fitting-source hashes, both model cutoffs, the selected frozen prefix, grade scale and manifest together. Current artifact-level verification is pending.

**Review status: BLOCKED.** The [review checklist](PHASE_8A_REVIEW_CHECKLIST.md) records the evidence needed to decide each stage.
