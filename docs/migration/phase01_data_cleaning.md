# Phase 01 — Data Cleaning Migration

اكتمل نقل الملفات السبعة المطلوبة إلى `Academic_Advisor_Stable` مع الحفاظ على السلوك الأصلي. نجحت **219 حالة اختبار**، دون فشل أو أخطاء أو تجاوز. هذا تحقق لوحدات المرحلة ومساراتها، ولم يُنفذ تنظيف فعلي للبيانات الكاملة.

## الملفات والتغييرات

- نُقلت `cleaning_utils.py` و`clean_degree_course.py` و`clean_student_course.py` و`clean_student_status.py` و`clean_student_diploma.py` و`clean_outliers.py` من `src/data/` في المصدر إلى `src/data/cleaning/` في الوجهة.
- نُقل `academic_calendar.py` إلى `src/data/`.
- أُضيفت إلى `pyproject.toml` اعتماديتا التشغيل `pandas` و`pyarrow` فقط. بقي `pytest` ضمن اعتماديات التطوير. تأتي `numpy` اعتمادًا غير مباشر لـ`pandas`.
- يعتمد `src/paths.py` على `Path(__file__).resolve().parents[1]`، دون أي مسار ثابت خاص بالجهاز. لا ينشئ الاستيراد مجلدات أو يقرأ بيانات.
- لم تُنقل Data Building أو Features أو Modeling، ولم يُنشأ Docker أو `requirements.txt`.

الفرع الموجود فعليًا هو `data_cleaning`، وقد بقي كما هو. لم يُنفذ Commit أو Merge أو تغيير للفرع.

## الحفاظ على السلوك

مصدر النقل هو **نسخة العمل الحالية** في `Academic_Advisor_Simple`، وليس نسخة HEAD وحدها. يتضمن `clean_student_status.py` تعديلًا سابقًا غير ملتزم يستخرج `filter_status_rows_after_enrollment`؛ نُقل كما هو دون إعادة تصميمه. يحفظ [سجل المصدر](phase01_source_manifest.json) رقم المراجعة وبصمات الملفات المستخدمة.

أكد [فحص التطابق](phase01_parity.json) تطابق الملفات السبعة نصيًا بعد حصر الاستثناء في الاستيرادات، وتطابق AST لجميع العبارات الأخرى، بما فيها أجسام دوال التحويل و`main` والثوابت. لم تتغير أسماء الأعمدة أو ترتيبها، الفلاتر، ترتيب حساب المحاولات، معالجة القيم المفقودة، أو قواعد القيم الشاذة.

تستخدم وحدات التنظيف صيغة `from src.paths import NAME as NAME_V2` عند الحاجة. هذه **أسماء محلية توافقية** تُبقي أجسام `main` وأسماء `monkeypatch` في الاختبارات الأصلية دون تغيير. لا توجد ثوابت مسارات V1/V2 في `src/paths.py`، ولا ملفات مخرجات متوازية؛ لكل منتج مسار واحد بلا لاحقة إصدار.

## المسارات المعتمدة

| الثابت | المسار من جذر المشروع |
|---|---|
| `STUDENT_COURSE_PATH` | `data/raw/v_crg_student_course_raw.parquet` |
| `STUDENT_STATUS_PATH` | `data/raw/v_add_student_degree_status.parquet` |
| `DEGREE_COURSE_PATH` | `data/raw/v_acd_degree_course.parquet` |
| `ACADEMIC_INFO_PATH` | `data/raw/v_add_academic_info.parquet` |
| `PRE_COMMON_STUDENT_COURSE_PATH` | `data/clean/student_course_pre_common.parquet` |
| `PRE_COMMON_STUDENT_STATUS_PATH` | `data/clean/student_status_pre_common.parquet` |
| `CLEAN_DEGREE_COURSE_PATH` | `data/clean/degree_course.parquet` |
| `CLEAN_STUDENT_DIPLOMA_PATH` | `data/clean/student_diploma.parquet` |
| `STUDENT_COURSE_ENRICHED_PATH` | `data/clean/student_course_enriched.parquet` |
| `STUDENT_COURSE_DIPLOMA_PATH` | `data/merged/student_course_enriched_with_diploma.parquet` |
| `STUDENT_COURSE_WITHOUT_OUTLIERS_PATH` | `data/merged/student_course_enriched_without_outliers.parquet` |
| `OUTLIER_STUDENTS_AUDIT_PATH` | `data/merged/outlier_students.parquet` |

يحافظ `pre_common` على معنى المنتج الأصلي: إنه ناتج التنظيف المستقل قبل تقاطع الطلاب، وليس الجدول المدمج أو المنتج النهائي للبناء.

## حدود التشغيل واعتماد Data Building

ملفات الإدخال الخام الأربعة المطلوبة موجودة حاليًا في `data/raw/` بالوجهة. تأكد وجودها من أسماء الملفات وأحجامها فقط؛ لم تُقرأ سجلاتها ولم يُشغّل تنظيف فعلي عليها. لم تنسخ هذه المهمة بيانات فعلية أو نتائج قديمة، ولم تُستخدم مسارات احتياطية إلى المستودع القديم.

تعتمد `clean_student_diploma.main()` على `data/clean/student_course_enriched.parquet`. ينتجه في المصدر `src/data/build_student_course_enriched.py` بعد `filter_common_students.py`. كلا الملفين خارج نطاق هذه المرحلة ولم يُنقلا.

