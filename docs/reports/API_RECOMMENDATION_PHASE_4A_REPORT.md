# Phase 4A — Registration policy consolidation

**Repository** Academic_Advisor_Stable

**Date** 2026-11-18

**Outcome** PASS WITH WARNINGS

## Initial Git state

The clean working tree was on `data_cleaning`, tracking `origin/data_cleaning` at `76624c8a98cde0a86565a3c60a7fa2363f52d520` (`P3`). There were no staged, unstaged, or non-ignored untracked changes. The Phase 2 and Phase 3 reports and test changes were present in the commit.

The flow below was checked against the current source and tests. The previous reports established the boundaries and the failure baseline. [API and recommendation audit](API_RECOMMENDATION_AUDIT.md) · [Consolidation plan](API_RECOMMENDATION_CONSOLIDATION_PLAN.md) · [Phase 2 parity report](API_RECOMMENDATION_PARITY_TESTS_REPORT.md) · [Phase 3 report](API_RECOMMENDATION_PHASE_3_REPORT.md)

## Previous and current responsibilities

| Area | Previous responsibility and behavior | Responsibility after Phase 4A |
|---|---|---|
| HTTP and requested credits | `schemas.RecommendationOptions` accepted an exact value or both range endpoints. `ApiService._build_engine_request` parsed finite nonnegative numbers, represented exact credits as a single-point interval, rejected reversed bounds, intersected the request with the effective provider interval, and used the upper endpoint as the exact target. | Request shape, numeric parsing, reversed-range diagnostics and error translation remain in the API. The service delegates interval intersection to `registration_policy.intersect_credit_bounds`. |
| Provider limits | `validators.courses._rules` verified the provider load type and every supplied interval, then intersected the general limits with the confirmed study or graduation profile. The same validation ran for validation-only calls. | Field parsing, profile selection, ordered-range checks and `CONFLICTING_RULES` diagnostics stay in the validator. The profile and request intersections now use the same calculation. |
| Course groups | The validator checked source identity, literal eligibility, official prior status, provenance, catalog agreement, policy mode and allowance. The adapter computed strict remaining credits or the zero-clamped approved-overflow cap, or deferred an unbounded group to availability. | The API keeps source checks, diagnostic ordering and stable degree-scoped group IDs. The adapter passes confirmed values to `registration_policy.requirement_group_cap`. |
| Requirement-type and elective caps | The service summed eligible, deduplicated candidate credits by type and used the same available-credit sum for unbounded groups. Direct callers could supply a type maximum with overflow, completed and reserved adjustments. Elective limits used those generic type and group caps. | `registration_policy.candidate_credit_caps` computes availability-based caps. `remaining_requirement_credits` supplies the shared zero-clamped arithmetic for explicit type caps and approved group overflow. Strict group subtraction retains its original Decimal representation. |
| Engine inputs | The service serialized the exact target, type and group caps, failed and optional withdrawn repeat budgets, and optional maximum new courses. `inputs.normalize_request_payload` and `PlanConstraints` validated the ready mapping. | The same engine payload shape and optional-field handling remain. The engine-side normalization now uses the consolidated credit calculation. `PlanConstraints`, candidate status classification, exact enumeration and ranking retain their existing behavior. |
| Direct bounds and precision | `plan_generation.resolve_credit_bounds` normalized direct credit inputs, and two arithmetic helpers supported exact addition and subset comparisons. `inputs` permitted exact plus valid range and chose the exact value. | Moved `resolve_credit_bounds`, `sum_credit_values`, and `decimal_credit_units` to the policy module. Their old `plan_generation` imports remain available. Exact-plus-range precedence and the direct positive-target rule remain at the ready-input boundary. |

The policy module uses only the Python standard library. It accepts normalized `Decimal` intervals and credits for calculations, with direct-core bounds normalization retaining its existing accepted input forms. It has no dependency on source attestation, `ApiError`, FastAPI, candidate scoring, or history. The API calls it after its own validation and translates empty intersections using the original messages and codes.

