"""Course source, eligibility, provenance, and academic policy validation."""
from collections.abc import Mapping

from src.recommendation.course_status import normalize_previous_status

from .common import ApiError, binding, check_record_identity, identifier, number, part, response_data, sourced


def validate_course_sources(request, catalog, result):
    """Check all source identities and duplicates before candidate filtering."""
    expected = binding(request, "courses")
    data = response_data(request.get("courses_api_response"), "courses")
    check_record_identity(request["courses_api_response"], expected)
    check_record_identity(data, expected)
    rows = data.get("availableCourses")
    rules = data.get("registserRule")
    if not isinstance(rows, list) or not isinstance(rules, Mapping):
        raise ApiError("INVALID_COURSES_SHAPE", "availableCourses and registserRule are required.")
    result.summary.update(source_count=len(rows), candidate_count=0, rejected_count=0, duplicate_count=0)
    result.checks["identity"] = "php_attested"
    for row in rows:
        if not isinstance(row, Mapping):
            raise ApiError("INVALID_COURSE_ROW", "Available courses must be records.")
        check_record_identity(row, expected)  # Check before filtering.
    _check_source_duplicates(rows)
    context = request.get("integration_context") or {}
    policy = context.get("registration_policy")
    if policy is not None:
        if not isinstance(policy, Mapping) or not isinstance(policy.get("source"), str) or not policy["source"].strip():
            raise ApiError("MISSING_PROVENANCE", "A confirmed registration policy source is required.")
        if part(policy.get("part_id")) != expected["part_id"]:
            raise ApiError("IDENTITY_MISMATCH", "Registration policy is for another semester.")
    else:
        result.add(ApiError("UNRESOLVED_POLICY", "Confirmed registration and requirement policies are required."))
    selected_catalog = None
    if catalog is not None:
        required = {"degree_id", "course_id", "course_type_id", "requirement_type_id", "course_credits",
                    "credits_count", "year_order", "semester_order"}
        if not required.issubset(catalog.columns):
            raise ApiError("CATALOG_INCOMPATIBLE", "Catalog columns are incompatible.", status_code=503)
        selected_catalog = catalog[catalog.degree_id.astype(str).eq(expected["degree_id"])].copy()
        if selected_catalog.course_id.duplicated().any():
            raise ApiError("CATALOG_INCOMPATIBLE", "Catalog course keys are not unique.", status_code=503)
        selected_catalog = selected_catalog.set_index("course_id")
        result.checks["catalog"] = "verified"
    return expected, data, rows, rules, context, policy, selected_catalog


def _check_source_duplicates(rows):
    """Reject contradictory academic records before eligibility can hide them."""
    numeric = {"COURSE_CREDITS", "ATTEMPTS_COUNT", "CREDITS_COUNT", "REQUIREMENT_PASSED_CREDITS",
               "YEAR_ORDER", "SEMESTER_ORDER", "LAST_REGISTER_SEMESTER_ID"}
    counts = {"ATTEMPTS_COUNT", "YEAR_ORDER", "SEMESTER_ORDER", "LAST_REGISTER_SEMESTER_ID"}
    identifiers = {"COURSE_ID", "REQUIREMENT_TYPE_ID", "REQUIREMENT_ID"}
    fields = numeric | identifiers | {"COURSE_NAME_SL", "IS_REQUESTABLE", "ALLOW_REGISTER",
                                      "STATUS_REASON_CODE", "FINISH_STATUS"}
    seen = {}
    for row in rows:
        course = identifier(row.get("COURSE_ID"), "COURSE_ID")
        comparison = {}
        for key in fields:
            value = row.get(key)
            if value is not None and key in numeric:
                value = number(value, key, integer=key in counts)
            elif value is not None and key in identifiers:
                value = identifier(value, key)
            comparison[key] = value
        if course in seen and comparison != seen[course]:
            raise ApiError("CONFLICTING_DUPLICATE", "Duplicate source course records conflict.", status_code=409)
        seen[course] = comparison


