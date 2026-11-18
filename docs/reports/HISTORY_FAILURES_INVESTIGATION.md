# Investigation of two history test failures

**Repository** Academic_Advisor_Stable  
**Date** 2026-11-18  
**Final decision** Both failures are test expectation/fixture problems.

| Failing test | Classification | Resolution |
|---|---|---|
| `tests/unit/test_cumulative_history.py:85–99` · `test_approved_initialization_preserves_full_weighted_history_and_source` | Incorrect expectation. The test requires different hashes for independently identified files whose contents can be identical. | Test correction. Verify each hash against its own file and verify source preservation and activation. |
| `tests/unit/test_history_update.py:337–350` · `test_latest_valid_load_skips_incomplete_corrupt_and_wrong_version` | The fixture labeled wrong-version remains valid. Its JSON is reformatted without changing any values. | Fixture correction. Create a violation of a current metadata invariant and retain the fallback and skip checks. |

The focused run reproduced both failures and passed 10 related cases. A separate synthetic probe confirmed the causes and exercised the proposed checks. Repository writes were limited to this report.

## 1. Cumulative initialization and state hashes

### Expected and actual behavior

Initialization publishes a verified copy of the approved cumulative `20251` state under a separate root. It preserves the weighted statistics and records both the source file identity and the published file identity. The active pointer uses the published file's digest. The contract requires each digest to match its corresponding file. Equality between the two digest values is permitted.

The test fails at `tests/unit/test_cumulative_history.py:96` because both `course_history_state.pkl` files had the same SHA-256. The probe confirmed byte-for-byte equality across all **4,234 bytes**:

```text
6582df8abcdc30ad6c83cfb5650c9fa5aafafa1aaaf868a33f1bd60f4dc6848a
```

The published `metadata.json` had different bytes from the source metadata. The probe also confirmed that the source files retained their original bytes, all five aggregate tables and the global sums matched exactly, and the durable pointer activated `20251` using the published pickle digest.

### Fixture and failing assertion

- `tests/unit/test_cumulative_history.py:24–39` builds a state with synthetic outcomes from `20211`, `20243` and `20251`. It writes the source using the **current** `save_frozen_history()` serializer and supplies the SHA-256 of that source `metadata.json` to initialization.
- `tests/unit/test_cumulative_history.py:50–58` initializes in a separate temporary directory with explicit confirmation and a stubbed model compatibility check.
- `tests/unit/test_cumulative_history.py:85–99` checks preserved global sums, three raw observations, weighted effective support of 2.25, approved provenance and hash relationships. The assertions through line 95 pass. Line 96 requires the published state digest to differ from `baseline_source_history_sha256`. The later active-cutoff and table checks are reached by the synthetic probe separately. The weight follows `src/features/temporal_features.py:55–57`, where the pre-2022 row contributes 0.25 and each newer row contributes 1.

### What each hash identifies

| Field or value | Exact hashed data and verification |
|---|---|
| `expected_source_hash` and stored `baseline_source_metadata_sha256` | Raw bytes of the **source** `as_of_20251/metadata.json`. Initialization compares this file digest with the supplied approval value before loading the source. `src/recommendation/cumulative_history.py:268–273,283–289` |
| `baseline_source_history_sha256` | Raw bytes of the **source** `course_history_state.pkl`. It comes from the source metadata's `artifact_sha256` entry after the loader verifies that entry against the actual source file. `src/features/frozen_history.py:194–211` and `src/recommendation/cumulative_history.py:283–289` |
| Published `artifact_sha256["course_history_state.pkl"]` and `new_history_sha256` | Raw bytes of the **published** `course_history_state.pkl`, serialized in staging. The publisher hashes the staged file, records that digest in both fields, reloads and verifies the staged state, then publishes the directory. The active pointer and activation record use the verified published digest. `src/features/frozen_history.py:148–183,229–267` and `src/recommendation/cumulative_history.py:313–328` |
| Loader-returned `metadata_sha256` | Raw bytes of the particular `metadata.json` just loaded. The loader computes it for provenance. This field is distinct from the pickle hash and from the initializer's explicit comparison with an approved source metadata hash. `src/features/frozen_history.py:35–40,194–210,224–226` and `src/recommendation/cumulative_history.py:268–270` |

