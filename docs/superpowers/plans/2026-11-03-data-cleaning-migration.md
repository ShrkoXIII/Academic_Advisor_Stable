# Phase 01 Data Cleaning Migration Implementation Plan

> **For agentic workers:** Execute inline under the user supplied Phase 01 specification; user constraints override generic workflow steps.

**Goal:** Copy the seven requested source files and seven existing unit test files while preserving cleaning behavior.

**Architecture:** Keep transformation and main function bodies unchanged. Change imports to the cleaning package and bind existing module variable names to one unversioned set of project relative Path constants.

**Tech Stack:** Python >=3.10, pandas, pyarrow; pytest for development.

**Spec:** The Phase 01 request in this chat is the binding specification.

## Global Constraints

- Work only in the destination repository on its existing data_cleaning branch; no commit, merge, or branch changes.
- Do not write to the source repository, change transformations, row exclusions, attempts, null handling, or outlier rules.
- Do not migrate Data Building, Features, Modeling, Docker, requirements.txt, or real datasets.
- Copy existing tests with import resolution changes only; retain every assertion, parameter, monkeypatch target, and success condition.

## Review Focus

- Preserve the source working copy, including its existing uncommitted status helper extraction.
- Preserve nullable dtypes, column order, stable sorts, attempt ordering, and outlier thresholds.
- Keep legacy _V2 module variable names for unchanged monkeypatch targets, bound to a single unversioned path per artifact.
- Document the missing Data Building input for diploma main and the resulting outlier dependency.
- Validate from an isolated environment and verify source hashes after all checks.

## Task 1: Copy modules and tests; define paths and dependencies

- [x] Record source revision, working copy hashes, and source Git status hash in docs/migration/phase01_source_manifest.json.
- [x] Copy src/data/{cleaning_utils,clean_degree_course,clean_student_course,clean_student_status,clean_student_diploma,clean_outliers}.py to src/data/cleaning/ and academic_calendar.py to src/data/.
- [x] Define only the four raw inputs and the eight required output/intermediate paths in src/paths.py, using PROJECT_ROOT from __file__.
- [x] Add pandas and pyarrow to pyproject.toml; retain pytest as a dev extra.
- [x] Copy tests/test_clean*.py and tests/test_academic_calendar.py to tests/unit/; adjust module imports and the import bootstrap depth only.
- [x] Verify exact source text equality after normalizing permitted import changes, plus AST equality of every transformation and main body; verify test bodies unchanged.

## Task 2: Validate and document the phase

- [x] Create destination .venv and install this project with its dev extra using pyproject.toml.
- [x] Run .venv/Scripts/python.exe -B -m pytest tests/unit -q, then the destination full suite once.
- [x] Confirm all path constants stay under the destination root when imported from another current directory; no duplicate version paths or developer absolute paths.
- [x] Verify all source hashes and Git status match the pre-migration manifest; run git diff --check.
- [x] Save commands, versions, results, path mapping, test exclusions, and Data Building dependencies in docs/migration/phase01_data_cleaning.md.

## Execution decisions

- Ruling: Continue implementation directly because the user explicitly requested execution of this bounded migration; no extra plan approval, commits, worktrees, or branch operations.
- Ruling: Existing source working copy is the authority, including clean_student_status.py's uncommitted extraction; no source edits.
- Ruling: Do not create substitute behavioral tests; use the seven original files and a separate migration parity check.

## Verification results

- Full destination suite: 219 passed, zero failures/errors/skips. This is also the focused suite: no other destination tests exist.
- Exact import-only text parity and non-import AST parity: all seven source files. Test bodies/decorators/assertions identical: all seven test files.
- Relocation, destination-only imports, twelve unique canonical paths, and dependency compatibility passed.
- Source protection: all 16 source hashes and source Git status hash unchanged. git diff --check passed.
- Independent read-only review complete: no Critical/Important code findings; corrected the report to state that all four raw inputs are present and only the Data Building intermediate is missing.
