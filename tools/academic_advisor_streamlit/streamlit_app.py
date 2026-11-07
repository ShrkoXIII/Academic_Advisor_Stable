"""Focused local recommendation and observed-plan evaluation UI."""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st

from src import paths
from src.api.adapters.history import adapt_history_delta
from src.api.schemas import HistoryDeltaRequest, RecommendationRequest
from src.api.service import ApiService
from src.api.catalog import load_catalog
from src.evaluation.observed_plan import attach_actual_outcomes, predict_observed_plan
from src.features.frozen_history import file_sha256
from src.recommendation.two_stage_engine import TwoStagePlanRecommender
from tools.academic_advisor_streamlit.ui_client import (
    ClientError, Config, HttpClient, load_context, parse_json, student_degree_id,
)
from tools.academic_advisor_streamlit.views import (
    canonical_identity, combine_request, comparison_rows, local_actual_outcomes, registered_courses,
)


@st.cache_resource
def local_engine(manifest_hash):
    return TwoStagePlanRecommender.load()


def read_json(upload, text=""):
    if upload is not None:
        return parse_json(upload.getvalue().decode("utf-8-sig"))
    return parse_json(text) if text.strip() else None


def verify_remote_history(history, cutoff):
    if int(history.get("part_id", -1)) != int(cutoff):
        raise ValueError("History API returned a different cutoff.")
    request = HistoryDeltaRequest.model_validate(history).model_dump()
    validation = adapt_history_delta(request)
    if validation.errors:
        raise ValueError("History API aggregates do not match the existing model contract.")


