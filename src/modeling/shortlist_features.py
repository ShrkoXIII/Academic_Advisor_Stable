"""The existing ordered 33-feature shortlist contract and matrix adapter."""
from src.features.feature_contract import BASE_FEATURES, prepare_model_matrix

REMOVED_CONTEXT_FEATURES = frozenset([
    "plan_course_count", "plan_total_credits", "plan_credit_weighted_fail_rate",
    "plan_credit_weighted_avg_mark", "plan_credit_weighted_avg_attempt", "plan_difficulty_credit_load",
    "peer_course_count", "peer_total_credits", "peer_credit_weighted_fail_rate",
    "peer_credit_weighted_avg_mark", "peer_credit_weighted_avg_attempt", "peer_difficulty_credit_load",
    "peer_max_fail_rate", "peer_difficulty_missing",
])
COURSE_ONLY_FEATURES = [f for f in BASE_FEATURES if f not in REMOVED_CONTEXT_FEATURES]
if (len(BASE_FEATURES) != 47 or len(COURSE_ONLY_FEATURES) != 33
        or set(BASE_FEATURES) - set(COURSE_ONLY_FEATURES) != REMOVED_CONTEXT_FEATURES):
    raise ValueError("Course-only experiment requires precisely the documented 47-minus-14 contract.")


def prepare_course_matrix(frame, category_levels):
    """Match official numeric/category handling without needing plan columns."""
    missing = set(COURSE_ONLY_FEATURES) - set(frame)
    if missing:
        raise ValueError(f"Missing course-only features: {sorted(missing)}")
    return prepare_model_matrix(frame, category_levels, model_features=COURSE_ONLY_FEATURES)

