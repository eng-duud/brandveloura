# تقرير المراجعة الهندسية الشاملة لمشروع Brand Veloura (Code Review Checklist Report)

**تاريخ المراجعة:** 2026-11-17  
**نطاق المراجعة:** كامل المشروع (`config/`, `store/`, `templates/`, `static/`, `Dockerfile`, `requirements.txt`, التوثيق والاختبارات)  
**المنهجية المعتمدة:** قائمة فحص مراجعة الأكواد الشاملة (Functionality, Security, Performance, Code Quality, Tests, Documentation & DevOps)

---

## 📊 الملخص التنفيذي وقائمة التحقق السريعة (Checklist Summary)

المشروع يمتلك بنية متقدمة وميزات غنية تناسب السوق المحلي (دعم عملتين `YER/SAR`، ركن الهدايا، تكامل Cloudinary وPWA، وإشعارات Web Push). ومع ذلك، كشفت المراجعة الدقيقة للكود عن **عدة أخطاء حرجة (P0)** في بيئة العمل الحالية وفي تفاعل `hx-boost` و`Service Worker` مع التحديثات الأخيرة، إلى جانب نقاط تحسين مهمة في الأمان، منطق المخزون، الكاشينج، وتقسيم الملفات الضخمة.

| المحور | الحالة العامة | أبرز الملاحظات المكتشفة |
| :--- | :---: | :--- |
| **1. الاستقرار الفوري (Working Tree)** | ❌ خطأ نشط | خطأ مطبعي غير محفوظ في Git بملف `store/admin.py:966` يعطّل صفحة الطلبات ويكسر الاختبارات. |
| **2. الوظائف والمنطق (Functionality)** | ⚠️ يحتاج إصلاحات P0 | تعارض `hx-boost="true"` مع طرق العرض الجزئية، ومشكلة `cache-first` في `Service Worker`، وتباين أسعار السلة/الفاتورة، وثغرة تجاوز المخزون عند تعدد الدرجات/الباقات. |
| **3. الأمان (Security)** | ⚠️ تحسينات ضرورية | قيم افتراضية خطيرة في `settings.py`، نقص التحقق من `state` و`aud` و`verified_email` في Google OAuth، وتمرير `locals()`، وعدم هروب النصوص في `onclick` و`sitemap.xml`. |
| **4. الأداء والكاشينج (Performance)** | ⚠️ تباين بين Workers | استخدام `LocMemCache` مع `--workers 2` في `start.sh`، وغياب حزمة `redis` من `requirements.txt`، واستعلامات `N+1` في `GiftBundle` و`admin.py`. |
| **5. جودة الكود والهيكلة (Code Quality)** | 🟡 متوسط | تضخم ملف `store/views.py` (3,068 سطراً) و`store/admin.py` (1,336 سطراً)، وتكرار منطق الصرف والمخزون، ووجود قوالب وملفات مهملة. |
| **6. الاختبارات (Tests)** | ⚠️ فشل حالي بـ `admin` | فشل `test_admin_routes` بسبب الخطأ المطبعي المذكور؛ وحاجة لتغطية `hx-boost` وسباقات المخزون وOAuth. |
| **7. التوثيق والتشغيل (Docs & DevOps)** | 🟡 يحتاج تحديثاً | تعارض `README.md` (يذكر Django 6.0 و83 اختباراً)، نقص `REDIS_URL` في `.env.example`، وتشغيل Docker بصلاحية `root`. |

---

## 🚨 أولاً: أخطاء حرجة يجب إصلاحها فوراً (P0 — Critical Bugs)

