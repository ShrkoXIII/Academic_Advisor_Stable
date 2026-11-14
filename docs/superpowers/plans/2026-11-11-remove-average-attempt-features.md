# Remove Average-Attempt Features Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan task-by-task. Each behavior change follows TDD.

**Goal:** Remove `plan_course_type_id` and all average-attempt features/sums from training, inference, frozen-history storage, and finalized history updates.

**Architecture:** Keep per-candidate `attempt_number` and historical `course_history_retake_rate`/`retake_sum`; remove the average-attempt aggregate and its model consumers. Preserve compatibility through the ordered feature and payload structure without numeric contract labels.

**Tech Stack:** Python, pandas, NumPy, pytest, LightGBM artifact manifests.

**Spec:** `docs/superpowers/specs/2026-11-11-remove-average-attempt-features-design.md`

## Global Constraints

- Never silently change academic rules, filtering conditions, GPA calculations, or remaining feature definitions.
- Preserve `attempt_number` and retake-rate behavior; remove only the approved average-attempt signal and `plan_course_type_id` model input.
- Do not retrain models, commit, merge, or push without explicit authorization.
- Append one concise dated entry to `docs/CHANGELOG.md` after code/test changes.
- Preserve all unrelated working-tree changes; repair only the existing `sor t=False` syntax typo in the file being edited so tests can import it.

## Review Focus

- Old 47/33 model manifests must fail version/feature-contract validation rather than score against 43/31 matrices; test stale feature version and wrong feature counts.
- Finalized history deltas missing `attempt_sum` must normalize, while old payloads that still include it must be rejected; test both shapes.
- Empty history states and empty semester deltas must keep table schemas/totals valid without `attempt_sum`; test empty and nonempty updates.
- Plan-context aggregation must retain every non-attempt output and its leave-one-out behavior; test the remaining column order and representative weighted values.
- Candidate inputs without `plan_course_type_id` must still normalize and score; test missing optional raw catalog value without changing other candidate validation.

---

### Task 1: Remove model-facing feature columns

**Files:**
- Modify: `src/features/feature_contract.py`
- Modify: `src/features/temporal_features.py`
- Modify: `src/features/build_temporal_features.py`
- Modify: `src/recommendation/two_stage_artifacts.py`
- Modify: `src/modeling/shortlist_features.py`
- Modify: `src/recommendation/two_stage_engine.py`
- Modify: `src/recommendation/inputs.py`
- Modify: `src/api/adapters/courses.py`
- Modify: `src/api/validators/courses.py`
- Test: `tests/unit/test_temporal_features.py`
- Test: `tests/unit/test_two_stage_artifacts.py`
- Test: `tests/unit/test_two_stage_engine.py`
- Test: `tests/integration/test_api_stable.py` or the owning course-adapter tests found during implementation

**Interfaces:**
- Consumes: current `BASE_FEATURES`, `COURSE_HISTORY_COLUMNS`, and `PLAN_CONTEXT_COLUMNS` contracts.
- Produces: 43 ordered Stage 2 features, 31 Stage 1 features, and 12 plan-context outputs; neither model matrix includes `plan_course_type_id` or any average-attempt feature.

- [x] **Step 1: Write failing tests** asserting the three removed average-attempt model columns and `plan_course_type_id` are absent from both model contracts; Stage 1 is 31, Stage 2 is 43, plan context is 12; candidate normalization accepts input without `plan_course_type_id`; remaining plan-context outputs preserve order and representative values.
- [x] **Step 2: Run focused tests and verify expected failures** in feature-contract, temporal-feature, two-stage artifact/engine, and candidate/API tests.
- [x] **Step 3: Implement minimal model-contract changes**; remove the two weighted-attempt plan outputs and direct average feature, preserve retake-rate and candidate attempt-number behavior, and repair the documented syntax typo.
- [x] **Step 4: Run the focused tests and verify they pass.**

### Task 2: Remove `attempt_sum` from history storage and update payloads

**Files:**
- Modify: `src/features/temporal_features.py`
- Modify: `src/features/frozen_history.py` if any serialized schema/version checks need adjustment
- Modify: `src/recommendation/history_update.py`
- Test: `tests/unit/test_history_update.py`
- Test: `tests/unit/test_cumulative_history.py`
- Test: `tests/unit/test_temporal_features.py`
- Test: `tests/unit/test_frozen_history.py`

**Interfaces:**
- Consumes: Task 1 keeps `retake_sum` as the only attempt-related history statistic.
- Produces: `HISTORY_SUM_COLUMNS` and delta rows without `attempt_sum`; canonical history delta payload.

- [x] **Step 1: Write failing tests** asserting new delta rows require no `attempt_sum`, reject legacy rows containing it, preserve retake counts, and update history state without an attempt-sum column or total.
- [x] **Step 2: Run focused tests and verify expected failures** in temporal history and update-payload tests.
- [x] **Step 3: Implement minimal history-schema changes** to remove attempt sums, average calculation/smoothing, validators, exact-addition checks, and payload mapping; retain `attempt_number > 1` retake counting.
- [x] **Step 4: Run focused history tests and verify they pass.**

### Task 3: Align tests, documentation, and final verification

**Files:**
- Modify: remaining tests and fixtures referencing removed columns or old 47/33 counts
- Modify: `docs/CHANGELOG.md`

**Interfaces:**
- Consumes: Tasks 1–2 feature and history contracts.
- Produces: repository tests and changelog aligned to the final feature/history contract.

- [x] **Step 1: Update remaining fixtures and assertions** to the 43/31 feature counts and attempt-sum-free history contract without weakening unrelated checks.
- [x] **Step 2: Run focused tests, then the repository test suite; record any environment-blocked tests accurately.**
- [x] **Step 3: Append one changelog entry** naming the removed features, contract/version changes, validation results, and affected files.
- [x] **Step 4: Review the final diff and verify no model-facing average-attempt or `plan_course_type_id` columns remain.**

No commits are included; the repository instructions prohibit them unless requested.
