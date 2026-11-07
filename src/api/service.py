"""Independent validation dependencies and lazy, manifest-gated inference."""
from collections import defaultdict
from threading import Lock

from src import paths
from src.features.frozen_history import validate_history_selection
from src.grade_scale import GradeScale
from src.recommendation.history_update import FrozenHistoryManager
from src.recommendation.plan_generation import sum_credit_values
from src.recommendation.ranking_policy import validate_ranking_policy
from src.recommendation.two_stage_artifacts import load_two_stage_artifacts
from src.recommendation.two_stage_engine import TwoStagePlanRecommender

from .adapters.courses import adapt_courses
from .adapters.history import adapt_history_delta
from .settings import ApiSettings
from .adapters.student import adapt_student
from .catalog import load_catalog
from .validators.common import ApiError, identifier, number, part


PUBLIC_METADATA = {"dataset_version", "feature_engineering_version", "input_fingerprint_version", "input_sha256",
                   "manifest_version", "grade_scale_sha256", "grade_scale_version", "grade_model_target",
                   "expected_points_method", "balance_policy_version", "received_candidate_count", "candidate_count",
                   "stage1_row_count", "feasible_plan_count", "shortlist_count", "shortlist_limit", "shortlist_plan_ids",
                   "scored_plan_count", "stage2_row_count", "returned_plan_count", "top_k", "global_top_k_guaranteed",
                   "credit_policy", "target_credits", "allowed_failed_repeat_credits", "allowed_withdrawn_repeat_credits",
                   "projected_gpa_method", "production_ranking_strategy", "usage", "max_new_courses"}


