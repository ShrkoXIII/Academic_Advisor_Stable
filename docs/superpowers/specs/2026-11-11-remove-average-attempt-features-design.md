# Remove Average-Attempt Features — Design

Date: 2026-11-11

## Intent

Remove `plan_course_type_id` and the average-attempt signal from the model contract and temporal-history state. The average-attempt signal includes `course_history_avg_attempt`, `plan_credit_weighted_avg_attempt`, `peer_credit_weighted_avg_attempt`, and the internal `attempt_sum` aggregate and history-update field. Keep `attempt_number` and `course_history_retake_rate`; they represent candidate attempt number and repeat rate, not the average-attempt signal selected for removal.

## Approaches

1. Remove only the direct model inputs and keep attempt averages in plan context and history storage. Rejected: the user asked to remove the average-attempt signal completely.
2. Remove the complete average-attempt signal, including the two dependent plan-context features and `attempt_sum` from state and finalized history deltas. Selected: this matches the clarified request, with an explicit history-update contract change.

## Proposed Change

- Remove `plan_course_type_id` from model feature preparation and candidate requirements.
- Remove all average-attempt features and sums from temporal feature building, plan-context calculations, frozen history state, and history-update payload normalization.
- Use ordered model feature contracts and artifact structure to reject incompatible assets without numeric contract labels.
- Update Stage 1/Stage 2 contracts and tests. Expected counts: 43 total model features, 31 for Stage 1, and 12 plan-context features.
- Preserve `attempt_number`, `course_history_retake_rate`, and `retake_sum` because they are separate repeat/retake signals.
- Update `docs/CHANGELOG.md` after code, tests, and API-contract changes.

## Constraints and Risks

- The finalized history-update producer must stop sending `attempt_sum`; prior delta payloads and frozen-history bundles may need regeneration under the current structure.
- Models trained with the old 47/33 contracts cannot serve the new 43/31 matrices. Retraining/rebuilding artifacts is a separate step and will not run without explicit authorization, per repository instructions.
- The current worktree already has an uncommitted syntax typo in `src/features/temporal_features.py` (`sor t=False`). It must be repaired in that touched file to run verification; preserve the surrounding existing edit.

## Out of Scope

- Removing the per-candidate `attempt_number` feature or repeat-policy behavior.
- Changing failure-rate, retake-rate, mark-history, GPA, or other feature definitions.
- Retraining models, publishing runtime packages, committing, or pushing.
