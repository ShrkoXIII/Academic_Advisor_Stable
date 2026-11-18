# Phase 2 — API and recommendation behavioral parity tests

**Repository** Academic_Advisor_Stable

**Date** 2026-11-18

## Starting point and protected files

- Branch `data_cleaning` tracked `origin/data_cleaning` with no ahead or behind count. Starting commit was `f18a89aa8c481979d69ae77f40e0763df54ad7d6`.
- `git status --short --branch --untracked-files=all` showed only the branch line. There were no staged or unstaged tracked changes and no non-ignored untracked files to carry forward. Existing ignored local configuration, source data, and dependency files were outside the edit scope.
- A fresh pre-edit run collected 963 cases and finished with **959 passed, 2 failed, 2 skipped**. Both frozen-history filename assertions reproduced. The previously reported Windows descendant timeout case passed in this baseline.

The review used the [API and recommendation audit](API_RECOMMENDATION_AUDIT.md), [consolidation plan](API_RECOMMENDATION_CONSOLIDATION_PLAN.md), [history failure investigation](HISTORY_FAILURES_INVESTIGATION.md), [Phase 1 test report](HISTORY_TEST_FIXES_REPORT.md), [API contract](../api_contract.md), and [architecture](../architecture.md). The matrix reflects the request routes and schemas, API service and adapters, core input normalization and scoring, and the frozen and cumulative history implementations in the checkout.

## Existing coverage matrix

| Behavior | Existing test | Coverage status before Phase 2 | Missing case |
|---|---|---|---|
| Combined HTTP recommendation and legacy route | `test_http_recommendation_runs_both_stages_and_alias` in [HTTP tests](../../tests/integration/test_api_stable.py) | Combined success, two-stage feature counts and alias body equality | Explicit successful alias status alongside response equality |
| Split request intake and response | `test_split_inputs_wait_then_return_the_same_owned_result` in [HTTP tests](../../tests/integration/test_api_stable.py), plus claim, owner and replay cases in [request-store tests](../../tests/unit/test_api_request_store.py) | Either intake order reaches a persisted result for exact credits | Full combined/split result equality with evidence supplied by each component, ranged intake, and explicit pending and lookup envelopes and headers |
| Exact feasibility and no lower fallback | `test_no_exact_credit_plan_has_explicit_empty_result` in [HTTP tests](../../tests/integration/test_api_stable.py), `test_credit_range_uses_upper_exact_target_without_lower_fallback` in [engine tests](../../tests/unit/test_two_stage_engine.py) and [constraint tests](../../tests/unit/test_two_stage_constraints.py) | Exact infeasibility at HTTP and exhaustive feasibility and upper-target behavior in core | HTTP range with a feasible lower load and an infeasible selected target, with public target and plan counts |
| Provider credit intersection and range errors | `test_invalid_request_constraints_are_rejected` in [payload tests](../../tests/unit/test_two_stage_payloads.py) and the existing HTTP exact case | Core bounds and constraints covered | HTTP provider clipping, reversed or disjoint request bounds, and distinct error codes for incomplete or mixed credit modes |
| Student evidence, course eligibility and error association | Identity, missing fields and target-outcome cases in [HTTP tests](../../tests/integration/test_api_stable.py) | Combined rejects representative invalid inputs before scoring or admitting target outcomes | Missing GPA-credit provenance, literal provider flags, unresolved exception and explicit exclusion, plus field and component diagnostics across validation-only, split and combined requests |
| Direct ready-input validation | `test_only_explicit_eligibility_rejection_removes_candidates`, `test_target_overrides_valid_range_and_legacy_fail_name_is_not_a_cap`, and missing field, identity and duplicate cases in [payload tests](../../tests/unit/test_two_stage_payloads.py) | Direct core accepts its documented eligibility vocabulary and exact precedence, and enforces normalized input rules | HTTP coverage for the intentionally stricter wire schema and source checks. Existing core assertions already protect the ready-input cases. |
| Frozen history loading and immutable publication | Bundle verification, fallback, provenance and update tests in [frozen-history tests](../../tests/unit/test_frozen_history.py) and [history-update tests](../../tests/unit/test_history_update.py) | Direct loader and manager behavior, including corrupt and conflicting bundles | Serving the intended exact history through HTTP when a newer bundle is present |
| Read-only serving, inspection and manual history administration | `test_serving_proxy_pins_requests_and_readonly_validation_preserves_pending`, `test_preview_commit_activation_separate_and_sequential_raw_equivalence`, and rollback tests in [cumulative-history tests](../../tests/unit/test_cumulative_history.py) | Direct store and proxy tests distinguish preview, commit, activation and rollback | HTTP status and delta validation preserve durable history, recommendation preserves the pending preview, and activation controls which committed cutoffs normal serving can use |
| Finalization | `test_manual_automatic_and_disabled_workflows` in [cumulative-history tests](../../tests/unit/test_cumulative_history.py) | Direct store modes, trusted event argument and replay | HTTP credential and proof gates, and activation through an accepted finalization event |
| Snapshot identity and data through activation | `test_request_retains_one_history_snapshot_during_atomic_update` in [engine tests](../../tests/unit/test_two_stage_engine.py) and `test_cross_worker_capture_pins_history_during_atomic_activation` in [cumulative-history tests](../../tests/unit/test_cumulative_history.py) | Existing deterministic concurrency tests pin history during an update or activation | End-to-end checks that the API serves the activated data, a previously captured snapshot retains its digest and features, and rollback restores normal serving |

## Tests added or strengthened

All edits are in [`tests/integration/test_api_stable.py`](../../tests/integration/test_api_stable.py).

