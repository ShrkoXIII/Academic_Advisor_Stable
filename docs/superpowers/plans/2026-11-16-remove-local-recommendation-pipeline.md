# Remove Local Recommendation Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the local-file recommendation adapter from the production input module while keeping the Backend payload boundary and local observed-plan evaluation intact.

**Architecture:** The production request path remains API validation/adaptation → `prepare_recommendation_payloads()` → `TwoStagePlanRecommender` → two-stage scoring and ranking → API response. Move only the local registered-course normalizer used by observed-plan evaluation to an evaluation-scoped module; remove the disconnected local snapshot/candidate loader and stale CLI branch.

**Tech Stack:** Python 3.11+, pandas, pytest, FastAPI service and existing two-stage engine.

**Spec:** User request, “Remove Local Recommendation Pipeline and Simplify the Project Architecture” (2026-11-16).

## Global Constraints

- Preserve `normalize_student_payload()`, `normalize_candidate_payloads()`, `normalize_request_payload()`, `prepare_recommendation_payloads()`, `PreparedRecommendationInputs`, and all payload validation behavior.
- Do not change ranking policy, prediction behavior, model artifacts, frozen history, feature definitions, data pipelines, or raw data.
- Keep observed-plan evaluation and its local registration/outcome sources available.
- Keep the API's catalog consistency validation and disclose it as a local serving dependency.
- Append one concise dated entry to `docs/CHANGELOG.md` after the code, tests, or configuration change.
- Do not overwrite the existing edits in `docs/CHANGELOG.md` or `src/features/feature_contract.py`; do not commit.

## Pre-change Dependency Map

| Responsibility | Current path and dependencies | Disposition |
|---|---|---|
| Production recommendation | `src/api/app.py` → `ApiService.recommend()` → `adapt_student()` / `adapt_courses()` → `_run_recommendation()` → `TwoStagePlanRecommender.recommend_from_payloads()` → `prepare_recommendation_payloads()` → history features → Stage 1 shortlist → Stage 2 scoring → ranking → API response | Keep; no local candidate-file or local student-table loader is on this path. |
| Backend payload boundary | `src/recommendation/inputs.py`: `PreparedRecommendationInputs`, payload normalizers, request constraints, validation helpers, GPA trend derivation | Keep unchanged in behavior. |
| Old local recommendation adapter | `load_local_inputs()` internally calls `read_candidate_file()`, `normalize_candidates()`, `build_student_snapshot()`, and `validate_snapshot()`; it reads cleaned candidate/catalog/history/status/diploma files. No CLI or external caller references `load_local_inputs()`. | Remove these local-only entry points and their production-module imports. |
| Shared local course normalization | `normalize_candidates()` is called by `load_local_inputs()` and `tools/academic_advisor_streamlit/views.py::registered_courses()`. The latter needs catalog matching and strictly prior attempt derivation for observed-plan evaluation. | Move and rename as `src.evaluation.local_course_inputs.normalize_registered_courses()`; update the evaluation caller. |
| API catalog check | `ApiService` loads the cleaned degree catalog; `adapt_courses()` uses it to compare supplied candidate properties. It does not construct the candidate list from a local candidate file. | Keep as existing payload consistency validation; document as a remaining local file dependency. |
| Build/data/evaluation workflows | `src/main.py` runs data, features, modeling, and observed-plan GPA evaluation. `evaluate_plan_gpa.py`, cleaning/building/features/training, and frozen history do not import the removed local loader. | Keep. Remove only the unreachable `recommendation` section branch in `_select_steps()`. |
| Nonexistent requested files | No `local_cli.py`, `benchmark_recommendation.py`, `output.py`, or standalone recommendation `engine.py` exists in this repository. | Nothing to delete; two-stage engine and shared plan/ranking modules remain. |

## Review Focus

1. Missing Backend snapshot fields remain rejected — `test_missing_ready_snapshot_field_is_rejected`.
2. Unknown nullable GPA history remains unknown — `test_missing_trend_stays_missing`.
3. Invalid/duplicate candidates and invalid supplied attempts remain rejected — `test_invalid_candidate_numbers_are_rejected`, `test_duplicate_course_identity_after_normalization_is_rejected`.
4. Explicitly ineligible candidates remain excluded — `test_only_explicit_eligibility_rejection_removes_candidates`.
5. Local observed registration still gets catalog data and strictly prior attempt counts — `test_local_registration_lookup_uses_canonical_identity_and_prior_attempts`.

---

### Task 1: Split evaluation-only local course normalization from production inputs

