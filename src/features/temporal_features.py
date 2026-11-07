from copy import deepcopy
from dataclasses import dataclass, field
import pickle

import numpy as np
import pandas as pd


COURSE_HISTORY_COLUMNS = [
    "course_history_avg_mark",
    "course_history_fail_rate",
    "course_history_avg_attempt",
    "course_history_retake_rate",
    "course_history_effective_support",
    "course_history_fallback_level",
    "course_history_missing",
]

PLAN_CONTEXT_COLUMNS = [
    "plan_course_count",
    "plan_total_credits",
    "plan_credit_weighted_fail_rate",
    "plan_credit_weighted_avg_mark",
    "plan_credit_weighted_avg_attempt",
    "plan_difficulty_credit_load",
    "peer_course_count",
    "peer_total_credits",
    "peer_credit_weighted_fail_rate",
    "peer_credit_weighted_avg_mark",
    "peer_credit_weighted_avg_attempt",
    "peer_difficulty_credit_load",
    "peer_max_fail_rate",
    "peer_difficulty_missing",
]

STUDENT_HISTORY_COLUMNS = [
    "gpa_prev_1",
    "gpa_prev_2",
    "gpa_trend_delta",
    "gpa_trend_missing",
    "prior_total_reg_courses",
    "prior_total_reg_credits",
    "prior_total_fail_courses",
    "prior_total_fail_credits",
    "prior_fail_credit_ratio",
    "prior_registered_semesters",
]

HISTORY_SUM_COLUMNS = [
    "effective_support",
    "raw_count",
    "mark_sum",
    "fail_sum",
    "attempt_sum",
    "retake_sum",
]


def temporal_weight(part_id):   ## weight
    year = pd.to_numeric(part_id).floordiv(10)
    return pd.Series(np.where(year < 2022, 0.25, 1.0), index=part_id.index)


def _joined_key(frame, columns):  # Build a stable composite history key.
    values = frame[columns[0]].astype("string").fillna("__MISSING__")
    for column in columns[1:]:
        other = frame[column].astype("string").fillna("__MISSING__")
        values = values.str.cat(other, sep="||")
    return values


def build_history_keys(frame):
    rounded_credits = (
        pd.to_numeric(frame["course_credits"], errors="coerce")
        .round()
        .astype("Int64")
        .astype("string")
        .fillna("__MISSING__")
    )
    key_frame = frame.copy(deep=False)
    key_frame = key_frame.assign(_rounded_credits=rounded_credits)
    return {
        1: _joined_key(key_frame, ["degree_id", "course_id"]),
        2: key_frame["course_id"].astype("string").fillna("__MISSING__"),
        3: _joined_key(
            key_frame,
            ["degree_id", "plan_requirement_type_id", "_rounded_credits"],
        ),
        4: _joined_key(
            key_frame,
            ["faculty_id", "plan_requirement_type_id", "_rounded_credits"],
        ),
        5: _joined_key(
            key_frame,
            ["plan_requirement_type_id", "_rounded_credits"],
        ),
    }


