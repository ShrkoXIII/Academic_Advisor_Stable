# API and recommendation consolidation plan

**Repository** Academic_Advisor_Stable  
**Date** 2026-11-18  
**Decision requested** Approve a staged, behavior-preserving consolidation after review.

The current service already has one engine and two supported ways to submit a request. The proposed architecture keeps that convergence and makes the recommendation package responsible for typed academic policy, serving preparation, plan evaluation and history. The API retains provider evidence checks, HTTP policy and the split request lifecycle. Finding IDs refer to the [audit](API_RECOMMENDATION_AUDIT.md).

## Proposed architecture

| Layer | Responsibilities |
|---|---|
| HTTP and deployment | `app.py` and `schemas.py` own routes, authentication, Decimal request parsing, schema errors, response serialization and HTTP status shapes. `settings.py` owns deployment and credential settings. |
| API application service | `service.py` preserves the service entry points and public diagnostics. It composes API dependencies, coordinates SQLite split intake and request ownership, translates authorized admin operations, and maps recommendation errors and metadata to the existing HTTP contract. The request store remains API-owned. |
| Source adaptation | API student and course adapters plus their validators bind the University Backend evidence to requests and map provider field names into typed facts. The catalog loader and catalog checks remain at this boundary. One history adapter translates and validates the HTTP delta envelope for diagnostics and administrative submission. |
| Recommendation preparation | `inputs.py` accepts the ready in-process payload and owns shared snapshot derivation. A `registration_policy.py` module turns validated typed load and requirement-group facts into the existing target and caps. `course_status.py` owns normalized meanings and candidate groups. `constraints.py` consumes those hard constraints. The API can still surface policy failures during validation by invoking the same pure policy logic. |
| Serving composition | `serving.py` owns application-independent artifact/policy compatibility and request-time history selection. It accepts loaded or injected dependencies and explicit serving options. It returns typed failures for API translation. API authentication, service keys, status codes, optional-dependency diagnostics and deployment flags stay at the boundary. Preserve lock behavior while drawing this boundary. |
| Inference and history | `two_stage_engine.py` orchestrates the existing 31 → 50 → 43 flow. Search, scoring, shortlist, hard constraints, Balance and ranking keep their separate responsibilities. Scoring computes metrics and ranking orders them. `history_update.py` keeps aggregate validation and immutable bundles, while `cumulative_history.py` owns pointer, approval, workflow and concurrency. `two_stage_artifacts.py` verifies and loads pinned assets. |

## File-by-file decisions

`MOVE` indicates a responsibility transfer. Several files remain in place with narrower responsibilities. `REMOVE` lists conditional removal candidates. `REVIEW` calls for more evidence before layout or interface changes.

### API (20)

