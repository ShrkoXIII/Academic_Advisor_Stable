# Academic Advisor Stable

مسار مستقل لإعادة بناء بيانات التوصية الأكاديمية من الخام، وتدريب نماذج LightGBM، وتشغيل `TwoStagePlanRecommender` عبر FastAPI وواجهة Streamlit للتقييم المحلي.

ملفات تنظيف Stable الحالية هي الأساس المعتمد. يحافظ النقل على السياسات والحسابات الحالية، بما فيها `diploma_gpa` و`null` والمحاولات والتقسيم والميزات والأوزان والقيود والترتيب. لا يحتاج التشغيل إلى المشروع القديم أو مخرجاته.

## التشغيل بعد البناء

تحتاج البيئة المثبتة والأصول الناتجة من الخطوات أدناه. انسخ `.env.example` إلى `.env.local` واضبط مفاتيح محلية مختلفة للخدمة والإدارة والتحديث النهائي. لا تنقل أسرار جهاز آخر.

شغّل API في نافذة طرفية:

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.api.app:create_app --factory --env-file .env.local --host 127.0.0.1 --port 8000
```

وشغّل الواجهة في نافذة أخرى:

```powershell
.\.venv\Scripts\python.exe -m streamlit run tools/academic_advisor_streamlit/streamlit_app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

الواجهة: <http://127.0.0.1:8501>، عقد HTTP: <http://127.0.0.1:8000/docs>، الجاهزية: <http://127.0.0.1:8000/health>. يجب أن تكون `recommendation_readiness.ready=true`؛ نجاح HTTP وحده لا يثبت جاهزية التوصية. أعد تشغيل الخدمتين بعد اعتماد أصول جديدة.

## التثبيت على جهاز جديد

تحقق النقل على Windows وPython 3.11. الاعتماديات المقفلة الحالية تتطلب Python 3.11 على الأقل؛ التشغيل على نظام آخر يحتاج تحققًا مناسبًا لذلك النظام.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e ".[api,ui,dev]"
.\.venv\Scripts\python.exe -m pip check
```

`pyproject.toml` هو تعريف الاعتماديات، و`requirements.lock` يسجل البيئة المختبرة. على Linux/macOS يكون Python داخل `.venv/bin/python`.

## الخام المطلوب

ضع الملفات الأصلية دون تعديل محتواها في `data/raw/`:

| الملف | الاستخدام |
|---|---|
| `v_crg_student_course_raw.parquet` | سجل المقررات والتسجيل والـroster |
| `v_add_student_degree_status.parquet` | حالة الطالب وتاريخه الأكاديمي |
| `v_acd_degree_course.parquet` | كتالوج الدرجة والمقررات |
| `v_add_academic_info.parquet` | بيانات الدبلوم |
| `v_acs_grade.parquet` | سلم تحويل العلامة إلى نقاط ودرجات |

ملف طلبات المقررات الخام الإضافي الموجود محليًا غير مطلوب للمسار الأساسي الحالي. لا تستخدم بيانات تنظيف أو ميزات أو نماذج قديمة لتعويض أي مرحلة مفقودة.

## البناء الكامل من الصفر

الأوامر التالية لبناء جديد يحتوي الكود والخام فقط. حزم التاريخ وshortlist ترفض الاستبدال المتعمد؛ لا تحذف مخرجات معتمدة لتجاوز ذلك. للبناء المستقل استخدم نسخة جديدة من الكود والخام، أو أرشفة معتمدة للمخرجات السابقة. تغيير الخام يستلزم إعادة بناء المراحل التابعة.

```powershell
.\.venv\Scripts\python.exe -m src.main --section data
.\.venv\Scripts\python.exe -m src.main --section features
.\.venv\Scripts\python.exe -m src.features.build_frozen_history --as-of-part 20243 --finalized-through-part 20243
.\.venv\Scripts\python.exe -m src.features.build_frozen_history --as-of-part 20251 --finalized-through-part 20251
.\.venv\Scripts\python.exe -m src.main --section modeling
.\.venv\Scripts\python.exe -m src.modeling.build_artifact_manifest --approval-reference "Preserve Business Logic: user decision 2026-11-05" --approval-date 2026-11-05
.\.venv\Scripts\python.exe -m src.main --section evaluation
```

مرجع الاعتماد في المثال يوثق قرار المستخدم بالحفاظ على سياسة Pareto/Balance الحالية. دون مرجع صريح يبقى manifest غير مفعل للترتيب. لا يعد هذا المرجع اعتمادًا أكاديميًا جديدًا لجودة النماذج أو البدائل.

```text
Standard: Data → Features → Modeling → Evaluation

