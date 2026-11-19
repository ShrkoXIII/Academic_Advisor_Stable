# Changelog

سجل موحد لتغييرات المشروع؛ لكل تعديل عنوان وتاريخ وأربعة أسطر موجزة كحد أقصى. تُضاف البنود الجديدة في نهاية الملف دون تعديل البنود السابقة.
البنود التاريخية أدناه تلخص الأدلة الموجودة ونتائج التشغيل السابقة؛ لم تُعد الاختبارات أو خطوط البيانات أثناء توحيد التوثيق.

## 2026-11-03 — Phase 01 — Data Cleaning Migration

- التغيير: نقل سبع وحدات للتنظيف والتقويم واختباراتها إلى المشروع الجديد، واعتماد مسارات موحدة قابلة للنقل.
- السبب: تأسيس مرحلة تنظيف مستقلة مع الحفاظ على السلوك؛ بقي اعتماد الدبلوم على ناتج Data Building خارج نطاق النقل.
- التحقق السابق: 219 اختبارًا ناجحًا دون فشل أو تجاوز؛ لم يُشغّل تنظيف البيانات الكاملة ضمن مهمة النقل.
- الملفات: `src/data/cleaning/`، `src/data/academic_calendar.py`، `src/paths.py`، `tests/unit/`، `pyproject.toml`.

## 2026-11-03 — Academic Calendar Tests

- التغيير: إضافة أربع حالات لحدود الفصل الصيفي وترتيب الفصول العكسي، ليصبح مجموع حالات التقويم 22.
- السبب: تثبيت استبعاد الصيفي من الانقطاع ورفض التسلسل الزمني العكسي، دون تغيير كود التقويم.
- التحقق السابق: شملها تشغيل 2026-11-04 الموثق؛ نجحت اختبارات المرحلة الـ249 دون فشل أو تجاوز.
- الملفات: `tests/unit/test_academic_calendar.py`؛ بقي `src/data/academic_calendar.py` دون تعديل.

## 2026-11-04 — Degree-Scoped Enrollment History Correction

- التغيير: فصل تاريخ المعدل والتسجيل بالمفتاح `(student_id, degree_id)` مع ترتيب زمني حاسم واستمرار التاريخ عند العودة للدرجة.
- السبب: منع انتقال المعدل والانقطاع بين الدرجات، مع إبقاء الفلاتر وسياسة `prev_gpa_points` وinitial fallback.
- التحقق السابق: أثبتت 7 حالات فشل الخلل أولًا؛ بعد الإصلاح نجح 63 اختبارًا للملف و249 للمرحلة، دون فشل أو تجاوز.
- الملفات: `src/data/cleaning/clean_student_status.py`، `tests/unit/test_clean_student_status.py`؛ لم يحتج `src/paths.py` إلى تعديل.

## 2026-11-04 — Student Status Data Rebuild

- التغيير: إعادة بناء `student_status_pre_common.parquet` ونشره بعد التحقق؛ الناتج 108,974 صفًا و36 عمودًا، دون تكرارات.
- السبب: تطبيق استقلال تاريخ الدرجة على بيانات Student Status وتجهيز المدخل المنظف للمرحلة التالية.
- التحقق السابق: تغيرت الميزتان التاريخيتان في 542 صفًا تخص 492 طالبًا؛ تطابقت الأعمدة الأخرى الـ34 ولم يُرصد تسرب مستقبلي.
- الملفات: `data/raw/v_add_student_degree_status.parquet` (قراءة فقط)، `data/clean/student_status_pre_common.parquet` (الناتج).

## 2026-11-04 — Unified Change Documentation

- التغيير: إنشاء هذا السجل وإضافة Change Documentation Policy إلى تعليمات الجذر، مع مراجعة تقارير الترحيل الحالية.
- السبب: توحيد توثيق التعديلات في بنود قصيرة ومنع تقارير المهام المنفصلة إلا بطلب صريح أو حاجة تحقق محددة.
- التحقق: مراجعة تنسيق البنود وحفظ التعليمات السابقة ونطاق الملفات؛ لم تُعد اختبارات المشروع أو خطوط البيانات ولم تُحذف تقارير.
- الملفات: `docs/CHANGELOG.md`، `Agents.md` (ملف تعليمات الجذر الموجود).