| File under `src/api` | Decision | Reason and impact |
|---|---|---|
| `__init__.py` | KEEP | Package marker. |
| `app.py` | KEEP | One transport for both intake forms. Preserve decimal parsing, dependency injection, aliases, authentication and envelopes. |
| `schemas.py` | KEEP | HTTP shape and strictness are separate from provider semantics and core ready-input validation. A shared request ID pattern may be introduced without changing schema fields. Preserve exact-or-range rejection and existing safe errors. |
| `service.py` | MOVE | Move load/cap assembly to recommendation `registration_policy` and artifact/history serving decisions to recommendation `serving`. Retain settings, dependency/bootstrap wiring, ingress diagnostics, split workflow, locks until safely redrawn, admin auth translation and response redaction here. Preserve `ApiService` constructor and public methods. F01, F03, F08–F09. |
| `settings.py` | REVIEW | Keep all current contracts while checking direct-fetch environment fields against deployment and downstream callers. Startup validation of configured values is observable even without a fetch consumer. F11. |
| `catalog.py` | KEEP | Small adapter with a concrete Parquet-to-string-ID contract. Keep isolated from policy code and candidate sourcing. |
| `request_store.py` | KEEP | SQLite claims and retention are unique to split intake and independent of academic state. Preserve typed serialization, thresholds and active DB compatibility. F09, F12. |
| `adapters/__init__.py` | KEEP | Package marker and orientation. |
| `adapters/student.py` | MOVE | Move pure derived snapshot values into the recommendation input surface. Keep PHP mapping, attestation, validation diagnostics and direct use of shared history features at the boundary. Maintain API `None` and core `NaN` behavior where observable. F02. |
| `adapters/courses.py` | MOVE | Move exact group-cap arithmetic and unbounded cap resolution to typed registration policy. Keep PHP names, normalized rows, stable group identity and diagnostic ordering in the adapter. Candidate-count double assignment is a small independent cleanup. F01, F11. |
| `adapters/history.py` | MERGE | Receive the small history validator implementation and share its envelope translator with administrative service calls. Keep the diagnostic method's callable shape, error mapping, read-only preview and normalized aggregate result. F08. |
| `validators/__init__.py` | KEEP | Package marker and orientation. |
| `validators/common.py` | KEEP | Boundary validators and error/diagnostic contracts. Keep API parsing and JSON conversion independent of core fingerprints and SQLite. F12. |
| `validators/student.py` | KEEP | Evidence and temporal interpretation of PHP fields belong here. Preserve the strict attested GPA-credit derivation and historic identity checks. F02, F12. |
| `validators/courses.py` | MOVE | Keep source identity, literal eligibility, reason/policy evidence and catalog checks. Move profile interval and typed group cap rules to `registration_policy`. Translate typed failures into existing API diagnostics, including validation-only calls. F01, F10. |
| `validators/history.py` | MERGE | Merge into `adapters/history.py` after caller checks. Keep core aggregate validation delegation and errors on the HTTP boundary. Consolidate finalization checking with `ApiService._finalized_payload()`. F08. |
| `validation.py` | REMOVE | Only import forwarding to `validators.common`. Scoped callers are absent. Require consumer verification before deleting this import path. F07. |
| `student_adapter.py` | REMOVE | Only import forwarding to `adapters.student`, with private aliases. No scoped consumer. Verify public and private alias use before deletion. F07. |
| `courses_adapter.py` | REMOVE | Only forwards names from the canonical adapter and course validators. No scoped consumer. Verify downstream imports, including its explicit `__all__`. F07. |
| `history_adapter.py` | REMOVE | Only forwards `adapt_history_delta`. No scoped consumer. Verify deployment and downstream imports before deletion. F07. |

### Recommendation (14)