Data: clean_degree_course → clean_student_course → clean_student_status
    → filter_common_students → build_student_course_enriched
    → clean_student_diploma → clean_outliers → build_temporal_split
    → build_registration_roster
Features: temporal outcomes + registration rosters → temporal features
Modeling: 47-feature grade/fail → 33-feature grade/fail
Evaluation: observed-plan GPA from test features and the 47-feature grade model

Explicit serving preparation:
    Temporal features → Frozen history by finalized cutoff
    Trained models → Fresh manifest
    Frozen history + Fresh manifest → TwoStagePlanRecommender → FastAPI → Streamlit
```

ترتيب البناء الحقيقي محفوظ في `src/main.py`. استعرضه بـ`--list` أو افحص الخطوات بـ`--all --dry-run`. التاريخ ذو cutoff محدد ونشر الأصول عمليتان صريحتان؛ لا ينفذهما `--all` تلقائيًا.

| الموضع | الناتج |
|---|---|
| `data/clean/` | التنظيف والربط والإثراء والـroster |
| `data/merged/` | مواضع الدبلوم والشذوذ المعتمدة سابقًا في Stable، محفوظة أثناء النقل |
| `data/temporal/` | التدريب والاختبار ونسختا الـroster |
| `data/features/` | ميزات التدريب والاختبار |
| `data/artifacts/history/as_of_*/` | حزم تاريخ ثابتة ومتحقق منها |
| `models/` | زوج 47 وmetadata؛ `shortlist_training/` ناتج تدريب 33 الجديد، و`shortlist/` الحزمة المنشورة |
| `data/artifacts/category_levels.json` | ترتيب فئات زوج 47 |
| `data/evaluation/` | تنبؤات ومقاييس التقييم الجديدة |
| `.api-state/` | SQLite للطلبات المنفصلة؛ ليست جزءًا من بيانات التدريب |

اللاحقة `V2` في metadata تشير إلى عقد التسلسل الحالي؛ توجد مجموعة واحدة من مسارات الإنتاج canonical. الـmanifest يثبت بصمات النماذج والفئات وGradeScale والمدخلات، ويتحقق من توافق الأهداف وترتيب الميزات والـcutoff.

تأتي مسارات المراحل من `src/paths.py` دون aliases أو لاحقات إصدارات للبيانات. فرع الـroster يقرأ الخام والحالة والكتالوج وسجل المستبعدين، ثم يغذي الميزات مع نتائج التقسيم الزمني؛ ليس نسخة بديلة من خط التنظيف. يبقى `data/artifacts/course_history_state.pkl` ناتج تاريخ التدريب، بينما `history/as_of_<part>/` حزم serving مستقلة حسب القطع الزمني.

لا يُشترط اسم ملف ذي لاحقة إصدار عند تمرير `--sources` لبناء التاريخ: يجب أن تحمل المصادر المخصصة `dataset_version="V2"` و`feature_engineering_version=2`، مع بقاء فحوص البصمات والنهائية والـcutoff وعدم الاستبدال. تبقى أسماء source views الخام، ونسخ schema والسياسات وmetadata، ومجلدات `as_of_*` كما هي. كذلك بقي نص `V2` التاريخي في مصدر تدريب shortlist دون تعديل لأن metadata الحالية تثبت بصمة هذا المصدر؛ `shortlist_training/` مصدر النشر و`shortlist/` حزمة serving، وليسا إصدارين متوازيين من البيانات.

يبقى `data/artifacts/build_manifest.json` سجلًا تاريخيًا للبناء السابق: بصمات خمسة ملفات مصدر تغيرت في هذا التنظيف الهيكلي، ولم يُعد توليد السجل أو أي ناتج. بقيت بصمات بياناته ونماذجه وبصمات مدخلات تدريب shortlist الإحدى عشرة مطابقة؛ لا تُحدّث أدلة التدريب أو النشر لتجاوز اختلاف المصدر.

## النماذج والتاريخ

Stage 1 يستعمل 33 ميزة لتقييم كل مرشح، ثم يجمع الخطط الصالحة بالساعات المطلوبة بالضبط ويحتفظ بما يصل إلى 50 خطة. Stage 2 يعيد حساب 14 ميزة للخطة والمقررات الأخرى، ويستعمل عقد 47 ميزة لإعادة التقييم والترتيب. الناتج أربعة نماذج: علامة ورسوب لكل مرحلة. لا يضمن المسار أفضل Top-K عالميًا.

الأهداف الحالية `final_mark` و`final_mark < 50`. بقيت شبكة المرشحين والأوزان والتحقق الزمني كما في المصدر؛ التدريب حتى 20243، والتحقق في 2023/2024، والتقييم المحفوظ في 20251/20252. لم يضف النقل تجربة تحسين أو اختيارًا بناءً على أرقام الاختبار. بيانات 2025 سبق استخدامها تاريخيًا وليست اختبارًا جديدًا أعمى.

يبنى التاريخ من prefix نتائج معتمد. لتقييم 20251 تُستخدم نسخة 20243، ولـ20252 نسخة 20251. لا تسمح الحزمة بنتائج الهدف أو المستقبل. يدعم API التحديثات النهائية والتحقق والنشر والتفعيل والرجوع وفق العقود الحالية. خط الأساس الإداري ما زال 20251 كما في المصدر.

## إدخال الطالب وعرض النتائج

في وضع JSON، حمّل أو الصق طلب `/api/v1/recommendations` نفسه، متضمنًا الهوية والفصل و`student_api_response` و`courses_api_response` و`source_contexts` و`integration_context` و`history_as_of_part` والساعات المطلوبة. تمر المدخلات بالتحقق نفسه المستخدم في HTTP.

في وضع الجامعة، اضبط الروابط الثلاثة في `.env.local`. أسماء الاستعلام الافتراضية Student: `studentId,semesterId`، Courses: `studentId,degreeId,semesterId`، History: `part_id`. يمكن ضبط mapping بالمتغيرات `ADVISOR_UI_STUDENT_PARAMS` و`ADVISOR_UI_COURSES_PARAMS` و`ADVISOR_UI_HISTORY_PARAMS`.

السياق الإضافي ملف JSON اختياري مهيأ بواسطة `ADVISOR_UI_INTEGRATION_CONTEXT_FILE`، وشكله `{"student": {...}, "courses": {...}}`. يجب توفير القيم والمصادر وتوقيت الساعات والسياسات المطلوبة فعليًا؛ لا تستنتج الواجهة القيم الناقصة.

رد الجامعة المتوقع للتاريخ هو `part_id, rows[], finalization?`. الصف الإنتاجي يحتاج `degree_id, course_id, faculty_id, plan_requirement_type_id, course_credits, count, fail_count, retake_count, mark_sum, attempt_sum`. صيغة `CoursesStatistsic` غير المكتملة لا تُحوّل تخمينيًا. يجلب وضع الجامعة الرد ويتحقق من عقده؛ التاريخ المستخدم في التنبؤ هو الحزمة المحلية المبنية والمثبتة. استيراد تحديثات الجامعة ونشرها وتفعيلها يتم عبر إدارة التاريخ، دون كتابة تلقائية أثناء طلب توصية.

تعرض الواجهة الطالب، الخطة المسجلة وتنبؤها، أفضل ثلاث خطط والمقارنة. تأتي الخطة الفعلية افتراضيًا من roster الجديد داخل Stable، وتستعمل IDs والساعات والكتالوج والمحاولات الأقدم من الهدف؛ لا تستبدل بها مجموعة المرشحين البديلة.

يمكن إدخال تسجيل فعلي مستقل عند عدم وجود سجل محلي:

```json
{"student_id":"synthetic-student","degree_id":"synthetic-degree","part_id":20251,
 "source":"approved-registration-source",
 "courses":[{"course_id":"synthetic-course","course_credits":3}]}
