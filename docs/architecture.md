## Production recommendation architecture

The production recommendation source is the University Backend/API. The Python service does not read a local JSON, Parquet, or table candidate list to construct production recommendations.

```text
University Backend/API
  → src/api/app.py
  → ApiService.recommend()
  → adapt_student() / adapt_courses()
  → _run_recommendation()
  → TwoStagePlanRecommender.recommend_from_payloads()
  → prepare_recommendation_payloads()
  → frozen course-history features → Stage 1 scoring/shortlist
  → Stage 2 scoring → ranking → API response
```

The Backend supplies source student and history data, candidate course properties and provider eligibility/attempt data, identity/context, and confirmed request and requirement policies through API responses. Python validates identities, provenance and payload fields; normalizes values; derives only existing features from supplied history; excludes explicitly ineligible candidates; normalizes constraints; runs the existing engine; and serializes the response. The catalog loaded by the API is a consistency/readiness check for supplied course fields, not a candidate-list builder.

A local JSON request is a complete payload that satisfies the API contract, not an adapter for local student or candidate files.

## Optional observed-plan evaluation

Observed-plan evaluation is a separate Streamlit UI path. Per evaluation request it may read a local registration roster, prior course history, degree catalog, evaluation predictions, and student status through `src/evaluation/local_course_inputs.py` and `src/evaluation/observed_plan.py`. It describes the registered plan; it is not a candidate source for production recommendation.

## Local serving dependencies

| Component | File/path | Purpose/category | Loading timing |
|---|---|---|---|
| API catalog consistency | `data/clean/degree_course.parquet` | Validation data for supplied Backend candidate properties and readiness; not a local candidate-list builder | `ApiService.initialize()` through `load_catalog()` at startup |
| Grade scale | `data/raw/v_acs_grade.parquet` | Source/model compatibility reference and GPA conversion | `ApiService.initialize()` GradeScale loader and the manifest-pinned `load_two_stage_artifacts()` loader at startup |
| Inference artifacts | `models/shortlist/manifest.json`; Stage 1 model pair/category levels under `models/shortlist/`; Stage 2 model pair/category levels under `models/` / `data/artifacts/`; `models/model_metadata.json` | Verified model assets and provenance | `load_two_stage_artifacts()` at startup |
| Frozen history | `data/artifacts/history/as_of_*/{course_history_state.pkl,metadata.json}` | Historical model features | `FrozenHistoryManager.load()` at startup, or when a requested cutoff is loaded lazily |
| Incremental history state | `data/artifacts/history_incremental/control.json` and activated bundles below that root | Active history pointer/state | `CumulativeHistoryStore` during readiness/request history refresh and for selected cutoffs |
| Split-intake request state | `.api-state/requests.sqlite3` (configurable) | Idempotent split-intake state and request-status lookup, not model input | `RequestStore`, created lazily for split student/courses intake or request-status lookup; unused by the combined route |
| Observed-plan evaluation only | `data/clean/registration_roster.parquet`, `data/clean/student_course.parquet`, `data/clean/degree_course.parquet`, `data/evaluation/plan_gpa_course_predictions_2025.parquet`, `data/clean/student_status.parquet` | Local registered-plan inputs and outcome comparison | Streamlit evaluation views per evaluation request |

`.env.local`, if present, is consumed by the Uvicorn launcher as deployment configuration; it is not recommendation input normalization. Production is therefore not file-independent: it requires approved models, GradeScale, and frozen history, while it reads no local candidate JSON or Parquet list for production recommendation.