| File under `src/recommendation` | Decision | Reason and impact |
|---|---|---|
| `__init__.py` | KEEP | Package marker. |
| `inputs.py` | MERGE | Receive common semester, trend/missing and compatible snapshot derivations. Continue to own validation for ready callers. Preserve exact-plus-range precedence for the direct contract and do not broaden the HTTP schema. F02, F10. |
| `course_status.py` | MERGE | Receive the canonical allowed candidate-group vocabulary. Keep the existing official vs semantic code modes and classification defaults. Update constraints and Balance to consume it without private cross-module access. F10. |
| `constraints.py` | MOVE | Move candidate-group vocabulary to `course_status`. Keep hard feasibility and independent budget enforcement. Review how to expose shared credit normalization without changing the wider accepted Decimal range. F10, F12. |
| `plan_generation.py` | KEEP | Exact subset enumeration and row expansion are distinct from policy and model scoring. Keep precision, optional zero-credit selections and direct helper APIs. F06, F12. |
| `plan_scoring.py` | MERGE | Receive shared derivation of metrics after weighted sums. Provide a summary path for the engine that skips the preliminary legacy sort. Retain public standalone output and sort until callers are verified. `empty_summaries()` is a separate removal review. F04–F05, F11. |
| `shortlist.py` | MOVE | Move shared metric derivation into scoring, keeping exact Fraction weighted aggregation in Stage 1 and all feasible rows needed for ranking. Pass request-owned eligible-set Balance data through the existing shortlist operation when performance evidence supports it. F05–F06. |
| `ranking.py` | KEEP | Shared academic reference, identity and final ordering belong together. Keep the diagnostic ranker and strategy interfaces. Clarify evaluation-era names and docstrings without breaking imports. F04, F11. |
| `ranking_policy.py` | KEEP | Human approval verification is a distinct contract. Use the existing validator from the new serving composition. Keep common engine strategy flexibility while the API continues to require Pareto v1 at both stages. F03. |
| `balance_policy.py` | KEEP | Soft versioned decision rules belong outside hard constraints and predictors. Review computing eligible availability once per request through narrow internal helpers. Avoid changing policy fractions, enabled flags or plan scope. F06, F10. |
| `two_stage_engine.py` | MOVE | Move redundant serving preflight and snapshot selection coordination into the shared serving implementation while preserving direct engine validation and factory behavior. Maintain scoring and result construction here. Keep the history delegate while direct engine tests and caller compatibility require it. F03–F05, F11. |
| `two_stage_artifacts.py` | KEEP | Separate artifact verification from activation and inference. Protect portable paths, hashes, model headers, feature order and manifest publication interfaces. F03. |
| `history_update.py` | MERGE | Provide core operations accepting a validated immutable `HistoryDelta` for diagnostic preview and durable workflow internals. Preserve existing public payload-taking validation methods, bundle format and lineage hashes. F08, F12. |
| `cumulative_history.py` | MERGE | Reuse normalized-delta operations, keeping transactional workflow, retry rules, read-only serving, rollback and exact activation checks. Consider a snapshot-reader interface after coverage. `CumulativeHistoryStore` and `FrozenHistoryManager` have different responsibilities and lifecycles. F03, F08. |

## Proposed target directory tree

This end state assumes compatibility aliases are cleared for removal. If caller evidence is incomplete, keep the affected import shims through a deprecation period.

```text
src/
  api/
    __init__.py
    app.py
    catalog.py
    request_store.py
    schemas.py
    service.py
    settings.py
    adapters/
      __init__.py
      courses.py
      history.py
      student.py
    validators/
      __init__.py
      common.py
      courses.py
      student.py
  recommendation/
    __init__.py
    balance_policy.py
    constraints.py
    course_status.py
    cumulative_history.py
    history_update.py
    inputs.py
    plan_generation.py
    plan_scoring.py
    ranking.py
    ranking_policy.py
    registration_policy.py    # new, pure policy construction from validated facts
    serving.py                # new, serving policy and request-owned snapshot
    shortlist.py
    two_stage_artifacts.py
    two_stage_engine.py
```

## Implementation order after approval

1. **Pin behavior before moving code.** Establish focused parity fixtures for combined, alias and split HTTP responses. Cover exact/range handling at both contracts, source eligibility and diagnostics, admin/read-only history differences, and snapshot identity during activation. Record current hashes, plan identities and ordering. Verify all four shim import paths and candidate stale settings against consumers within an approved wider lookup. Keep existing assertions. Address any failing baseline before attributing differences to consolidation.
2. **Remove low-risk duplication in place.** Drop the duplicate count assignment, unused local import and duplicate protected-root item. Keep compatibility-specific byte limits and validation guards. Consolidate the group vocabulary and request ID pattern with their existing casing, types and error semantics. Treat public signature cleanup as a compatibility change.
3. **Extract registration and shared snapshot calculations.** Move one typed rule at a time from API validators/adapters/service. Compare provider diagnostics, successful candidate order, requirement group arithmetic, exact Decimal target, plan IDs and public response. Maintain recommendation's ready-input contract and API adapter field-readiness output.
4. **Make scoring and ranking each do one job.** Keep per-stage aggregation and predictor inputs, share derived calculations, and bypass the legacy sort for the engine. Verify final order, Balance flags, ties, display values, exact fractions and empty-plan behavior before assessing removal of compatibility helpers. Measure reuse of eligible-set Balance data separately from any search or ranking algorithm change.
5. **Consolidate serving and history safely.** Keep distinct artifact-shape and activation gates. Have serving preparation share the Pareto check and capture one verified history snapshot per inference. Add concurrency/fault-path characterization first. Share delta envelope translation and normalized core delta handling while preserving read-only diagnostics, durable preview, commit, activation and recovery. Retain original public wrappers until the owner-facing HTTP and direct-core tests pass.
6. **Retire verified-unused paths.** Remove import-only modules only after supported consumers are migrated or absence is documented. Verify import compatibility decisions, portability and release layout. Review stale configuration and `empty_summaries()` separately. Align relevant architecture documentation with 31/43 and the shared ranker when documentation edits are approved.