@dataclass
class CourseHistoryState:
    smoothing_k: float = 20.0  ## for smoothing the low priority smoothed = (local_sum + smoothing_k * prior) / (support + smoothing_k) كلما زاد الدعم قل التاثير
    min_support: float = 20.0
    tables: dict = field(
        default_factory=lambda: {
            level: pd.DataFrame(columns=HISTORY_SUM_COLUMNS).rename_axis("key")
            for level in range(1, 6)
        }
    )
    global_sums: dict = field(
        default_factory=lambda: {column: 0.0 for column in HISTORY_SUM_COLUMNS}
    )
    as_of_part: int | None = None

    def update(self, outcomes): ## we store sums to make the average re calculatable  add to the history
        if outcomes.empty:
            return
        if self.as_of_part is not None and outcomes["part_id"].le(self.as_of_part).any():
            raise ValueError("Course history updates must follow the saved cutoff.")
        weight = temporal_weight(outcomes["part_id"]).astype("float64")
        mark = pd.to_numeric(outcomes["final_mark"], errors="coerce")
        attempt = pd.to_numeric(outcomes["attempt_number"], errors="coerce")
        base = pd.DataFrame(index=outcomes.index)
        base["effective_support"] = weight
        base["raw_count"] = 1.0
        base["mark_sum"] = mark * weight
        base["fail_sum"] = mark.lt(50).astype("float64") * weight
        base["attempt_sum"] = attempt * weight
        base["retake_sum"] = attempt.gt(1).astype("float64") * weight

        keys = build_history_keys(outcomes)
        for level, key in keys.items():
            work = base.assign(key=key).groupby("key", sort=False)[
                HISTORY_SUM_COLUMNS
            ].sum()
            if self.tables[level].empty:
                self.tables[level] = work
            else:
                self.tables[level] = (
                    pd.concat([self.tables[level], work])
                    .groupby(level=0, sort=False)[HISTORY_SUM_COLUMNS]
                    .sum()
                )

        for column in HISTORY_SUM_COLUMNS:
            self.global_sums[column] += float(base[column].sum())
        self.as_of_part = int(outcomes["part_id"].max())

    def apply(self, frame): # return the history for each columns
        if self.as_of_part is not None and frame["part_id"].le(self.as_of_part).any():
            raise ValueError("Course history must end before the target semester.")
        row_count = len(frame)
        global_support = float(self.global_sums["effective_support"])
        if global_support:
            global_values = {
                "course_history_avg_mark": self.global_sums["mark_sum"]
                / global_support,
                "course_history_fail_rate": self.global_sums["fail_sum"]
                / global_support,
                "course_history_avg_attempt": self.global_sums["attempt_sum"]
                / global_support,
                "course_history_retake_rate": self.global_sums["retake_sum"]
                / global_support,
            }
        else:
            global_values = {
                "course_history_avg_mark": np.nan,
                "course_history_fail_rate": np.nan,
                "course_history_avg_attempt": np.nan,
                "course_history_retake_rate": np.nan,
            }

        values = {
            column: np.full(row_count, global_value, dtype="float64")
            for column, global_value in global_values.items()
        }
        selected_support = np.full(row_count, global_support, dtype="float64")
        selected_level = np.full(row_count, 6, dtype="int64")
        keys = build_history_keys(frame)

        sum_column = {
            "course_history_avg_mark": "mark_sum",
            "course_history_fail_rate": "fail_sum",
            "course_history_avg_attempt": "attempt_sum",
            "course_history_retake_rate": "retake_sum",
        }
        for level in range(5, 0, -1):
            table = self.tables[level]
            support = keys[level].map(table["effective_support"])
            available = support.notna().to_numpy()
            support_values = support.fillna(0).to_numpy(dtype="float64")
            selected_support[available] = support_values[available]
            selected_level[available] = level

            for output_column, raw_sum_column in sum_column.items():
                local_sum = keys[level].map(table[raw_sum_column]).fillna(0)
                local_sum_values = local_sum.to_numpy(dtype="float64")
                prior = global_values[output_column]
                smoothed = (
                    local_sum_values + self.smoothing_k * prior
                ) / (support_values + self.smoothing_k)
                values[output_column][available] = smoothed[available]

        result = pd.DataFrame(values, index=frame.index)
        result["course_history_effective_support"] = selected_support
        result["course_history_fallback_level"] = selected_level
        result["course_history_missing"] = (
            (selected_level >= 3) | (selected_support < self.min_support)
        ).astype("int64")
        return result[COURSE_HISTORY_COLUMNS]


def build_temporal_course_history( ## make sure their is no leackage then calculate the state for each row using its previous data 
    temporal_train,
    temporal_train_roster,
    temporal_test,
    temporal_test_roster,
):
    """Apply each semester before updating from its finalized outcomes.

    Holdout semesters roll forward on a separate state. The returned state
    always ends at the training cutoff and remains reusable as a baseline.
    """
    state = CourseHistoryState()
    train_features = pd.DataFrame(index=temporal_train.index)
    train_roster_features = pd.DataFrame(index=temporal_train_roster.index)

    for part_id in sorted(temporal_train["part_id"].unique().tolist()):
        target_mask = temporal_train["part_id"].eq(part_id)
        roster_mask = temporal_train_roster["part_id"].eq(part_id)
        train_features.loc[target_mask, COURSE_HISTORY_COLUMNS] = state.apply(
            temporal_train.loc[target_mask]
        ).to_numpy()
        train_roster_features.loc[roster_mask, COURSE_HISTORY_COLUMNS] = state.apply(
            temporal_train_roster.loc[roster_mask]
        ).to_numpy()
        state.update(temporal_train.loc[target_mask])

    train_features["course_history_fallback_level"] = train_features[
        "course_history_fallback_level"
    ].astype("int64")
    train_features["course_history_missing"] = train_features[
        "course_history_missing"
    ].astype("int64")
    train_roster_features["course_history_fallback_level"] = (
        train_roster_features["course_history_fallback_level"].astype("int64")
    )
    train_roster_features["course_history_missing"] = train_roster_features[
        "course_history_missing"
    ].astype("int64")

    test_state = deepcopy(state)
    test_features = pd.DataFrame(
        index=temporal_test.index, columns=COURSE_HISTORY_COLUMNS, dtype="float64",
    )
    test_roster_features = pd.DataFrame(
        index=temporal_test_roster.index, columns=COURSE_HISTORY_COLUMNS, dtype="float64",
    )
    test_parts = sorted(set(temporal_test["part_id"]) | set(temporal_test_roster["part_id"]))
    for part_id in test_parts:
        target_mask = temporal_test["part_id"].eq(part_id)
        roster_mask = temporal_test_roster["part_id"].eq(part_id)
        test_features.loc[target_mask, COURSE_HISTORY_COLUMNS] = test_state.apply(
            temporal_test.loc[target_mask]
        ).to_numpy()
        test_roster_features.loc[roster_mask, COURSE_HISTORY_COLUMNS] = test_state.apply(
            temporal_test_roster.loc[roster_mask]
        ).to_numpy()
        # Roster rows supply plan context, never additional finalized outcomes.
        test_state.update(temporal_test.loc[target_mask])

    for features in (test_features, test_roster_features):
        for column in ("course_history_fallback_level", "course_history_missing"):
            features[column] = features[column].astype("int64")
    return (
        train_features,
        train_roster_features,
        test_features,
        test_roster_features,
        state,
    )