class ApiService:
    def __init__(self, *, settings=None, catalog=None, grade_scale=None, history_manager=None, engine=None, history_store=None,
                 request_store=None):
        self.settings = settings or ApiSettings()
        self.catalog, self.grade_scale = catalog, grade_scale
        self.history_manager = history_manager or (engine.history_manager if engine is not None else None)
        self.engine = engine
        self.artifacts = engine.artifacts if engine is not None else None
        self._inference_lock = Lock()
        self._request_store = request_store
        self._request_store_lock = Lock()
        if history_store is None:
            from src.recommendation.cumulative_history import CumulativeHistoryStore
            history_store = CumulativeHistoryStore(self.settings.incremental_history_root,
                default_mode=self.settings.history_update_mode, compatibility_check=self._history_compatibility,
                legacy_root=self.settings.history_baseline_source_root)
        self.history_store = history_store

    def _get_request_store(self):
        """Open request storage only for ingestion; diagnostics stay read-only."""
        with self._request_store_lock:
            if self._request_store is None:
                from .request_store import RequestStore
                self._request_store = RequestStore(
                    self.settings.request_store_path,
                    pending_ttl_seconds=self.settings.request_pending_ttl_seconds,
                    processing_ttl_seconds=self.settings.request_processing_ttl_seconds,
                    result_ttl_seconds=self.settings.request_result_ttl_seconds,
                    max_requests=self.settings.request_max_count,
                    max_payload_bytes=self.settings.request_max_payload_bytes)
        return self._request_store

    def submit_recommendation_input(self, component, request, *, owner):
        """Validate one component, claim a complete pair, reuse recommend once."""
        from pydantic import ValidationError
        from .schemas import StudentInputRequest, CoursesInputRequest
        schema = {"student": StudentInputRequest, "courses": CoursesInputRequest}.get(component)
        if schema is None:
            raise ApiError("INVALID_COMPONENT", "Unknown recommendation component.")
        try:
            request = schema.model_validate(request).model_dump()
        except ValidationError:
            raise ApiError("INVALID_REQUEST_SCHEMA", "Request does not satisfy the documented HTTP schema.") from None
        store = self._get_request_store()
        request_id = request["request_id"]
        replay = store.replay(owner, request_id, component, request)
        if replay is not None:
            return replay
        validate = self.validate_student if component == "student" else self.validate_courses
        diagnostic = validate(request)
        if diagnostic.errors:
            raise ApiError("INVALID_INPUTS", "Recommendation input validation failed.",
                           status_code=diagnostic.http_status, details={component: diagnostic.public()})
        state = store.submit(owner, request_id, component, request)
        if not state.get("claimed"):
            return state
        try:
            combined = self._assemble_recommendation_request(state["components"])
            result = self.recommend(combined)
            return store.complete(owner, request_id, state["claim_token"], result)
        except ApiError as error:
            return store.fail(owner, request_id, state["claim_token"], error.issue, http_status=error.status_code)
        except Exception:
            error = ApiError("INTERNAL_ERROR", "Request could not be completed.", status_code=500)
            return store.fail(owner, request_id, state["claim_token"], error.issue, http_status=500)

    def lookup_recommendation_request(self, request_id, *, owner):
        """Retrieve persisted status/result without launching inference."""
        return self._get_request_store().lookup(owner, request_id)

    @staticmethod
    def _assemble_recommendation_request(components):
        """Combine consistent evidence without treating the two responses alike."""
        from pydantic import ValidationError
        from .schemas import RecommendationRequest

        def merge_evidence(left, right):
            if left is None:
                return right
            if right is None:
                return left
            if isinstance(left, dict) and isinstance(right, dict):
                merged = dict(left)
                for key, value in right.items():
                    merged[key] = merge_evidence(merged[key], value) if key in merged else value
                return merged
            if left != right:
                raise ApiError("REQUEST_CONTEXT_CONFLICT", "Student and courses source evidence disagrees.", status_code=409)
            return left

        student, courses = components["student"], components["courses"]
        combined = {key: student[key] for key in ("student_id", "degree_id", "part_id", "student_api_response")}
        combined["courses_api_response"] = courses["courses_api_response"]
        for key in ("source_contexts", "integration_context"):
            combined[key] = merge_evidence(student[key], courses[key])
        combined.update(student["recommendation"])
        try:
            return RecommendationRequest.model_validate(combined).model_dump()
        except ValidationError:
            raise ApiError("INVALID_REQUEST_SCHEMA", "Assembled recommendation does not satisfy the HTTP schema.") from None

    def _history_compatibility(self, state, metadata):
        """Loaded artifacts retain their original manifest and approval validation."""
        if self.artifacts is None:
            raise ValueError("SERVING_ARTIFACTS_UNAVAILABLE")
        policy = validate_ranking_policy(self.artifacts.manifest, require_approved=True)
        if any(policy[key] != {"name": "pareto", "version": "v1"} for key in
               ("stage1_shortlist_strategy", "final_ranking_strategy")):
            raise ValueError("SERVING_POLICY_INCOMPATIBLE")
        for stage in self.artifacts.manifest["stages"].values():
            columns = stage["feature_contract"]["model_features"]
            if any("specialty_history" in column or "degree_history" in column for column in columns):
                raise ValueError("SPECIALTY_HISTORY_AGGREGATES_UNAVAILABLE")
        if metadata.get("dataset_version") != "V2" or state.as_of_part != metadata.get("as_of_part"):
            raise ValueError("SERVING_HISTORY_INCOMPATIBLE")

    def _load_history(self):
        if self.history_store.status().get("active_as_of_part") is not None:
            return self.history_store.serving_manager()
        return FrozenHistoryManager.load()

    def _bind_history_manager(self, manager):
        self.history_manager = manager
        if self.engine is not None:
            self.engine.history_manager = manager
        elif self.artifacts is not None:
            self.engine = TwoStagePlanRecommender.from_loaded_artifacts(self.artifacts, manager)

    def _refresh_history_manager(self):
        """Workers started before migration adopt the durable serving pointer."""
        try:
            manager = self.history_store.serving_manager()
            if manager is not None:
                self._bind_history_manager(manager)
        except (ValueError, OSError):
            raise ApiError("HISTORY_UNAVAILABLE", "Durable serving history is unavailable or incompatible.", status_code=503) from None

    def initialize(self, *, catalog_loader=None, grade_scale_loader=None, history_loader=None, model_loader=None):
        """Load each dependency independently; ordinary load errors leave HTTP usable."""
        import pandas as pd
        loaders = {"catalog": catalog_loader or load_catalog,
                   "grade_scale": grade_scale_loader or (lambda: GradeScale.from_parquet(paths.GRADE_SCALE_PATH)),
                   "history_manager": history_loader or self._load_history,
                   "artifacts": model_loader or load_two_stage_artifacts}
        for name, loader in loaders.items():
            if getattr(self, name) is None:
                try:
                    value = loader()
                    if name == "artifacts":
                        policy = validate_ranking_policy(value.manifest, require_approved=True)
                        if any(policy[key] != {"name": "pareto", "version": "v1"} for key in
                               ("stage1_shortlist_strategy", "final_ranking_strategy")):
                            raise ValueError("API requires the approved pareto v1 policy at both stages.")
                    setattr(self, name, value)
                except Exception:
                    # Never expose loader errors, private artifact paths or input data.
                    setattr(self, name, None)
        if self.engine is None and self.artifacts is not None and self.history_manager is not None:
            try:
                self.engine = TwoStagePlanRecommender.from_loaded_artifacts(self.artifacts, self.history_manager)
            except Exception:
                self.engine = None

    def health(self):
        try:
            self._refresh_history_manager()
            history_ready = self.history_manager is not None
        except ApiError:
            history_ready = False
        return {"api_health": "healthy", "model_readiness": {"ready": self.artifacts is not None},
                "history_readiness": {"ready": history_ready},
                "catalog_readiness": {"ready": self.catalog is not None},
                "grade_scale_readiness": {"ready": self.grade_scale is not None},
                "recommendation_readiness": {"ready": history_ready and all(value is not None for value in
                    (self.engine, self.catalog, self.grade_scale))},
                "production_operational_limits": "UNRESOLVED"}

    def validate_student(self, request):
        return adapt_student(request, settings=self.settings, grade_scale=self.grade_scale)

    def validate_courses(self, request):
        return adapt_courses(request, catalog=self.catalog)

    def validate_delta(self, request):
        try:
            self._refresh_history_manager()
            manager = self.history_manager
        except ApiError:
            manager = None
        return adapt_history_delta(request, manager=manager)

    def history_status(self):
        return self.history_store.status()

    @staticmethod
    def _finalized_payload(request, *, require_finalized=False):
        cutoff = part(request.get("part_id"))
        proof = request.get("finalization")
        if proof is None:
            if require_finalized:
                raise ApiError("FINALIZATION_REQUIRED", "An authoritative semester finalization reference is required.")
            return {"delta_part": cutoff, "aggregates": request.get("rows")}, None
        if part(proof.get("finalized_part_id")) != cutoff:
            raise ApiError("FINALIZATION_CONFLICT", "Finalization reference must identify the delta semester.")
        reference = identifier(proof.get("approval_reference"), "approval_reference")
        return {"delta_part": cutoff, "aggregates": request.get("rows"), "finalized": True}, reference

    def _history_operation(self, operation, **kwargs):
        if not self._inference_lock.acquire(blocking=False):
            raise ApiError("HISTORY_OPERATION_BUSY", "Serving worker is busy; retry the administrative operation.", status_code=503)
        try:
            result = getattr(self.history_store, operation)(**kwargs)
            if operation in {"initialize", "activate", "finalize"}:
                manager = self.history_store.serving_manager()
                if manager is not None:
                    self._bind_history_manager(manager)
            return result
        except (ValueError, OSError) as error:
            code = getattr(error, "code", "HISTORY_OPERATION_REJECTED")
            safe_codes = {"HISTORY_DISABLED", "MANUAL_MODE_REQUIRED", "AUTO_MODE_REQUIRED", "HISTORY_UNINITIALIZED",
                          "HISTORY_CONFLICT", "STALE_PREVIEW", "CONFIRMATION_REQUIRED", "INVALID_DELTA",
                          "HISTORY_INCOMPATIBLE", "SPECIALTY_HISTORY_AGGREGATES_UNAVAILABLE", "SERVING_ARTIFACTS_UNAVAILABLE",
                          "BASELINE_APPROVAL_REQUIRED", "BASELINE_NOT_CUMULATIVE", "SOURCE_HASH_MISMATCH",
                          "OUT_OF_ORDER_DELTA", "HISTORY_VERSION_UNAVAILABLE", "ROLLBACK_CONFIRMATION_REQUIRED",
                          "HISTORY_ROOT_OVERLAP", "HISTORY_CONTROL_INVALID", "HISTORY_LOCK_BUSY", "FINALIZATION_REQUIRED",
                          "SERVING_POLICY_INCOMPATIBLE", "SERVING_HISTORY_INCOMPATIBLE", "ADMIN_WORKFLOW_REQUIRED",
                          "HISTORY_VERSION_NOT_ACTIVATED", "HISTORY_CUTOFF_AFTER_ACTIVE"}
            if code not in safe_codes:
                code = "HISTORY_OPERATION_REJECTED"
            raise ApiError(code, "History operation rejected; correct the mode, approval, lineage or compatibility evidence.",
                           component="history", status_code=getattr(error, "status_code", 409)) from None
        finally:
            self._inference_lock.release()

    def set_history_mode(self, request):
        return self._history_operation("set_mode", mode=request["mode"])

    def initialize_history(self, request):
        if request.get("confirmation") is not True:
            raise ApiError("CONFIRMATION_REQUIRED", "Explicit administrator confirmation is required.")
        if request.get("cumulative_history_confirmed") is not True:
            raise ApiError("BASELINE_NOT_CUMULATIVE", "Administrator must attest the baseline includes all approved history through 20251.")
        return self._history_operation("initialize", source_root=self.settings.history_baseline_source_root,
            expected_source_hash=request["expected_source_hash"], approval_reference=request["approval_reference"],
            confirmation=True, cumulative_history_confirmed=True)

    def preview_history(self, request):
        payload, _ = self._finalized_payload(request)
        return self._history_operation("preview", history_payload=payload)

    def commit_history(self, request):
        if request.get("confirmation") is not True:
            raise ApiError("CONFIRMATION_REQUIRED", "Explicit administrator confirmation is required.")
        payload, reference = self._finalized_payload(request, require_finalized=True)
        return self._history_operation("commit", history_payload=payload, preview_token=request["preview_token"],
            confirmation=True, approval_reference=reference)

    def activate_history(self, request):
        if request.get("confirmation") is not True:
            raise ApiError("CONFIRMATION_REQUIRED", "Explicit administrator confirmation is required.")
        return self._history_operation("activate", cutoff=part(request["history_as_of_part"]),
            expected_history_sha256=request["expected_history_sha256"], confirmation=True, rollback=request.get("rollback", False))

    def finalize_history(self, request):
        payload, reference = self._finalized_payload(request, require_finalized=True)
        return self._history_operation("finalize", history_payload=payload, approval_reference=reference, trusted_event=True)

    def recommend(self, request):
        """Validate and prepare PHP inputs, run inference, then expose safe output."""
        student, courses = self._validate_recommendation_inputs(request)
        cutoff, target, mode, candidates = self._prepare_recommendation_context(request, student, courses)
        engine_request = self._build_engine_request(request, courses, candidates, target)
        output = self._run_recommendation(student, candidates, engine_request, request, cutoff, mode)
        return self._recommendation_response(output, student, courses, target, cutoff, mode)

    def _validate_recommendation_inputs(self, request):
        """Collect both diagnostics before rejecting invalid inputs."""
        student, courses = self.validate_student(request), self.validate_courses(request)
        errors = [*student.errors, *courses.errors]
        if errors:
            status = max(student.http_status, courses.http_status)
            raise ApiError("INVALID_INPUTS", "Recommendation inputs need correction.", status_code=status,
                           details={"student": student.public(), "courses": courses.public()})
        return student, courses

    def _prepare_recommendation_context(self, request, student, courses):
        """Check temporal selection, dependencies and model cutoffs in serving order."""
        self._refresh_history_manager()
        cutoff, target = part(request.get("history_as_of_part"), "history_as_of_part"), part(request.get("part_id"))
        mode = request.get("mode", "normal")
        if mode not in {"normal", "backtesting"} or (mode == "backtesting" and not self.settings.enable_backtesting):
            raise ApiError("BACKTESTING_DISABLED", "Backtesting requires explicit mode and service authorization.")
        try:
            validate_history_selection(target, cutoff, allow_older_history=mode == "backtesting")
        except ValueError:
            raise ApiError("INVALID_HISTORY_CUTOFF", "History cutoff does not satisfy the requested temporal policy.") from None
        candidates = courses.normalized["candidates"]
        if (self.settings.performance_test_mode and
                len(candidates) > self.settings.performance_test_max_candidates):
            raise ApiError("PERFORMANCE_TEST_LIMIT", "Entire request exceeds the configured performance test limit.")
        if not self.health()["recommendation_readiness"]["ready"]:
            raise ApiError("DEPENDENCY_UNAVAILABLE", "Recommendation dependencies are unavailable.", status_code=503)
        # Unknown histories are retained only where the existing snapshot contract
        # permits null; no totals or GPA lags are invented here.
        if "observed_gap_semesters" in student.unavailable_fields or student.checks.get("student_history_schema") != "verified":
            raise ApiError("INSUFFICIENT_STUDENT_HISTORY", "Student history cannot support required temporal features.")
        for stage in self.artifacts.manifest["stages"].values():
            if target <= part(stage["training_as_of_part"]):
                raise ApiError("TRAINING_CUTOFF_OVERLAP", "Target must follow every model training cutoff.")
        try:
            self.history_manager.capture(target_part=target, history_as_of_part=cutoff, allow_older_history=mode == "backtesting")
        except (ValueError, OSError):
            raise ApiError("HISTORY_UNAVAILABLE", "The exact requested history snapshot is unavailable or incompatible.", status_code=503) from None
        return cutoff, target, mode, candidates

    def _build_engine_request(self, request, courses, candidates, target):
        """Intersect confirmed credit bounds and prepare exact plan constraints."""
        rules = courses.normalized["registration_rules"]
        exact = request.get("target_credits")
        if exact is not None:
            lower = upper = number(exact, "target_credits")
        else:
            lower, upper = number(request.get("min_credits"), "min_credits"), number(request.get("max_credits"), "max_credits")
        if lower > upper:
            raise ApiError("INVALID_CREDIT_BOUNDS", "Requested credit minimum exceeds maximum.")
        lower, upper = max(lower, rules["effective_min"]), min(upper, rules["effective_max"])
        if lower > upper:
            raise ApiError("CREDIT_RANGE_CONFLICT", "Requested and confirmed credit ranges do not intersect.")
        categories, groups = defaultdict(list), defaultdict(list)
        for row in candidates:
            categories[row["plan_requirement_type_id"]].append(row["course_credits"])
            groups[row["requirement_group_id"]].append(row["course_credits"])
        policies = courses.normalized["requirement_group_policies"]
        policy = courses.normalized["registration_policy"]
        engine_request = {"student_id": request["student_id"], "degree_id": request["degree_id"], "part_id": target,
                          "target_credits": upper,
                          "allowed_failed_repeat_credits": number(policy.get("allowed_failed_repeat_credits"), "allowed_failed_repeat_credits"),
                          "allowed_withdrawn_repeat_credits": number(policy.get("allowed_withdrawn_repeat_credits"),
                              "allowed_withdrawn_repeat_credits", nullable=True),
                          "requirement_policies": [{"plan_requirement_type_id": key, "max_credits": sum_credit_values(values)}
                                                   for key, values in categories.items()],
                          "requirement_group_policies": {key: sum_credit_values(groups[key]) if value is None else value
                                                         for key, value in policies.items()},
                          "max_new_courses": rules["MAX_NEW_COURSES"]}
        if engine_request["allowed_withdrawn_repeat_credits"] is None:
            engine_request.pop("allowed_withdrawn_repeat_credits")
        return engine_request

    def _run_recommendation(self, student, candidates, engine_request, request, cutoff, mode): ## send to engine
        """Protect the existing engine call with the serving-worker lock."""
        if not self._inference_lock.acquire(blocking=False):
            raise ApiError("INFERENCE_BUSY", "Recommendation worker is busy.", status_code=503)
        try:
            output = self.engine.recommend_from_payloads(student_payload={"snapshot": student.normalized, "candidates": candidates},
                        request_payload=engine_request, top_k=request.get("top_k", 3), history_as_of_part=cutoff,
                        allow_older_history=mode == "backtesting")
        except ValueError:
            raise ApiError("INCOMPATIBLE_INPUTS", "Prepared inputs do not satisfy the inference contract.") from None
        finally:
            self._inference_lock.release()
        return output

    def _recommendation_response(self, output, student, courses, target, cutoff, mode):
        """Expose the original metadata allowlist and input diagnostics."""
        metadata = {key: value for key, value in output["metadata"].items() if key in PUBLIC_METADATA}
        metadata.update(mode=mode, history_as_of_part=cutoff, part_id=target,
                        input_validation={"student": student.status, "courses": courses.status},
                        unavailable_student_fields=sorted(set(student.unavailable_fields)),
                        identity_verification={"student": student.checks["identity"], "courses": courses.checks["identity"]},
                        performance_test_mode=self.settings.performance_test_mode)
        return {"status": output["status"], "metadata": metadata, "recommendations": output["recommendations"]}
