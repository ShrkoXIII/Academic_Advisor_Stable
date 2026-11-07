from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.features.feature_contract import (  # noqa: E402
    CATEGORICAL_FEATURES,
    LEAKAGE_COLUMNS,
    BASE_FEATURES,
    NUMERIC_FEATURES,
    RAW_ID_COLUMNS,
    learn_category_levels,
    prepare_model_matrix,
)
from src.features.temporal_features import (  # noqa: E402
    COURSE_HISTORY_COLUMNS,
    STUDENT_HISTORY_COLUMNS,
    CourseHistoryState,
    add_student_history_features,
    build_temporal_course_history,
    compute_plan_context_features,
    load_course_history_state,
    save_course_history_state,
)


def course_rows(parts, marks, attempts=None):
    attempts = attempts or [1] * len(parts)
    return pd.DataFrame(
        {
            "part_id": parts,
            "degree_id": ["D1"] * len(parts),
            "faculty_id": ["F1"] * len(parts),
            "course_id": ["C1"] * len(parts),
            "plan_requirement_type_id": ["R1"] * len(parts),
            "course_credits": [3.0] * len(parts),
            "final_mark": marks,
            "attempt_number": attempts,
        }
    )


def semester_rows(student_id, parts, gpas):
    sequence = np.arange(1, len(parts) + 1)
    return pd.DataFrame(
        {
            "student_status_id": [
                f"{student_id}-{part_id}" for part_id in parts
            ],
            "student_id": [student_id] * len(parts),
            "degree_id": ["D1"] * len(parts),
            "part_id": parts,
            "gpa_points": gpas,
            "last_enrolled_gpa": [np.nan] * len(parts),
            "total_reg_courses": (sequence - 1) * 5,
            "semester_reg_courses": [5] * len(parts),
            "total_reg_credits": (sequence - 1) * 15.0,
            "semester_reg_credits": [15.0] * len(parts),
            "total_fail_courses": [0] * len(parts),
            "semester_fail_courses": [0] * len(parts),
            "total_fail_credits": [0.0] * len(parts),
            "semester_fail_credits": [0.0] * len(parts),
            "reg_total_semesters": sequence,
        }
    )


