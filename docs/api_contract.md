# Stable integration and migration contract

The user's 2026-11-05 instruction, "Start Stable Migration — Preserve Business Logic",
authorizes preserving the existing approved cleaning, missing-value, history,
feature, training, scoring, constraint and ranking behavior while adapting paths,
imports, packaging and runtime integration. Stable cleaning remains authoritative.

The single recommendation path is TwoStagePlanRecommender: 33-feature candidate
scoring, feasible exact-credit plans, at most 50 shortlisted plans, then 47-feature
plan-context scoring. Preserve Pareto v1 at both stages and the existing
B_observed_middle_v1 soft Balance policy. Global Top-K optimality is not guaranteed.

Fresh model artifacts and history are rebuilt only from Stable raw data. A fresh
manifest records their actual hashes, categories, features and training metadata.
An explicit migration approval reference authorizes retaining the ranking policy;
it does not claim that old validation reports validate newly trained models.
Without that explicit reference, publication retains the unapproved ranking gate.

Projected cumulative GPA retains the standard additive formula without official
repeat replacement. Eligibility relies on validated provider flags and policies.
Actual outcomes are evaluation-only and must never enter target-semester features.
Operational capacity limits and institution-level quality approval remain separate.