```

تحتاج IDs إلى كتالوج مطابق، وهذه أمثلة اصطناعية. تُستخدم لقطة Student API المتحقق منها نفسها لتنبؤ الخطة الفعلية؛ لا تعاد مقارنة توقعات بمدخلات طلاب مختلفة.

تُربط النتائج بعد التنبؤ فقط. عند توفر نتائج خارجية موثقة، يكون شكلها:

```json
{"student_id":"synthetic-student","degree_id":"synthetic-degree","part_id":20251,
 "source":"approved-final-ledger","finalized":true,
 "courses":[{"course_id":"synthetic-course","course_credits":3,"actual_mark":70,"actual_points":2.5}],
 "semester_gpa":2.5,"cumulative_gpa":2.8}
```

حقلا GPA الرسميان اختياريان. غياب النتيجة يبقى غير متاح؛ لا يولد النظام درجات فعلية للبدائل. معدل المقررات المحسوب وصفي، والإسقاط التراكمي المتوقع إضافي دون استبدال المحاولات الرسمي. نتائج التقييم المحلية مشتقة من التصدير وفق قواعد التنظيف الحالية؛ النقل لا يضيف مصادقة جامعية مستقلة.

## API والمصادقة

الخدمة تستقبل `X-API-Key`. مفاتيح الخدمة والإدارة والتحديث النهائي مختلفة. الإعدادات النسبية تُحل بالنسبة إلى جذر المشروع؛ `.env.local` يحمل محليًا بواسطة `--env-file` عند تشغيل Uvicorn، وتقرأ الواجهة `.env.local` من جذر المشروع، مع دعم `.env` عند غياب الملف المحلي.

| الوظيفة | المسار |
|---|---|
| الجاهزية | `GET /health` |
| تحقق الطالب والمقررات | `POST /api/v1/inputs/{student,courses}/validate` |
| التوصية | `POST /api/v1/recommendations`؛ alias: `POST /recommend` |
| الإدخال المنفصل | `POST /api/v1/recommendation-inputs/{student,courses}` |
| حالة الطلب المملوك للمتصل | `GET /api/v1/recommendation-requests/{request_id}` |
| تحقق delta دون نشر | `POST /api/v1/history/deltas/validate` |
| حالة التاريخ | `GET /api/v1/admin/history/status` |
| الوضع | `PUT /api/v1/admin/history/mode` |
| الإدارة الصريحة | `POST /api/v1/admin/history/{initialize,preview,commit,activate,finalization-events}` |

الإدخال المنفصل يعيد 202 حتى اكتمال المكونين، ويمنع التنفيذ المزدوج وإعادة الطلب المتعارضة. `preview` الإداري يكتب حالة معلقة؛ `commit` و`activate` عمليتان مختلفتان. لا تشغل عمليات الإدارة كاختبارات قراءة.

## الاختبارات والتحقق المستقل

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe tools/verify_standalone.py --approval-reference "Preserve Business Logic: user decision 2026-11-05" --approval-date 2026-11-05
```

