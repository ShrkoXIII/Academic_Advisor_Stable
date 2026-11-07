"""Official prior-course meanings for constraints, independent of model targets."""
import pandas as pd


OFFICIAL_PREVIOUS_STATUS = {
    "F": "FAILED", "FE": "FAILED", "FA": "FAILED", "W": "WITHDRAWN",
    "P": "PASSED", "D": "OTHER", "Z": "OTHER", "ST": "OTHER", "T": "OTHER",
    "I": "UNRESOLVED", "IP": "UNRESOLVED",
}
SEMANTIC_PREVIOUS_STATUS = {
    **OFFICIAL_PREVIOUS_STATUS,
    "NEW": "NEW", "NEVER_TAKEN": "NEW", "FAILED": "FAILED",
    "WITHDRAWN": "WITHDRAWN", "PASSED": "PASSED", "OTHER": "OTHER",
    "UNKNOWN": "UNKNOWN", "UNRESOLVED": "UNRESOLVED",
}
CANDIDATE_GROUPS = {
    "NEW": "NEW", "FAILED": "FAILED_RETAKE", "WITHDRAWN": "WITHDRAWN_RETAKE",
}


def normalize_previous_status(value, *, official=False):
    """Map source codes without inferring a status from marks or attempt counts."""
    if value is None or pd.isna(value):
        return "UNKNOWN"
    value = str(value).strip().upper()
    if value in {"", "NAN", "NONE", "NULL", "<NA>", "__MISSING__", "__UNKNOWN__"}:
        return "UNKNOWN"
    mapping = OFFICIAL_PREVIOUS_STATUS if official else SEMANTIC_PREVIOUS_STATUS
    return mapping.get(value, "UNRESOLVED")


def classify_candidate_status(record):
    """Return canonical meaning/group; reject conflicting supplied meanings.

    Presence is checked per record so a missing field in another candidate does
    not become a second, conflicting status after DataFrame construction.
    """
    statuses = []
    if "previous_course_status" in record:
        statuses.append(normalize_previous_status(record["previous_course_status"]))
    if "previous_finish_status" in record:
        statuses.append(normalize_previous_status(record["previous_finish_status"], official=True))
    if len(statuses) == 2 and statuses[0] != statuses[1]:
        raise ValueError("Conflicting previous_course_status and previous_finish_status meanings.")
    status = statuses[0] if statuses else "UNKNOWN"
    return status, CANDIDATE_GROUPS.get(status, "OTHER_PREVIOUS")
