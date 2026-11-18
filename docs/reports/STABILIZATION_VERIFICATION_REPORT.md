# Stabilization verification after local recommendation removal

Date: 2026-11-17

## A. Executive summary

**Final status — BLOCKED for release.** The feature contract, dry-run test, and artifact validation defect were corrected. The complete two-stage flow passed with synthetic API requests and model fixtures. All three Streamlit integration tests completed on Windows.

The full suite completed with **956 passed, 5 failed, and 2 skipped**. Production readiness remains false because the approved model bundle is absent and both checkout history bundles fail the current history contract. No representative real University Backend payload was available.

## B. Changes made

| File | Change in this phase |
|---|---|
| [Feature contract](../../src/features/feature_contract.py) | Restored `peer_difficulty_missing` at its existing ordered position. This one targeted correction matches `HEAD` and therefore disappears from the working tree diff against `HEAD`. |
| [Artifact loader](../../src/recommendation/two_stage_artifacts.py) | Removed `ranking_policy` from the unconditional manifest field check. The existing ranking policy validator still requires the policy for approved manifests, and production activation still requires complete human approval. |
| [Main runner tests](../../tests/unit/test_main_runner.py) | Changed the outdated dry-run banner assertion to check the actual dry-run completion message. The subprocess guard, build order and exclusions, and obsolete CLI rejection test remain. |
| [Changelog](../CHANGELOG.md) | Appended one dated entry. |
| [Stabilization verification report](STABILIZATION_VERIFICATION_REPORT.md) | Recorded the investigation, commands, results, and release blockers. |

Before editing, the working tree already contained the prior local adapter removal, Streamlit evaluation adapter and tests, CLI branch removal, API docstring, and documentation edits. These were preserved. No production files were created under `models/` or `data/`. The history bundles, prediction logic, ranking and shortlist logic, data pipelines, and evaluation adapter separation were preserved. Artifact tests use temporary synthetic assets. No commit was created.

The CLI documents `--list` as a listing and `--all --dry-run` as a command preview. Running both showed that the canonical pipeline banner is printed by the former. The failed assertion was a stale test expectation. The dry run printed its completion message, and the regression test continues to verify rejection of `--section recommendation`.

## C. Feature contract investigation

The malformed `peer_dif   ficulty_missing` spelling was present in the working copy before this phase. The authoritative [feature generator](../../src/features/temporal_features.py) emits `peer_difficulty_missing` and includes it in `PLAN_CONTEXT_COLUMNS`. The [shortlist feature definition](../../src/modeling/shortlist_features.py), temporal feature tests, engine test expectations, and the committed feature contract agree. A repository search found the malformed spelling only in the working feature contract before correction.

The base list still contained 43 entries, but only 11 of the 12 plan-context columns matched. Stage 1 would therefore retain 32 columns and failed the subset/size invariant before scoring. The correction changed one name in place. An ordered comparison with `HEAD` confirmed exact numeric and categorical lists. The artifact, matrix, and temporal tests verified the expected ordered 31-column Stage 1 and 43-column Stage 2 contracts. The artifact tests also verified compatibility with generated model headers and comparison of synthetic predictions after publication. The real approved model headers, hashes, and predictions could not be compared because the serving bundle is absent.

The wider artifact run exposed a separate publisher/loader contradiction already present in `HEAD`. An unapproved publication writes `ranking_approval` and omits `ranking_policy`, which is the representation accepted by the approval validator for evaluation. The loader previously rejected it with `Incomplete two-stage manifest contract.` before the validator ran. The fix delegates the conditional requirement to [the existing validator](../../src/recommendation/ranking_policy.py). The tests verify that missing or malformed approval still blocks production activation and that approval cannot bypass feature and hash checks.

## D. Test results

