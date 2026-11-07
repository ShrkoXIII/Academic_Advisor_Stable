"""Map verified course sources into candidate records and registration policies."""
from decimal import Decimal
import json

from src.recommendation.plan_generation import sum_credit_values

from ..validators.common import ApiError, ValidationResult
from ..validators.courses import (
    check_candidate_duplicate, validate_course_catalog,
    validate_course_fields, validate_course_rules, validate_course_sources, validate_group_policy,
    validate_previous_course_status,
)


def group_identity(degree_id, requirement_id):
    return json.dumps([degree_id, requirement_id], ensure_ascii=False, separators=(",", ":"))


def adapt_courses(request, *, catalog=None):
    result = ValidationResult(checks={"identity": "unavailable", "catalog": "unavailable"})
    try:
        expected, data, rows, rules, context, policy, selected_catalog = validate_course_sources(request, catalog, result)
        candidates, seen, group_sources, group_policies = [], {}, {}, {}
        for index, raw in enumerate(rows):
            try:
                _course(raw, index, expected, context, policy, selected_catalog, candidates, seen,
                        group_sources, group_policies, result)
            except ApiError as error:
                result.add(error)
        result.summary["candidate_count"] = len(candidates)
        rule_values, optional_flag = validate_course_rules(data, rules, policy, result)
        result.summary["candidate_count"] = len(candidates)
        result.normalized = {"candidates": sorted(candidates, key=lambda row: row["course_id"]),
                             "requirement_group_policies": group_policies, "registration_rules": rule_values,
                             "allow_register_all_optional": optional_flag, "registration_policy": policy}
    except ApiError as error:
        result.add(error)
    return result


def _course(raw, index, expected, context, policy, catalog, candidates, seen, group_sources, group_policies, result):
    """Keep validation phases ordered around mapping and deduplication."""
    field = f"availableCourses[{index}]"
    values = validate_course_fields(raw, field, group_sources, result)
    if values is None:
        return
    course, maximum, passed = values["course"], values["maximum"], values["passed"]
    group_id = group_identity(expected["degree_id"], values["group"])
    record = {"course_id": course, "course_name": values["name"], "course_credits": values["credits"],
              "attempt_number": values["attempts"] + 1, "plan_requirement_type_id": values["requirement"],
              "plan_year_order": values["year"], "plan_semester_order": values["semester"],
              "plan_credits_count": maximum, "requirement_group_id": group_id}
    status, reason = validate_previous_course_status(raw, values, field, expected, context, policy, result)
    record["previous_course_status"] = status
    record["plan_course_type_id"] = validate_course_catalog(values, catalog, field, result)
    mode, overflow = validate_group_policy(values, policy, field, result)
    if mode == "strict_remaining":
        group_policies[group_id] = sum_credit_values((maximum, passed.copy_negate()))
    elif mode == "approved_overflow":
        group_policies[group_id] = max(Decimal(0), sum_credit_values((maximum, overflow, passed.copy_negate())))
    elif mode == "unbounded":
        # The service computes all available group credits after deduplication.
        group_policies[group_id] = None
    if check_candidate_duplicate(record, reason, seen, field):
        result.summary["duplicate_count"] += 1
        return
    candidates.append(record)
