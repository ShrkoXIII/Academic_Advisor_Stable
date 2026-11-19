# Phase 7 — Compatibility audit and documentation consolidation

**Date** 2026-11-19

**Status** PASS WITH WARNINGS

## Initial Git state

The working tree was clean on `data_cleaning`, tracking `origin/data_cleaning`, at `2eb30c7bbb765c9cb8c0a5e75c87ff4d5054fac4` (`P5+P6`). Git reported zero staged, unstaged, or non-ignored untracked changes.

The reference reports were [the API and recommendation audit](API_RECOMMENDATION_AUDIT.md), [the consolidation plan](API_RECOMMENDATION_CONSOLIDATION_PLAN.md), [the Phase 2 parity report](API_RECOMMENDATION_PARITY_TESTS_REPORT.md), [the Phase 3 report](API_RECOMMENDATION_PHASE_3_REPORT.md), and [the Phase 4A report](API_RECOMMENDATION_PHASE_4A_REPORT.md). The current Git tree, locally available Git refs and documentation inventory yielded no standalone Phase 4B, 5, or 6 reports. Their completion records are the dated [changelog entries](../CHANGELOG.md) and the corresponding code and tests in commits `435f70f` and `2eb30c7`.

## Consumer audit and decisions

| Module | Internal consumers | Tests | Public/export references | Recommendation |
|---|---|---|---|---|
| `src.api.validation` | None found. The API uses `validators.common`. | No existing shim imports. API and HTTP tests exercise canonical validation. | Eleven names are available through the directly importable module. The initial README listed the module, and its file is included in source releases. | Retain. External use of the validation helpers and exception/result classes is unverified. |
| `src.api.student_adapter` | None found. The service uses `adapters.student`. | No existing shim imports. Student snapshot parity and HTTP tests exercise the canonical path. | Six names can be explicitly imported, including the old `_history` alias. The initial README listed the module, and its file is included in source releases. | Retain. External use of the adapter, constants and private aliases is unverified. |
| `src.api.courses_adapter` | None found. The service uses `adapters.courses`, which calls `validators.courses`. | No existing shim imports. HTTP and policy tests cover the canonical path. | Five names are explicitly listed in `__all__`, including three underscore-prefixed names. The initial README listed the module, and its file is included in source releases. | Retain. External use of the explicit export list is unverified. |
| `src.api.history_adapter` | None found. The API and Streamlit use `adapters.history`. | No existing shim imports. HTTP and history tests cover the canonical path. | `adapt_history_delta` is explicitly listed in `__all__`. The initial README listed the module, and its file is included in source releases. | Retain. External use of the delta adapter is unverified. |

### Export inventory

| Compatibility module | Origin | Names available through the compatibility module |
|---|---|---|
| `src.api.validation` | `src.api.validators.common` | `ApiError`, `ValidationResult`, `binding`, `check_record_identity`, `identifier`, `identity`, `json_safe`, `number`, `part`, `response_data`, `sourced` |
| `src.api.student_adapter` | `src.api.adapters.student` | `COUNTS`, `DIRECT`, `SOURCED_FIELDS`, `_official_gpa_credits`, `adapt_student`, and `_history` (the alias of `add_history_features`) |
| `src.api.courses_adapter` | `src.api.adapters.courses` | `_course`, `adapt_courses`, `group_identity` |
| `src.api.courses_adapter` | `src.api.validators.courses` | `_check_source_duplicates`, `_rules` |
| `src.api.history_adapter` | `src.api.adapters.history` | `adapt_history_delta` |

`validation.py` and `student_adapter.py` have no explicit `__all__`. Wildcard imports from the student shim expose its three constants and `adapt_student`. Its two private names remain accessible through explicit import. The course shim's explicit `__all__` includes all five forwarded names. The history shim's explicit `__all__` includes its single adapter.

### Consumer evidence and removal gate

- Parsed all 132 tracked Python files for absolute imports, resolved relative imports and `from`-imported package submodules. Searched path strings and checked dynamic import and module-discovery call sites, including `import_module`, `find_spec`, `__import__`, `getattr`, and path-based loading. Found no runtime, test, or script consumers of these four paths. The generic package/source collectors include the files.
- Inspected `src/api/__init__.py` and the adapter and validator package initializers. They publish no re-exports of the shims. Setuptools discovers `src` and `src.*` via `pyproject.toml`. The release source collector and allowlist in `tools/prepare_release.py` include all four files.
- The tracked README launcher and release verification use `src.api.app:create_app`. Standalone verification imports `src.api.service.ApiService`, and the Streamlit client calls HTTP endpoints. Repository documentation and examples supplied module inventory references and historical audit references. They contained no integration example that imports a shim.
- None of the four modules passes the removal gate for independent deployments. A downstream inventory and release or deployment-owner confirmation would be needed to establish usage. If retiring these imports is still desired, document the canonical paths and observe a deprecation period covering at least one published release before reconsidering removal. This phase records the recommendation and sets no removal date.

