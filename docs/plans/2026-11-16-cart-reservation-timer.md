# خطة تنفيذ نظام مؤقت حجز السلة وتحرير المخزون (Cart Reservation Timer)

> **المعيار الفني:** Brand Veloura Luxury Urgency & Real Inventory Protection.
> **الهدف:** حماية مخزون المتجر من الحجوزات المعلقة والفارغة، وتوفير مؤقت حجز زمني فاخر ومتحكم به بالدقائق من لوحة الإدارة (StoreSettings)، مع عداد تنازلي حي يظهر للعميل في السلة والدفع، وإلغاء حجز السلة تلقائياً عند انتهاء الوقت لإتاحة المنتجات للعملاء الآخرين.

---

## 1. التشخيص وهدف الميزة (Goal & Context)

### أ. الوضع الحالي:
- حالياً، المنتجات المضافة للسلة تظل محفوظة في الجلسة وقاعدة البيانات دون حد زمني لانتهاء الجلسة.
- المخزون الفعلي `stock_quantity` يُخصم فقط عند إتمام الطلب في `checkout_view`.
- ومع ذلك، بقاء المنتجات في السلة لعدة أيام أو أسابيع دون إتمام الشراء قد يوهم العميل أن القطع محجوزة له، أو يسبب تعارضاً إذا نفد المخزون أثناء غيابه. والأهم من ذلك: عدم وجود مؤقت يفوّت على المتجر عامل **الحث والتحفيز على الشراء (Scarcity & Urgency)** الذي يزيد معدل التحويل (Conversion Rate) ويمنع تجميد رغبات الشراء بحجوزات وهمية.

### ب. المطلوب تنفيذه:
1. **مدة حجز قابلة للتحكم بالكامل من لوحة الإدارة (`StoreSettings`):**
   - إضافة خيار `cart_reservation_minutes` (الافتراضي: 60 دقيقة، ويمكن للأدمن تعيينها 30 أو 45 أو 120 دقيقة، أو تعيينها 0 لتعطيل المؤقت).
2. **تتبع توقيت الحجز في الجلسة والحساب (`cart_expires_at`):**
   - عند إضافة أو تعديل عناصر في السلة، يتم ضبط موعد انتهاء الحجز `expires_at = now + (cart_reservation_minutes * 60)`.
3. **عداد تنازلي حي وفخم (Luxury Live Countdown):**
   - ظهور شريط فاخر بلون الورد والذهب في أعلى سلة المشتريات وصفحة الدفع:
     `⏳ المنتجات في سلتك محجوزة لك مؤقتاً: [45:20 دقيقة] - أكمل طلبك قبل تحرير الحجز لإتاحة القطع للمتسوقين الآخرين`.
4. **التحرير التلقائي عند انتهاء الوقت (Auto-Release on Expiration):**
   - إذا انتهت المدة دون إتمام الطلب، يتم تفريغ السلة تلقائياً وإخطار العميل برسالة راقية:
     *"انتهت مدة حجز السلة المؤقتة وتم تحرير المنتجات لتوفيرها للمتسوقين الآخرين. يمكنك اختيار منتجاتك من جديد."*

---

## 2. الهيكلية المعمارية للحل المقترح (Architecture)

```mermaid
flowchart TD
    A["العميل يضيف منتجاً للسلة"] --> B["ضبط وقت انتهاء الحجز في Session & Profile"]
    B --> C["قراءة المدة من StoreSettings (مثلاً 60 دقيقة)"]
    C --> D["عرض شريط العد التنازلي الفاخر في السلة وصفحة الدفع"]
    
    D --> E{"هل انتهت المدة؟"}
    E -->|نعم| F["تفريغ السلة تلقائياً وتحرير الحجز"]
    F --> G["تنبيه العميل برسالة راقية: انتهت مهلة الحجز"]
    
    E -->|لا (خلال المهلة)| H["العميل يدخل صفحة الدفع"]
    H --> I["تأكيد الطلب والدفع بنجاح"]
    I --> J["خصم المخزون الفعلي وتصفير السلة"]
```

---

## 3. خطة التغييرات المقترحة بالملفات (Proposed Changes)

### 1. طبقة النماذج والإدارة (Models & Admin)
#### `store/models.py`
- إضافة حقل في نموذج `StoreSettings`:
  ```python
  cart_reservation_minutes = models.PositiveIntegerField(
      default=60,
      verbose_name='مدة حجز السلة بالدقائق (المؤقت)',
      help_text='المدة بالدقائق التي تظل فيها عناصر السلة محجوزة للعميل قبل انتهاء الصلاحية وتحرير المخزون (مثال: 30 أو 60 دقيقة. ضع 0 لتعطيل المؤقت).'
  )
  ```
- إنشاء وتطبيق الهجرة: `python manage.py makemigrations store --name storesettings_cart_reservation_minutes` و `python manage.py migrate`.

#### `store/admin.py`
- إضافة الحقل `cart_reservation_minutes` في `StoreSettingsAdmin` ضمن قسم إدارة المخزون والمتجر ليسهل تعديله بزر وسهم بسيط.

---