تبقى `clean_student_diploma()` و`merge_student_course_with_diploma()` قابلتين للاستخدام والاختبار مستقلتين. يحافظ `main()` على ترتيب الأصل: يكتب جدول الدبلوم النظيف أولًا، ثم يقرأ الملف المثرى. لذلك قد يكتب `student_diploma.parquet` ثم يفشل إذا كانت البيانات الأكاديمية موجودة والملف المثرى مفقودًا؛ لم يتغير هذا السلوك.

تعتمد `clean_outliers.main()` على الملف الناتج عن دمج الدبلوم، ولذلك يتوقف تشغيله الكامل أيضًا على المنتج السابق. لم تُنقل مرحلة البناء لتجاوز هذا الاعتماد.

## الاختبارات القديمة

نُقلت الملفات السبعة التالية إلى `tests/unit/`. اقتصر التعديل على مسار استيراد الوحدة وتصحيح عمق جذر المشروع في `sys.path` بسبب الانتقال إلى `tests/unit/`. بقيت أجسام الاختبارات وfixtures وdecorators والتوقعات وأسماء monkeypatch حرفيًا كما هي.

| ملف الاختبارات | الحالات الناجحة |
|---|---:|
| `test_academic_calendar.py` | 18 |
| `test_clean_degree_course.py` | 6 |
| `test_clean_outliers.py` | 65 |
| `test_clean_student_course.py` | 61 |
| `test_clean_student_diploma.py` | 8 |
| `test_clean_student_status.py` | 37 |
| `test_clean_utils.py` | 24 |

المجموع: **219 ناجحًا، 0 فشل، 0 أخطاء، 0 تجاوز**. هذه الاختبارات هي كامل المجموعة الحالية في المستودع الجديد؛ مجلدا integration وe2e لا يحتويان اختبارات بعد. أُجري تشغيل واحد للمجموعة الكاملة، وهو يغطي اختبارات المرحلة المركزة كلها. لم تُنشأ بدائل للاختبارات الأصلية.

عثر البحث أيضًا على ملفات مختلطة تُركت في المصدر لأنها تختبر مكونات غير منقولة:

| الملف | الاعتماد خارج المرحلة |
|---|---|
| `tests/test_main_runner.py` | مشغّل المشروع ومراحل Features/Modeling/Evaluation/Experiments |
| `tests/test_v2_pipeline.py` | مسار البناء والسمات الكامل |
| `tests/test_t0_enrollment_parity.py` | Features وPilot وأدوات مطابقة التسجيل |
| `tests/test_historical_api_temporal_audit.py` | أداة تدقيق API التاريخية |

لم تُحذف هذه الاختبارات أو تُعدّل أو توضع عليها علامة skip/xfail. لا تمثل نتيجة 219 اختبارًا نتيجة المجموعة الكاملة للمشروع القديم.

## البيئة والأوامر

تم إنشاء `.venv` مستقلة داخل الوجهة وتثبيت المشروع نفسه بوضع editable من `pyproject.toml`. البيئة المختبرة: Python 3.11.5, pandas 3.0.5, pyarrow 25.0.1, numpy 2.4.6, pytest 9.1.1. لم تُختبر إصدارات Python الأخرى المسموح بها في metadata خلال هذه المرحلة.

لم تتوفر pandas في ذاكرة uv المؤقتة، لذا تعذر التثبيت الأول دون اتصال، ثم نجح التنزيل والتثبيت بهذه النسخ المطابقة لاعتماديات التنظيف والاختبار في بيئة المصدر:

```powershell
uv pip install --python .venv/Scripts/python.exe -e ".[dev]" pandas==3.0.5 pyarrow==25.0.1 pytest==9.1.1
```

هذه نسخ بيئة التحقق؛ أُبقي تصريح اعتماديات pandas وpyarrow في `pyproject.toml` دون قيود إصدار مثل المصدر.

أوامر التحقق المنفذة من جذر الوجهة:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q --tb=short --junitxml=docs/migration/phase01_tests.xml
uv pip check --python .venv/Scripts/python.exe
git diff --check
```

لإعادة الإعداد على جهاز آخر باستخدام Python المثبت:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

جرى أيضًا نسخ `src` إلى مجلد مؤقت مختلف وتشغيل الاستيرادات من مجلد عمل مستقل: نجحت الوحدات السبع، وبقيت جميع المسارات تحت جذر النسخة المنقولة. أكدت المراجعة وجود 12 مسار منتج/إدخال مميزًا دون تكرار. نجح فحص توافق الاعتماديات.

## أدلة التحقق

- [نتيجة الاختبارات](phase01_tests.txt) و[JUnit XML](phase01_tests.xml).
- [تطابق المصدر والاختبارات](phase01_parity.json).
- [البيئة والمسارات وفحص النقل](phase01_environment.json).
- [بصمات ملفات المصدر قبل العمل](phase01_source_manifest.json).
- [نتيجة التحقق النهائية](phase01_verification.json).

أُعيد التحقق من بصمات 16 ملفًا في المصدر ومن بصمة حالته في Git: لم تتغير. نجح `git diff --check`. تقتصر الجاهزية المثبتة هنا على نقل وحدات التنظيف واختباراتها؛ ملفات الخام متوفرة، ويبقى تشغيل المسار الكامل متوقفًا على منتج مرحلة البناء المشار إليه؛ لم تُنفذ هذه المهمة تشغيلًا فعليًا للبيانات.

أكدت مراجعة مستقلة للقراءة فقط سلامة النقل وحدود المرحلة، ولم تجد مشكلات برمجية حرجة أو مهمة. صُحح وصف توفر ملفات الخام في هذا التقرير بعد مقارنة البيئة المحفوظة بجرد أسماء الملفات وأحجامها.