def validate_course_fields(raw, field, group_sources, result):
    """Normalize eligible fields, retaining group evidence before later checks."""
    course = identifier(raw.get("COURSE_ID"), field + ".COURSE_ID")
    flags = []
    for key in ("IS_REQUESTABLE", "ALLOW_REGISTER"):
        if not isinstance(raw.get(key), str) or raw.get(key) not in {"Y", "N"}:
            raise ApiError("INVALID_ELIGIBILITY", "Explicit Y/N registration flags are required.", field=field + "." + key)
        flags.append(raw[key])
    if "N" in flags:
        result.summary["rejected_count"] += 1
        return
    credits = number(raw.get("COURSE_CREDITS"), field + ".COURSE_CREDITS")
    attempts = number(raw.get("ATTEMPTS_COUNT"), field + ".ATTEMPTS_COUNT", integer=True)
    requirement = identifier(raw.get("REQUIREMENT_TYPE_ID"), field + ".REQUIREMENT_TYPE_ID")
    group = identifier(raw.get("REQUIREMENT_ID"), field + ".REQUIREMENT_ID")
    maximum = number(raw.get("CREDITS_COUNT"), field + ".CREDITS_COUNT")
    passed = number(raw.get("REQUIREMENT_PASSED_CREDITS"), field + ".REQUIREMENT_PASSED_CREDITS")
    source = (requirement, maximum, passed)
    if group in group_sources and group_sources[group] != source:
        raise ApiError("CONFLICTING_GROUP", "Requirement-group records disagree.", field=field)
    group_sources[group] = source
    year = number(raw.get("YEAR_ORDER"), field + ".YEAR_ORDER", integer=True)
    semester = number(raw.get("SEMESTER_ORDER"), field + ".SEMESTER_ORDER", integer=True)
    name = raw.get("COURSE_NAME_SL")
    if not isinstance(name, str) or not name.strip():
        raise ApiError("MISSING_FIELD", "A course display name is required.", field=field + ".COURSE_NAME_SL")
    return {"course": course, "credits": credits, "attempts": attempts, "requirement": requirement,
            "group": group, "maximum": maximum, "passed": passed, "year": year, "semester": semester, "name": name}


def validate_previous_course_status(raw, values, field, expected, context, policy, result):
    """Retain reason diagnostics before resolving authoritative prior outcomes."""
    course, attempts = values["course"], values["attempts"]
    reason = raw.get("STATUS_REASON_CODE")
    if reason == "EXCEPTION":
        if policy is None or course not in policy.get("approved_exception_course_ids", []):
            result.add(ApiError("UNRESOLVED_EXCEPTION", "Exception eligibility requires confirmed authorization.", field=field))
    elif reason != "REQUESTABLE":
        result.add(ApiError("UNRESOLVED_REASON", "Eligibility reason needs a confirmed source interpretation.", field=field))
    status = None
    supplied = context.get("previous_course_statuses", {}).get(course)
    if supplied is not None:
        try:
            status = normalize_previous_status(sourced(supplied, expected["part_id"], field + ".previous_status"))
        except ValueError as error:
            if isinstance(error, ApiError):
                raise
            raise ApiError("INVALID_STATUS", "Previous course status is unsupported.", field=field) from None
    if raw.get("LAST_REGISTER_SEMESTER_ID") is not None:
        previous = part(raw["LAST_REGISTER_SEMESTER_ID"], field + ".LAST_REGISTER_SEMESTER_ID")
        if previous >= expected["part_id"]:
            raise ApiError("FUTURE_SOURCE", "Prior course status must precede the target.", field=field)
        if attempts == 0:
            raise ApiError("CONFLICTING_STATUS", "Zero previous attempts cannot include a prior registration semester.", field=field)
    if attempts == 0:
        if raw.get("FINISH_STATUS") is not None or (supplied is not None and status != "NEW"):
            raise ApiError("CONFLICTING_STATUS", "Zero previous attempts cannot include a previous outcome.", field=field)
        status = "NEW"
    elif raw.get("FINISH_STATUS") is not None:
        try:
            actual = normalize_previous_status(raw["FINISH_STATUS"], official=True)
        except ValueError:
            raise ApiError("INVALID_STATUS", "Official course status is unsupported.", field=field) from None
        if status is not None and status != actual:
            raise ApiError("CONFLICTING_STATUS", "Course status sources conflict.", field=field)
        status = actual
    if status in {None, "UNKNOWN", "UNRESOLVED"}:
        result.add(ApiError("MISSING_PREVIOUS_STATUS", "An authoritative previous course status is required.", field=field))
        status = "UNKNOWN"
    if (attempts == 0 and status not in {"NEW", "UNKNOWN"}) or (attempts > 0 and status == "NEW"):
        raise ApiError("CONFLICTING_STATUS", "Previous attempts and supplied status conflict.", field=field)
    return status, reason


