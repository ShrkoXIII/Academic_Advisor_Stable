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
- إزالة أسماء المسارات المحلية ذات لاحقة V2 من وحدات التنظيف الخمس واعتماد ثوابت `src/paths.py` مباشرة، دون تغيير المسارات أو منطق التنظيف.
- تحديث `monkeypatch` في ملفات الاختبارات الخمسة المقابلة ووصف `src/paths.py`؛ لم يحتج التقويم إلى تعديل ولم تُعد بناء البيانات.
- التحقق: نجح 203 اختبارات مركزة ثم جميع اختبارات `tests/unit` وعددها 249؛ لا توجد أسماء V1/V2 في نطاق التنظيف والتقويم والاختبارات.

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
- Removed runner dataset labels/mixed-version handling and the custom-history `_v2` filename requirement; preserved CLI order, serialized contracts, cutoffs, and academic/null/diploma behavior.
- Clarified canonical paths, branches, and staging labels in `src/{main,paths}.py`, `src/data/building/filter_common_students.py`, `src/features/{build_frozen_history,frozen_history}.py`, `src/modeling/build_artifact_manifest.py`, `src/recommendation/two_stage_artifacts.py`, and `README.md`.
- Updated `tests/unit/test_{main_runner,frozen_history,filter_common_students}.py`: 28 focused and 837 relevant unit tests passed; 67 source imports/compilation, 49 unique paths, dependency connections, and CLI checks passed without executing pipeline stages or training.
- Preserved data/models/manifests and all 11 shortlist input/source hashes; the build manifest retains historical source fingerprints for five edited files. No datasets, history, models, or evaluation artifacts were rebuilt, overwritten, published, or deleted.