## 2026-11-04 — Canonical Data Cleaning Path Names
- إزالة أسماء المسارات المحلية القديمة من وحدات التنظيف الخمس واعتماد ثوابت `src/paths.py` مباشرة، دون تغيير المسارات أو منطق التنظيف.
- تحديث `monkeypatch` في ملفات الاختبارات الخمسة المقابلة ووصف `src/paths.py`؛ لم يحتج التقويم إلى تعديل ولم تُعد بناء البيانات.
- التحقق: نجح 203 اختبارات مركزة ثم جميع اختبارات `tests/unit` وعددها 249؛ أزيلت أسماء المسارات القديمة من نطاق التنظيف والتقويم والاختبارات.

## 2026-11-05 — Data Building Migration and Raw Rebuild
- نقل وحدات common-student/enrichment/temporal split/registration roster واختباراتها إلى `src/data/building/` و`tests/unit/` دون تغيير المنطق؛ تطابقت AST بعد تطبيع الاستيرادات والمسارات.
- إضافة المسارات اللازمة في `src/paths.py` وتوسيع اختبار قابلية النقل؛ أضيفت اعتماديات المراحل اللاحقة إلى `pyproject.toml`.
- التحقق: 16 اختبار نقل ثم 266 اختبار وحدة ناجحًا؛ أعيد بناء البيانات من خام Stable مع ثبات SHA256 للخام، ونتج 356882 صف تدريب و67548 صف اختبار.
- بقيت سياسة الدبلوم/null والفلاتر ونطاق المحاولات وحدود التقسيم كما هي؛ لم يُكتب أو يُشغّل شيء داخل Legacy.

## 2026-11-05 — Temporal Features Migration and Rebuild
- نقل `feature_contract.py` و`temporal_features.py` و`build_temporal_features.py` إلى `src/features/`، مع اعتمادياتها واختباراتها؛ اقتصر التغيير على المسارات والاستيرادات.
- التحقق: 83 اختبارًا مركزًا ثم 286 اختبار وحدة ناجحًا؛ تطابقت AST للوحدات الثلاث بعد تكييف المسارات، دون تغيير الحسابات أو سياسة القيم المفقودة.
- بُنيت ميزات 356882 صف تدريب و67548 صف اختبار داخل Stable، بواقع 95 عمودًا تشمل الميزات الـ47؛ انتهت حالة تاريخ التدريب عند 20243.
- بقي نطاق GPA التاريخي في كود الميزات كما في المصدر دون تطبيق تصحيح مقترح؛ الملفات: `src/features/`، `src/modeling/training_config.py`، `src/paths.py` واختباراتها.

## 2026-11-05 — Frozen History Build from Stable Outcomes
- نقل `src/features/frozen_history.py` و`build_frozen_history.py` واختبارات الحزم الأساسية؛ إضافة مساعدات المسارات إلى `src/paths.py` دون تغيير التجميع أو القطع الزمني.
- جرى تكييف أسماء المسارات وتسجيل مصادر البناء بمسارات نسبية وبصمات، مع إبقاء فحوص الإصدار والسلامة وعدم الاستبدال.
- التحقق: 17 اختبار تاريخ ثم 303 اختبارات وحدة ناجحة ونجاح `pip check`؛ بُنيت وأعيد تحميل نسختي 20243 و20251 من 356882 و391296 صف نتيجة جديد داخل Stable.
- لم تُنسخ بيانات أو حزم تاريخ أو نماذج Legacy؛ ثبتت اعتماديات المراحل التالية في بيئة Stable فقط.

