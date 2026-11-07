"""HTTP envelopes; backend payloads keep their actual external field names."""
from typing import Any, Literal
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Identity(Envelope):
    student_id: StrictStr
    degree_id: StrictStr
    part_id: StrictInt | StrictStr


class SourceContexts(Envelope):
    student: Identity | None = None
    courses: Identity | None = None


class SourcedValue(Envelope):
    value: Any
    source: StrictStr
    as_of_part: StrictInt | StrictStr


class RegistrationPolicy(Envelope):
    source: StrictStr
    part_id: StrictInt | StrictStr
    requirement_group_modes: dict[StrictStr, Literal["strict_remaining", "unbounded", "approved_overflow"]]
    group_overflow_credits: dict[StrictStr, Decimal] = Field(default_factory=dict)
    allow_register_all_optional_confirmed: StrictBool = False
    approved_exception_course_ids: list[StrictStr] = Field(default_factory=list)
    allowed_failed_repeat_credits: Decimal
    allowed_withdrawn_repeat_credits: Decimal | None = None
    attempts_scope_confirmed: StrictBool = False
    load_profile: Literal["study", "graduation"]


class TotalRegCreditsSource(Envelope):
    """PHP attestation for official registered credits and their temporal meaning."""
    source: StrictStr
    target_part: StrictInt | StrictStr
    as_of_part: StrictInt | StrictStr
    timing: Literal["beginning_of_semester", "end_of_semester"]
    rules_reference: StrictStr
    semester_complete: StrictBool = False
    additive_credit_accounting: StrictBool = False
    semester_gpa_counted_credits: Decimal | None = None


class IntegrationContext(Envelope):
    student_values: dict[StrictStr, SourcedValue] = Field(default_factory=dict)
    total_reg_credits_source: TotalRegCreditsSource | None = None
    previous_course_statuses: dict[StrictStr, SourcedValue] = Field(default_factory=dict)
    registration_policy: RegistrationPolicy | None = None


class StudentValidationRequest(Identity):
    student_api_response: dict
    source_contexts: SourceContexts
    integration_context: IntegrationContext = Field(default_factory=IntegrationContext)


class CoursesValidationRequest(Identity):
    courses_api_response: dict
    source_contexts: SourceContexts
    integration_context: IntegrationContext = Field(default_factory=IntegrationContext)


class RecommendationOptions(Envelope):
    """Existing cutoff and credit choices, carried by the student submission."""
    history_as_of_part: StrictInt | StrictStr
    target_credits: Decimal | None = None
    min_credits: Decimal | None = None
    max_credits: Decimal | None = None
    top_k: StrictInt = Field(default=3, ge=1, le=50)
    mode: Literal["normal", "backtesting"] = "normal"

    @model_validator(mode="after")
    def credit_mode(self):
        if self.target_credits is not None:
            if self.min_credits is not None or self.max_credits is not None:
                raise ValueError("Supply exact credits or bounds, not both.")
        elif self.min_credits is None or self.max_credits is None:
            raise ValueError("Supply exact credits or both bounds.")
        return self


class RecommendationRequest(StudentValidationRequest, RecommendationOptions):
    courses_api_response: dict


class StudentInputRequest(StudentValidationRequest):
    request_id: StrictStr = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    recommendation: RecommendationOptions


class CoursesInputRequest(CoursesValidationRequest):
    request_id: StrictStr = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class Finalization(Envelope):
    finalized_part_id: StrictInt | StrictStr
    approval_reference: StrictStr


class HistoryDeltaRequest(Envelope):
    part_id: StrictInt | StrictStr
    rows: list[dict]
    finalization: Finalization | None = None


class HistoryModeRequest(Envelope):
    mode: Literal["disabled", "manual", "auto_on_finalization"]


class HistoryInitializeRequest(Envelope):
    expected_source_hash: StrictStr
    approval_reference: StrictStr
    confirmation: StrictBool
    cumulative_history_confirmed: StrictBool


class HistoryCommitRequest(HistoryDeltaRequest):
    preview_token: StrictStr
    confirmation: StrictBool


class HistoryActivationRequest(Envelope):
    history_as_of_part: StrictInt | StrictStr
    expected_history_sha256: StrictStr
    confirmation: StrictBool
    rollback: StrictBool = False