| Test | Change | Contract protected |
|---|---|---|
| `test_http_recommendation_runs_both_stages_and_alias` | Strengthened | `/recommend` and `/api/v1/recommendations` both return HTTP 200 and the same body. The existing 31- and 43-column checks remain. |
| `test_split_inputs_wait_then_return_the_same_owned_result` | Strengthened | Both exact-credit submission orders and a ranged request converge on the full combined response, including its input fingerprint, ordered recommendations and public metadata. Split intake retains HTTP 202 for pending, HTTP 200 with the recommendation body on completion, and lookup with a nested result. Split responses carry `X-Request-ID`. |
| `test_no_exact_credit_plan_has_explicit_empty_result` | Strengthened | An infeasible exact target and a range whose selected upper end is infeasible return HTTP 200, `no_feasible_plan`, the selected credit target, zero feasible and returned plans, and an empty list. |
| `test_credit_range_uses_upper_end_of_provider_intersection` | Added | A request for 3–9 credits with a provider study cap of 6 produces the same response as an exact six-credit request, and every plan totals six credits. |
| `test_invalid_credit_requests_report_the_rejecting_boundary` | Added | Mixed credit modes and a missing upper bound fail HTTP schema validation in combined and split student payloads. Reversed bounds and an interval outside the provider range produce distinct API errors before inference. |
| `test_source_evidence_errors_keep_component_and_field_diagnostics` | Added | Missing GPA-credit attestation, a boolean provider flag and an unapproved exception yield their respective field-level errors. A literal negative flag is counted as an exclusion. Validation-only endpoints expose the diagnostic payload, split errors attach it to the submitted component, and combined errors include both payloads. |
| `test_http_manual_history_workflow_keeps_reads_and_activation_distinct` | Added | Status inspection and delta validation preserve the files and pending state. Administrative preview persists evidence, and recommendation serving preserves it. Commit makes a verified bundle available for inspection, activation makes it usable for normal serving, and rollback requires explicit confirmation. Cutoffs, digests and history-derived predictions identify the selected bundle. The previously captured snapshot preserves its original metadata and feature values after activation. |
| `test_http_finalization_requires_its_credential_and_auto_mode` | Added | A trusted finalization event requires automatic mode, the finalization credential and finalized-semester proof. A wrong-mode attempt records a failure while preserving the active cutoff and available versions. A successful event commits and activates the next snapshot. |

The tests use in-process FastAPI requests, generated provider payloads, deterministic predictors, and temporary directories for SQLite and history state. The history test uses a synthetic Stage 2 grade predictor that returns a snapshot feature so the selected data is visible in the response.

## Verification

| Run | Result |
|---|---|
| Full suite before edits | **959 passed, 2 failed, 2 skipped** in 85.50 s |
| Changed HTTP cases | **14 passed**, 7 deselected in 7.30 s |
| Relevant unit tests | **561 passed, 2 failed, 2 skipped** in 73.02 s |
| Complete HTTP integration file | **21 passed** in 6.87 s |
| Full suite after edits | **969 passed, 2 failed, 2 skipped** in 97.19 s (973 cases) |

The relevant unit run included the API request store, portable settings and runtime catalog, candidate contract, all two-stage modules, ranking and Balance, artifact provenance, and frozen, cumulative and incremental history tests. All runs used the existing Windows virtual environment with temporary directories outside the checkout. In-process HTTP runs required the local loopback socket pair used by Windows asyncio and made no external requests.

### Baseline comparison

- `tests/unit/test_frozen_history.py::test_cli_accepts_custom_source_by_contract_without_filename_label[finalized_outcomes.parquet]` and `[export.parquet]` failed in the baseline, relevant unit run and final full suite. Both cases supply `outcomes.parquet` while asserting a different filename in the metadata. The artifact checksum matched.
- `tests/unit/test_standalone_timeout.py::test_timeout_stops_owned_descendants_before_temporary_cleanup` had a previously documented Windows failure. It passed in both full-suite runs in this phase.
- The two full-suite skips covered the POSIX permission case on Windows and pinned-model activation with absent model artifacts. The HTTP runs emitted a Starlette TestClient dependency deprecation warning.
- The final run added 10 passing cases. It reproduced the same two failure nodes and two skips as the fresh pre-edit baseline, with no new failing nodes.

## Ambiguities and coverage boundaries

- HTTP parity covers the route alias `/recommend`. External callers of the Python compatibility modules were outside this phase, so the tests provide no evidence about which import paths those callers need.
- The API exposes the selected cutoff and keeps the full snapshot provenance in the core. The tests connect public predictions to the snapshot's data and verify the digest through the public history inspection and snapshot interfaces.
- Normal-mode HTTP behavior after rollback is covered. Older-history backtesting and simultaneous worker capture have existing direct tests. This phase does not establish an HTTP timing guarantee for simultaneous requests and activation.
- The tested diagnostics retain error codes and field association. Precedence among all possible combinations of independent invalid inputs remains unspecified. These runs used synthetic data and did not verify live University Backend payloads or trained model performance.

## Final Git diff

| Path | Git status | Change |
|---|---|---|
| `tests/integration/test_api_stable.py` | Modified | 333 insertions, 17 deletions |
| `docs/reports/API_RECOMMENDATION_PARITY_TESTS_REPORT.md` | New, untracked | Requested Phase 2 coverage and verification report |

The final diff has **zero production files** and no staged changes. Scoped whitespace checks passed. The Phase 2 stop condition limits the change set to the integration tests and this report.

**Final status** PASS WITH WARNINGS. Phase 2 is complete and Phase 3 awaits explicit approval.