### Root cause and contract evidence

The implementation intentionally preserves **the state and accurate provenance**. It loads the source, checks the finalized cumulative prefix and compatibility, and passes the loaded `CourseHistoryState` to the atomic publisher (`src/recommendation/cumulative_history.py:255–289,313–328`). The state pickle contains `as_of_part`, `smoothing_k`, `min_support`, `tables` and `global_sums`. Publication time, approval and provenance are written separately to JSON. Since the fixture source uses the current serializer, the current load-and-save sequence emits the same byte stream in this case. The current implementation validates logical equivalence and the accuracy of the published digest. Its validation permits both byte-preserving and byte-changing reserialization. `src/features/temporal_features.py:420–444` and `src/features/frozen_history.py:162–182,244–256`.

Commit `7b1a0dd` supplies direct evidence for the intended distinction. Its change to `src/recommendation/cumulative_history.py` removed the previous rejection of published bytes differing from the source. It changed activation to use the published digest and retained the source digest as provenance. In the same diff, the test added independent hash assertions and the inequality at line 96. The inequality tries to distinguish source and output by their digest values. The implementation and `docs/CHANGELOG.md:112–116` distinguish them by **which bytes each field identifies**. The recovery path follows that rule as well. It checks the recorded source digest against the source and the existing artifact digest against `new_history_sha256`, then checks the aggregates. `src/recommendation/cumulative_history.py:290–312`.

For a positive control, the synthetic probe added the retired outer `format_version: 2` key to a scratch source pickle and recomputed the corresponding source metadata hash and artifact hash. Commit `d9c4019` removed that key from the canonical writer. The current loader accepts a payload with the required state keys and reconstructs the same aggregates (`src/features/temporal_features.py:433–444`). The probe published a **4,234-byte** canonical pickle from the **4,253-byte** synthetic source. Both digests matched their own files, and activation still succeeded. This demonstrates that reserialization can change the bytes while preserving the state.

### Recommended resolution after approval

**Test correction.** Replace the inequality-only check with a direct digest check against the separately published pickle. Retain the source file digest and source metadata digest checks, and keep the weighted aggregate, provenance and cutoff assertions. Strengthen coverage by comparing source file bytes before and after initialization and checking that the active pointer records the published digest. A separate deliberately noncanonical fixture can cover differing digests if that case needs an explicit regression test. No production-code change is required for this failure.

## 2. Latest valid history selection

### Expected and actual behavior

`FrozenHistoryManager.load()` scans validly named `as_of_*` directories in descending cutoff order and returns the first bundle that passes verification. Its `skipped_bundles` records failed candidates encountered before the successful candidate. It does not collect diagnostics for older directories once it finds a valid bundle. `src/recommendation/history_update.py:278–299`.

The test expects `20251` and three skipped bundles. The current fixture's newest bundle, `20261`, passes validation, so the manager returns it and reports **zero** skips. The assertion at `tests/unit/test_history_update.py:349` fails before the skip-count assertion. `capture(target_part=20262)` selects the pinned `20261` snapshot. That is the immediately preceding academic part (`src/recommendation/history_update.py:301–321` and `src/features/frozen_history.py:43–60`). Selection of `20261` is correct for the fixture as written.

### Fixture and relevant assertions

`weighted_state()` creates two synthetic rows. `save_initial()` assigns the requested cutoff, sets matching source-maximum and finalized-through fields, and writes the current bundle format. The helper deliberately stamps cutoffs on a fixed synthetic state for loader testing. It does not test underlying semester-data provenance. `tests/unit/test_history_update.py:35–43,59–68`.