الفحص المستقل ينسخ الكود والخام فقط إلى مجلد OS مؤقت، وينشئ بيئة جديدة ويثبت القفل، ثم يعيد البناء والتاريخ والتدريب والنشر والتقييم والاختبارات. يرفض قراءات Python المدققة للمشروع الأصلي وLegacy، ويفحص العمل من دليل مختلف وثبات الخام. تدقيق Python ليس عزلًا على مستوى نظام التشغيل ولا يغطي كل I/O داخل المكتبات الأصلية؛ يكمله فحص اعتماديات المصدر ومسارات الأصول المرتبطة بجذر النسخة الجديدة. لا ينسخ مخرجات التحقق إلى المشروع؛ تنظف بيئته المؤقتة بعد إيقاف عماله المملوكين لها.

تتضمن الاختبارات الفلاتر والربط والحدود الزمنية والفئات والأصول والقيود والترتيب والتاريخ وSQLite وHTTP وJSON المحلي وفصل النتائج عن التنبؤ وعرض Streamlit. بعض بيئات Windows المعزولة تمنع إنشاء حلقة asyncio؛ عند ظهور ذلك شغّل اختبارات HTTP/Streamlit في بيئة تسمح بالاتصال المحلي. اختبار POSIX الخاص بصلاحيات الملفات متجاوز على Windows.

