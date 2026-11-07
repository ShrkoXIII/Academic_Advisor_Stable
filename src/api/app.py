"""Optional FastAPI transport. Importing this module never loads artifacts."""
from contextlib import asynccontextmanager
from decimal import Decimal
import json
from secrets import compare_digest #مقارنة المفاتيح السرية بطريقة تقلل تسريب معلومات عبر زمن المقارنة
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from .schemas import StudentValidationRequest, CoursesValidationRequest, RecommendationRequest, HistoryDeltaRequest
from .schemas import HistoryModeRequest, HistoryInitializeRequest, HistoryCommitRequest, HistoryActivationRequest
from .schemas import StudentInputRequest, CoursesInputRequest
from .service import ApiService
from .settings import ApiSettings
from .validators.common import ApiError, json_safe


class DecimalRequest(Request): ## تخصيص قراءة الطلب 
    async def json(self):
        if not hasattr(self, "_json"): ## منع اعادة القراءة
            body = await self.body() ## قراءة البيانات من الشبكة
            def reject_constant(value): ## رفض القيم الغير محددة
                raise json.JSONDecodeError("Nonfinite JSON numbers are unsupported.", "", 0)
            self._json = json.loads(body, parse_float=Decimal, parse_constant=reject_constant) # قراءة وتحويل ورفض 
        return self._json


class DecimalRoute(APIRoute):  ## يرث من APIRoute
    def get_route_handler(self):
        handler = super().get_route_handler()   
        async def preserve_credit_precision(request):
            try:
                decimal_request = DecimalRequest(request.scope, request.receive)
                if request.method == "POST" and request.url.path in {
                        "/api/v1/recommendation-inputs/student", "/api/v1/recommendation-inputs/courses"}:
                    limit = request.app.state.api_service.settings.request_max_payload_bytes
                    chunks, size = [], 0
                    async for chunk in decimal_request.stream():
                        size += len(chunk)
                        if size > limit:
                            raise ApiError("REQUEST_PAYLOAD_TOO_LARGE", "Recommendation input exceeds the configured size limit.", status_code=413)
                        chunks.append(chunk)
                    decimal_request._body = b"".join(chunks)
                return await handler(decimal_request)
            except (ApiError, RequestValidationError, HTTPException):
                raise
            except Exception:
                # A generic Exception handler still rethrows to the ASGI server.
                # Convert at the route boundary so private tracebacks never leak.
                raise ApiError("INTERNAL_ERROR", "Request could not be completed.", status_code=500) from None
        return preserve_credit_precision ## المعالجة المغلفة 
##DecimalRequest يحدد كيف نقرأ البيانات، وDecimalRoute يضمن استخدام هذه الطريقة عند معالجة المسارات

def create_app(*, settings=None, service=None):
    """Create an app; injected services are already initialized for tests/tools."""
    api = service or ApiService(settings=settings or ApiSettings.from_env())
    @asynccontextmanager
    async def lifespan(app):
        if service is None:
            await run_in_threadpool(api.initialize) ## تنفيذ التهيئة في خطوة منفصلة من service 
        yield
    app = FastAPI(title="Academic Advisor Integration", version="1.0", lifespan=lifespan)
    app.router.route_class = DecimalRoute
    app.state.api_service = api
