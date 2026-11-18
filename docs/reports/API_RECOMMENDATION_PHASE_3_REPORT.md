# Phase 3 — Safe API and recommendation consolidation

**Repository** Academic_Advisor_Stable

**Date** 2026-11-18

**Outcome** PASS WITH WARNINGS

## Initial Git state

- Branch `data_cleaning` tracked `origin/data_cleaning` at `f18a89aa8c481979d69ae77f40e0763df54ad7d6`. There were no staged changes.
- The working tree already contained an unstaged change to `tests/integration/test_api_stable.py` and the untracked `docs/reports/API_RECOMMENDATION_PARITY_TESTS_REPORT.md`. Before-and-after SHA-256 checks confirmed that both files retained their original bytes.
- The [audit](API_RECOMMENDATION_AUDIT.md), [consolidation plan](API_RECOMMENDATION_CONSOLIDATION_PLAN.md), [history failure investigation](HISTORY_FAILURES_INVESTIGATION.md), [Phase 1 history test report](HISTORY_TEST_FIXES_REPORT.md), and [Phase 2 parity report](API_RECOMMENDATION_PARITY_TESTS_REPORT.md) guided the edits. The locations and consumers below were verified in the current source.

## Findings and changes

| Item | Finding verified before editing | Change |
|---|---|---|
| A. Candidate count | `adapt_courses()` assigned the same count on both sides of `validate_course_rules()`. If rule validation raised an error, the first assignment supplied the diagnostic count. | Removed the second assignment in `src/api/adapters/courses.py`. |
| B. Startup import | `ApiService.initialize()` imported pandas locally without using it in the method or its default loader callables. | Removed the local import in `src/api/service.py`. |
| C. Protected history root | `CumulativeHistoryStore` resolved the canonical frozen-history path twice in the same list and optionally added a separate legacy root. | Kept one canonical entry and the separate legacy-root check in `src/recommendation/cumulative_history.py`. |
| D. Course groups | Constraints held a separate set of the three groups emitted by classification plus `OTHER_PREVIOUS`. Balance read the private constraints set. | Derived the allowed set from the existing mapping and fallback in `src/recommendation/course_status.py`. Both `src/recommendation/constraints.py` and `src/recommendation/balance_policy.py` now import it from there and preserve their existing aliases. The classification values and the normalization and validation at each consumer remain the same. |
| E. Request ID pattern | Split HTTP schemas repeated the same anchored pattern with strict strings and field length limits. The request store used Python full-match against a bounded regex and returned its own errors. | Shared the first and subsequent character classes in `src/api/validators/common.py`. `src/api/schemas.py` and `src/api/request_store.py` still construct their exact original regex strings and enforce types and length at the same points. |

All five items were implemented. The similar expression in `src/api/settings.py` validates service-account owner names under a separate contract. No recommendation module validates HTTP request IDs. The four compatibility modules and the two known failing cases are outside this change set.

## Behavioral parity evidence

- **A and B.** The before-and-after probe returned the same public course diagnostics for a valid request and for a rejected load rule. Both reported four adapted candidates. Initialization with the existing synthetic dependencies returned the same readiness and recommendation body.
- **C.** The probe tested root equality, ancestry and descendants against a temporary canonical root and checked the separate legacy root. Overlap returned the same `HISTORY_ROOT_OVERLAP` error code and status, and an unrelated root was accepted.
- **D.** The new `test_classified_groups_flow_through_feasibility_and_balance` in `tests/unit/test_two_stage_payloads.py` passed before and after the production edits. It verifies all four groups through classification, exact feasibility and Balance credit totals. Missing and unrecognized statuses retain their distinct status meanings and both map to `OTHER_PREVIOUS`. A raw `UNKNOWN` group is rejected by both downstream consumers.
- **E.** The probe compared both split JSON schemas, 30 split HTTP responses, and lookup responses. Cases included mixed-case and case-distinct IDs, one and 128 characters, over-limit and malformed strings, and numeric, boolean and null values. It also compared error precedence with invalid authentication and with invalid store owner and request ID. The canonical and alias recommendation results and completed split bodies matched, including their input fingerprint, ordered plans and metadata.
- The before-and-after probe's serialized observations had the same SHA-256 digest, `ab16da70a200c73b14a58f12b39e625d2c6a3652fe5bc4a4a0f76121ef10e7f9`. A fresh process imported the changed API and recommendation modules successfully. The shared dependencies have no imports back to their consumers.

## Verification and Phase 2 comparison

| Run | Result |
|---|---|
| Phase 2 full-suite baseline | **969 passed, 2 failed, 2 skipped** |
| Fresh Phase 3 pre-edit API, recommendation and HTTP subset | **262 passed, 1 skipped** in 17.97 s |
| New course-group test against original production code | **1 passed** in 0.74 s |
| Phase 3 focused group, request ID and history-root cases | **24 passed** in 1.14 s |
| Relevant API and recommendation unit tests | **562 passed, 2 failed, 2 skipped** in 76.23 s |
| `tests/integration/test_api_stable.py` | **21 passed** in 7.00 s |
| Full suite after Phase 3 | **970 passed, 2 failed, 2 skipped** in 91.62 s (974 cases) |

The historical filename assertions in `tests/unit/test_frozen_history.py` reproduced in both post-edit runs that included them.

- `test_cli_accepts_custom_source_by_contract_without_filename_label[finalized_outcomes.parquet]`
- `test_cli_accepts_custom_source_by_contract_without_filename_label[export.parquet]`

The full suite gained one passing case compared with Phase 2, with the same two failing nodes and two skips. The previously reported Windows subprocess timeout passed.

The Windows POSIX-permission skip and missing pinned-model artifacts remained. The in-process HTTP run used the Windows asyncio loopback socket pair and emitted the existing Starlette TestClient deprecation warning. Fixtures and probe outputs used temporary scratch storage and synthetic payloads.

## Final Git diff

| File | Phase 3 change |
|---|---|
| `src/api/adapters/courses.py` | 0 insertions, 1 deletion |
| `src/api/service.py` | 0 insertions, 1 deletion |
| `src/recommendation/cumulative_history.py` | 1 insertion, 1 deletion |
| `src/recommendation/course_status.py` | 3 insertions, 1 deletion |
| `src/recommendation/constraints.py` | 1 insertion, 3 deletions |
| `src/recommendation/balance_policy.py` | 2 insertions, 1 deletion |
| `src/api/validators/common.py` | 4 insertions |
| `src/api/schemas.py` | 7 insertions, 2 deletions |
| `src/api/request_store.py` | 3 insertions, 2 deletions |
| `tests/unit/test_two_stage_payloads.py` | 34 insertions |
| `docs/CHANGELOG.md` | Phase 3 entry appended |
| `docs/reports/API_RECOMMENDATION_PHASE_3_REPORT.md` | This report, new and untracked |

The reviewed production diff totals 21 insertions and 12 deletions. Whitespace checks passed. The two pre-existing Phase 2 paths remained present and were excluded from the Phase 3 diff totals. No changes were staged.

## Remaining risks and boundary

Live University Backend payloads and real pinned-model activation were outside the synthetic parity check. The two baseline filename failures remain. Phase 3 is complete and Phase 4 awaits explicit approval.