## Compatibility and risk gates

| Risk | Required evidence for the proposed change |
|---|---|
| Academic interpretation | Current provider Y/N and exception evidence, prior status/attempt meaning, GPA-credit attestation, cutoffs, exact upper-intersection target, group modes, maximum new courses, repeat allowances and treatment of missing fields match the baseline. Preserve the current use of type totals. University eligibility and official repeat replacement would need separate policy authority. |
| Numerical and ranking drift | Preserve credit exponent precision, normalized fingerprint and delta hash versions, canonical plan IDs, zero-credit choices, failed versus withdrawn caps, shortlist of 50, reference slots, Pareto fronts/ties, final course predictions and additive projected GPA. Assert deterministic order and compare numerical outputs under existing tolerance and precision guarantees. |
| Split request safety | Preserve request/owner keys, typed serialization, transaction ordering, conflict semantics, claim count, retention/410 behavior, private payload scrubbing, body/storage limits, result envelopes and persisted DB replay across versions. |
| History state and deployment | Preserve active cutoff and authorized backtesting selection, lock and retry semantics, staged versus activated releases, immutable bundle and control formats, rollback and finalization authentication. An inferred model cutoff or new history version must never silently substitute for the requested one. Preserve degraded readiness and safe HTTP diagnostics. |
| Removal and imports | Confirm downstream import paths before removing shims or public helper names. Keep injected dependencies and monkeypatch seams stable or migrate affected tests without weakening assertions. Verify artifact promotion and observed evaluation consumers before changing scoring or loader interfaces. |
| Runtime scaling | Measure feasible-plan count, duration and peak memory under representative approved workloads before proposing search changes. The existing cap bounds Stage 2 work and leaves full Stage 1 enumeration/ranking. Operational capacity targets are unresolved. |

### Tests likely to change with the implementation

- HTTP characterization in `tests/integration/test_api_stable.py` should cover the additional semantic and history contracts above. Unit tests for adapter and serving surfaces should assert the same wire errors and public payloads. Store and catalog tests should remain valid when their responsibilities stay in place.
- `tests/unit/test_two_stage_payloads.py`, `test_candidate_input_contract.py`, `test_two_stage_constraints.py` and `test_two_stage_shortlist.py` should add parity cases for extracted policy and ready inputs. Existing literal-provider and optional ready-flag semantics should remain distinguishable.
- `test_two_stage_engine.py`, `test_ranking_strategies.py`, `test_balance_policy.py` and `test_two_stage_activation.py` should continue to assert values, routes, ranking order and identities. Tests that monkeypatch engine loader globals may need to target the location of the dependency after extraction.
- `test_history_update.py` and `test_cumulative_history.py` may need internal fixture or patch-point updates when normalization and selection move. Keep persistence bytes/hashes, fsync/atomic update recovery, cross-process locking and old snapshots in the parity checks.
- `test_two_stage_artifacts.py`, `test_two_stage_matrix.py`, `test_migration_ranking_provenance.py` and `test_fresh_artifact_metadata.py` protect serving and staging interfaces. Include the relevant observed evaluation tests before any change to standalone score-summary ordering.

This plan awaits approval. The audit produced documentation only.