def validate_course_catalog(values, catalog, field, result):
    """Resolve course type from the compatible catalog and compare properties."""
    course, credits = values["course"], values["credits"]
    maximum, requirement = values["maximum"], values["requirement"]
    if catalog is None:
        course_type = None
        result.unavailable_fields.append("plan_course_type_id")
    else:
        if course not in catalog.index:
            raise ApiError("UNRESOLVED_COURSE_TYPE", "Course is absent from the selected degree catalog.", field=field)
        row = catalog.loc[course]
        course_type = identifier(row.course_type_id, "catalog.course_type_id")
        for external, internal in ((credits, "course_credits"), (maximum, "credits_count"),
                                   (values["year"], "year_order"), (values["semester"], "semester_order")):
            if external != number(row[internal], "catalog." + internal):
                raise ApiError("CATALOG_CONFLICT", "Source course properties conflict with the catalog.", field=field)
        if requirement != identifier(row.requirement_type_id, "catalog.requirement_type_id"):
            raise ApiError("CATALOG_CONFLICT", "Requirement classification conflicts with the catalog.", field=field)
    return course_type


def validate_group_policy(values, policy, field, result):
    """Return the confirmed mode and any validated overflow allowance."""
    if policy is None:
        return None, None
    group = values["group"]
    mode = policy.get("requirement_group_modes", {}).get(group)
    if mode == "strict_remaining":
        if values["passed"] > values["maximum"]:
            raise ApiError("CONFLICTING_GROUP", "Passed group credits exceed the strict requirement limit.", field=field)
    elif mode == "approved_overflow":
        return mode, number(policy.get("group_overflow_credits", {}).get(group), "group_overflow_credits")
    elif mode != "unbounded":
        result.add(ApiError("UNRESOLVED_GROUP_POLICY", "Every candidate group requires a confirmed policy.", field=field))
    return mode, None


def check_candidate_duplicate(record, reason, seen, field):
    """Compare normalized records after the existing group-policy checks."""
    course = record["course_id"]
    if course in seen:
        comparison = dict(record, status_reason=reason)
        if seen[course] != comparison:
            raise ApiError("CONFLICTING_DUPLICATE", "Duplicate course records conflict.", field=field, status_code=409)
        return True
    seen[course] = dict(record, status_reason=reason)
    return False


def validate_course_rules(data, rules, policy, result):
    """Check load rules before optional and previous-attempt interpretations."""
    rule_values = _rules(rules, policy)
    optional_flag = data.get("allowRegisterAllOptional")
    if not isinstance(optional_flag, str) or optional_flag not in {"Y", "N"}:
        raise ApiError("INVALID_OPTIONAL_FLAG", "allowRegisterAllOptional must be Y or N.")
    if optional_flag == "Y" and (policy is None or policy.get("allow_register_all_optional_confirmed") is not True):
        result.add(ApiError("UNRESOLVED_OPTIONAL_POLICY", "Optional registration permission requires a confirmed interpretation."))
    if policy is not None and policy.get("attempts_scope_confirmed") is not True:
        result.add(ApiError("UNRESOLVED_ATTEMPT_SCOPE", "Previous-attempt counting must match the training contract."))
    return rule_values, optional_flag


def _rules(rules, policy):
    if rules.get("LOAD_TYPE") != "CREDIT":
        raise ApiError("UNRESOLVED_LOAD_TYPE", "Only the confirmed credit-load rule is supported.")
    values = {key: number(rules.get(key), key, integer=key == "MAX_NEW_COURSES",
                          nullable=key == "MAX_NEW_COURSES" and key not in rules)
              for key in ("MIN_CREDITS", "MAX_CREDITS", "MIN_STUDY_CREDITS", "MAX_STUDY_CREDITS",
                          "GRAD_MAX_LOAD", "GRAD_MIN_LIMIT", "MAX_NEW_COURSES")}
    for lower, upper in (("MIN_CREDITS", "MAX_CREDITS"), ("MIN_STUDY_CREDITS", "MAX_STUDY_CREDITS"),
                         ("GRAD_MIN_LIMIT", "GRAD_MAX_LOAD")):
        if values[lower] > values[upper]:
            raise ApiError("CONFLICTING_RULES", "Registration minimum exceeds its maximum.")
    profile = None if policy is None else policy.get("load_profile")
    if profile not in {None, "study", "graduation"}:
        raise ApiError("UNRESOLVED_LOAD_PROFILE", "Applicable registration profile is unresolved.")
    if profile is not None:
        lo, hi = ("MIN_STUDY_CREDITS", "MAX_STUDY_CREDITS") if profile == "study" else ("GRAD_MIN_LIMIT", "GRAD_MAX_LOAD")
        values["effective_min"] = max(values["MIN_CREDITS"], values[lo])
        values["effective_max"] = min(values["MAX_CREDITS"], values[hi])
        if values["effective_min"] > values["effective_max"]:
            raise ApiError("CONFLICTING_RULES", "Registration rule ranges do not intersect.")
    return values