## حدود السلوك المحفوظة والتسليم

بقيت سياسة الدبلوم والقيم المفقودة واستبعاد تاريخ الطالب الكامل وفق الشذوذ كما اعتمدها المستخدم. كذلك بقي نطاق تاريخ GPA والمحاولات في الوحدات المنقولة كما في المصدر، مع الحفاظ على تصحيح حدود الدرجة الموجود أصلًا في تنظيف Stable. استبعاد المجموعة قبل التقسيم قد يتأثر بسجلات لاحقة؛ نجاح النقل لا يحوله إلى إثبات خلو كل مراحل الاختيار من التسرب.

يتطلب تقييم T0 إثبات توقيت لقطة الطالب والأهلية والكتالوج. التراكمي المتوقع لا يطبق الاستبدال الرسمي، وحدود الأداء التشغيلي ما زالت غير محسومة. نجاح الاختبارات والتنبؤ بالخطة المرصودة لا يثبت النتيجة الفعلية لخطة بديلة.

يتكون تسليم قابل لإعادة البناء من `src/`, `tools/`, `tests/`, `pyproject.toml`, `requirements.lock`, `.env.example`, هذا README و`docs/api_contract.md` والخام المصرح به. تُولد البيانات المعالجة والنماذج داخله. لا تُسلّم `.venv`, `.env.local`, SQLite أو تقارير الطلاب دون حاجة وصلاحية محددتين. التغييرات مسجلة بإيجاز في `docs/CHANGELOG.md`؛ لم يُنشأ commit أو merge ضمن النقل.

## سجل ملفات النقل والتعديلات التقنية

الاختصارات بين الأقواس أدناه تسرد الملفات الفعلية داخل الدليل المذكور. لم تُستبدل ملفات التنظيف أو `academic_calendar.py` أو ملفات `__init__.py` القائمة بنسخ Legacy.

| الملفات | السبب |
|---|---|
| `src/data/building/{filter_common_students,build_student_course_enriched,build_temporal_split,build_registration_roster}.py` | نقل بناء البيانات وتكييف الاستيرادات والمسارات |
| `src/features/{feature_contract,temporal_features,build_temporal_features,frozen_history,build_frozen_history}.py` | نقل الميزات والتاريخ؛ مصادر metadata نسبية |
| `src/modeling/{training_config,train_models,shortlist_features,train_shortlist_models,build_artifact_manifest}.py` | تدريب الزوجين من الجديد، واستخراج الاعتماد الضروري من experiments ونشر manifest متوافق |
| `src/recommendation/{two_stage_engine,two_stage_artifacts,inputs,constraints,course_status,plan_generation,plan_scoring,shortlist,ranking,ranking_policy,balance_policy,history_update,cumulative_history}.py` | مسار TwoStage الحالي؛ التحقق من الفائز الجديد ومرجع تفويض السياسة دون تغيير حسابها |
| `src/grade_scale.py` | تحويل العلامات والنقاط الحالي دون تغيير |
| `src/api/{app,schemas,service,settings,request_store,validation,student_adapter,courses_adapter,history_adapter}.py` | خدمة HTTP وعقودها وSQLite؛ إعدادات نسبية إلى جذر المشروع |
| `src/api/adapters/{__init__,student,courses,history}.py`؛ `src/api/validators/{__init__,common,student,courses,history}.py` | المحولات والتحقق اللازمان للخدمة، مع توافق أسماء الاستيراد |
| `src/evaluation/{__init__,evaluate_plan_gpa,observed_plan}.py` | تقييم جديد؛ فصل التنبؤ بالخطة المسجلة عن ربط نتائجها، ومنع طباعة معرفات الطلاب |
| `src/{main,paths}.py` | نقطة تشغيل وترتيب اعتماديات ومسارات مركزية canonical |
| `tools/__init__.py`؛ `tools/academic_advisor_streamlit/{__init__,ui_client,views,streamlit_app}.py` | واجهة تقييم مخصصة وعميل HTTP ومقارنات بمدخلات محققة |
| `tools/verify_standalone.py` | بناء مستقل من الكود والخام وبيئة جديدة، مع تنظيف العمليات المملوكة عند timeout |
| `pyproject.toml`؛ `requirements.lock` | اعتماديات المراحل والقفل المختبر وPython 3.11 واكتشاف حزمة tools |
| `.gitignore`؛ `.env.example` | إهمال حالة API والأسرار المحلية وشرح متغيرات التشغيل |
| `README.md`؛ `docs/api_contract.md`؛ `docs/CHANGELOG.md` | تعليمات إعادة البناء والعقود ومرجع قرار الحفاظ على السياسة وسجل التحقق |