| Test group | Passed | Failed | Skipped | Status | Notes |
|---|---:|---:|---:|---|---|
| Backend payload / Streamlit view unit tests | 69 | 0 | 0 | PASS | 62 payload and 7 view tests. |
| Observed plan | 16 | 0 | 0 | PASS | Previously failed before assertions during artifact fixture construction. |
| Constraints | 53 | 0 | 0 | PASS | Feasibility and policy checks. |
| Shortlist and ranking | 63 | 0 | 0 | PASS | 14 shortlist and 49 ranking tests. |
| Feature matrix, temporal features, ordered contract | 30 | 0 | 0 | PASS | 11 matrix, 18 temporal, and one ordered contract test. The five rows above ran together and total 231. |
| Main runner | 3 | 0 | 0 | PASS | Dry run and obsolete CLI rejection. |
| RequestStore | 48 | 0 | 1 | PASS WITH SKIP | Windows deployment uses service-account ACLs. |
| Two-stage engine | 72 | 0 | 0 | PASS | Synthetic history and models. |
| API integration | 11 | 0 | 0 | PASS | FastAPI TestClient with synthetic provider requests and an injected engine. |
| Streamlit integration | 3 | 0 | 0 | PASS | All AppTests completed on Windows. |
| Artifact publication and activation | 90 | 0 | 1 | PASS WITH SKIP | Pinned artifact activation skipped because the serving bundle is missing. |
| Full suite | 956 | 5 | 2 | FAIL | 963 collected. Completed in 111.75 seconds with one TestClient deprecation warning. |

Focused runs used the project virtual environment. The full command was:

```powershell
.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider
git diff --check
```

The earlier broad run, after correcting the feature and CLI checks but before correcting the loader, completed with 881 passed, 80 failed, and 2 skipped. Seventy-four failures originated at the unapproved manifest publication check, including tests that could not reach their intended validation assertions. The final run recovered all of them. Five assertion failures remained in both runs:

| Failing test | Actual failure |
|---|---|
| `test_cumulative_history.py::test_approved_initialization_preserves_full_weighted_history_and_source` | The reserialized history has the same SHA-256 as its source. The test asserts unequal hashes even though the publisher preserves the same valid state and records each hash independently. |
| `test_frozen_history.py::test_cli_accepts_custom_source_by_contract_without_filename_label[finalized_outcomes.parquet]` and the `[export.parquet]` case | The test creates and passes `outcomes.parquet` in both cases, then expects the parameterized filename in the recorded provenance. The CLI reported the path it was given. |
| `test_history_update.py::test_latest_valid_load_skips_incomplete_corrupt_and_wrong_version` | The supposed invalid `20261` bundle has its metadata rewritten without changing any values. The loader correctly considers that bundle valid and selects it instead of `20251`. |
| `test_standalone_timeout.py::test_timeout_stops_owned_descendants_before_temporary_cleanup` | After the expected timeout, the Windows child still writes `surviving-worker.txt`. The assertion also failed in isolation. The cause of descendant survival was not established. |

The earlier broad run also encountered a transient Windows `WinError 5` directory rename during `test_missing_serving_compatibility_allows_partial_preview_but_blocks_publication`. That test passed in isolation and in the final full suite. These history and standalone verification issues were left outside the targeted changes.

The final repository-wide `git diff --check` returned exit 2 for trailing spaces on the `start_agpa_points` check in `src/recommendation/inputs.py:109`. That whitespace appeared outside this phase's edits and was preserved. The stabilization changes passed their scoped tracked-file check, and the new report has no whitespace diagnostics.

## E. Engine verification

The successful synthetic HTTP run exercised the FastAPI schema, student and candidate adapters, request identity and credit policies, catalog comparison, `ApiService.recommend()`, payload preparation, frozen-history selection, Stage 1 scoring, feasible plan generation, shortlisting, Stage 2 scoring, final ranking, and JSON serialization. Engine tests separately exercise cutoff rejection, preservation of the selected history snapshot, plan feasibility, the shortlist cap, and the use of Stage 2 predictions in final output.

A separate read-only synthetic HTTP probe added an extra course to the injected catalog and blocked all `pandas.read_parquet` calls during the request. It verified:

- Omitting either provider response returned HTTP 422 before inference.
- Conflicting course credits returned HTTP 422 with `CATALOG_CONFLICT`.
- A complete request returned HTTP 200, with 31 Stage 1 inputs, 43 Stage 2 inputs, and three ranked plans. Every returned course came from the Backend candidate records, and zero Parquet reads occurred during the requests.

This verifies the source and catalog boundary with test doubles. In an actual service readiness probe the catalog and GradeScale were ready, and model, history, and recommendation readiness were false. The source scan found no production reference to the removed file loader. Serving against deployed artifacts and a real payload remains unverified.

## F. Backend integration

**Real University Backend integration remains unverified.** The fixture and release example are explicitly synthetic. The source and fixture scan found no representative real provider request. To repeat the probe with the University team, obtain one approved, de-identified request for matching catalog entries with:

- The request envelope `student_id`, `degree_id`, `part_id`, both `source_contexts`, `history_as_of_part`, either `target_credits` or both `min_credits` and `max_credits`, plus any `top_k` and `mode` used.
- A full `student_api_response.data.studentDegreeInfo`, including the IDs and semester, `FACULTY_ID`, `GRADE_VERSION_ID`, the `START_AGPA_POINTS` and `START_TOTAL_IN_*` values, `DEGREE_CREDITS_COUNT`, configured diploma fields, and provider totals with their documented temporal meaning. Include `studentSummaryInfo` rows containing `STUDENT_STATUS_ID`, `STUDENT_ID`, `DEGREE_ID`, `PART_ID`, `GPA_POINTS`, and `SEMESTER_REG_COURSES` from before the target.
- A full `courses_api_response.data`, including `registserRule` (provider spelling), `allowRegisterAllOptional`, and `availableCourses` rows with `COURSE_ID`, `COURSE_NAME_SL`, `COURSE_CREDITS`, `REQUIREMENT_TYPE_ID`, `REQUIREMENT_ID`, `CREDITS_COUNT`, `REQUIREMENT_PASSED_CREDITS`, `YEAR_ORDER`, `SEMESTER_ORDER`, `IS_REQUESTABLE`, `ALLOW_REGISTER`, `STATUS_REASON_CODE`, `ATTEMPTS_COUNT`, and applicable `FINISH_STATUS` and `LAST_REGISTER_SEMESTER_ID`.
- The `integration_context` attestations used by that record. Include `total_reg_credits_source` with timing and cutoff, any required `student_values` for prior counters and GPA-counted credits, the semester-specific `registration_policy` with group modes, repeat budgets, load profile, and attempt-scope confirmation, and `previous_course_statuses` when the provider response needs a sourced supplement. Retain actual field types, nulls, and source timing in the sanitized example.

## G. Environment limitations

Earlier Windows sandbox execution stalled before Streamlit application code, in `asyncio.new_event_loop()` → `socketpair()` → `accept()`. In this run, the isolated event loop completed under an eight-second watchdog, the smallest AppTest passed, and all three AppTests passed in both the focused and full runs. The historical stall was not reproduced on this Windows session (Python 3.11.5 and Streamlit 1.66.1). No application workaround or alternative environment was needed. The separate standalone descendant-cleanup test still fails on this Windows run.

## H. Remaining risks

| Severity | Issue |
|---|---|
| Critical | The approved production manifest and four pinned model files are absent. The real artifact activation test skipped. |
| Critical | The `20243` and `20251` history bundles contain the retired `attempt_sum` aggregate. Both fail `CourseHistoryState` validation and no serving history is ready. |
| High | University Backend contract and production responses are unverified on a representative provider request. |
| Medium | History provenance tests and the Windows descendant-cleanup test leave the full suite red. The Windows rename error from the earlier run did not recur. |

## I. Final recommendation

| Use | Decision |
|---|---|
| Continued internal testing | Suitable with synthetic fixtures, including both recommendation stages and the observed-plan path. |
| University Backend integration testing | Suitable for an input-boundary trial once the team supplies a representative payload. Full scoring integration also requires an approved compatible model bundle and valid serving history. |
| Production deployment | Blocked. Restore compatible approved assets, verify history and readiness, and test a real Backend request through the complete flow before release. |