def compute_student_gpa_history(student_status):
    """Pure enrolled-GPA shifts shared by full status and partial API summaries.

    Missing earlier history stays unknown. A supplied last_enrolled_gpa retains
    cleaning's existing initial-history fallback; absent values use the shifts.
    """
    required = {"student_status_id", "student_id", "part_id", "semester_reg_courses", "gpa_points"}
    if not required.issubset(student_status.columns):
        raise ValueError("Incomplete student GPA history columns.")
    semester = student_status.drop_duplicates("student_status_id").sort_values(
        ["student_id", "part_id", "student_status_id"],
        kind="stable",
    ).copy()
    registered = semester["semester_reg_courses"].gt(0)
    computed_previous = (
        semester["gpa_points"].where(registered)
        .groupby(semester["student_id"], sort=False).ffill()
        .groupby(semester["student_id"], sort=False).shift(1)
    )
    semester["gpa_prev_1"] = (semester["last_enrolled_gpa"].combine_first(computed_previous)
                              if "last_enrolled_gpa" in semester else computed_previous)
    semester["gpa_prev_2"] = (
        semester["gpa_prev_1"].where(registered)
        .groupby(semester["student_id"], sort=False).ffill()
        .groupby(semester["student_id"], sort=False).shift(1)
    )
    semester["gpa_trend_delta"] = (
        semester["gpa_prev_1"] - semester["gpa_prev_2"]
    )
    semester["gpa_trend_missing"] = semester["gpa_trend_delta"].isna().astype(
        "int64"
    )
    return semester[["student_status_id", "gpa_prev_1", "gpa_prev_2", "gpa_trend_delta", "gpa_trend_missing"]]


def add_student_history_features(temporal_train, temporal_test, student_status=None):
    # Production passes status history BEFORE the course/outcome filters.
    if student_status is None:
        student_status = pd.concat([temporal_train, temporal_test], ignore_index=True)
    semester = student_status.drop_duplicates("student_status_id").sort_values(
        ["student_id", "part_id", "student_status_id"], kind="stable",
    ).copy()
    gpa = compute_student_gpa_history(semester)
    for column in ("gpa_prev_1", "gpa_prev_2", "gpa_trend_delta", "gpa_trend_missing"):
        semester[column] = gpa[column]

    # Source total_* values already describe the START of the semester.
    # Subtracting semester_fail_* here would expose the target's outcomes.
    semester["prior_total_reg_courses"] = semester["total_reg_courses"]
    semester["prior_total_reg_credits"] = semester["total_reg_credits"]
    semester["prior_total_fail_courses"] = semester["total_fail_courses"]
    semester["prior_total_fail_credits"] = semester["total_fail_credits"]
    semester["prior_fail_credit_ratio"] = (
        semester["prior_total_fail_credits"]
        / semester["prior_total_reg_credits"].replace(0, pd.NA)
    )
    # Unlike total_* above, this counter can depend on the current outcome.
    # Read the previous status; leave left-censored history unknown.
    previous_count = semester.groupby(
        ["student_id", "degree_id"], sort=False
    )["reg_total_semesters"].shift(1)
    semester["prior_registered_semesters"] = previous_count.mask(
        previous_count.isna() & semester["total_reg_courses"].eq(0), 0
    )

    lookup = semester[["student_status_id", *STUDENT_HISTORY_COLUMNS]]
    train = temporal_train.merge(lookup, on="student_status_id", how="left")
    test = temporal_test.merge(lookup, on="student_status_id", how="left")
    return train, test