## 2026-11-05 — Fresh Primary and Shortlist Model Training
- نقل `train_models.py` واستخراج trainer ومصفوفة shortlist إلى `src/modeling/` مع بقاء الأهداف والأوزان والمرشحين والتحقق الزمني كما هي؛ تحقق تطابق AST لدوال التدريب.
- أُعيد تدريب النماذج الأربعة من ميزات Stable؛ اختير regularized_47 للعلامة وbalanced_31 للرسوب في زوج 47، دون فرض اختيارات التدريب القديم.
- التحقق: 19 اختبار تدريب ثم 324 اختبار وحدة ناجحًا؛ حُمّلت الأصول الأربعة وتحققت الميزات والفئات والتواقيع الجديدة؛ MAE الاختبار 9.72786 لزوج 47 و9.74439 لزوج 33.
- الملفات: `src/modeling/`، `src/main.py`، `src/paths.py`، اختبارات التدريب والـrunner، `requirements.lock`؛ بصمات البناء الجديدة في `data/artifacts/build_manifest.json` دون قراءة أصول Legacy.

## 2026-11-05 — Two-Stage Recommendation and Fresh Manifest
- نقل وحدات TwoStage والقيود والحساب والترتيب وHistoryManager وGradeScale؛ بقيت العمليات الحسابية وسياسة Pareto/Balance كما هي، مع تكييف الاستيرادات والمسارات فقط.
- كُيّف التحقق ليربط المرشح الفائز بتقرير التحقق الزمني الجديد؛ أُنشئ manifest من الأصول الجديدة مع مرجع تفويض المستخدم بالحفاظ على السياسة، دون نسخ أدلة أو تواقيع تدريب قديمة.
- التحقق: 811 اختبارًا ناجحًا؛ حمّل المحرك النماذج والتاريخ الجديدين وأنتج 3 خطط من 70 خطة اصطناعية صالحة، عبر shortlist من 50؛ استُبعدت أربع مقارنات تخص المحرك الأحادي/التقارير القديمة من نطاق النقل.
- الملفات: `src/recommendation/`، `src/grade_scale.py`، `src/modeling/build_artifact_manifest.py`، `src/paths.py`، `docs/api_contract.md` واختباراتها؛ جودة البدائل الأكاديمية وحدود التشغيل ليست اعتمادًا جديدًا ضمن هذا النقل.

## 2026-11-05 — FastAPI and Durable Input State
- نقل `src/api/` اللازم وعقود التحقق وSQLite و`cumulative_history.py` مع الحفاظ على السلوك؛ بقي خط الأساس الإداري 20251 كما في المصدر ومتوافقًا مع التاريخ المعاد بناؤه.
- تكييف مسارات إعدادات البيئة النسبية إلى جذر Stable، وتحديث `.env.example` و`.gitignore`؛ أضيفت اختبارات HTTP ببيانات اصطناعية مولدة من مثال العقد، دون نسخ استجابات طلاب أو fixtures قديمة.
- التحقق: 903 اختبارات ناجحة، اختبار POSIX متجاوز على Windows وتحذير deprecation في TestClient؛ نجحت الصحة الفعلية وتوصية ثلاث خطط اصطناعية بالأصول الجديدة.
- نُفذت اختبارات HTTP خارج العزل بعد إثبات تعليق إنشاء asyncio داخله؛ لم يُغير كود الخدمة لتعويض قيد البيئة، ولم يحدث اتصال بواجهات الجامعة.

## 2026-11-05 — Fresh Observed-Plan Evaluation
- نقل `src/evaluation/evaluate_plan_gpa.py` مع مساراته واختباراته، ومنع طباعة معرفات الطلاب فقط؛ بقيت صيغ العلامات والنقاط وGPA كما هي.
- إضافة `observed_plan.py` كموصل لحسابات Stage 2 الحالية على الخطة الفعلية، مع ربط النتائج النهائية في واجهة لاحقة منفصلة والتحقق من الهوية والساعات والمصدر.
- التحقق: 13 اختبارًا مركزًا ناجحًا؛ قُيّمت 67548 مادة ضمن 12715 خطة من مخرجات Stable الجديدة؛ MAE=0.4563 وRMSE=0.6431، والمقارنة وصفية للمواد المقيمة.
- الملفات: `src/evaluation/`، `src/paths.py` واختبارات التقييم؛ لم يُنقل تحليل يعيد التدريب خفية، ولا استُخدمت نتائج Legacy أو معدلات بديلة مختلقة.

