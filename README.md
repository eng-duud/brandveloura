# 💎 Brand Veloura — بوتيك العطور والساعات الفاخرة

<div align="center">

![Brand Veloura Banner](https://brandveloura.com/static/images/logo.png)

**منصة تجارة إلكترونية فاخرة وتطبيق ويب تقدمي (PWA) فائق السرعة، مبني خصيصاً لقطاع المنتجات الفاخرة ومخصص للسوق اليمني والخليجي.**

[![Django](https://img.shields.io/badge/Django-6.0+-092e20?style=for-the-badge&logo=django&logoColor=white)](https://www.djangoproject.com/)
[![Python](https://img.shields.io/badge/Python-3.12+-3776ab?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-3.4+-38bdf8?style=for-the-badge&logo=tailwind-css&logoColor=white)](https://tailwindcss.com/)
[![HTMX](https://img.shields.io/badge/HTMX-1.9+-336699?style=for-the-badge&logo=htmx&logoColor=white)](https://htmx.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-336791?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Railway](https://img.shields.io/badge/Deployed_on-Railway-0B0D0E?style=for-the-badge&logo=railway&logoColor=white)](https://railway.com/)
[![Cloudflare](https://img.shields.io/badge/Protected_by-Cloudflare-F38020?style=for-the-badge&logo=cloudflare&logoColor=white)](https://www.cloudflare.com/)
[![Tests](https://img.shields.io/badge/Tests-83%20Passed-success?style=for-the-badge&logo=checkmarx&logoColor=white)](#-حزمة-الاختبارات-وضمان-الجودة)

🌐 **المتجر الحي:** [brandveloura.com](https://brandveloura.com) | 🚀 **سيرفر الاستضافة:** [web-production-f1ff6.up.railway.app](https://web-production-f1ff6.up.railway.app)

</div>

---

## 📖 جدول المحتويات
- [نظرة عامة](#-نظرة-عامة)
- [أبرز المميزات والخصائص](#-أبرز-المميزات-والخصائص)
- [التقنيات المستخدمة](#-التقنيات-المستخدمة-tech-stack)
- [التشغيل والتثبيت محلياً](#-التشغيل-والتثبيت-محلياً-local-development)
- [حزمة الاختبارات وضمان الجودة](#-حزمة-الاختبارات-وضمان-الجودة)
- [النشر على منصة Railway السحابية](#-النشر-على-منصة-railway-السحابية)
- [مرجع متغيرات البيئة](#-مرجع-متغيرات-البيئة-environment-variables)
- [هيكلية المشروع](#-هيكلية-المشروع)
- [الأوامر الإدارية المخصصة](#-الأوامر-الإدارية-المخصصة)

---

## 🌟 نظرة عامة

**براند فيلورا (Brand Veloura)** هو متجر متكامل للتجارة الإلكترونية يجمع بين فخامة العرض والسرعة الفائقة وتجربة المستخدم السلسة. تم تصميمه لمعالجة خصوصية السوق اليمني والخليجي؛ من حيث تعدد العملات (ريال يمني / ريال سعودي)، طرق الدفع المحلية كالكريمي والمحافظ الإلكترونية، ورفع وتأكيد سندات التحويل المالي، مع تقديم تجربة تطبيق أصلي على الهواتف الذكية عبر تقنية الـ PWA دون الحاجة لتحميل تطبيقات من المتاجر.

---

## ✨ أبرز المميزات والخصائص

### 1. نظام الأقسام والتصنيفات الهرمي المرن (Unified Category System)
- **أقسام رئيسية وفرعية غير محدودة:** إمكانية إنشاء تصنيفات شجرية حرة (عطور، ساعات، بخور، مستحضرات تجميل، هدايا...) دون أي قيود برمجية مصطنعة.
- **إدارة سلسة وبسيطة:** لوحة إدارة نظيفة تتيح إنشاء القسم الرئيسي بتركه حراً، أو اختياره كقسم فرعي تابع لقسم أعلى منه مباشرة.
- **مزامنة ذكية مع الماركات:** ربط المنتجات بالماركات العالمية تلقائياً مع فلاتر حية سريعة.

### 2. محرك التسعير المزدوج الذكي (Dual Currency Engine)
- **تسعير متعدد العملات:** إدخال الأسعار بالريال اليمني (YER) مع حساب آلي دقيق لمعادلها بالريال السعودي (SAR) في كافة الواجهات.
- **تحديث سعر الصرف اليومي بنقرة زر:** تحديث سعر صرف (YER / SAR) من لوحة التحكم لينعكس فورياً في كامل المتجر والسلة وصفحات المنتجات.
- **مفتاح تحويل فوري للعميل:** زر أنيق في ترويسة الموقع للتبديل الفوري بين عرض الأسعار بالريال اليمني أو السعودي.

### 3. تدفق الدفع والتحقق المالي المحلي (Manual & Local Payments Flow)
- **دعم البنوك والمحافظ اليمنية:** حسابات بنك الكريمي، محفظة جوالي، كاش، الحوالات المصرفية، والدفع عند الاستلام (COD).
- **نسخ الحساب بنقرة واحدة:** تسهيل نسخ رقم الحساب أو الآيبان لراحة المشتري.
- **رفع ومراجعة إشعارات التحويل:** إمكانية رفع صورة سند التحويل البنكي أو إدخال رقم الحوالة أثناء إنهاء الطلب.
- **فحص وتكبير السندات (Lightbox Preview):** لوحة تحكم إدارية تمكّن الإدارة من معاينة سند التحويل وتكبيره بضغطة زر وتأكيد حالة الدفع بنقرة واحدة.
- **إشعار فوري عبر واتساب:** زر مباشر بعد إتمام الطلب لمشاركة تفاصيل الفاتورة والسند مع خدمة العملاء لسرعة التجهيز.

### 4. تجربة الجوال الفائقة وتطبيق الويب التقدمي (Mobile-First PWA)
- **تثبيت التطبيق بضغطة واحدة:** بانر ذكي يتيح للزائر تثبيت المتجر كتطبيق مستقل على شاشة هاتفه الرئيسية (Android & iOS).
- **شريط تنقل سفلي (Bottom Navigation Bar):** إمكانية الوصول السريع للرئيسية، الأقسام، السلة، والملف الشخصي بأسلوب التطبيقات الأصلية.
- **درج سلة الشراء التفاعلي (Cart Drawer):** فتح واستعراض السلة وتعديل الكميات دون الحاجة لمغادرة الصفحة الحالية.
- **المعاينة السريعة للمنتج (Quick View Modal):** نافذة منبثقة تفاعلية تعمل عبر تقنية **HTMX** لعرض تفاصيل وصور المنتج والطلب السريع في أقل من 50 جزء من الثانية دون إعادة تحميل الصفحة.
- **دعم العمل في ظروف ضعف الإنترنت (Offline Caching):** معمارية Service Worker تحفظ الملفات الثابتة لتشغيل فوري ومستقر.

### 5. حماية أمنية متقدمة وفخ للوحة التحكم (Admin Honeypot)
- **مسار إدارة مخصص وسري:** إمكانية تخصيص رابط لوحة التحكم عبر متغير بيئة `DJANGO_ADMIN_URL` (مثال: `/cpanel-secure-path/`).
- **فخ وهمي لمخترقي المسارات التقليدية (Admin Honeypot):** المسار التقليدي `/admin/` يعيد كود خطأ (404 Not Found) مضلل لصد هجمات المسح الآلي والتخمين.

---

## 🛠 التقنيات المستخدمة (Tech Stack)

| المجال | التقنية | الاستخدام |
| :--- | :--- | :--- |
| **Backend** | Python 3.12+ / Django 6.x | المنطق البرمجي، الأمان، وإدارة البيانات |
| **Admin UI** | Django Unfold | واجهة إدارة حديثة وفاخرة متوافقة مع الهواتف |
| **Frontend** | Tailwind CSS & HTMX | واجهات تفاعلية وسريعة بدون ثقل أطر عمل SPA |
| **Database** | PostgreSQL | قاعدة البيانات السحابية للإنتاج |
| **Storage** | Cloudinary & WhiteNoise | استضافة سحابية فائقة للصور مع كاش سريع للملفات الثابتة |
| **PWA** | Service Worker & Web Manifest | تحويل المتجر لتطبيق جوال وتخزين محلي |
| **Server / Cloud** | Gunicorn & Railway | تشغيل ونشر الحاويات السحابية بأداء عالي |
| **Security & CDN** | Cloudflare | شهادات SSL مجانية، تسريع المحتوى، وحماية من الهجمات |

---

## 💻 التشغيل والتثبيت محلياً (Local Development)

### المتطلبات المسبقة:
- بايثون 3.12 أو أحدث مثبت على جهازك.
- أداة Git.
- Node.js/npm (اختياري عند إعادة بناء Tailwind محلياً؛ صورة Docker تعيد البناء تلقائياً).

### خطوات التثبيت:

1. **استنساخ المستودع (Clone):**
   ```bash
   git clone https://github.com/eng-duud/brandveloura.git
   cd brandveloura
   ```

2. **إنشاء وتفعيل البيئة الافتراضية:**
   ```bash
   # لنظام ويندوز (PowerShell):
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1

   # لنظام ماك / لينكس:
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **تثبيت الحزم المطلوبة:**
   ```bash
   pip install -r requirements.txt
   ```

4. **إعادة بناء CSS عند تعديل القوالب أو الأنماط (اختياري محلياً):**
   ```bash
   npm ci
   npm run build:css
   ```
   يتولى بناء Docker هذه الخطوة تلقائياً عند إنشاء صورة الإنتاج.

5. **إعداد ملف متغيرات البيئة:**
   انسخ ملف `.env.example` إلى `.env`:
   ```bash
   # ويندوز (PowerShell):
   Copy-Item .env.example .env

   # لينكس / ماك:
   cp .env.example .env
   ```

6. **تطبيق هجرات قاعدة البيانات:**
   ```bash
   python manage.py migrate
   ```

7. **جمع الملفات الثابتة وإعداد manifest:**
   ```bash
   python manage.py collectstatic --noinput
   ```

8. **تعبئة البيانات الأولية وحساب المدير التجريبي:**
   ```bash
   # إضافة منتجات فاخرة وحسابات بنكية ومناطق شحن أولية:
   python manage.py seed_data

   # أو إنشاء حساب مدير مخصص بدون أسئلة تفاعلية:
   python manage.py setup_admin --username=admin --password=yourpassword --email=admin@brandveloura.com
   ```

9. **تشغيل خادم التطوير:**
   ```bash
   python manage.py runserver
   ```
   تفضل بزيارة المتجر على المتصفح عبر: `http://127.0.0.1:8000/`

---

## 🧪 حزمة الاختبارات وضمان الجودة

يحتوي المشروع على حزمة اختبارات شاملة مؤتمتة (Unit & Integration Tests) تغطي مسارات المتجر، تدفق السلة والطلبات، رفع السندات، حساب العملات، ومسارات لوحة الإدارة والأمان:

```bash
python manage.py test
```

> **آخر تحقق:** اجتازت جميع الـ **90 اختباراً** بنجاح، بما فيها اختبارات صيغ WebP و`srcset`.

---

## ☁️ النشر على منصة Railway السحابية

المشروع مهيأ تلقائياً للعمل بأعلى كفاءة على [Railway](https://railway.com) باستخدام سكربت الإقلاع التلقائي `start.sh` وملف تكوين الإنتاج:

1. ارفع الكود إلى مستودع GitHub الخاص بك:
   ```bash
   git push origin main
   ```
2. ادخل إلى لوحة تحكم Railway وأنشئ مشروعاً جديداً عبر خيار **Deploy from GitHub repo**.
3. أضف قاعدة بيانات **PostgreSQL** بنقرة واحدة (`+ New -> Database -> Add PostgreSQL`). سيقوم Railway بربط متغير `DATABASE_URL` تلقائياً.
4. أضف متغيرات البيئة في قسم **Variables** (راجع الجدول أدناه).
5. سيتولى Railway بناء الحاوية وتشغيل الهجرات (`migrate`) وإنشاء حساب المشرف آلياً وتشغيل خادم Gunicorn فائق الأداء.

---

## 🔐 مرجع متغيرات البيئة (Environment Variables)

| المتغير | مطلوب | الوصف | مثال |
| :--- | :---: | :--- | :--- |
| `DJANGO_SECRET_KEY` | ✅ | المفتاح السري لتشفير الجلسات في بيئة الإنتاج | `django-insecure-xxxx...` |
| `DJANGO_DEBUG` | ✅ | وضع التطوير (`True` محلياً، و `False` في الإنتاج) | `False` |
| `DJANGO_ALLOWED_HOSTS` | ✅ | النطاقات المصرح لها بالاتصال بالمتجر | `brandveloura.com,*.railway.app` |
| `CSRF_TRUSTED_ORIGINS` | ✅ | النطاقات الموثوقة لمنع هجمات CSRF | `https://brandveloura.com,https://*.up.railway.app` |
| `DJANGO_ADMIN_URL` | ⚙️ | المسار السري للوحة الإدارة (يحمي من الاختراق) | `cpanel-0x110` |
| `DATABASE_URL` | ✅ | رابط الاتصال بقاعدة بيانات PostgreSQL | `postgresql://user:pass@host:5432/db` |
| `DJANGO_SUPERUSER_USERNAME`| ⚙️ | اسم مستخدم المدير للإنشاء التلقائي عند الإقلاع | `admin` |
| `DJANGO_SUPERUSER_PASSWORD`| ⚙️ | كلمة مرور المدير للإنشاء التلقائي عند الإقلاع | `SecretAdminPass2026!` |
| `CLOUDINARY_CLOUD_NAME` | ⚙️ | اسم سحابة Cloudinary لحفظ الصور | `brandveloura-cloud` |
| `CLOUDINARY_API_KEY` | ⚙️ | مفتاح واجهة برمجة تطبيقات Cloudinary | `123456789012345` |
| `CLOUDINARY_API_SECRET` | ⚙️ | السر الخاص بسحابة Cloudinary | `AbCdEfGhIjKlMnOpQrStUvWxYz` |
| `GOOGLE_CLIENT_ID` | ⚙️ | معرف عميل Google لتسجيل الدخول السريع | `xxxx.apps.googleusercontent.com` |
| `STORE_WHATSAPP` | ⚙️ | رقم الواتساب لخدمة العملاء وتأكيد الفواتير | `967770000000` |

---

## 📂 هيكلية المشروع

```text
brandveloura/
├── config/                      # التكوين الأساسي للمشروع
│   ├── settings.py              # إعدادات Unfold, PostgreSQL, Cloudinary, WhiteNoise
│   ├── urls.py                  # المسارات العامة وفخ لوحة الإدارة
│   └── wsgi.py                  # مدخل خادم الإنتاج WSGI
├── store/                       # التطبيق الرئيسي للمتجر
│   ├── models.py                # جداول الأقسام، الماركات، المنتجات، الطلبات، والسندات
│   ├── admin.py                 # تخصيص لوحة إدارة Unfold الفاخرة وتكبير السندات
│   ├── views.py                 # منطق العرض وتدفق الطلب ومعالجات HTMX
│   ├── urls.py                  # مسارات صفحات المتجر والسلة وإتمام الشراء
│   ├── tests/                   # حزمة الاختبارات الشاملة (90 اختباراً)
│   └── management/commands/     # أوامر مخصصة (seed_data, setup_admin)
├── templates/                   # قوالب HTML المبنية بـ Tailwind CSS و HTMX
│   ├── base.html                # القالب الأساسي وشريط التنقل السفلي والـ PWA
│   └── store/                   # قوالب المنتجات، السلة، الدفع، والملف الشخصي
├── static/                      # الملفات الثابتة، الخطوط، والأيقونات
│   ├── manifest.json            # ملف تعريف تطبيق الويب التقدمي (PWA)
│   └── sw.js                    # مشغل الـ Service Worker للكاش
├── start.sh                     # سكربت الإقلاع التلقائي للإنتاج على Railway
├── Dockerfile                   # بناء حاوية دوكر للإنتاج
├── .railwayignore               # استثناء الملفات الضخمة وتسريع الرفع
├── requirements.txt             # حزم بايثون المعتمدة
└── README.md                    # هذا الدليل التوثيقي الشامل
```

---

## ⚡ الأوامر الإدارية المخصصة

تم تزويد المشروع بأوامر مخصصة عبر `manage.py` لتسهيل الإدارة والنشر:

- **`python manage.py seed_data`**: تعبئة المتجر ببيانات تجريبية راقية (أقسام، ماركات، عطور، ساعات، إعدادات عملة، حسابات الكريمي والمحافظ، ومناطق الشحن).
- **`python manage.py setup_admin`**: إنشاء أو تحديث حساب المشرف الأعلى (Superuser) دون الحاجة لمدخلات تفاعلية، مع دعم قراءة المتغيرات من بيئة التشغيل تلقائياً.

---

## 📄 الترخيص وحقوق الملكية

تم تطوير هذا النظام لصالح بوتيك **Brand Veloura**. جميع الحقوق محفوظة © 2026.