اختبارات المرحلة المنقولة أو المضافة والتعديل التقني الوحيد على اختبارات التنظيف:

| الملفات داخل `tests/` | الغرض |
|---|---|
| `unit/test_{filter_common_students,build_student_course_enriched,build_temporal_split,build_registration_roster}.py`؛ `unit/test_clean_student_status.py` | بناء البيانات وفحص مجموعة المسارات canonical بدقة |
| `unit/test_{temporal_features,feature_contract_responsibilities,frozen_history}.py` | الميزات وحدود التاريخ وسلامة الحزم |
| `unit/test_{train_models,training_config,main_runner,fresh_artifact_metadata,migration_ranking_provenance}.py` | عقود التدريب والتشغيل والفائز الفعلي ومرجع السياسة |
| `unit/test_two_stage_{artifacts,engine,constraints,shortlist,payloads,matrix,activation}.py`؛ `unit/test_{ranking_strategies,balance_policy,history_update,grade_scale}.py` | الأصول والقيود والمصفوفات والحساب والترتيب والتاريخ |
| `unit/{two_stage_fixtures,recommendation_fixtures}.py` | مساعدات اصطناعية للاختبارات دون بيانات طلاب محفوظة |
| `unit/test_{api_request_store,api_portable_settings,cumulative_history}.py`؛ `integration/test_api_stable.py`؛ `synthetic_api.py` | SQLite والإعدادات والتاريخ وعقد HTTP بمدخلات اصطناعية |
| `unit/test_{evaluate_plan_gpa,observed_plan}.py` | حساب GPA، فصل النتائج، الهوية والقيم المفقودة والمدخلات المشوهة |
| `unit/test_{ui_client,stable_ui_views,standalone_staging,standalone_timeout}.py`؛ `integration/{__init__,test_streamlit_stable}.py` | النقل والإعدادات الخاصة وعرض الخطط والبناء المستقل وتنظيف العمال |

المخرجات المولدة في المواضع المبينة أعلاه، ومنها `data/artifacts/build_manifest.json`، ليست ملفات منقولة من Legacy. بقيت بقية اختبارات التنظيف السابقة ضمن مجموعة الانحدار دون تغيير سياساتها.

نتيجة التحقق بتاريخ 2026-11-05: نجح البناء الكامل من الكود والخام في بيئة Python جديدة ومجلد مؤقت مستقل، بما فيه التاريخ والنماذج الأربعة والنشر والتقييم وجاهزية API. نجح 951 اختبارًا في Stable، و951 في النسخة المستقلة؛ تجاوز اختبار صلاحيات POSIX على Windows، وبقي تحذير deprecation من TestClient. تطابقت AST لـ38 وحدة بعد تكييف الاستيرادات والمسارات، وثبتت بصمات الخام وملفات التنظيف. لم يختبر النقل الاتصال الفعلي بواجهات الجامعة، واعتمد فحص عرض الواجهة على Streamlit AppTest لعدم توفر متصفح IAB.