def main():
    st.set_page_config(page_title="Academic Advisor Stable", layout="wide")
    st.title("Academic Advisor — Stable")
    st.caption("توصية بمرحلتين وتقييم الخطة الفعلية، باستخدام أصول أُعيد بناؤها داخل Stable.")
    try:
        config = Config.from_env()
        client = HttpClient(config)
    except (ClientError, ValueError) as error:
        st.error(str(error))
        return
    mode = st.sidebar.radio("مصدر المدخلات", ["JSON محلي", "واجهات الجامعة"])
    st.sidebar.caption("التاريخ المستخدم في التنبؤ هو حزمة Stable المثبتة عند الفصل المحدد.")
    if st.sidebar.button("فحص جاهزية الخدمة", key="health"):
        try:
            code, health = client.health()
            if code == 200 and health.get("recommendation_readiness", {}).get("ready"):
                st.sidebar.success("النماذج والتاريخ والكتالوج جاهزة")
            else:
                st.sidebar.warning("الخدمة أو أصول التوصية غير جاهزة")
        except ClientError as error:
            st.sidebar.error(str(error))
    request_upload = request_text = None
    if mode == "JSON محلي":
        st.write("حمّل طلبًا مطابقًا لعقد FastAPI، أو الصقه. يتضمن الطالب والفصل وردود Student وCourses والسياق الموثق.")
        request_upload = st.file_uploader("طلب التوصية JSON", type=["json"])
        request_text = st.text_area("أو الصق طلب JSON", height=170)
    else:
        student_id = st.text_input("معرف الطالب")
        degree_id = st.text_input("معرف الدرجة — اختياري إذا أعاده Student API")
        part_id = st.number_input("الفصل المستهدف", value=20251, step=1)
        cutoff = st.number_input("التاريخ حتى الفصل", value=20243, step=1)
        credits = st.number_input("الساعات المطلوبة بالضبط", value=18.0, min_value=0.5, step=0.5)
        st.info("يُجلب رد Frozen History للتحقق من عقده؛ نشر تحديثاته وتفعيلها يتمان عبر إدارة التاريخ، دون استيراد تلقائي أثناء التوصية.")
    with st.expander("الخطة الفعلية والنتائج — اختياري"):
        registration_upload = st.file_uploader("تسجيل فعلي موثق JSON — عند عدم توفره في بناء Stable", type=["json"])
        outcomes_upload = st.file_uploader("نتائج نهائية موثقة JSON — للتقييم فقط", type=["json"])
        st.caption("عند غياب الملفين، تُقرأ سجلات الطالب المطابقة من مخرجات Stable الجديدة إن توفرت.")
    if st.button("إنتاج التوصية والتقييم", type="primary", key="run_evaluation"):
        st.session_state.pop("evaluation", None)
        try:
            if mode == "JSON محلي":
                request = read_json(request_upload, request_text or "")
                if request is None:
                    raise ValueError("أدخل طلب JSON أولًا.")
            else:
                student = client.student(student_id, int(part_id))
                selected_degree = degree_id.strip() or student_degree_id(student, student_id, int(part_id))
                courses = client.courses(student_id, selected_degree, int(part_id))
                history = client.frozen_history(int(cutoff))
                verify_remote_history(history, int(cutoff))
                student_context, courses_context = load_context(config)
                request = combine_request(student_id, selected_degree, int(part_id), int(cutoff),
                    str(credits), student, courses, student_context, courses_context)
            RecommendationRequest.model_validate(request)
            request["top_k"] = 3
            code, result, _ = client.advisor("POST", "/api/v1/recommendations", data=request)
            if code != 200:
                st.error("تعذر إنتاج التوصية؛ راجع نقص المدخلات أو التوافق أو جاهزية الأصول.")
                st.json(result)
            else:
                state = {"request": request, "result": result, "registration": None, "actual": None}
                try:
                    state.update(registration=read_json(registration_upload), actual=read_json(outcomes_upload))
                except (ClientError, ValueError, OSError) as error:
                    state["evaluation_error"] = str(error)
                st.session_state["evaluation"] = state
        except (ClientError, ValueError, OSError, KeyError, TypeError) as error:
            st.error(str(error))
    state = st.session_state.get("evaluation")
    if state is None:
        st.info("ابدأ بطلب JSON محلي أو حدّد الطالب والفصل من واجهات الجامعة.")
        return
    request, result = state["request"], state["result"]
    info = request["student_api_response"]["data"]["studentDegreeInfo"]
    st.subheader("معلومات الطالب")
    st.write({"الطالب": request["student_id"], "الدرجة": request["degree_id"], "الفصل": request["part_id"]})
    st.metric("المعدل التراكمي قبل الفصل", str(info.get("START_AGPA_POINTS", "غير متاح")))
    st.caption("كل معدل تراكمي متوقع إسقاط إضافي، دون تطبيق استبدال المحاولات الرسمي.")
    observed = None
    st.subheader("الخطة الفعلية")
    try:
        if state.get("evaluation_error"):
            raise ValueError(state["evaluation_error"])
        engine = local_engine(file_sha256(paths.TWO_STAGE_MANIFEST_PATH))
        api = ApiService(engine=engine, catalog=load_catalog(),
                         grade_scale=engine.artifacts.grade_scale)
        validated = api.validate_student(request)
        if validated.errors or validated.normalized is None:
            raise ValueError("لقطة الطالب غير مكتملة لتنبؤ الخطة الفعلية.")
        identity = canonical_identity(validated.normalized)
        courses = registered_courses(identity, state["registration"])
        if courses:
            observed = predict_observed_plan(engine, validated.normalized, courses,
                                            history_as_of_part=request["history_as_of_part"])
            actual = state["actual"] if state["actual"] is not None else local_actual_outcomes(identity)
            if actual is not None:
                try:
                    observed = attach_actual_outcomes(observed, actual)
                except (ValueError, TypeError, KeyError) as error:
                    st.warning("النتائج الفعلية غير مقبولة؛ يبقى التنبؤ مستقلًا عنها: " + str(error))
            else:
                st.info("النتائج الفعلية المعتمدة غير متاحة؛ تُعرض التنبؤات فقط.")
            st.dataframe(observed["courses"], hide_index=True, width="stretch")
            if observed.get("mark_mae") is not None:
                st.metric("متوسط خطأ العلامة المطلق", f"{observed['mark_mae']:.3f}")
            st.caption("تنبؤ وصفي للخطة المسجلة. النقاط المتوقعة محولة من العلامة عبر سلم الدرجات.")
        else:
            st.info("الخطة الفعلية غير متاحة في مدخلات هذه الحالة أو بيانات Stable.")
    except (ValueError, OSError, KeyError, TypeError) as error:
        st.warning("تعذر استكمال تقييم الخطة الفعلية: " + str(error))
    st.subheader("أفضل ثلاث خطط")
    plans = result.get("recommendations", [])
    if not plans:
        st.info("لا توجد خطة صالحة تحقق القيود والساعات المطلوبة بالضبط.")
    for plan in plans:
        st.markdown(f"**الخطة {plan['rank']} — {plan['total_credits']:g} ساعات**")
        left, right = st.columns(2)
        left.metric("المعدل الفصلي المتوقع", f"{plan['expected_plan_gpa']:.3f}")
        right.metric("التراكمي المتوقع — إضافي", f"{plan['projected_cumulative_gpa']:.3f}")
        st.dataframe(pd.DataFrame(plan["courses"]), hide_index=True, width="stretch")
    st.caption("الترتيب هو ترتيب النظام ضمن مساره ذي المرحلتين؛ لا يضمن أفضل ثلاث خطط عالميًا.")
    st.subheader("المقارنة")
    st.dataframe(pd.DataFrame(comparison_rows(result, observed)), hide_index=True, width="stretch")
    st.caption("لا توجد نتائج فعلية للخطط البديلة غير المنفذة. القيم غير المتاحة تبقى فارغة.")


if __name__ == "__main__":
    main()