## Phase mapping

The Phase 7 request identifies serving readiness as the subject of the original Phase 4B proposal. The archived consolidation plan lists shared student snapshot calculations, scoring separation, and serving/history as successive implementation steps. The proposal title and the completed phase labels describe different points in the project's history. The implementation records show this sequence.

| Completed phase | Changes recorded | Evidence |
|---|---|---|
| 4A | Shared registration credit bounds, exact arithmetic and caps. The Phase 4A scope deferred serving and history work. | [Phase 4A report](API_RECOMMENDATION_PHASE_4A_REPORT.md), `435f70f` |
| 4B | Shared request-time student snapshot indicators, including term/semester, GPA trend, failed-credit ratio and observed enrollment gap, with API source checks retained. | [Changelog](../CHANGELOG.md), `435f70f`, [student snapshot tests](../../tests/unit/test_student_snapshot_parity.py) |
| 5 | Shared derived GPA metrics and separated aggregation from final ranking. The observed-plan caller kept the sorted summary helper. | [Changelog](../CHANGELOG.md), `2eb30c7`, [scoring tests](../../tests/unit/test_plan_scoring.py) |
| 6 | Consolidated serving compatibility and readiness and pinned a verified history snapshot for each request sent to the built-in engine. | [Changelog](../CHANGELOG.md), `2eb30c7`, [HTTP tests](../../tests/integration/test_api_stable.py) |

The historical reports and earlier changelog entries preserve their original labels. The broader plan also proposed consolidating history-delta translation. That work is outside the recorded Phase 6 implementation and this audit.

## Documentation and files

| File | Update |
|---|---|
| [`README.md`](../../README.md) | Corrected the 31/43 feature counts and 12 context features. Updated history-delta fields to reflect rejection of `attempt_sum`. Distinguished canonical modules from retained import paths. |
| [`docs/PIPELINE_AND_LOGIC_MAP.md`](../PIPELINE_AND_LOGIC_MAP.md) | Aligned training and serving counts, shared credit policy, snapshot capture, scoring aggregation and final ranking with the implementation. Linked current verification and kept the historical evidence. |
| [`docs/architecture.md`](../architecture.md) | Updated the request flow and module responsibilities, including read-only history capture and durable administration. |
| [`docs/api_contract.md`](../api_contract.md) | Documented dependency readiness, history selection, the request snapshot lifetime, and canonical Python import paths for new integrations. |
| [`docs/CHANGELOG.md`](../CHANGELOG.md) | Appended the audit outcome, phase mapping and validation result. |
| `docs/reports/API_RECOMMENDATION_PHASE_7_REPORT.md` | Added the Phase 7 audit and verification record. |

Files removed, renamed or changed under `src/`, `tests/` and `tools/`: zero.

## Verification

Fresh Python import smoke checks loaded all four shims. All 23 exported names pointed to the same objects as their canonical implementations. Each wildcard import matched its original export set. The smoke checks also verified the Uvicorn factory path, the service and engine paths, the three Phase 4A credit-helper re-exports, inclusion of all four shim files in reviewed release source collection, and the 31/43 feature contracts with 12 added plan-context features. There were zero changed import paths.

| Run | Result |
|---|---|
| Focused shim and canonical import smoke checks | **Passed**, all four modules and 23 names |
| API and adapter unit tests | **60 passed, 1 skipped** |
| Recommendation and related unit tests | **552 passed, 1 skipped** |
| HTTP integration (`tests/integration/test_api_stable.py`) | **29 passed** |
| Phase 6 full-suite baseline | **996 passed, 2 failed, 2 skipped** |
| Phase 7 full suite | **996 passed, 2 failed, 2 skipped** |

The same two filename cases failed in `tests/unit/test_frozen_history.py::test_cli_accepts_custom_source_by_contract_without_filename_label`.

- `[finalized_outcomes.parquet]`
- `[export.parquet]`

Both fixtures supplied `outcomes.parquet` and asserted their parameterized filename in the recorded metadata. The checksums matched. There were no new failing nodes. The skips were Windows ACL coverage and missing pinned model artifacts. The Windows subprocess timeout test passed.

The first HTTP run stalled in the sandbox. A minimal Windows asyncio loop probe stalled there as well. Both attempts were stopped, and the completed HTTP and full runs used local loopback outside the sandbox. Starlette emitted the existing TestClient deprecation warning. The verification used synthetic inputs and made no live University Backend call.

## Final Git diff and remaining risks

The diff consists of five modified Markdown files and one new Markdown report. The final review checked whitespace, new relative links and the exact changed path set. Historical reports and earlier changelog entries were preserved. The four shim files and the production, test and packaging code matched the initial Git state. No files were removed or staged.

External Python consumers and old release installations remain outside the available evidence. Source collection and import checks establish current checkout compatibility. Production readiness with deployed model assets and a live University Backend remains unverified.

Phase 7 stops here for review.