## 2026-11-05 — Focused Streamlit Evaluation UI
- إعادة استخدام عميل HTTP في `tools/academic_advisor_streamlit/ui_client.py` وإنشاء `streamlit_app.py` و`views.py` لمسار TwoStage واحد، مع JSON محلي وواجهات الجامعة والخطة الفعلية والمقارنة.
- فصل النتائج النهائية عن التنبؤ؛ عولجت ملاحظات المراجعة باختبارات فشل ثم نجاح: حفظ جميع مواد الخطة الفعلية، توحيد الهوية، ورفض القيم العددية المشوهة/المنطقية دون تعطيل Top3؛ لم يتغير منطق Legacy.
- التحقق: 42 اختبارًا مركزًا ثم 24 اختبار تكامل/انحدار ناجحًا، تشمل عرض ثلاث خطط ومسح الحالة القديمة؛ تعمل الخدمتان محليًا. لم يتوفر متصفح IAB للفحص البصري المباشر.
- الملفات التقنية: `.env` محلي مهمل بأسرار مولدة دون عرضها أو نسخها، `pyproject.toml` (Python 3.11 وحزمة tools)، `README.md`، `src/main.py` واختبارات الواجهة؛ التاريخ المبني محليًا هو المستخدم، وتحديث API التاريخ يحتاج نشرًا وتفعيلًا صريحين.

## 2026-11-05 — Standalone Verification and Private Local Configuration
- إضافة `tools/verify_standalone.py` واختباري staging/timeout لإعادة البناء من الكود والخام داخل بيئة جديدة، مع إيقاف شجرة العمليات المملوكة قبل التنظيف؛ تدقيق الوصول يغطي أحداث Python فقط.
- تصحيح وصف الإعدادات السابق: `.env` متتبع أصلًا وأعيد إلى بايتاته السابقة؛ الإعدادات والمفاتيح المولدة في `.env.local` المهمل، ويختاره عميل الواجهة افتراضيًا؛ تحديث `.env.example` و`README.md`.
- توثيق قائمة ملفات النقل وأسبابها في README؛ نجح اختبارا الاستقلال و18 اختبار عميل، واعتمدت المراجعة إصلاحات التحقق والمدخلات دون تغيير السياسات والحسابات.
- الملفات: أداة التحقق واختباراتها و`ui_client.py` و`test_ui_client.py` وREADME والإعدادات المذكورة؛ إعادة البناء المستقلة الكاملة قيد التحقق.

## 2026-11-05 — Complete Independent Rebuild Verified
- نجح `tools/verify_standalone.py`: بيئة جديدة من الكود والخام فقط، ثم البيانات والميزات والتاريخ والنماذج الأربعة والنشر والتقييم وجاهزية API والعمل من دليل مختلف؛ نظفت البيئة المؤقتة بنجاح.
- التحقق: 951 اختبارًا ناجحًا في Stable و951 في النسخة المستقلة، مع تجاوز POSIX واحد وتحذير TestClient واحد؛ تطابقت AST لـ38 وحدة، وثبتت بصمات الخام والتنظيف وخلت ملفات JSON التسعة للأصول من مسارات جهاز مطلقة.
- نواتج Stable: 356882 صف تدريب و67548 اختبار وحزمتا تاريخ و4 نماذج جديدة؛ لم تتغير السياسات والحسابات، ولم تنسخ مخرجات Legacy أو تظهر محاولة وصول Python مدققة إليه أثناء البناء المستقل.
- تحديث `README.md` و`docs/CHANGELOG.md` بنتيجة PASS WITH WARNINGS؛ الاتصال الفعلي بالجامعة والفحص البصري عبر IAB غير متحققين، بينما نجحت اختبارات HTTP وStreamlit AppTest؛ لا commit أو merge.