| Bundle | What the failing test actually constructs |
|---|---|
| `20243` and `20251` | Complete synthetic bundles. |
| `20252` | An empty directory. The required `metadata.json` is missing. |
| `20253` | A complete bundle whose pickle is replaced with invalid bytes. The saved digest still refers to the original pickle, so verification stops at the checksum mismatch. |
| `20261` | A complete bundle. The test reads and reserializes its metadata without changing any decoded values or touching the pickle. |

The construction and expectations are at `tests/unit/test_history_update.py:337–350`. The probe confirmed that the JSON formatting changed the metadata file SHA-256 and left the decoded values and the actual pickle SHA-256 unchanged. The ordinary frozen loader returns a freshly computed metadata digest as provenance. It does not compare that digest with a previously approved value during discovery. The expected source-metadata digest comparison applies separately to cumulative initialization. `src/features/frozen_history.py:194–226` and `src/recommendation/cumulative_history.py:268–270`.

### Current conditions for skipping a bundle

| Validation | Evidence |
|---|---|
| Discovery accepts directories with parseable `YYYY1`, `YYYY2` or `YYYY3` cutoffs. Invalid names and non-directories are ignored before a bundle is attempted. | `src/paths.py:56–64` and `src/recommendation/history_update.py:283–288` |
| An attempted bundle fails when required files are missing or unreadable, metadata cannot be parsed, `history_type` differs, `as_of_part` or `source_max_part` disagrees with the directory cutoff, or `finalized_through_part` is absent, invalid or earlier than the cutoff. | `src/features/frozen_history.py:194–210` |
| File digest mismatch, supported pickle load errors, missing required serialized state keys or state cutoff mismatch reject an attempted bundle. If a specialty artifact is present or declared, its file/hash, required keys and cutoff are checked too. | `src/features/frozen_history.py:63–67,201–226` and `src/features/temporal_features.py:433–444` |
| After file loading, the manager validates state type/configuration, five table levels, statistic schema and consistency, finite nonnegative sums, valid keys and agreement between table and global sums. If metadata declares `aggregate_delta_v1`, it also checks that delta's lineage and recorded digests. This source fixture has no aggregate-delta update method. | `src/recommendation/history_update.py:134–162,242–259,291–298` |
| The manager records handled load failures and continues to an older cutoff. If no candidate passes, it raises `FileNotFoundError`. A request-time cutoff failure occurs later in `capture()` and follows its separate temporal rule. | `src/recommendation/history_update.py:289–321` |

### Root cause, contract evidence and recommended resolution

Commit `d9c4019` removed numbered dataset/format gates, as documented in `docs/CHANGELOG.md:118–122`. The diff for `tests/unit/test_history_update.py` also removed the line that assigned `metadata["dataset_version"] = "V1"`. This left a formatting-only write and retained the earlier fallback assertions. The current writer excludes retired version fields and the reader validates its single canonical contract through contents, cutoffs and artifact hashes. `src/features/frozen_history.py:172–179,186–211`. The baseline report had already observed selection of `20261` in this case. `docs/reports/STABILIZATION_VERIFICATION_REPORT.md:57–64`.

**Fixture correction.** Set `source_max_part` to `20253` in the synthetic `as_of_20261` metadata, leaving the directory and state at `20261`. This exercises the existing cutoff rule and retains the intended assertions for selection of `20251` and three skips. Rename the case to describe metadata/cutoff mismatch. The scratch probe produced the exact rejection sequence `20261` (metadata/cutoff mismatch), `20253` (pickle hash mismatch), `20252` (missing metadata), then returned `20251`. No production-code change or new version rule is required.

## Verification and scope

- The focused pytest run exercised both reproductions plus approval and baseline recovery, deterministic serialization, corrupt-file and corrupt-lineage rejection, and no-overwrite checks. **10 passed and 2 failed**. The two failures were the original assertions at `tests/unit/test_cumulative_history.py:96` and `tests/unit/test_history_update.py:349`.
- The synthetic probe used the existing fixture helpers in a disposable workspace directory. Both initialization variants and both discovery variants passed their checks.
- The decisions apply to these two tests and the current contract. Historical project bundles were outside the runtime probe. The report stops at the recommended test corrections pending approval.