class CourseHistoryTests(unittest.TestCase):
    def test_fallback_uses_the_most_specific_available_history(self):
        state = CourseHistoryState()
        state.update(course_rows([20241], [40]))
        targets = course_rows([20242] * 6, [90] * 6)
        targets["degree_id"] = ["D1", "D2", "D1", "D2", "D2", "D2"]
        targets["course_id"] = ["C1", "C1", "C2", "C3", "C4", "C5"]
        targets["faculty_id"] = ["F1", "F1", "F1", "F1", "F2", "F2"]
        targets["plan_requirement_type_id"] = ["R1", "R1", "R1", "R1", "R1", "R2"]
        targets["course_credits"] = [3.0, 3.0, 3.0, 3.0, 3.0, 5.0]

        result = state.apply(targets)
        self.assertEqual(result.course_history_fallback_level.tolist(), [1, 2, 3, 4, 5, 6])
        self.assertEqual(result.course_history_effective_support.tolist(), [1.0] * 6)
        self.assertEqual(result.course_history_avg_mark.tolist(), [40.0] * 6)

    def test_roster_only_courses_never_become_finalized_history(self):
        train = course_rows([20241], [40])
        roster_only = course_rows([20241], [100]).assign(course_id="C2")
        train_roster = pd.concat([train, roster_only], ignore_index=True)
        test = course_rows([20242], [80]).assign(course_id="C2")
        _, _, test_features, _, state = build_temporal_course_history(
            train, train_roster, test, test.copy(),
        )
        self.assertEqual(state.global_sums["raw_count"], 1)
        self.assertEqual(test_features.iloc[0].course_history_fallback_level, 3)
        self.assertEqual(test_features.iloc[0].course_history_avg_mark, 40.0)

    def test_consecutive_test_parts_roll_forward_only_after_each_outcome(self):
        train = course_rows([20243], [40])
        test = course_rows([20251, 20252], [100, 55])

        _, _, features, _, training_state = build_temporal_course_history(
            train, train.copy(), test, test.copy(),
        )
        changed_test = test.copy()
        changed_test.loc[changed_test.part_id.eq(20251), "final_mark"] = 0
        _, _, changed_features, _, changed_training_state = build_temporal_course_history(
            train, train.copy(), changed_test, changed_test.copy(),
        )

        self.assertEqual(features.course_history_avg_mark.tolist(), [40.0, 70.0])
        self.assertEqual(changed_features.course_history_avg_mark.tolist(), [40.0, 20.0])
        self.assertEqual(training_state.as_of_part, 20243)
        self.assertEqual(changed_training_state.as_of_part, 20243)
        self.assertEqual(training_state.global_sums["raw_count"], 1)

    def test_saved_state_cannot_score_its_own_or_earlier_semester(self):
        state = CourseHistoryState()
        state.update(course_rows([20241], [40]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.pkl"
            save_course_history_state(state, path)
            restored = load_course_history_state(path)
        self.assertEqual(restored.as_of_part, 20241)
        for part in [20233, 20241]:
            with self.assertRaisesRegex(ValueError, "before the target"):
                restored.apply(course_rows([part], [80]))

    def test_current_semester_result_does_not_change_its_history_features(self):
        state = CourseHistoryState()
        state.update(course_rows([20221], [40]))
        current_low = course_rows([20222], [5])
        current_high = current_low.assign(final_mark=99)

        assert_frame_equal(
            state.apply(current_low),
            state.apply(current_high),
        )

    def test_pre_2022_history_uses_quarter_weight(self):
        state = CourseHistoryState()
        state.update(course_rows([20213, 20221], [40, 80]))
        features = state.apply(course_rows([20222], [70])).iloc[0]

        self.assertAlmostEqual(features["course_history_effective_support"], 1.25)
        self.assertAlmostEqual(features["course_history_avg_mark"], 72.0)
        self.assertAlmostEqual(features["course_history_fail_rate"], 0.2)

    def test_test_outcomes_cannot_update_frozen_train_state(self):
        state = CourseHistoryState()
        state.update(course_rows([20241, 20242], [60, 80]))
        before = dict(state.global_sums)
        test_fail = course_rows([20251], [0])
        test_pass = test_fail.assign(final_mark=100)

        assert_frame_equal(state.apply(test_fail), state.apply(test_pass))
        self.assertEqual(before, state.global_sums)


class PlanContextTests(unittest.TestCase):
    def test_groups_are_isolated_by_student_degree_and_part(self):
        roster = pd.DataFrame({
            "student_id": ["S1", "S1", "S1", "S1", "S2"],
            "degree_id": ["D1", "D1", "D2", "D1", "D1"],
            "part_id": [20241, 20241, 20241, 20242, 20241],
            "course_id": ["A", "B", "C", "D", "E"],
            "course_credits": [2.0, 3.0, 5.0, 7.0, 11.0],
            "course_history_fail_rate": [0.1, 0.4, 0.9, 0.8, 0.7],
            "course_history_avg_mark": [90.0, 60.0, 20.0, 30.0, 40.0],
            "course_history_avg_attempt": [1.0, 2.0, 3.0, 4.0, 5.0],
        })
        result = compute_plan_context_features(roster)
        self.assertEqual(result.plan_course_count.tolist(), [2, 2, 1, 1, 1])
        self.assertEqual(result.plan_total_credits.tolist(), [5.0, 5.0, 5.0, 7.0, 11.0])
        self.assertAlmostEqual(result.loc[0, "peer_credit_weighted_fail_rate"], 0.4)
        self.assertAlmostEqual(result.loc[1, "peer_credit_weighted_fail_rate"], 0.1)
        self.assertTrue(result.loc[2:, "peer_credit_weighted_fail_rate"].isna().all())
        self.assertEqual(result.peer_difficulty_missing.tolist(), [0, 0, 1, 1, 1])

    def test_peer_max_handles_tied_maximum_and_missing_course_history(self):
        roster = pd.DataFrame({
            "student_id": ["S"] * 4, "degree_id": ["D"] * 4,
            "part_id": [20241] * 4, "course_id": ["A", "B", "C", "D"],
            "course_credits": [3.0] * 4,
            "course_history_fail_rate": [0.6, 0.6, 0.2, np.nan],
            "course_history_avg_mark": [40.0, 50.0, 80.0, np.nan],
            "course_history_avg_attempt": [2.0, 2.0, 1.0, np.nan],
        })
        result = compute_plan_context_features(roster)
        self.assertEqual(result.peer_max_fail_rate.tolist(), [0.6] * 4)
        self.assertAlmostEqual(result.loc[3, "peer_credit_weighted_fail_rate"], (0.6 + 0.6 + 0.2) / 3)

    def test_credit_weighting_and_leave_one_out_match_manual_values(self):
        roster = pd.DataFrame(
            {
                "student_id": ["S1", "S1", "S1"],
                "degree_id": ["D1", "D1", "D1"],
                "part_id": [20241, 20241, 20241],
                "course_id": ["A", "B", "C"],
                "course_credits": [2.0, 6.0, 2.0],
                "course_history_fail_rate": [0.1, 0.5, np.nan],
                "course_history_avg_mark": [90.0, 60.0, np.nan],
                "course_history_avg_attempt": [1.0, 2.0, np.nan],
            }
        )
        features = compute_plan_context_features(roster)

        self.assertAlmostEqual(features.loc[0, "plan_total_credits"], 10.0)
        self.assertAlmostEqual(
            features.loc[0, "plan_credit_weighted_fail_rate"], 0.4
        )
        self.assertAlmostEqual(
            features.loc[0, "peer_credit_weighted_fail_rate"], 0.5
        )
        self.assertAlmostEqual(
            features.loc[0, "peer_difficulty_credit_load"], 3.0
        )
        self.assertAlmostEqual(features.loc[1, "peer_total_credits"], 4.0)
        self.assertAlmostEqual(
            features.loc[1, "peer_credit_weighted_fail_rate"], 0.1
        )
        self.assertAlmostEqual(
            features.loc[2, "peer_credit_weighted_fail_rate"], 0.4
        )


class StudentHistoryTests(unittest.TestCase):
    def test_current_and_future_results_cannot_change_current_history(self):
        history = semester_rows("S1", [20241, 20242, 20243], [2.0, 0.0, 4.0])
        empty = history.iloc[:0]
        original, _ = add_student_history_features(history, empty)
        changed = history.copy()
        current_or_future = changed.part_id.ge(20242)
        changed.loc[current_or_future, "gpa_points"] = 4.0
        changed.loc[current_or_future, "semester_fail_courses"] = 5
        changed.loc[current_or_future, "semester_fail_credits"] = 15.0
        changed.loc[current_or_future, "reg_total_semesters"] = 0
        updated, _ = add_student_history_features(changed, empty)
        assert_frame_equal(
            original.loc[original.part_id.le(20242), STUDENT_HISTORY_COLUMNS],
            updated.loc[updated.part_id.le(20242), STUDENT_HISTORY_COLUMNS],
        )

    def test_source_totals_are_already_before_current_semester(self):
        history = semester_rows("S1", [20251, 20252], [0.0, 0.0])
        history["semester_fail_courses"] = 5
        history["semester_fail_credits"] = 15.0
        history["total_fail_courses"] = [0, 5]
        history["total_fail_credits"] = [0.0, 15.0]
        enriched, _ = add_student_history_features(history, history.iloc[:0])
        for suffix in ["reg_courses", "reg_credits", "fail_courses", "fail_credits"]:
            self.assertEqual(
                enriched[f"prior_total_{suffix}"].tolist(),
                history[f"total_{suffix}"].tolist(),
            )
        self.assertTrue(pd.isna(enriched.iloc[0].prior_fail_credit_ratio))
        self.assertEqual(enriched.iloc[1].prior_fail_credit_ratio, 1.0)
        self.assertEqual(enriched.prior_registered_semesters.tolist(), [0, 1])

    def test_full_status_history_keeps_excluded_and_non_enrolled_semesters(self):
        history = semester_rows("S1", [20241, 20242, 20243, 20251], [3.0, 1.0, 0.0, 4.0])
        history.loc[2, "semester_reg_courses"] = 0
        train = history.iloc[[0]].copy()
        test = history.iloc[[3]].copy()
        _, enriched = add_student_history_features(train, test, history)
        self.assertEqual(enriched.iloc[0].gpa_prev_1, 1.0)
        self.assertEqual(enriched.iloc[0].gpa_prev_2, 3.0)
        self.assertEqual(enriched.iloc[0].gpa_trend_delta, -2.0)

    def test_gpa_trend_distinguishes_decline_and_improvement(self):
        declining = semester_rows("DOWN", [20221, 20222, 20223], [4.0, 3.0, 2.5])
        improving = semester_rows("UP", [20221, 20222, 20223], [2.0, 3.0, 3.5])
        train = pd.concat([declining, improving], ignore_index=True)
        empty_test = train.iloc[0:0].copy()
        enriched, _ = add_student_history_features(train, empty_test)

        down = enriched[
            enriched["student_status_id"].eq("DOWN-20223")
        ].iloc[0]
        up = enriched[enriched["student_status_id"].eq("UP-20223")].iloc[0]
        self.assertAlmostEqual(down["gpa_trend_delta"], -1.0)
        self.assertAlmostEqual(up["gpa_trend_delta"], 1.0)

    def test_20252_uses_20251_but_not_future_student_history(self):
        train = semester_rows("S1", [20242, 20243], [1.0, 2.0])
        test = semester_rows("S1", [20251, 20252, 20253], [3.0, 4.0, 0.0])
        _, enriched_test = add_student_history_features(train, test)
        target = enriched_test[
            enriched_test["student_status_id"].eq("S1-20252")
        ].iloc[0]

        self.assertAlmostEqual(target["gpa_prev_1"], 3.0)
        self.assertAlmostEqual(target["gpa_prev_2"], 2.0)
        self.assertAlmostEqual(target["gpa_trend_delta"], 1.0)


class FeatureContractTests(unittest.TestCase):
    def test_model_contract_excludes_raw_ids_and_leakage(self):
        self.assertTrue(set(BASE_FEATURES).isdisjoint(LEAKAGE_COLUMNS))
        self.assertTrue(set(BASE_FEATURES).isdisjoint(RAW_ID_COLUMNS))

    def test_changing_current_mark_changes_no_model_feature(self):
        values = {column: [1.0] for column in NUMERIC_FEATURES}
        values.update({column: ["category"] for column in CATEGORICAL_FEATURES})
        frame = pd.DataFrame(values).assign(final_mark=10, is_fail=1)
        levels = learn_category_levels(frame)
        original = prepare_model_matrix(frame, levels)
        changed = prepare_model_matrix(
            frame.assign(final_mark=95, is_fail=0),
            levels,
        )

        assert_frame_equal(original, changed)


if __name__ == "__main__":
    unittest.main()