##app: تطبيق FastAPI الذي يستقبل اتصالات الشبكة.
##api: كائن ApiService الذي ينفذ عمليات المشروع.

    def authenticate(value, *, admin=False, finalization=False):
        if admin or finalization:
            key = api.settings.finalization_key if finalization else api.settings.admin_key
            credentials = {"finalization" if finalization else "admin": key} if key else {}
        else:
            credentials = dict(api.settings.service_keys)
            if api.settings.service_key:
                credentials["legacy"] = api.settings.service_key
        if not credentials:
            raise ApiError("AUTH_UNCONFIGURED", "Service authentication is unavailable.", status_code=503)
        if value is None:
            raise ApiError("AUTH_REQUIRED", "A service credential is required.", status_code=401)
        matched = [owner for owner, expected in credentials.items()
                   if compare_digest(value.encode("utf8"), expected.encode("utf8"))]
        if not matched:
            raise ApiError("AUTH_FORBIDDEN", "Service credential is not authorized.", status_code=403)
        return matched[0]

    def service_auth(x_api_key: str | None = Header(default=None)):
        return authenticate(x_api_key)

    def admin_auth(x_api_key: str | None = Header(default=None)):
        authenticate(x_api_key, admin=True)

    def finalization_auth(x_api_key: str | None = Header(default=None)):
        authenticate(x_api_key, finalization=True)

    @app.exception_handler(ApiError)
    async def api_error(request, error):
        return JSONResponse(status_code=error.status_code, content=json_safe({"error": error.issue}))

    @app.exception_handler(RequestValidationError)
    async def schema_error(request, error):
        # Pydantic's input/context and arbitrary dictionary keys may contain PII.
        return JSONResponse(status_code=422, content={"error": {"code": "INVALID_REQUEST_SCHEMA",
                            "message": "Request does not satisfy the documented HTTP schema."}})

    @app.exception_handler(Exception)
    async def internal_error(request, error):
        return JSONResponse(status_code=500, content={"error": {"code": "INTERNAL_ERROR",
                            "message": "Request could not be completed."}})

    def diagnostic(result):
        return JSONResponse(status_code=result.http_status, content=json_safe(result.public()))

    @app.get("/health")
    async def health():
        return api.health()

    @app.post("/api/v1/inputs/student/validate", dependencies=[Depends(service_auth)])
    async def validate_student(body: StudentValidationRequest):
        return diagnostic(await run_in_threadpool(api.validate_student, body.model_dump()))

    @app.post("/api/v1/inputs/courses/validate", dependencies=[Depends(service_auth)])
    async def validate_courses(body: CoursesValidationRequest):
        return diagnostic(await run_in_threadpool(api.validate_courses, body.model_dump()))

    @app.post("/recommend", dependencies=[Depends(service_auth)])
    @app.post("/api/v1/recommendations", dependencies=[Depends(service_auth)])
    async def recommend(body: RecommendationRequest):
        result = await run_in_threadpool(api.recommend, body.model_dump())
        return JSONResponse(content=json_safe(result))

    def input_response(state, *, lookup=False):
        headers = {"X-Request-ID": state["request_id"]}
        if state["status"] == "completed" and not lookup:
            return JSONResponse(content=json_safe(state["result"]), headers=headers)
        public = {key: state[key] for key in ("request_id", "status", "received", "missing")}
        if state["status"] == "completed":
            public["result"] = state["result"]
            status_code = 200
        elif state["status"] == "failed":
            public["error"] = state["error"]
            status_code = state["http_status"]
        else:
            status_code = 202
        return JSONResponse(status_code=status_code, content=json_safe(public), headers=headers)

    @app.post("/api/v1/recommendation-inputs/student")
    async def student_input(body: StudentInputRequest, owner: str = Depends(service_auth)):
        state = await run_in_threadpool(api.submit_recommendation_input, "student", body.model_dump(), owner=owner)
        return input_response(state)

    @app.post("/api/v1/recommendation-inputs/courses")
    async def courses_input(body: CoursesInputRequest, owner: str = Depends(service_auth)):
        state = await run_in_threadpool(api.submit_recommendation_input, "courses", body.model_dump(), owner=owner)
        return input_response(state)

    @app.get("/api/v1/recommendation-requests/{request_id}")
    async def recommendation_request(request_id: str, owner: str = Depends(service_auth)):
        state = await run_in_threadpool(api.lookup_recommendation_request, request_id, owner=owner)
        return input_response(state, lookup=True)

    @app.post("/api/v1/history/deltas/validate", dependencies=[Depends(admin_auth)])
    async def validate_delta(body: HistoryDeltaRequest):
        return diagnostic(await run_in_threadpool(api.validate_delta, body.model_dump()))

    @app.get("/api/v1/admin/history/status", dependencies=[Depends(admin_auth)])
    async def history_status():
        return json_safe(await run_in_threadpool(api.history_status))

    @app.put("/api/v1/admin/history/mode", dependencies=[Depends(admin_auth)])
    async def history_mode(body: HistoryModeRequest):
        return json_safe(await run_in_threadpool(api.set_history_mode, body.model_dump()))

    @app.post("/api/v1/admin/history/initialize", dependencies=[Depends(admin_auth)])
    async def initialize_history(body: HistoryInitializeRequest):
        return json_safe(await run_in_threadpool(api.initialize_history, body.model_dump()))

    @app.post("/api/v1/admin/history/preview", dependencies=[Depends(admin_auth)])
    async def preview_history(body: HistoryDeltaRequest):
        return json_safe(await run_in_threadpool(api.preview_history, body.model_dump()))

    @app.post("/api/v1/admin/history/commit", dependencies=[Depends(admin_auth)])
    async def commit_history(body: HistoryCommitRequest):
        return json_safe(await run_in_threadpool(api.commit_history, body.model_dump()))

    @app.post("/api/v1/admin/history/activate", dependencies=[Depends(admin_auth)])
    async def activate_history(body: HistoryActivationRequest):
        return json_safe(await run_in_threadpool(api.activate_history, body.model_dump()))

    @app.post("/api/v1/admin/history/finalization-events", dependencies=[Depends(finalization_auth)])
    async def finalization_event(body: HistoryDeltaRequest):
        return json_safe(await run_in_threadpool(api.finalize_history, body.model_dump()))

    return app