### 2. طبقة العرض والخدمات (Views & Context Processors)
#### `store/views.py`
- **دالة التحقق والتفريغ الآلي عند انتهاء الحجز:**
  - إنشاء دالة مساعدة `check_and_expire_cart(request)`:
    - تفحص إذا كان هناك سلة مفعلة وإذا تم تجاوز `cart_expires_at`.
    - إذا انتهى الوقت، تفرغ السلة من `request.session['cart']` ومن `user.store_profile.cart_data` وترسل رسالة تنبيه للعميل.
- **تحديث `cart_add` و `cart_update_quantity`:**
  - عند إضافة أو تعديل عناصر في السلة، يتم تحديث موعد الانتهاء `request.session['cart_expires_at'] = now + minutes * 60` ومزامنته مع الحساب.
- **تحديث `cart_view` و `checkout_view`:**
  - استدعاء `check_and_expire_cart(request)` في بداية العرض.
  - حساب الثواني المتبقية `remaining_seconds` وتمريرها للقالب للعداد الحي.
- **تحديث `_render_cart_response`:**
  - تمرير الثواني المتبقية حتى تتحدث استجابات HTMX مع العداد بسلاسة.

#### `store/context_processors.py`
- تمرير `cart_remaining_seconds` و `cart_reservation_minutes` تلقائياً للسياق العام.

---

### 3. طبقة الواجهات والقوالب (Templates & Frontend)
#### `templates/store/partials/cart_table.html`
- إضافة شريط الحجز والعداد التنازلي التفاعلي بلغة جافاسكريبت خفيفة (Vanilla JS بدون مكتبات خارجية):
  ```html
  {% if cart_remaining_seconds > 0 and store_settings.cart_reservation_minutes > 0 %}
  <div id="cart-reservation-banner" class="bg-gradient-to-r from-pink-50 via-rose-50 to-pink-50 border border-brand-200/90 rounded-2xl p-3 sm:p-4 mb-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 shadow-2xs">
      <div class="flex items-center gap-3">
          <div class="w-9 h-9 rounded-xl bg-brand-500/10 text-brand-600 flex items-center justify-center shrink-0">
              <i data-lucide="timer" class="w-5 h-5 animate-pulse"></i>
          </div>
          <div>
              <p class="text-xs sm:text-sm font-bold text-slate-900 leading-snug">
                  منتجاتك محجوزة في سلتك مؤقتاً
              </p>
              <p class="text-[11px] text-slate-500">
                  يرجى استكمال الطلب قبل انتهاء العداد لتحرير الحجز وإتاحة القطع للآخرين
              </p>
          </div>
      </div>
      <div class="flex items-center gap-2 bg-white border border-brand-200 px-3.5 py-1.5 rounded-xl shrink-0 self-end sm:self-auto shadow-2xs">
          <i data-lucide="clock" class="w-4 h-4 text-brand-500"></i>
          <span id="cart-timer-display" data-seconds="{{ cart_remaining_seconds }}" class="font-mono font-extrabold text-sm sm:text-base text-brand-600 font-num">
              --:--
          </span>
      </div>
  </div>
  {% endif %}
  ```
- كود جافاسكريبت لتشغيل العداد ثانية بثانية، وعند انتهاء العداد لـ `00:00` يقوم بتحديث السلة تلقائياً (`htmx.ajax` أو `window.location.reload()`) لعرض رسالة التحرير والتفريغ.

#### `templates/store/checkout.html`
- عرض شريط المؤقت المماثل في صفحة إتمام الطلب لتذكير العميل بالوقت المتبقي لإتمام السداد ورفع السند.

---

### 4. الاختبارات الآلية (Automated Verification)
- إضافة اختبارات في `store/tests/test_user_routes.py`:
  1. اختبار ضبط `cart_expires_at` عند إضافة منتج للسلة.
  2. اختبار تفريغ السلة تلقائياً عند تجاوز الوقت المحدد (`now > expires_at`).
  3. اختبار إمكانية تعطيل المؤقت من إعدادات المتجر بجعل المدة `0`.
  4. اختبار عرض العداد التنازلي والثواني المتبقية في سياق السلة وصفحة الدفع.
  5. فحص كافة اختبارات النظام (125+ اختباراً) للتأكد من عدم تأثر أي وظيفة قائمة.

---

## 4. أسئلة للتأكيد والخيارات (User Review Required)

> [!IMPORTANT]
> **المدة الافتراضية المقترحة:**
> جعلنا المدة الافتراضية **60 دقيقة** (ساعة كاملة)، مع إمكانية تغييرها في أي وقت من لوحة الإدارة إلى 30 دقيقة أو ساعتين أو أي رقم تفضله. هل تناسبك مهلة الـ 60 دقيقة كبداية افتراضية؟
> 
> **سلوك المؤقت عند إضافة منتج جديد:**
> عند قيام العميل بإضافة قطعة جديدة لسلة فيها منتجات سابقة، هل يفضل إعادة تمديد العداد للبدء من جديد (مثال: إعادة المؤقت لـ 60 دقيقة)، أم الاحتفاظ بالتوقيت الأصلي للقطعة الأولى؟ (الأفضل والمتبع عالمياً هو إعادة التمديد ليتمكن العميل من متابعة تسوقه براحة).

---

يرجى مراجعة الخطة وإعطاء إشارة البدء للتنفيذ الفوري.