## 2026-11-07 — Canonical Pipeline Labels and History Source Paths
- Removed runner dataset labels and mixed dataset handling; custom history no longer requires a specially suffixed filename. Preserved CLI order, serialized contracts, cutoffs, and academic/null/diploma behavior.
- Clarified canonical paths, branches, and staging labels in `src/{main,paths}.py`, `src/data/building/filter_common_students.py`, `src/features/{build_frozen_history,frozen_history}.py`, `src/modeling/build_artifact_manifest.py`, `src/recommendation/two_stage_artifacts.py`, and `README.md`.
- Updated `tests/unit/test_{main_runner,frozen_history,filter_common_students}.py`: 28 focused and 837 relevant unit tests passed; 67 source imports/compilation, 49 unique paths, dependency connections, and CLI checks passed without executing pipeline stages or training.
- Preserved data/models/manifests and all 11 shortlist input/source hashes; the build manifest retains historical source fingerprints for five edited files. No datasets, history, models, or evaluation artifacts were rebuilt, overwritten, published, or deleted.

## 2026-11-11 — Remove Average-Attempt Features
- Removed `plan_course_type_id` and all average-attempt model signals; contracts now expose 31 Stage 1 and 43 Stage 2 features.
- Removed `attempt_sum` from frozen history and finalized delta rows; retained `attempt_number`, retake-rate features, and `retake_sum`; updated `src/features/`, `src/modeling/`, `src/recommendation/`, and `src/api/`.
- Updated cumulative baseline provenance to distinguish source and newly serialized history hashes; documented the new model contract in `docs/api_contract.md`.
- Validation: 193 focused tests passed; full unit collection is blocked by missing `pydantic`. Models were not retrained and data/history artifacts were not rebuilt.

## 2026-11-12 — توحيد عقد الميزات والتاريخ
- أزيلت أرقام عقد الميزات والتاريخ من الكود والـmetadata المحفوظة؛ نُظفت خصائص Parquet وحزم Frozen History دون إعادة تدريب أو تغيير صفوفها.
- السبب: تثبيت مسار واحد نهائي للتاريخ والتدريب دون تسميات عقد رقمية.
- التحقق: لم تُشغّل الاختبارات أو مراحل البيانات ضمن هذا التعديل.
- الملفات: `src/features/`، `src/modeling/`، `src/recommendation/`، `src/api/service.py`، `src/evaluation/`، `models/`، `data/features/`، `data/artifacts/`، `tests/unit/`، `README.md`.

## 2026-11-14 — حذف نماذج بعقود ميزات قديمة
- حُذفت أوزان 33/47 ميزة وmetadata والـmanifests والفئات المرتبطة بها؛ لم يُجر تدريب جديد.
- السبب: منع استخدام أصول لا تطابق العقد الحالي 31/43.
- التحقق: تأكدت إزالة الملفات المحددة؛ لم تُشغّل اختبارات أو تدريب.
- الملفات: `models/grade_regressor.txt`، `models/fail_risk_classifier.txt`، `models/model_metadata.json`، `models/shortlist/`، `models/shortlist_training/`، `data/artifacts/build_manifest.json`، `data/artifacts/category_levels.json`.

## 2026-11-14 — تنظيف نتائج تدريب النماذج القديمة
- حُذفت تقارير تحقق ونتائج holdout ومقارنة مرتبطة بنماذج shortlist القديمة.
- السبب: ترك مخارج التدريب الحالية فارغة قبل تدريب العقود الجديدة لاحقًا.
- التحقق: مجلد `data/evaluation/shortlist/` لم يعد موجودًا؛ لم يُشغّل تدريب أو اختبار.
- الملفات: `data/evaluation/shortlist/`.