def compute_plan_context_features(roster, group_columns=None):## بدي احسب حمل الفصل 
    group_columns = group_columns or ["student_id", "degree_id", "part_id"]
    groupers = [roster[column] for column in group_columns]
    credits = pd.to_numeric(roster["course_credits"], errors="coerce").fillna(0.0)
    grouped_credits = credits.groupby(groupers, sort=False, dropna=False)
    plan_count = roster.groupby(group_columns, sort=False, dropna=False)[
        "course_id"
    ].transform("size")
    plan_credits = grouped_credits.transform("sum")

    result = pd.DataFrame(index=roster.index)
    result["plan_course_count"] = plan_count.astype("int64")
    result["plan_total_credits"] = plan_credits
    result["peer_course_count"] = (plan_count - 1).astype("int64")  ## peer is for each course individual
    result["peer_total_credits"] = plan_credits - credits

    weighted_specs = {
        "fail_rate": "course_history_fail_rate",
        "avg_mark": "course_history_avg_mark",
        "avg_attempt": "course_history_avg_attempt",
    }
    peer_outputs = {}
    for label, source_column in weighted_specs.items():
        source = pd.to_numeric(roster[source_column], errors="coerce")
        valid_credits = credits.where(source.notna(), 0.0)
        weighted = (source * credits).fillna(0.0)
        group_weighted = weighted.groupby(groupers, sort=False, dropna=False).transform(
            "sum"
        ) ## مجموع الأوزان 
        group_valid_credits = valid_credits.groupby(
            groupers,
            sort=False,
            dropna=False,
        ).transform("sum")
        own_weighted = weighted
        own_valid_credits = valid_credits
        peer_weighted = group_weighted - own_weighted
        peer_valid_credits = group_valid_credits - own_valid_credits

        result[f"plan_credit_weighted_{label}"] = group_weighted.div(
            group_valid_credits.replace(0, np.nan)
        )
        peer_outputs[label] = peer_weighted.div(
            peer_valid_credits.replace(0, np.nan)
        )
        result[f"peer_credit_weighted_{label}"] = peer_outputs[label]

        if label == "fail_rate":
            result["plan_difficulty_credit_load"] = group_weighted.where(
                group_valid_credits.gt(0)
            )
            result["peer_difficulty_credit_load"] = peer_weighted.where(
                peer_valid_credits.gt(0)
            )

    fail_rate = pd.to_numeric(
        roster["course_history_fail_rate"], errors="coerce"
    )
    group_max = fail_rate.groupby(groupers, sort=False, dropna=False).transform("max")
    at_max = fail_rate.eq(group_max) & fail_rate.notna()
    max_count = at_max.astype("int64").groupby(
        groupers,
        sort=False,
        dropna=False,
    ).transform("sum")
    below_max = fail_rate.where(fail_rate.lt(group_max))
    second_max = below_max.groupby(groupers, sort=False, dropna=False).transform("max")
    result["peer_max_fail_rate"] = group_max.mask(at_max & max_count.eq(1), second_max)
    result.loc[result["peer_course_count"].eq(0), "peer_max_fail_rate"] = np.nan
    result["peer_difficulty_missing"] = result[
        "peer_credit_weighted_fail_rate"
    ].isna().astype("int64")
    return result[PLAN_CONTEXT_COLUMNS]


def save_course_history_state(state, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format_version": 2,
        "as_of_part": state.as_of_part,
        "smoothing_k": state.smoothing_k,
        "min_support": state.min_support,
        "tables": state.tables,
        "global_sums": state.global_sums,
    }
    with path.open("wb") as stream:
        pickle.dump(payload, stream)


def load_course_history_state(path):
    with path.open("rb") as stream:
        payload = pickle.load(stream)
    if payload.get("format_version") != 2:
        raise ValueError("Rebuild temporal features: saved history has no cutoff.")
    return CourseHistoryState(
        smoothing_k=payload["smoothing_k"],
        min_support=payload["min_support"],
        tables=payload["tables"],
        global_sums=payload["global_sums"],
        as_of_part=payload["as_of_part"],
    )
