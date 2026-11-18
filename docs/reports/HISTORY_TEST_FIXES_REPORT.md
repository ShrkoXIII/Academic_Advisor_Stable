# Phase 1 history test fixes

**Repository** Academic_Advisor_Stable  
**Date** 2026-11-18  
**Phase status** PASS WITH WARNINGS. Both approved corrections pass. Verification found failures outside the two corrected tests.

## Changes

| Test | Exact change |
|---|---|
| `tests/unit/test_cumulative_history.py:85–110` · `test_approved_initialization_preserves_full_weighted_history_and_source` | Snapshot the existing synthetic source bundle's filenames and bytes before initialization and compare them afterward. Preserve the source metadata and source state SHA-256 checks against their actual files. Replace the source/published inequality with a digest of the published pickle and require both published metadata fields and the active pointer to match it. Preserve the weighted sums and table comparisons, approval provenance checks and active cutoff `20251`. |
| `tests/unit/test_history_update.py:337–351` · `test_latest_valid_load_skips_incomplete_corrupt_and_cutoff_mismatch` | Rename the test to describe the current metadata rule. Set `source_max_part` to `20253` in the synthetic `as_of_20261/metadata.json` while retaining the directory and state cutoff at `20261`. Keep the expected fallback to `20251` and three skipped bundles. |

Both changes follow `docs/reports/HISTORY_FAILURES_INVESTIGATION.md`. The shared fixture helpers are the same. Phase 1 made zero production code changes.

## Verification

| Run | Result |
|---|---|
| Before editing, the two original nodes | **2 failed** in 2.25 s. Cumulative initialization produced matching source and published SHA-256 digests. The formatting-only fixture kept `20261` valid. |
| After editing, the two corrected nodes | **2 passed** in 2.15 s. |
| Related history files (`test_cumulative_history.py`, `test_history_update.py`, `test_frozen_history.py`) | **109 passed, 2 failed** in 26.79 s. Both failures were the previously documented filename-parameter cases in `test_frozen_history.py`. |
| Complete `tests` suite | **958 passed, 3 failed, 2 skipped** in 190.16 s (963 collected, one warning). Both corrected cases passed in the full run. |

The tests ran with Stable's existing virtual environment, pytest caching and bytecode writes disabled, and scratch fixtures outside the checkout. The full run used the writable audit workspace as the starting directory to avoid Windows working-directory restoration errors. The repository was on the Python import path. Network permission enabled the Windows asyncio loopback socket pair used by in-process integration tests.

## Failures outside this phase

- `tests/unit/test_frozen_history.py:123–132` · `test_cli_accepts_custom_source_by_contract_without_filename_label[finalized_outcomes.parquet]` and `[export.parquet]`. Both cases pass `outcomes.parquet` to the CLI but expect their parameterized filename in provenance. The actual path was `outcomes.parquet` and the checksum matched. The same two failures were documented in `docs/reports/STABILIZATION_VERIFICATION_REPORT.md:59–64`.
- `tests/unit/test_standalone_timeout.py:19` · `test_timeout_stops_owned_descendants_before_temporary_cleanup`. The child wrote `surviving-worker.txt` after the timeout. This failure was previously documented in `docs/reports/STABILIZATION_VERIFICATION_REPORT.md:64`.

The full suite skipped the POSIX request-store permissions case on Windows and the pinned-model activation case because the required model and manifest files were absent. FastAPI's Starlette TestClient issued one dependency deprecation warning.

## Final Git diff

| Tracked file modified by Phase 1 | Insertions | Deletions |
|---|---:|---:|
| `tests/unit/test_cumulative_history.py` | 17 | 6 |
| `tests/unit/test_history_update.py` | 2 | 1 |
| **Total** | **19** | **7** |

The checkout had 13 pre-existing tracked modifications. Direct working-tree diff commands hit a Windows access restriction, so the Git diff was inspected using a writable snapshot of the tracked worktree and the repository's real Git index. A byte-level comparison against the pre-edit snapshot of all 150 tracked paths confirmed these were the only two tracked changes introduced in this phase. Scoped `git diff --check` passed. The requested `docs/reports/HISTORY_TEST_FIXES_REPORT.md` is the new report. The index has no staged changes.

Phase 1 stops here pending approval for further work.