## 2026-11-17 — Backend-Driven Recommendation Inputs
- Removed the local-file recommendation adapter from `src/recommendation/inputs.py`; moved registered-course normalization to `src/evaluation/local_course_inputs.py` for observed-plan evaluation.
- Removed the stale CLI branch and documented the Backend→API→two-stage path and local runtime dependencies in README/docs; clarified request-store use and Streamlit evaluation wording; added regression tests.
- Validation: payload/UI 69 passed; request-store 48 passed/1 skipped; API adapter/settings 2 passed; CLI rejection 1 passed; constraint/shortlist/ranking 111 passed/5 fixture failures; observed-plan 16 fixture failures; runner 2 passed/1 existing assertion failure.
- Full suite collected 963 tests but could not finish: API fixtures hit the pre-existing feature-contract mismatch, then Windows AppTest blocked creating `asyncio.socketpair` in the sandbox. No live University Backend integration was available.

## 2026-11-17 — Recommendation Stabilization Verification
- Restored the canonical feature name, aligned the dry-run assertion with the CLI, and corrected manifest validation while preserving production approval checks.
- Backend payload, two-stage engine, API, and Streamlit tests passed with synthetic fixtures. Full suite finished with 956 passed, 5 failed, and 2 skipped.
- Production remains blocked by missing approved models, incompatible history bundles, and unverified University Backend payloads.
- See `docs/reports/STABILIZATION_VERIFICATION_REPORT.md` for changes, test details, and release requirements.

## 2026-11-18 — Safe API and recommendation consolidation
- Removed the duplicate candidate count and protected root and the unused startup import.
- Shared course-group and request ID definitions across their consumers to prevent drift.
- Added parity coverage in `tests/unit/test_two_stage_payloads.py`. The full suite had 970 passes, 2 known failures and 2 skips.
- The [Phase 3 report](reports/API_RECOMMENDATION_PHASE_3_REPORT.md) lists the affected files and before-and-after checks.

## 2026-11-18 — Consolidate registration policy calculations
- Centralized credit bounds, exact arithmetic and registration caps in `src/recommendation/registration_policy.py`.
- Updated the API course validators, adapter, service and core inputs and constraints to share calculations while retaining their validation.
- Added policy and HTTP parity coverage. The full suite had 981 passes, 2 known failures and 2 skips.
- See the [Phase 4A report](reports/API_RECOMMENDATION_PHASE_4A_REPORT.md) for affected files and verification.

## 2026-11-18 — Phase 4B student snapshot consolidation
- Shared semester and GPA trend derivation in `src/recommendation/inputs.py`, preserving each boundary's missing values.
- Delegated failed-credit ratio and enrollment-gap calculations from `src/api/adapters/student.py` while retaining source evidence checks.
- Added nine cases in `tests/unit/test_student_snapshot_parity.py` and matched before-and-after responses for 13 synthetic student scenarios.
- All 26 HTTP cases passed. The full suite had 990 passes, 2 known frozen-history filename failures and 2 skips.

## 2026-11-18 — Phase 5 scoring and ranking separation
- Split aggregation from the legacy sorted summary in `src/recommendation/plan_scoring.py`. `src/recommendation/two_stage_engine.py` uses aggregation before final ranking.
- Shared GPA metrics in `src/recommendation/shortlist.py` and the final scorer while preserving each stage's weighted totals.
- Added three checks in `tests/unit/test_plan_scoring.py`. Synthetic recommendation and observed-plan outputs matched before and after.
- Passed 200 focused and 26 HTTP cases. The full suite had 993 passes, 2 known frozen-history filename failures and 2 skips.

## 2026-11-18 — Phase 6 readiness and frozen history selection
- Shared Pareto and history compatibility checks in `src/recommendation/serving.py` and consolidated readiness in `src/api/service.py`.
- Passed one verified history snapshot per built-in engine request into `src/recommendation/two_stage_engine.py`, preserving the public injected-engine call.
- Added rollback, busy-worker and injected-engine checks in `tests/integration/test_api_stable.py`. All 16 before-and-after serving scenarios matched.
- All 29 HTTP tests passed. The full suite had 996 passes, 2 known frozen-history filename failures and 2 skips.