### 1. خطأ مطبعي غير مُلتزم يعطّل لوحة الطلبات بالكامل
- **الموقع:** [store/admin.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/admin.py#L966) (ضمن تعديل غير محفوظ في `git diff`)
- **المشكلة:** الكود الحالي يحتوي على `obj.get_status_dispchelay()` بدلاً من `obj.get_status_display()`.
- **الأثر الفعلي (تم التحقق منه):** عند تشغيل `python manage.py test store.tests.test_admin_routes`، ينهار المسار `/cpanel-0x110/store/order/` بالخطأ:
  `AttributeError: 'Order' object has no attribute 'get_status_dispchelay'`
- **التعديل المقترح:** إرجاع السطر فوراً إلى `obj.get_status_display()`.

---

### 2. تعارض `hx-boost="true"` مع طرق العرض الجزئية يُدمر تخطيط الموقع عند التنقل
- **المواقع:**
  - [templates/base.html](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/base.html#L177) (`<body ... hx-boost="true">`)
  - [store/views.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/views.py#L359) (`brands_list_view`)
  - [store/views.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/views.py#L444) (`brand_detail_view`)
  - [store/views.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/views.py#L633) (`product_list_view`)
  - [store/views.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/views.py#L661) (`product_detail_view`)
  - [templates/store/partials/quick_view_modal.html](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/partials/quick_view_modal.html#L217)
- **المشكلة:** عند تفعيل `hx-boost="true"` على `<body>`، يرسل HTMX ترويسة `HX-Request: true` **مع** `HX-Boosted: true` عند النقر على أي رابط عادي. الدوال الأربع المذكورة تتحقق فقط من `if request.headers.get('HX-Request') and not request.GET.get('full_page'):` دون استثناء `HX-Boosted`.
- **الأثر:** النقر على روابط **"الأقسام"** أو **"الماركات"** أو **"عرض كامل تفاصيل المنتج"** يقوم باستبدال كامل جسم الصفحة `<body>` بملف جزئي (`product_grid.html` أو `brands_grid.html` أو `quick_view_modal.html`) ويختفي الهيدر والشريط السفلي والفلاتر والتذييل!
- **التعديل المقترح:** تعديل الشرط في الدوال الأربع ليصبح:
  ```python
  is_htmx_partial = (
      request.headers.get('HX-Request')
      and not request.headers.get('HX-Boosted')
      and not request.GET.get('full_page')
  )
  ```

---

### 3. تعطل نصوص التهيئة (`DOMContentLoaded`) و`extra_head` وإعادة تعريف المتغيرات تحت `hx-boost="true"`
- **المواقع:**
  - [templates/store/checkout.html](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/checkout.html#L32) و [السطر 887](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/checkout.html#L887-L929)
  - [templates/store/gift_builder.html](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/gift_builder.html#L1601-L1614)
  - [templates/store/auth/account.html](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/auth/account.html#L638-L644)
  - [templates/store/gift_slip.html](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/gift_slip.html#L392-L394)
  - [templates/store/home.html](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/home.html#L251-L345) و [السطر 490](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/home.html#L490)
  - [templates/store/auth/login.html](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/auth/login.html#L9) و [السطر 85](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/auth/login.html#L85)
  - [templates/store/auth/register.html](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/auth/register.html#L9) و [السطر 84](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/auth/register.html#L84)
  - [templates/store/order_success.html](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/order_success.html#L5-L8)
- **المشاكل المترابطة:**
  1. حدث `DOMContentLoaded` لا يُطلق عند الانتقال بين الصفحات عبر `hx-boost`؛ بالتالي عند الانتقال من السلة إلى `/checkout/` لا تعمل تهيئة طرق الدفع ولا مؤقت العد التنازلي ولا حماية النقر المزدوج، وفي `/gifting/` لا تعمل فلاتر الخطوة الأولى.
  2. HTMX لا يعيد تحميل السكربتات وأنماط CSS داخل `{% block extra_head %}` أثناء `hx-boost`، ما يعطّل مكتبة Google Sign-In في صفحتي الدخول والتسجيل و`html2canvas` وتنسيقات الفاتورة في `order_success.html`.
  3. عند تسجيل الدخول أو الخروج عبر نموذج لا يحمل `hx-boost="false"`، يغيّر Django رمز CSRF (`rotate_token`)، بينما يظل الوسم `<body hx-headers='{"X-CSRFToken": "..."}'>` حاملاً للرمز القديم؛ فتفشل طلبات `hx-post` التالية (مثل "أضف للسلة") بخطأ `403 Forbidden`.
  4. في `home.html`، المتغيرات العامة `let currentSlide = 0; const slides = ...; const bvSliders = {};` خارج نطاق مغلق (IIFE)، وعند العودة للرئيسية عبر `hx-boost` يحدث خطأ `SyntaxError: Identifier 'currentSlide' has already been declared` وتتسرب مؤقتات `setInterval` و`requestAnimationFrame`.
- **التعديل المقترح:**
  - إضافة `hx-boost="false"` على النماذج والصفحات المعتمدة على `extra_head` أو تدوير CSRF: `login.html`، `register.html`، `checkout.html`، وروابط الإدارة في `product_list.html`.
  - نقل منطق التهيئة في القوالب من `DOMContentLoaded` إلى دالة تُنفذ فوراً وتُستدعى أيضاً عند `htmx:afterSettle` (أو تغليف سكربتات الصفحات في IIFE وتنظيف `clearInterval` / `cancelAnimationFrame` عند `htmx:beforeCleanupElement`).
  - تحديث قيمة `X-CSRFToken` ديناميكياً عبر مستمع `htmx:configRequest` من حقل مخفي أو ترويسة حديثة بدلاً من ربطه بسمة ثابتة على `<body>` لا تتبدل مع `hx-boost`.

---

### 4. `Service Worker` يحفظ استجابات HTMX و`home-deferred` للأبد (`Cache-First`)
- **الموقع:** [store/views.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/views.py#L2158-L2203)
- **المشكلة:**
  1. السطور 2189-2201 تطبق استراتيجية **`Cache-First` دائمة** على كل طلب `GET` غير تنقلي (`event.request.mode !== 'navigate'`). وبما أن السطور 2161-2168 لم تستثنِ `/partials/` أو `/notifications/` أو `/get-shipping-fee/` أو `/products/`، فإن المتصفح يخزن `/partials/home-deferred/` و`/notifications/dropdown/` في Cache Storage.
  2. النتيجة: لو حدّثت الإدارة منتجاً أو سعراً، أو بدّل العميل العملة بين `YER` و`SAR`، سيعيد الـ `Service Worker` الرد المخزن القديم من المتصفح ولن يرى العميل الأسعار الجديدة أبداً!
  3. كما أن الشرط `url.pathname.startsWith('/admin')` يتجاهل المسار المخصص `DJANGO_ADMIN_URL`، ومسار `navigate` يخزن صفحات مصادقة مثل `/login/` و`/register/` في الكاش.
- **التعديل المقترح:**
  - حصر استراتيجية `Cache-First` حصراً على المسار `/static/` (والأيقونات/الخطوط الثابتة).
  - منع تخزين أي مسار يحتوي `HX-Request` أو يبدأ بـ `/partials/`، `/notifications/`، `/set-currency/`، `/get-shipping-fee/`، `/login/`، `/register/`، أو المسار الديناميكي للوحة التحكم `admin_url`.

---

### 5. تباين مالي وفراغ تحقق في إتمام الطلب والمخزون (`Checkout & Stock`)
- **المواقع:**
  - [store/views.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/views.py#L864-L873) (`cart_add`)
  - [store/views.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/views.py#L1546-L1566) مقابل [السطر 1746](file:///c:/Users/hp/Desktop/projects/brandveloura/store/views.py#L1746) (`checkout_view`)
  - [store/views.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/views.py#L1593-L1651)
  - [store/views.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/views.py#L1674-L1782)
- **المشاكل:**
  1. **تباين سعر الطلب عن بنود الفاتورة:** يحسب `checkout_view` قيمة `subtotal_yer` بالأسعار الحية من قاعدة البيانات (السطور 1556-1566)، ولكنه عند إنشاء `OrderItem` في السطر 1746 يقرأ السعر القديم من الجلسة `item_data.get('price_yer', 0)`. إذا تغير سعر منتج بعد إضافته للسلة، لن يتطابق مجموع بنود الفاتورة مع `Order.subtotal_yer`.
  2. **احتمال تجاوز المخزون لنفس المنتج بصيغتين:** إذا أضاف العميل نفس المنتج بدرجتين (`original` و`master`) أو بمقاسين، أو أضافه منفرداً وداخل `GiftBundle`، فإن `cart_add` (السطر 864) و`checkout_view` (السطور 1683 و1696) يفحصان كل سطر على حدة دون تجميع الكمية الكلية للـ `product_id` نفسه في الطلب الواحد، وبذلك قد ينجح التحقق لكل سطر ويُباع أكثر من المتوفر بالمخزون.
  3. **غياب التحقق الخادمي من الحقول المطلوبة ونشاط المدينة/الحساب:** لا يوجد تحقق backend في `checkout_view` من أن `customer_name` و`customer_phone` و`shipping_address` غير فارغة، ولا يتحقق السطر 1646/1650 (وكذلك `get_shipping_fee` السطر 1093) من `is_active=True` للمدينة أو وسيلة الدفع.
  4. **الاعتماد على أسعار قديمة في صفحة السلة:** `cart_view` و`_render_cart_response` يعرضان `price_yer` من قاموس الجلسة/الملف الشخصي بدلاً من تحديث الأسعار من قاعدة البيانات (بينما يتغير السعر فجأة عند الوصول إلى `checkout`).
- **التعديل المقترح:**
  - حساب السعر المعتمد مرة واحدة في دالة مشتركة وتمريره لإنشاء `OrderItem` وتحديث عناصر السلة عند عرضها أو دمجها.
  - تجميع الكميات المطلوبة لكل `product_id` (من المنتجات المنفردة والباقات معاً) قبل فحص وخصم `stock_quantity` باستخدام `F('stock_quantity')` داخل `transaction.atomic()`.
  - استخدام Django Form للتحقق الصارم من مدخلات `checkout_view` واشتراط `is_active=True` في `ShippingZone` و`PaymentAccount`.

---

## 🔒 ثانياً: المراجعة الأمنية (Security Review — P1 / P2)

### 1. إعدادات افتراضية غير آمنة في الإنتاج (`config/settings.py` & `docker-compose.yml` & `seed_data.py`)
- **المواقع:**
  - [config/settings.py](file:///c:/Users/hp/Desktop/projects/brandveloura/config/settings.py#L15-L21)
  - [docker-compose.yml](file:///c:/Users/hp/Desktop/projects/brandveloura/docker-compose.yml#L8-L29)
  - [store/management/commands/seed_data.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/management/commands/seed_data.py#L31-L33)
- **الملاحظات:**
  - `SECRET_KEY` يمتلك قيمة احتياطية ثابتة مكتوبة في المستودع (`'brand-veloura-luxury-secret-key-2026-prod-grade'`).
  - `DEBUG` يأخذ القيمة الافتراضية `'True'` إذا غاب `DJANGO_DEBUG`.
  - `DJANGO_ALLOWED_HOSTS` يأخذ القيمة الافتراضية `'*'` (يعرّض الموقع لهجمات `Host Header Injection` إن نُسي المتغير).
  - كلمات مرور `seed_data.py` الافتراضية (`admin123456`) وبيانات `docker-compose.yml` (`brandpass123`) مكشوفة في Git.
- **التعديل المقترح:** قلب الافتراضي في `settings.py` ليصبح `DEBUG = False`، وإلزام وجود `DJANGO_SECRET_KEY` و`DJANGO_ALLOWED_HOSTS` محددين في بيئة الإنتاج (`not DEBUG`) مع عدم تشغيل `seed_data` في الإنتاج إلا بمتغيرات بيئية قوية.

---

### 2. ثغرات في تدفق Google OAuth 2.0 وتسجيل الدخول بالهاتف
- **المواقع:**
  - [store/views.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/views.py#L2490-L2651) (`google_login_redirect`, `google_auth_callback`)
  - [store/views.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/views.py#L2357-L2364) و [L2427](file:///c:/Users/hp/Desktop/projects/brandveloura/store/views.py#L2427) (`login_view`, `register_view`)
  - [store/views.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/views.py#L2273) و [L2328](file:///c:/Users/hp/Desktop/projects/brandveloura/store/views.py#L2328) و [L2399](file:///c:/Users/hp/Desktop/projects/brandveloura/store/views.py#L2399)
- **الملاحظات:**
  1. **غياب التحقق من `state` CSRF في Google OAuth (Login CSRF):** يمرر `google_login_redirect` قيمة `next_url` مباشرة داخل `state` دون توليد رمز عشوائي محفوظ في الجلسة (`secrets.token_urlsafe`), كما أن `google_auth_callback` يحمل `@csrf_exempt` ولا يتحقق من `g_csrf_token` في تدفق GIS أو من `state` في تدفق `code`.
  2. **تجاوز التحقق من `aud` و`email_verified`:** في تدفق `credential` (السطر 2549)، الشرط `if client_id and payload.get('aud') != client_id:` يتجاهل التحقق من `aud` إذا كان `client_id` فارغاً! وفي تدفق `code` (السطر 2594) لا يتم فحص `verified_email` / `email_verified`. كما يتم إرسال `id_token` في رابط GET إلى `tokeninfo`؛ يفضل التحقق محلياً عبر `google-auth` أو التحقق من `iss` و`aud` بشكل إلزامي.
  3. **عدم توحيد وتقييد رقم الهاتف في `UserProfile`:** حقل `UserProfile.phone` لا يمتلك `unique=True` ولا تطبيعاً (Normalization) للأرقام (`+967`/`00967`/`77...`). الاعتماد على `phone__endswith=clean_digits[-8:]` قد يطابق أرقاماً قصيرة إذا لم يتم اشتراط حد أدنى للطول عند الدخول.
  4. **تجاوز قواعد قوة كلمة المرور وتمرير `locals()`:** `register_view` (السطر 2441) و`account_profile_view` (السطر 2674) يفحصان `len(password) < 6` فقط بدلاً من استدعاء `django.contrib.auth.password_validation.validate_password()` المُعد في `settings.py`؛ كما أن `register_view` يمرر `locals()` إلى `render()` مما يضع `password` و`password_confirm` داخل سياق القالب.
  5. **حماية Rate Limiting قابلة للالتفاف:** الدوال تقرأ أول IP من `HTTP_X_FORWARDED_FOR` دون التحقق من البروكسي الموثوق، ويمكن تزييف الترويسة لتجاوز عداد المحاولات؛ كما أن `push_subscribe` يحمل `@csrf_exempt` رغم إمكانية إرسال `X-CSRFToken` من الواجهة.
- **التعديل المقترح:** إضافة `state` عشوائي مرتبط بالجلسة في OAuth، وإلزام فحص `aud` و`email_verified` في المسارين، وتفعيل `validate_password()`، واستبدال `locals()` بقاموس سياق صريح، وتطبيع أرقام الهواتف عند التسجيل/الدخول في دالة موحدة.

---

### 3. مخاطر حقن JavaScript / HTML / XML وتخزين الأسرار
- **المواقع:**
  - [templates/store/components/product_card.html](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/components/product_card.html#L122)
  - [templates/store/partials/quick_view_modal.html](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/partials/quick_view_modal.html#L200) و [L209](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/partials/quick_view_modal.html#L209)
  - [templates/store/product_detail.html](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/product_detail.html#L339) و [L351](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/product_detail.html#L351)
  - [store/views.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/views.py#L2973) (`sitemap_xml`) و [L1067](file:///c:/Users/hp/Desktop/projects/brandveloura/store/views.py#L1067) (`toggle_currency`)
  - [store/admin.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/admin.py#L277) و [L488-L537](file:///c:/Users/hp/Desktop/projects/brandveloura/store/admin.py#L488-L537) و [L870-L883](file:///c:/Users/hp/Desktop/projects/brandveloura/store/admin.py#L870-L883)
  - [store/models.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/models.py#L355-L395) (`HeroBanner.custom_url`) و [L1336](file:///c:/Users/hp/Desktop/projects/brandveloura/store/models.py#L1336) (`Notification.notify_admin`)
- **الملاحظات:**
  1. **حقن JS في `onclick`:** استخدام `showToast('تمت إضافة {{ product.name_ar }}...')` بدون `|escapejs` يكسر JavaScript أو يتيح XSS إذا احتوى اسم المنتج على علامة تنصيص مفردة `'`. كما أن الإشعار يظهر تفاؤلياً قبل رد الخادم حتى لو نفد المخزون! (الأفضل تفعيل التوست عبر `HX-Trigger` عند نجاح `cart_add` فعلياً).
  2. **إرجاع HTML خام وإدراج رمز CSRF من Cookie غير مضمون في `toggle_currency`:** `config/settings.py:78` يضبط `CSRF_COOKIE_HTTPONLY = True`، وفي `toggle_currency` السطر 1067 يقرأ `request.COOKIES.get("csrftoken", "")` الذي قد يكون فارغاً؛ يجب استخدام `django.middleware.csrf.get_token(request)` مع قالب جزئي `render()` بدلاً من f-string HTML.
  3. **`format_html()` بدون وسائط في `store/admin.py`:** استدعاء `format_html(html)` على سلاسل f-string مسبقة التشكيل في `currency_preview_info` و`invoice_print_actions` و`ProductImageInline.preview` يخرق قواعد Django 5.1+ الأمنية وسيُلغى كخطأ صريح في Django 6.0، كما يعطل التنسيق إذا احتوت القيم أقواساً `{}`.
  4. **مسار `/admin/` مكشوف وتخطي Honeypot:** كل من `Notification.notify_admin` (`store/models.py:1336`), `checkout_view` (`store/views.py:1769, 1801`), و`robots_txt` (`store/views.py:2895`) تكتب `/admin/` حرفياً بدلاً من `reverse('admin:...')`، مما يكسر التنقل للإدارة عند تفعيل `DJANGO_ADMIN_URL` المخصص!
  5. **عدم التحقق من روابط `HeroBanner.custom_url` و`Notification.link`:** يجب التأكد عبر `clean()` و`url_has_allowed_host_and_scheme` من رفض روابط `javascript:` أو `data:`.
  6. **حقول الأسرار في DB:** تخزين `google_client_secret` و`vapid_private_key` كنص صريح في `StoreSettings` مع غياب إخفاء القيمة (`PasswordInput`) في `StoreSettingsAdmin`.
  7. **`sitemap_xml`:** يجب تمرير الروابط عبر `xml.sax.saxutils.escape()` و`iri_to_uri()` لضمان صحة XML عند وجود علامات `&` أو رموز خاصة.

---

## ⚡ ثالثاً: مراجعة الأداء والكاشينج (Performance & Caching Review)

### 1. تعارض `LocMemCache` مع تعدد العمال (`--workers 2` / `--workers 3`) ونقص `redis`
- **المواقع:**
  - [config/settings.py](file:///c:/Users/hp/Desktop/projects/brandveloura/config/settings.py#L92-L111)
  - [start.sh](file:///c:/Users/hp/Desktop/projects/brandveloura/start.sh#L15) و [nixpacks.toml](file:///c:/Users/hp/Desktop/projects/brandveloura/nixpacks.toml#L11)
  - [requirements.txt](file:///c:/Users/hp/Desktop/projects/brandveloura/requirements.txt#L1-L12)
- **المشكلة:**
  1. `config/settings.py` يدعم `django.core.cache.backends.redis.RedisCache` عند وجود `REDIS_URL`، **ولكن حزمة `redis` غير موجودة أصلاً في `requirements.txt`** (وتأكدنا أنها غير مثبتة بالبيئة)! إذا أضيف `REDIS_URL` في Railway، سيتوقف التطبيق عند التشغيل بخطأ `ModuleNotFoundError: No module named 'redis'`.
  2. في حال غياب `REDIS_URL`، يعمل التطبيق بـ `LocMemCache` بينما يشغّل `start.sh` خادم Gunicorn بـ `--workers 2`. أي تعديل من المشرف يفرغ الكاش في Worker واحد فقط، ويبقى Worker الآخر يعرض الأسعار والمنتجات القديمة لمدة 15 دقيقة!
- **التعديل المقترح:** إضافة `redis>=5.0.0` (وتفعيل خدمة Redis على Railway مع `REDIS_URL` في `.env.example`)، أو استخدام `DatabaseCache` كبديل مشترك بين الـ Workers عند غياب Redis.

---

### 2. إبطال الكاش المفرط وتجاوز الإشارات في لوحة التحكم
- **المواقع:**
  - [store/signals.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/signals.py#L20-L53)
  - [store/admin.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/admin.py#L564-L605) و [L1261-L1270](file:///c:/Users/hp/Desktop/projects/brandveloura/store/admin.py#L1261-L1270)
  - [store/models.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/models.py#L132-L166) و [store/context_processors.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/context_processors.py#L100-L109)
- **الملاحظات:**
  1. عند كل عملية شراء في `checkout_view` (السطر 1762)، يُستدعى `prod.save(update_fields=['stock_quantity'])`؛ فيُطلق `product_cache_invalidation` ويمسح كامل كاش الصفحة الرئيسية حتى لو لم ينفد المخزون! يفضل تفحص `update_fields`: إذا اقتصر التحديث على `stock_quantity` وبقي المنتج متوفراً (`> 0`)، لا داعي لهدم كاش الصفحة الرئيسية في كل طلب.
  2. على العكس تماماً، الإجراءات الجماعية في `ProductAdmin` (`make_active`، `make_featured`، `mark_out_of_stock`...) و`NotificationAdmin` (`mark_as_read`، `mark_as_unread`) تستخدم `queryset.update(...)` الذي **لا يطلق إشارات Django**؛ فيظل الكاش قديماً بعد تعديلات الإدارة الجماعية! يجب استدعاء `invalidate_home_and_catalog_cache()` صراحة داخل تلك الإجراءات.
  3. في `StoreSettings.get_settings()` (السطور 137-166)، يقوم بعملية `.save()` (كتابة في قاعدة البيانات + تفريغ الكاش) أثناء عملية قراءة (`GET`) إذا اختلفت متغيرات البيئة عن قاعدة البيانات، بينما يقوم `store_context()` أصلاً بتعديل القيم على الكائن المخزن في الذاكرة؛ ويفضل فصل مزامنة متغيرات البيئة في أمر إداري أو خاصية قراءة فقط دون كتابة DB أثناء طلبات الزوار.

---

### 3. استعلامات `N+1` وفهارس قاعدة البيانات المفقودة
- **المواقع:**
  - [store/models.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/models.py#L888-L931) (`GiftBundle`) و [L1045-L1109](file:///c:/Users/hp/Desktop/projects/brandveloura/store/models.py#L1045-L1109) (`Order`)
  - [store/admin.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/admin.py#L248) (`BrandAdmin`) و [L720-L748](file:///c:/Users/hp/Desktop/projects/brandveloura/store/admin.py#L720-L748) (`GiftBundleAdmin`)
  - [templates/store/components/gift_bundles_strip.html](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/components/gift_bundles_strip.html#L68-L99)
- **الملاحظات:**
  1. `GiftBundle.get_image_url()` ينفذ `self.items.select_related('product').first()` و`GiftBundle.items_count` ينفذ `self.items.count()`؛ كلاهما يتجاهل `_prefetched_objects_cache` (مثل `prefetch_related('items__product__images')`)، ما يولد حتى **4 استعلامات إضافية لكل بطاقة باقة** لأن `gift_bundles_strip.html` يقيّم `primary_image_url` ثلاث مرات (`if`, `src`, `srcset`)!
  2. `GiftBundle.price_sar` يستدعي `StoreSettings.get_settings()` بدلاً من `StoreSettings.get_exchange_rate()`.
  3. `BrandAdmin.products_count` و`GiftBundleAdmin.items_count_display` ينفذان `count()` منفصلاً لكل صف بدون `annotate()` في `get_queryset()`.
  4. **فهارس مفقودة (`Meta.indexes`):** الحقول الأكثر استخداماً في الفلترة والترتيب بلا فهارس مركبة: `(is_active, is_featured, -created_at)` على `Product`، و`(status, -created_at)` و`customer_phone` على `Order`، و`(for_admin, is_read)` و`(recipient, is_read)` على `Notification`، و`phone` على `UserProfile`.
  5. `Category.get_descendants_and_self_ids()` ([store/models.py:473](file:///c:/Users/hp/Desktop/projects/brandveloura/store/models.py#L473)) يجلب مستوى واحداً فقط من الأبناء (`self.subcategories`) ولن يجلب الأحفاد إذا أُنشئ تصنيف من 3 مستويات.

---

## 🧩 رابعاً: جودة الكود والهيكلة والملفات الميتة (Code Quality & Maintainability)

1. **ملفات ضخمة متمركزة (God Files):**
   - [store/views.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/views.py) بلغ **3,068 سطراً** ويجمع في ملف واحد: الصفحات العامة، الكاش، السلة ومؤقت الحجز، صانع الهدايا، إتمام الطلب، الفواتير، PWA & Service Worker، المصادقة وOAuth، الإشعارات، SEO، وفحص السلامة!
   - [store/admin.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/admin.py) بلغ **1,336 سطراً**، و[templates/base.html](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/base.html) بلغ **1,591 سطراً**.
   - **الاقتراح:** تقسيم `store/views.py` إلى حزمة منظمة (`store/views/catalog.py`, `cart.py`, `checkout.py`, `gifting.py`, `auth.py`, `pwa.py`, `seo.py`) مع `store/services/cart_service.py` و`pricing.py`، وتقسيم JavaScript المضمن في `base.html` إلى ملفات ثابتة مخدومة عبر WhiteNoise.
2. **تكرار منطق السلة وحساب السعر السعودي (`DRY`):**
   - عبارة `settings.yer_per_sar or Decimal('530.00')` وحساب `int(math.ceil(yer / rate))` مكررة في 8+ مواضع بملفات `models.py` و`views.py` و`context_processors.py`.
   - منطق حساب بنود السلة متكرر بين `_render_cart_response` و`cart_view` و`checkout_view`.
   - دالة `refresh_cart_reservation(request)` مستدعاة مرتين متتاليتين بدون فائدة في `cart_add` ([السطور 892-893](file:///c:/Users/hp/Desktop/projects/brandveloura/store/views.py#L892-L893)) و`cart_update_quantity` ([السطور 929-931](file:///c:/Users/hp/Desktop/projects/brandveloura/store/views.py#L929-L931)).
   - منطق خصم وإرجاع المخزون مكرر بين `Order.restore_stock`/`deduct_stock` و`Order.save()`، وبين `checkout_view`.
   - تناقض الدرجة الافتراضية للعطور ذات الدرجات: `product_card.html` و`quick_view_modal.html` يختاران `master` افتراضياً بينما `product_detail.html:316` يختار `original` افتراضياً دون التحقق من وجود سعر لتلك الدرجة!
3. **حقول نموذج غير ظاهرة في لوحة التحكم:**
   - `Product.specifications` (`JSONField`) مستخدم في فلترة الجنس والمواصفات لكنه غير مدرج في `ProductAdmin.fieldsets`.
   - حقول `vapid_public_key`, `vapid_private_key`, `vapid_claims_email` في `StoreSettings` غير ظاهرة في `StoreSettingsAdmin.fieldsets`.
4. **أعطال واجهة الجوال وتوقيت السلة:**
   - [templates/store/partials/cart_badge.html](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/partials/cart_badge.html) لا يُحدّث شارة شريط الجوال السفلي (`#bottom-bar-cart-badge`) عبر `hx-swap-oob="true"` عند الضغط على "أضف للسلة".
   - [templates/store/partials/cart_table.html:221](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/partials/cart_table.html#L221) يستدعي `htmx.ajax('GET', '{% url "store:cart_view" %}', {target: '#cart-container'})` بينما `cart_view` يعيد صفحة `cart.html` الكاملة (الهيدر والفوتر) بدلاً من الجزء `cart_table.html` أو استخدام `select: '#cart-container'`.
   - `store_context` ([store/context_processors.py:38-46](file:///c:/Users/hp/Desktop/projects/brandveloura/store/context_processors.py#L38-L46)) يستعيد `profile.cart_data` دون استدعاء `check_and_expire_cart` أو تعيين `cart_expires_at`، ما قد يجعل العداد 0 أو يظهر عناصر منتهية الصلاحية لحظة الاستعادة.
   - أزرار `+` في `product_detail.html:323` و`quick_view_modal.html:186` لا تقيد `q.value` بـ `max="{{ product.stock_quantity }}"` في الواجهة.
5. **ملفات وقوالب مهملة (Dead Code & Repo Clutter):**
   - قوالب كتالوج لم تعد مستخدمة بعد تحويل مساراتها إلى `redirect`: [perfumes_list.html](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/perfumes_list.html)، [watches_list.html](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/watches_list.html)، [cosmetics_list.html](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/store/cosmetics_list.html) (والأيقونات/التصنيف القديم `Category.CATEGORY_TYPES` في `models.py:407`).
   - ملفات تخطيط وصورة قديمة متروكة في جذر المشروع: `gifting-share-invoices-overhaul.md`، `invoice-modal-and-gift-polish.md`، `logo.jpg` (مكررة مع `static/images/logo.jpg`).
   - مسودات `run.bat` و`run.ps1` تطبع كلمة المرور الافتراضية `admin123456` وتفترض `/admin/`.

---

## 🧪 خامساً: مراجعة الاختبارات وضمان الجودة (Tests Review)

- **الوضع الحالي:** تشغيل `python manage.py test store.tests.test_admin_routes` يفشل حالياً في اختبار واحد (`ERROR: AttributeError: 'Order' object has no attribute 'get_status_dispchelay'`) بسبب التعديل غير المحفوظ في `store/admin.py:966`.
- **نواحي غير مغطاة بالاختبارات (Test Coverage Gaps):**
  1. اختبار طلبات `HX-Boosted: true` مع `HX-Request: true` للتأكد من عدم رجوع fragments مقطوعة الرأس والتذييل في `product_list` و`product_detail` و`brands_list`.
  2. اختبار مطابقة إجمالي `Order.subtotal_yer` مع مجموع `OrderItem.total_price_yer` عند تغير سعر منتج بعد إضافته للسلة.
  3. اختبار منع تجاوز المخزون عند شراء نفس المنتج بدرجتين أو منفرداً + داخل `GiftBundle` في نفس الطلب.
  4. اختبار التحقق من `state` CSRF و`aud` الفارغ و`verified_email` في `google_auth_callback`.
  5. اختبار `test_notifications` لارتباط روابط `notify_admin` مع `DJANGO_ADMIN_URL` المخصص، واختبار إجراءات `ProductAdmin` الجماعية وإبطال الكاش.
  6. إضافة ملف `500.html` مستقل لا يعتمد على `base.html` أو قاعدة البيانات واختبار استجابته عند تعطل قاعدة البيانات.

---

## 📄 سادساً: التوثيق والبنية التشغيلية (Documentation & DevOps)

1. **`README.md` غير محدث:** يذكر `Django 6.0+` و`83 Passed Tests` بينما المشروع يعتمد فعلياً على `Django>=5.1,<5.2` (في `requirements.txt`) ولديه `133` اختباراً في آخر التزام (`d12815b`).
2. **`.env.example`:** يوصي بـ `DJANGO_ALLOWED_HOSTS=*` ويفتقد لتوثيق `REDIS_URL` و`VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY`/`VAPID_CLAIMS_EMAIL`.
3. **إعدادات `Dockerfile` و`requirements.txt` و`nixpacks.toml`:**
   - الحزم في `requirements.txt` غير مقيدة بإصدارات دقيقة (`>=`) ولا تشمل `redis`.
   - حاوية `Dockerfile` تعمل بصلاحية `root` دون إنشاء مستخدم غير جذري (`USER appuser`).
   - وجود `nixpacks.toml` بجانب `railway.json` (`builder: DOCKERFILE`) و`Procfile` بأوامر تشغيل متباينة (`--workers 3` مقابل `--workers 2 --threads 4`).
4. **أخطاء `500.html`:** قالب [templates/500.html](file:///c:/Users/hp/Desktop/projects/brandveloura/templates/500.html#L1) يرث من `base.html`؛ في حالة انهيار قاعدة البيانات قد يفشل عرض صفحة الخطأ 500 نفسها.

---

## 🎯 سابعاً: خطة العمل المقترحة حسب الأولوية (Prioritized Roadmap)

### المرحلة 1: إصلاحات عاجلة ومانعة للأعطال (P0 — Immediate Fixes)
- [x] **إصلاح `store/admin.py:966`:** تصحيح `obj.get_status_dispchelay()` إلى `obj.get_status_display()` وإعادة التحقق من نجاح كامل الاختبارات (141 اختباراً بعد التوسعة).
- [x] **إصلاح تعارض `hx-boost`:** إضافة دالة `_is_htmx_partial()` (`not request.headers.get('HX-Boosted')`) في `product_list_view` و`product_detail_view` و`brands_list_view` و`brand_detail_view` و`cart_view`.
- [x] **إصلاح السكربتات وCSRF تحت `hx-boost`:** إضافة `hx-boost="false"` لنماذج الدخول والتسجيل وإتمام الطلب ورابط إضافة القسم بالإدارة، وتحديث CSRF عبر `#bv-csrf-token` و`htmx:configRequest`، وتشغيل تهيئة `checkout.html` و`gift_builder.html` و`account.html` و`gift_slip.html` عند `readyState !== 'loading'`، وتغليف سكربت `home.html` بـ IIFE مع تنظيف المؤقتات.
- [x] **إصلاح `Service Worker`:** ترقية الإصدار إلى `brand-veloura-pwa-v5` وقصر `Cache-First` على `/static/` فقط واستثناء `/partials/` و`/notifications/` وترويسة `HX-Request` وردود `Cache-Control: no-store / private` (بما يحمي أي `DJANGO_ADMIN_URL` مخصص دون كشفه).
- [x] **إصلاح تناسق Checkout والمخزون:** توحيد السعر الحي عند إنشاء `OrderItem` داخل `transaction.atomic()`، وتجميع كميات `product_id` عبر الدرجات والباقات لمنع البيع الزائد مع خصم ذري عبر `F()`، وإضافة تحقق الخادم للحقول الإلزامية ونشاط `ShippingZone` و`PaymentAccount`.

### المرحلة 2: تحصين الأمان والاستقرار (P1 — High Priority)
- [x] استبدال `SECRET_KEY` الثابتة و`DEBUG=True` و`ALLOWED_HOSTS=*` في `config/settings.py` بإعدادات آمنة افتراضياً مع دعم `brandveloura.com` وRailway وبناء `Dockerfile` (`collectstatic`) دون تعطل.
- [x] إضافة `state` CSRF عشوائي وإلزام فحص `aud` و`iss` و`g_csrf_token` و`email_verified` في Google OAuth وإزالة `@csrf_exempt` عن `push_subscribe` مع إرسال `X-CSRFToken` من `base.html`.
- [x] تفعيل `validate_password()` واستبدال `locals()` بسياق صريح في `register_view` وتطبيع أرقام الهواتف في البحث والمطابقة (`_normalize_phone`).
- [x] إضافة `|escapejs` و`|urlencode` ونقل التوست إلى `hx-on::after-request` (`HX-Trigger: cartUpdated`) مع مستمعات `outOfStock` / `maxStockReached` في `base.html`.
- [x] استبدال `/admin/` الثابتة بـ `reverse('admin:...')` في إشعارات `checkout_view` و`Notification.notify_admin` مع الإبقاء على `Disallow: /admin/` في `robots.txt` لعدم كشف المسار السري `DJANGO_ADMIN_URL` للزواحف، وإخفاء أسرار `StoreSettingsAdmin` عبر `PasswordInput`.
- [x] إضافة `redis>=5.0.0` إلى `requirements.txt` وتوثيق `REDIS_URL` في `.env.example` و`README.md`.

### المرحلة 3: الأداء والواجهة والبيانات (P2 — Medium Priority)
- [x] تحسين `GiftBundle.get_image_url()` و`items_count` و`BrandAdmin`/`GiftBundleAdmin` (`get_queryset` مع `prefetch_related` و`annotate`) لتفادي استعلامات `N+1`، ودعم التفرع متعدد المستويات في `Category.get_descendants_and_self_ids()`.
- [x] ضبط `StoreSettings.get_settings()` لتجنب الكتابة المتكررة في قاعدة البيانات أثناء طلبات `GET`، ومنع إبطال كامل كاش الرئيسية عند مجرد خصم مخزون مع بقائه `> 0`، مقابل إبطال الكاش في Bulk Actions بلوحة التحكم، وتأمين `HeroBanner.custom_url` ضد `javascript:`/`data:`.
- [x] تحديث شارة الجوال `#bottom-bar-cart-badge` بـ `hx-swap-oob="innerHTML"` وتحديث `#cart-container` جزئياً عند انتهاء مؤقت السلة، وتهيئة `cart_expires_at` عند استعادة السلة في `store_context`، وتوحيد افتراضات الدرجة وحدود الكمية في القوالب.
- [x] إضافة 10 فهارس DB مركبة عبر الهجرة `store/migrations/0027_add_performance_indexes.py`، وفصل `templates/500.html` كصفحة مستقلة لا تعتمد على `base.html` أو قاعدة البيانات.
- [x] تصحيح استدعاءات `format_html()` في `store/admin.py` وتنظيف `cancel_and_restore_stock_action` و`Order` (إزالة التكرار عبر `_adjust_stock_from_items`). *(ملاحظة: أُبقي على إخفاء `specifications` في `ProductAdmin` التزاماً باختبارات `test_streamlined_admin_and_specs.py`، كما أُبقي على إخفاء حقول VAPID من نموذج التعديل العام تجنباً لتصفيرها عند الحفظ السريع مع تهيئة `PasswordInput` لقيمتها متى ما فُعّلت).*

### المرحلة 4: إعادة الهيكلة والتنظيف والتوثيق (P3 — Clean-up & Architecture)
- [ ] تقسيم `store/views.py` و`store/admin.py` إلى وحدات فرعية متعددة (مؤجل لمسار إعادة هيكلة مستقل حفاظاً على استقرار الإنتاج وعدم كسر الاستيرادات الحالية في `urls.py` والاختبارات؛ بينما أُضيفت دوال مساعدة موحدة لتقليل التكرار).
- [x] إزالة القوالب والملفات غير المستخدمة (`templates/store/perfumes_list.html`, `watches_list.html`, `cosmetics_list.html`, والملفات الجذرية `logo.jpg`, `gifting-share-invoices-overhaul.md`, `invoice-modal-and-gift-polish.md`).
- [x] تحديث `README.md` و`.env.example` وإضافة مستخدم غير جذري (`USER appuser`) في `Dockerfile`.

---

> **حالة التنفيذ (تحديث 2026-11-17):** تم تطبيق كافة البنود المؤشر عليها أعلاه وإضافة حزمة الاختبارات الجديدة [test_security_and_hardening.py](file:///c:/Users/hp/Desktop/projects/brandveloura/store/tests/test_security_and_hardening.py).
