# Stable integration and migration contract

The user's 2026-11-05 instruction, "Start Stable Migration — Preserve Business Logic",
authorizes preserving the existing approved cleaning, missing-value, history,
feature, training, scoring, constraint and ranking behavior while adapting paths,
imports, packaging and runtime integration. Stable cleaning remains authoritative.

The single recommendation path is TwoStagePlanRecommender: 31-feature candidate
scoring, feasible exact-credit plans, at most 50 shortlisted plans, then 43-feature
plan-context scoring. Preserve Pareto v1 at both stages and the existing
B_observed_middle_v1 soft Balance policy. Global Top-K optimality is not guaranteed.

## Serving history and readiness

Check `recommendation_readiness.ready` in `GET /health` for dependency
readiness. Recommendation requests also validate the requested cutoff and model
training cutoffs. Normal mode requires the immediately preceding academic
semester. Backtesting can request an older eligible cutoff when explicitly
enabled. The API verifies and captures one snapshot for the built-in engine.
If another worker changes the active history during inference, scoring continues
with the captured snapshot. A new request evaluates the current history selection
rules again and can receive `503 HISTORY_UNAVAILABLE` for an unavailable cutoff.

Serving requests and delta validation read history without publishing or
activating bundles. Durable preview, commit, activation, rollback and
finalization belong to the administrative workflow.

## Python imports

Use `src.api.app:create_app` as the Uvicorn factory. Use the canonical paths
below for new in-process integrations. The older paths still forward imports.
The Phase 7 audit found no executable consumers in this repository. Usage in
independently deployed Python clients remains unverified.

| Compatibility import | Canonical implementation |
|---|---|
| `src.api.validation` | `src.api.validators.common` |
| `src.api.student_adapter` | `src.api.adapters.student` |
| `src.api.courses_adapter` | `src.api.adapters.courses` and `src.api.validators.courses` |
| `src.api.history_adapter` | `src.api.adapters.history` |

## Artifact and evaluation requirements

Fresh model artifacts and history are rebuilt only from Stable raw data. A fresh
manifest records their actual hashes, categories, features and training metadata.
An explicit migration approval reference authorizes retaining the ranking policy;
it does not claim that old validation reports validate newly trained models.
Without that explicit reference, publication retains the unapproved ranking gate.

Projected cumulative GPA retains the standard additive formula without official
repeat replacement. Eligibility relies on validated provider flags and policies.
Actual outcomes are evaluation-only and must never enter target-semester features.
Operational capacity limits and institution-level quality approval remain separate.