**Files:**
- Create: `src/evaluation/local_course_inputs.py`
- Modify: `src/recommendation/inputs.py`
- Modify: `tools/academic_advisor_streamlit/views.py`
- Test: `tests/unit/test_two_stage_payloads.py`
- Test: `tests/unit/test_stable_ui_views.py`

**Interfaces:**
- Consumes: Existing `normalize_candidates(raw, catalog, course_history, student_id, degree_id, part_id)` behavior and existing Backend payload adapter API.
- Produces: `normalize_registered_courses(raw, catalog, course_history, student_id, degree_id, part_id)` in `src.evaluation.local_course_inputs`; unchanged Backend payload API in `src.recommendation.inputs`.

- [x] Add assertions that `src.recommendation.inputs` does not expose the local loader, reader, snapshot builder, validator, or local candidate normalizer; retain all current Backend payload assertions.
- [x] Move the existing catalog match and strictly-prior attempt calculation into `normalize_registered_courses()` without changing its evaluation output; update `registered_courses()` to import it.
- [x] Add evaluation regressions for same-course attempts, target/future attempts excluded from prior counts, canonical ID formats, catalog consistency, and missing catalog matches.
- [x] Remove `CandidateImportError`, `read_candidate_file()`, the local-table `build_student_snapshot()`, `validate_snapshot()`, and `load_local_inputs()` from `src/recommendation/inputs.py`, along with imports used only by them.
- [x] Keep the distinct `src/api/adapters/student.py::build_student_snapshot()` because it adapts Backend API values and does not read local student tables.
- [x] Run focused tests: payload and UI tests passed (69); adding observed-plan tests produced 16 fixture-setup failures at the pre-existing 43-minus-12 contract check.

### Task 2: Remove the dead local recommendation CLI branch

**Files:**
- Modify: `src/main.py`
- Test: `tests/unit/test_main_runner.py`

**Interfaces:**
- Consumes: Existing data/features/modeling/evaluation sections and `STEPS` mapping.
- Produces: CLI choices contain only supported pipeline sections and steps.

- [x] Add a test that `--section recommendation` is rejected and is not listed as a supported section.
- [x] Remove the unregistered `recommendation` branch while preserving the data, feature, modeling, and evaluation runner behavior.
- [x] Run focused tests: 2 passed; 1 existing dry-run output assertion failed.

### Task 3: Document the production path and remaining local evaluation dependencies

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/PIPELINE_AND_LOGIC_MAP.md`
- Modify: `tools/academic_advisor_streamlit/streamlit_app.py` (description only)

**Interfaces:**
- Consumes: Final implementation from Tasks 1–2.
- Produces: One documented Backend → validation/normalization → two-stage engine → response path, with local observed-plan evaluation and remaining model/catalog/history files clearly scoped.

- [x] Update the README's input and evaluation wording to distinguish Backend-supplied recommendation payloads from optional local observed-plan evaluation.
- [x] Document Python/Backend responsibilities and the actual API/engine chain in `docs/architecture.md`; update the logic map's recommendation and evaluation paths.
- [x] Verify the `recommendation` section is absent from CLI choices, then remove its stale branch.

### Task 4: Full verification and reference audit

**Files:**
- No additional intended source changes; adjust earlier task files only for verified failures.

- [x] Search again for all removed function names and stale CLI references; confirm no production imports remain.
- [x] Inspect all imports/indirect references, entry points, configurations, scripts, Streamlit and evaluation imports; verify the Backend boundary, catalog check, engine/model loading, and local evaluation paths remain intact.
- [x] Start the full suite; 963 tests collected, but the run was interrupted at the first Streamlit AppTest after diagnosing Windows `asyncio.socketpair` blocking in the sandbox. Full-suite totals are unavailable.
- [x] Record available focused counts and warnings; distinguish unit tests, local evaluation, and live Backend integration evidence. No live University Backend integration was tested.
- [x] Leave unrelated pre-existing failures and edits untouched and identify them by test/file.

### Task 5: Final architecture and handover report

- Modify: `docs/CHANGELOG.md`

- [x] Report deleted files (none), modified files, and every function/class removed or moved in the final handover.
- [x] Show the actual final recommendation path and list remaining local catalog, frozen history, model/manifest, and other runtime dependencies with loading component and purpose.
- [x] State whether a live Backend integration was tested; do not treat unit tests as that evidence.
- [x] Append one concise dated entry to `docs/CHANGELOG.md` after implementation and verification, preserving existing edits.
- [x] List risks and unresolved issues. No commit created.

**Review complete:** The plan covers all user requirements and tests the five highest-risk preserved behaviors. The existing dirty feature-contract edit may affect unrelated tests and will be reported without modification.