## Files changed and final Git diff

| File | Change |
|---|---|
| `src/recommendation/registration_policy.py` | New module for bounds, exact credit arithmetic and cap calculations |
| `src/recommendation/plan_generation.py` | Re-export the relocated credit helpers for compatibility. Search and row expansion are intact. |
| `src/recommendation/inputs.py` | Import the direct credit normalizer from its new home |
| `src/recommendation/constraints.py` | Delegate net requirement-credit calculation. ID, alias and cap enforcement stay here. |
| `src/api/validators/courses.py` | Delegate the effective provider credit intersection |
| `src/api/adapters/courses.py` | Delegate confirmed group cap arithmetic after source validation |
| `src/api/service.py` | Delegate request intersection and availability-based caps, preserving the engine payload |
| `tests/unit/test_registration_policy.py` | New six-case direct policy and elective feasibility coverage |
| `tests/integration/test_api_stable.py` | Added five HTTP cases for group modes and evidence diagnostics. The existing assertions remain intact. |
| `docs/CHANGELOG.md` | Appended the Phase 4A entry |
| `docs/reports/API_RECOMMENDATION_PHASE_4A_REPORT.md` | This report |

The reviewed diff consists of eight modified tracked files and three new files. Scoped whitespace checks passed. No changes were staged. The earlier phase reports and tests remain in place, with the only Phase 4A change to the existing HTTP test file being an insertion.

## Tests and behavioral parity

| Run | Result |
|---|---|
| Phase 3 full-suite reference | **970 passed, 2 failed, 2 skipped** |
| Fresh pre-edit constraints, payload, shortlist and HTTP subset | **151 passed** in 8.60 s |
| New registration policy unit tests | **6 passed** in 0.76 s |
| Relevant API and recommendation unit tests | **459 passed, 2 skipped** in 63.27 s |
| Complete `tests/integration/test_api_stable.py` file | **26 passed** in 8.18 s |
| Full suite after Phase 4A | **981 passed, 2 failed, 2 skipped** in 93.22 s (985 cases) |

- Existing HTTP cases verify exact and ranged requests, provider clipping, schema rejection of a missing bound, reversed and disjoint range diagnostics, and the absence of a lower-target fallback. The clip-to-exact case compares the complete response, including the normalized fingerprint and ranking.
- New direct cases verify the matching exact target from different accepted intervals, the direct invalid-bounds contract, fractional caps, zero-clamped approved overflow, and elective type caps after completed and reserved credits. HTTP cases verify strict, approved-overflow and unbounded groups at an identical target, candidate deduplication, and field-level rejection of conflicting strict group evidence before scoring.
- The synthetic before-and-after probe serialized public HTTP bodies and statuses, normalized adapter results, engine constraint payloads, and ready-core outcomes. All 18 HTTP and five ready-core observations matched byte for byte. The shared digest was `4534bb2342fe5dfb99dae5293430f1e351f891540fb0c67da7b50a891ca40859`. A fresh-process import check loaded the policy alone without loading API modules and then loaded the legacy helper, engine input and API modules successfully.
- The full suite reproduced both known filename assertions in `tests/unit/test_frozen_history.py`, `test_cli_accepts_custom_source_by_contract_without_filename_label[finalized_outcomes.parquet]` and `[export.parquet]`. Those tests were outside the diff. The final result adds 11 passing cases to the Phase 3 reference, with the same failing nodes and skips. The known Windows subprocess timeout passed.

## Remaining limits

The phase used synthetic provider evidence and deterministic predictors. Live University Backend payloads and pinned-model behavior remain unverified. The full-suite skips covered POSIX permissions on Windows and missing pinned model artifacts. In-process HTTP testing used Windows asyncio local loopback. Starlette TestClient emitted its existing dependency deprecation warning.

Phase 4A ends here. Phase 4B awaits explicit approval.
