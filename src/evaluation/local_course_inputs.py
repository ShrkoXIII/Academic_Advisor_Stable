"""Local course normalization used only by observed-plan evaluation."""
import numpy as np
import pandas as pd

from src.data.cleaning.cleaning_utils import clean_column_names, clean_id, clean_id_columns


class CandidateImportError(ValueError):
    def __init__(self, report):
        self.report = report
        super().__init__("Candidate import failed; see import_report.json: " + "; ".join(report["errors"]))


def normalize_registered_courses(raw, catalog, course_history, student_id, degree_id, part_id):
    """Normalize local registered courses against the degree catalog and prior attempts."""
    student_id, degree_id = clean_id(pd.Series([student_id, degree_id])).tolist()
    rows = clean_column_names(raw)
    report = {"source_rows": len(rows), "errors": [], "warnings": []}
    missing = {"course_id", "course_credits"} - set(rows.columns)
    if missing:
        report["errors"].append(f"Missing columns: {sorted(missing)}")
        raise CandidateImportError(report)
    rows = clean_id_columns(rows, [c for c in ["student_id", "degree_id", "course_id"] if c in rows])
    if "is_requestable" in rows and "student_id" not in rows:
        report["errors"].append("A company export with is_requestable must include student_id.")
    if "student_id" in rows:
        rows = rows[rows.student_id.eq(student_id)].copy()
    if "is_requestable" in rows:
        rows = rows[rows.is_requestable.astype("string").str.strip().str.upper().eq("Y")].copy()
    report["selected_rows"] = len(rows)
    report["filtered_rows"] = report["source_rows"] - len(rows)
    if "degree_id" in rows and rows.degree_id.ne(degree_id).fillna(True).any():
        report["errors"].append("Selected rows contain a missing or different degree_id.")
    if "part_id" in rows:
        parts = pd.to_numeric(rows.part_id, errors="coerce")
        if (rows.part_id.notna() & (parts.isna() | parts.ne(int(part_id)))).any():
            report["errors"].append("Selected rows contain another semester; supply a target-specific list.")
        if parts.isna().any():
            report["warnings"].append("Null part_id rows use the explicitly supplied target semester.")
    rows["course_credits"] = pd.to_numeric(rows.course_credits, errors="coerce")
    if (~np.isfinite(rows.course_credits.astype(float)) | rows.course_credits.lt(0)).any():
        report["errors"].append("Course credits must be finite and nonnegative.")
    if rows.course_id.isna().any() or rows.course_id.eq("").any():
        report["errors"].append("Missing course_id.")
    report["duplicate_course_ids"] = rows.loc[rows.course_id.duplicated(keep=False), "course_id"].drop_duplicates().tolist()
    comparison = [c for c in ["course_credits", "course_type_id", "requirement_type_id", "year_order", "semester_order"] if c in rows]
    for course_id, group in rows[rows.course_id.duplicated(keep=False)].groupby("course_id"):
        if any(group[c].nunique(dropna=False) > 1 for c in comparison):
            report["errors"].append(f"Conflicting duplicate course: {course_id}")
    report["duplicate_rows_removed"] = int(rows.course_id.duplicated().sum())
    rows = rows.drop_duplicates("course_id").copy()
    name_column = next((c for c in ["course_name_sl", "course_name"] if c in rows), None)
    rows["provided_name"] = rows[name_column] if name_column else pd.Series(None, index=rows.index, dtype="string")
    rows = rows[["course_id", "course_credits", "provided_name"]]
    catalog = clean_id_columns(catalog, ["degree_id", "course_id"])
    catalog = catalog[catalog.degree_id.eq(degree_id)].copy()
    if catalog.course_id.duplicated().any():
        report["errors"].append("Degree catalog has duplicate course keys.")
    if report["errors"]:
        raise CandidateImportError(report)
    catalog = catalog.rename(columns={
        "course_credits": "catalog_credits", "course_name_sl": "catalog_name",
        "requirement_type_id": "plan_requirement_type_id", "year_order": "plan_year_order",
        "semester_order": "plan_semester_order", "credits_count": "plan_credits_count",
    })
    cols = ["course_id", "catalog_credits", "catalog_name", "plan_requirement_type_id",
            "plan_year_order", "plan_semester_order", "plan_credits_count"]
    rows = rows.merge(catalog[cols], on="course_id", how="left", validate="one_to_one", indicator=True)
    report["unmatched_course_ids"] = rows.loc[rows._merge.eq("left_only"), "course_id"].tolist()
    conflict = rows._merge.eq("both") & rows.course_credits.ne(pd.to_numeric(rows.catalog_credits))
    report["credit_conflicts"] = rows.loc[conflict, ["course_id", "course_credits", "catalog_credits"]].to_dict("records")
    if report["unmatched_course_ids"]:
        report["errors"].append("Courses missing from the selected degree catalog.")
    if report["credit_conflicts"]:
        report["errors"].append("Supplied credits conflict with the degree catalog.")
    if report["errors"]:
        raise CandidateImportError(report)
    history = clean_id_columns(course_history, ["student_id", "course_id"])
    prior = history[history.student_id.eq(student_id) & history.part_id.lt(int(part_id))]
    attempts = prior.groupby("course_id").attempt_number.max()
    rows["attempt_number"] = rows.course_id.map(attempts).fillna(0).astype("int64") + 1
    rows["course_name"] = rows.provided_name.combine_first(rows.catalog_name).astype("string")
    rows = rows.drop(columns=["provided_name", "catalog_name", "catalog_credits", "_merge"])
    report["candidate_count"] = len(rows)
    report["history_latest_part"] = int(prior.part_id.max()) if len(prior) else None
    return rows.sort_values("course_id", kind="stable").reset_index(drop=True), report
