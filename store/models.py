import uuid
import os
import re
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils.text import slugify
from django.core.exceptions import ValidationError


def sanitize_image_url(url, fallback=''):
    """تنظيف وتصحيح روابط الصور وتفادي مشاكل البادئات المكررة في Cloudinary"""
    if not url:
        return fallback
    url_str = str(url).strip()
    if 'image/upload/http' in url_str:
        c_name = getattr(settings, 'CLOUDINARY_STORAGE', {}).get('CLOUD_NAME', '') or os.getenv('CLOUDINARY_CLOUD_NAME', 'ct6yw21y')
        pattern = r'https?://res\.cloudinary\.com/[^/]+/image/upload/https?:/+(?:res\.cloudinary\.com/[^/]+/)?'
        url_str = re.sub(pattern, f'https://res.cloudinary.com/{c_name}/image/upload/', url_str)
    return url_str


class StoreSettings(models.Model):
    """إعدادات المتجر العامة وسعر الصرف والهوية"""
    store_name = models.CharField(max_length=200, default='Brand Veloura', verbose_name='اسم المتجر')
    store_tagline = models.CharField(max_length=250, default='بوتيك الفخامة الأول للعطور والساعات ومستلزمات التجميل', verbose_name='الشعار النصي')
    store_logo = models.ImageField(upload_to='settings/', null=True, blank=True, verbose_name='شعار المتجر')
    
    # سعر صرف الريال السعودي مقابل اليمني (كم ريال يمني يساوي 1 ريال سعودي)
    yer_per_sar = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=Decimal('530.00'), 
        verbose_name='سعر صرف 1 ريال سعودي بالريال اليمني',
        help_text='مثال: 530 يعني كل 1 ريال سعودي = 530 ريال يمني. سيتم قسمة السعر اليمني على هذا الرقم تلقائياً'
    )
    
    contact_phone = models.CharField(max_length=50, default='+967 770 000 000', verbose_name='رقم الهاتف')
    contact_whatsapp = models.CharField(max_length=50, default='967770000000', verbose_name='رقم الواتساب للطلبات والدعم')
    contact_instagram = models.CharField(max_length=100, blank=True, default='brandveloura', verbose_name='حساب انستغرام')
    
    announcement_text = models.CharField(
        max_length=300, 
        default='✨ أهلاً بكم في Brand Veloura — عطور وساعات ومستحضرات تجميل أصلية 100% مع توصيل سريع لكافة المحافظات', 
        verbose_name='نص شريط الإعلانات العلوي'
    )
    is_announcement_active = models.BooleanField(default=True, verbose_name='تفعيل شريط الإعلانات')
    
    # القسم الافتراضي لصفحة الأقسام والكتالوج
    default_category = models.ForeignKey(
        'Category',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name='القسم الافتراضي لصفحة الأقسام',
        help_text='حدد القسم الرئيسي الذي يفتح تلقائياً عند زيارة صفحة الأقسام بدون تحديد قسم معين'
    )

    # رسوم خدمة التغليف الملكي للهدايا
    gift_wrapping_fee_yer = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('2000.00'), blank=True,
        verbose_name='سعر خدمة التغليف الفاخر للهدايا (ريال يمني)'
    )
    
    # إعدادات تسجيل الدخول السريع عبر Google OAuth
    google_client_id = models.CharField(
        max_length=255, 
        blank=True, 
        default='', 
        verbose_name='معرف عميل جوجل (Google Client ID)',
        help_text='معرف تطبيق Google OAuth من Google Cloud Console لتفعيل الدخول بحساب جوجل'
    )
    google_client_secret = models.CharField(
        max_length=255, 
        blank=True, 
        default='', 
        verbose_name='المفتاح السري لعميل جوجل (Google Client Secret)',
        help_text='المفتاح السري لتطبيق Google OAuth'
    )
    
    # إعدادات إشعارات الويب وتطبيق الهاتف (Web Push Notifications - VAPID)
    vapid_public_key = models.CharField(
        max_length=255, blank=True, default='',
        verbose_name='مفتاح VAPID العام للإشعارات (Public Key)'
    )
    vapid_private_key = models.CharField(
        max_length=255, blank=True, default='',
        verbose_name='مفتاح VAPID السري للإشعارات (Private Key)'
    )
    vapid_claims_email = models.CharField(
        max_length=150, blank=True, default='mailto:support@brandveloura.com',
        verbose_name='البريد الإلكتروني للجهة المصدرة لـ VAPID'
    )
    
    updated_at = models.DateTimeField(auto_now=True, verbose_name='آخر تحديث')

    class Meta:
        verbose_name = 'إعدادات المتجر وسعر الصرف'
        verbose_name_plural = 'إعدادات المتجر وسعر الصرف'

    def __str__(self):
        return f"{self.store_name} (سعر الصرف: 1 ر.س = {self.yer_per_sar} ر.ي)"

    @classmethod
    def get_settings(cls):
        from django.core.cache import cache
        from django.db import connection

        cache_key = 'bv_store_settings'
        use_cache = not connection.in_atomic_block
        try:
            settings_obj = cache.get(cache_key) if use_cache else None
        except Exception:
            settings_obj = None

        if settings_obj is None:
            settings_obj = cls.objects.first()
        if not settings_obj:
            settings_obj, created = cls.objects.get_or_create(id=1)
        else:
            created = False
        
        # Sync environment variables if present
        env_phone = os.getenv('STORE_PHONE', '').strip()
        env_wa = os.getenv('STORE_WHATSAPP', '').strip()
        env_insta = os.getenv('STORE_INSTAGRAM', '').strip()
        
        updated = False
        if env_phone and (created or settings_obj.contact_phone != env_phone):
            settings_obj.contact_phone = env_phone
            updated = True
        if env_wa and (created or settings_obj.contact_whatsapp != env_wa):
            settings_obj.contact_whatsapp = env_wa
            updated = True
        if env_insta and (created or settings_obj.contact_instagram != env_insta):
            settings_obj.contact_instagram = env_insta
            updated = True
            
        if updated:
            try:
                settings_obj.save()
            except Exception:
                pass

        if use_cache:
            try:
                cache.set(cache_key, settings_obj, timeout=60)
            except Exception:
                pass

        return settings_obj

    @classmethod
    def get_exchange_rate(cls):
        """الحصول على سعر الصرف المعتمد من الكاش السريع لتفادي N+1 استعلامات في القوائم والمنتجات"""
        try:
            from django.core.cache import cache
            cached_rate = cache.get('bv_yer_per_sar')
            if cached_rate is not None:
                return cached_rate
        except Exception:
            pass

        rate = cls.objects.values_list('yer_per_sar', flat=True).first()
        if not rate:
            settings_obj = cls.get_settings()
            rate = settings_obj.yer_per_sar or Decimal('530.00')

        try:
            from django.core.cache import cache
            cache.set('bv_yer_per_sar', rate, timeout=300)
        except Exception:
            pass
        return rate

    def clean(self):
        super().clean()
        if self.yer_per_sar is not None and self.yer_per_sar <= 0:
            raise ValidationError({'yer_per_sar': 'يجب أن يكون سعر صرف الريال السعودي أكبر من الصفر.'})
        if self.gift_wrapping_fee_yer is not None and self.gift_wrapping_fee_yer < 0:
            raise ValidationError({'gift_wrapping_fee_yer': 'لا يمكن أن تكون رسوم التغليف سالبة.'})

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.default_category_id:
            try:
                Category.objects.filter(id=self.default_category_id).update(is_default=True)
                Category.objects.exclude(id=self.default_category_id).update(is_default=False)
            except Exception:
                pass
        try:
            from django.core.cache import cache
            cache.delete('bv_yer_per_sar')
            cache.delete('bv_store_settings')
        except Exception:
            pass

    def delete(self, *args, **kwargs):
        try:
            from django.core.cache import cache
            cache.delete('bv_yer_per_sar')
            cache.delete('bv_store_settings')
        except Exception:
            pass
        super().delete(*args, **kwargs)



    @property
    def effective_google_client_id(self):
        return self.google_client_id.strip() or os.getenv('GOOGLE_CLIENT_ID', '').strip()

    @property
    def effective_google_client_secret(self):
        return self.google_client_secret.strip() or os.getenv('GOOGLE_CLIENT_SECRET', '').strip()

    @property
    def instagram_url(self):
        """رابط حساب انستغرام المعالج بشكل سليم مهما كانت طريقة كتابته"""
        val = (self.contact_instagram or '').strip()
        if not val:
            return ''
        if val.startswith('http://') or val.startswith('https://'):
            return val
        clean_user = val.lstrip('@').strip().strip('/')
        return f"https://instagram.com/{clean_user}"

    @property
    def get_logo_url(self):
        """رابط شعار المتجر"""
        if self.store_logo:
            return sanitize_image_url(self.store_logo.url, '/static/images/logo.jpg')
        return '/static/images/logo.jpg'

    @property
    def gift_wrapping_fee_sar(self):
        """سعر التغليف بالريال السعودي"""
        if self.yer_per_sar and self.yer_per_sar > 0:
            return round(self.gift_wrapping_fee_yer / self.yer_per_sar, 1)
        return Decimal('3.80')


class PaymentAccount(models.Model):
    """حسابات التحويل البنكي والمحافظ الإلكترونية في اليمن والسعودية (للمغتربين)"""
    CURRENCY_CHOICES = [
        ('BOTH', 'يقبل الريالين (يمني وسعودي)'),
        ('SAR', 'ريال سعودي فقط (للمغتربين والتحويل الخارجي)'),
        ('YER', 'ريال يمني فقط (محلي)'),
    ]
    COUNTRY_CHOICES = [
        ('YE', 'اليمن (محلي)'),
        ('SA', 'المملكة العربية السعودية (للمغتربين)'),
    ]

    provider_name = models.CharField(max_length=150, verbose_name='اسم وسيلة الدفع / البنك / المحفظة', help_text='مثال: بنك الكريمي، مصرف الراجحي، محفظة جوالي، كاش، الدفع عند الاستلام')
    currency = models.CharField(max_length=10, choices=CURRENCY_CHOICES, default='BOTH', verbose_name='العملة المقبولة بالحساب')
    bank_country = models.CharField(max_length=10, choices=COUNTRY_CHOICES, default='YE', verbose_name='دولة الحساب')
    account_number = models.CharField(max_length=150, blank=True, verbose_name='رقم الحساب أو رقم المحفظة / الهاتف')
    iban = models.CharField(max_length=50, blank=True, verbose_name='رقم الآيبان الدولي (IBAN) إن وجد')
    account_holder_name = models.CharField(max_length=150, blank=True, verbose_name='اسم المستلم / صاحب الحساب')
    instructions = models.TextField(blank=True, verbose_name='تعليمات التحويل للعميل', help_text='تظهر للعميل عند اختيار وسيلة الدفع مع بيانات الحساب')
    is_cod = models.BooleanField(default=False, verbose_name='هل هذه طريقة الدفع عند الاستلام (COD)؟')
    is_active = models.BooleanField(default=True, verbose_name='مفعل')
    display_order = models.PositiveIntegerField(default=0, verbose_name='ترتيب العرض')

    class Meta:
        verbose_name = 'حساب تحويل / وسيلة دفع'
        verbose_name_plural = 'حسابات التحويل ووسائل الدفع'
        ordering = ['display_order', 'id']

    def __str__(self):
        curr_label = dict(self.CURRENCY_CHOICES).get(self.currency, '')
        return f"{self.provider_name} ({curr_label})"


class ShippingZone(models.Model):
    """مناطق ومحافظات التوصيل ورسوم الشحن"""
    city_name = models.CharField(max_length=100, verbose_name='اسم المدينة / المحافظة', help_text='مثال: صنعاء، عدن، تعز، المكلا، إب')
    delivery_fee_yer = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name='رسوم التوصيل (ريال يمني)')
    estimated_delivery_time = models.CharField(max_length=100, default='خلال 24-48 ساعة', verbose_name='مدة التوصيل التقريبية')
    is_active = models.BooleanField(default=True, verbose_name='مفعل')

    class Meta:
        verbose_name = 'منطقة شحن وتوصيل'
        verbose_name_plural = 'مناطق الشحن والمدن'
        ordering = ['city_name']

    def __str__(self):
        return f"{self.city_name} — {self.delivery_fee_yer:,.0f} ر.ي"


class HeroBanner(models.Model):
    """البانرات الترويجية المتحركة في الصفحة الرئيسية"""
    title = models.CharField(max_length=200, verbose_name='العنوان الرئيسي')
    subtitle = models.CharField(max_length=300, blank=True, verbose_name='العنوان الفرعي / الوصف')
    tag_badge = models.CharField(max_length=100, blank=True, default='تشكيلة حصرية 2026', verbose_name='شارة ترويجية')
    image = models.ImageField(upload_to='banners/', null=True, blank=True, verbose_name='صورة البانر')
    image_url_fallback = models.URLField(blank=True, verbose_name='رابط صورة خارجي (في حال عدم رفع ملف)')
    button_text = models.CharField(max_length=100, default='تسوق التشكيلة الآن', verbose_name='نص الزر')
    button_link = models.CharField(max_length=250, default='/products/', verbose_name='رابط الزر')
    display_order = models.PositiveIntegerField(default=0, verbose_name='ترتيب العرض')
    is_active = models.BooleanField(default=True, verbose_name='مفعل')

    class Meta:
        verbose_name = 'بانر ترويجي'
        verbose_name_plural = 'البانرات الترويجية'
        ordering = ['display_order']

    def __str__(self):
        return self.title

    @property
    def get_image_url(self):
        fallback = self.image_url_fallback or 'https://images.unsplash.com/photo-1547887537-6158d64c35b3?auto=format&fit=crop&w=1600&q=80'
        if self.image:
            return sanitize_image_url(self.image.url, fallback)
        return fallback


class Category(models.Model):
    """أقسام المتجر الرئيسية"""
    CATEGORY_TYPES = [
        ('perfumes', 'عطور فاخرة (Perfumes)'),
        ('watches', 'ساعات راقية (Watches)'),
        ('general', 'عام / أقسام أخرى (General)'),
    ]

    ALL_CATEGORY_TYPES = [
        ('perfumes', 'عطور فاخرة (Perfumes)'),
        ('watches', 'ساعات راقية (Watches)'),
        ('general', 'عام / أقسام أخرى (General)'),
        ('cosmetics', 'مستحضرات تجميل (Cosmetics)'),
        ('care', 'عناية بالبشرة والجسم (Skincare & Care)'),
        ('bundles', 'باقات الهدايا والمناسبات (Gift Bundles)'),
    ]

    name_ar = models.CharField(max_length=150, verbose_name='اسم القسم بالعربي')
    name_en = models.CharField(max_length=150, blank=True, verbose_name='اسم القسم بالإنجليزي')
    slug = models.SlugField(unique=True, allow_unicode=True, blank=True, verbose_name='الرابط الدائم (Slug)')
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='subcategories',
        verbose_name='القسم الرئيسي (اتركه فارغاً إذا كان هذا قسماً رئيسياً)'
    )
    category_type = models.CharField(max_length=20, choices=ALL_CATEGORY_TYPES, default='general', verbose_name='نوع القسم والمواصفات')
    description = models.TextField(blank=True, verbose_name='وصف القسم')
    image = models.ImageField(upload_to='categories/', null=True, blank=True, verbose_name='صورة القسم')
    image_url_fallback = models.URLField(blank=True, verbose_name='رابط صورة خارجي')
    display_order = models.PositiveIntegerField(default=0, verbose_name='ترتيب العرض')
    is_default = models.BooleanField(default=False, verbose_name='القسم الافتراضي لصفحة الأقسام', help_text='تحديد هذا القسم كقسم رئيسي افتراضي يفتح تلقائياً للعميل عند دخول صفحة الأقسام')
    is_featured = models.BooleanField(default=True, verbose_name='عرض في الرئيسية')
    is_active = models.BooleanField(default=True, verbose_name='مفعل')

    class Meta:
        verbose_name = 'قسم / فئة'
        verbose_name_plural = 'الأقسام والفئات'
        ordering = ['display_order', 'id']

    def __str__(self):
        if self.parent:
            return f"{self.parent.name_ar} » {self.name_ar}"
        return self.name_ar

    @property
    def is_main_category(self):
        return self.parent is None

    def get_descendants_and_self_ids(self):
        """إرجاع قائمة بمعرفات هذا القسم وكافة تصنيفاته الفرعية"""
        ids = [self.id]
        ids.extend(self.subcategories.values_list('id', flat=True))
        return ids

    def clean(self):
        super().clean()
        if self.parent_id and self.pk and self.parent_id == self.pk:
            raise ValidationError({'parent': 'لا يمكن تحديد القسم كقسم رئيسي لنفسه.'})
        curr = self.parent
        visited = {self.pk} if self.pk else set()
        while curr:
            if curr.pk in visited:
                raise ValidationError({'parent': 'خطأ في التفرع الهرمي: لا يمكن تحديد تصنيف تابع كقسم رئيسي تجنباً للتكرار الدائري.'})
            visited.add(curr.pk)
            curr = curr.parent

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name_en or self.name_ar, allow_unicode=True)
            self.slug = base if base else f"cat-{uuid.uuid4().hex[:6]}"
        super().save(*args, **kwargs)
        if self.is_default:
            Category.objects.filter(is_default=True).exclude(pk=self.pk).update(is_default=False)
        try:
            from django.core.cache import cache
            cache.delete('bv_active_categories')
        except Exception:
            pass

    def delete(self, *args, **kwargs):
        try:
            from django.core.cache import cache
            cache.delete('bv_active_categories')
        except Exception:
            pass
        super().delete(*args, **kwargs)


    @property
    def get_image_url(self):
        fallback = self.image_url_fallback or 'https://images.unsplash.com/photo-1522335789203-aabd1fc54bc9?auto=format&fit=crop&w=800&q=80'
        if self.image:
            return sanitize_image_url(self.image.url, fallback)
        return fallback


class Brand(models.Model):
    """الماركات والبراندات العالمية الفاخرة"""
    name_ar = models.CharField(max_length=150, verbose_name='اسم الماركة بالعربي')
    name_en = models.CharField(max_length=150, blank=True, verbose_name='اسم الماركة بالإنجليزي / Brand Name')
    slug = models.SlugField(unique=True, allow_unicode=True, blank=True, verbose_name='الرابط الدائم (Slug)')
    logo = models.ImageField(upload_to='brands/', null=True, blank=True, verbose_name='شعار الماركة (Logo)')
    logo_url_fallback = models.URLField(blank=True, verbose_name='رابط صورة الشعار خارجي (في حال عدم رفع ملف)')
    cover_image = models.ImageField(upload_to='brands/covers/', null=True, blank=True, verbose_name='صورة غلاف الماركة (اختياري)')
    description = models.TextField(blank=True, verbose_name='نبذة وتاريخ الماركة')
    website = models.URLField(blank=True, verbose_name='موقع الماركة الرسمي (اختياري)')
    categories = models.ManyToManyField(Category, blank=True, related_name='brands', verbose_name='الأقسام المرتبطة')
    display_order = models.PositiveIntegerField(default=0, verbose_name='ترتيب العرض')
    is_featured = models.BooleanField(default=True, verbose_name='عرض في شريط الرئيسية')
    is_active = models.BooleanField(default=True, verbose_name='نشط ومعروض بالمتجر')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإضافة')

    class Meta:
        verbose_name = 'ماركة / براند'
        verbose_name_plural = 'الماركات والبراندات العالمية'
        ordering = ['display_order', 'name_ar']

    def __str__(self):
        return f"{self.name_ar} ({self.name_en})" if self.name_en else self.name_ar

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name_en or self.name_ar, allow_unicode=True)
            self.slug = base if base else f"brand-{uuid.uuid4().hex[:6]}"
        super().save(*args, **kwargs)

    @property
    def get_logo_url(self):
        fallback = self.logo_url_fallback or 'https://images.unsplash.com/photo-1522335789203-aabd1fc54bc9?auto=format&fit=crop&w=400&q=80'
        if self.logo:
            return sanitize_image_url(self.logo.url, fallback)
        return fallback

    @property
    def get_cover_url(self):
        if self.cover_image:
            return sanitize_image_url(self.cover_image.url, '')
        return ''


class Product(models.Model):
    """المنتج الفاخر والمواصفات الذكية"""
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='products', verbose_name='القسم')
    brand = models.ForeignKey('Brand', on_delete=models.SET_NULL, null=True, blank=True, related_name='products', verbose_name='الماركة / البراند')
    name_ar = models.CharField(max_length=250, verbose_name='اسم المنتج بالعربي')
    name_en = models.CharField(max_length=250, blank=True, verbose_name='اسم المنتج بالإنجليزي / الماركة العالمية')
    slug = models.SlugField(unique=True, allow_unicode=True, max_length=250, blank=True, verbose_name='الرابط الدائم')
    brand_name = models.CharField(max_length=150, blank=True, verbose_name='الماركة (Brand)')
    description = models.TextField(blank=True, verbose_name='وصف المنتج')
    
    # السعر الأساسي بالريال اليمني
    price_yer = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), blank=True, verbose_name='السعر الافتراضي بالريال اليمني')
    compare_at_price_yer = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='السعر قبل الخصم (ريال يمني - اختياري)')
    
    # خاصية العطور: الأصلي والماستر (طبق الأصل)
    has_grades = models.BooleanField(
        default=False, 
        verbose_name='يتوفر بنوعين (أصلي 100% وماستر طبق الأصل)؟',
        help_text='فعّل هذا الخيار إذا كان المنتج يتوفر بنسخة أصلية ونسخة ماستر بأسعار مختلفة'
    )
    price_original_yer = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, 
        verbose_name='سعر الأصلي 100% الحالي (ريال يمني)'
    )
    compare_at_price_original_yer = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, 
        verbose_name='سعر الأصلي قبل الخصم (ريال يمني - اختياري)'
    )
    price_master_yer = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, 
        verbose_name='سعر الماستر / طبق الأصل الحالي (ريال يمني)'
    )
    compare_at_price_master_yer = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, 
        verbose_name='سعر الماستر قبل الخصم (ريال يمني - اختياري)'
    )
    
    stock_quantity = models.PositiveIntegerField(default=10, verbose_name='الكمية المتوفرة بالمخزون')
    sku = models.CharField(max_length=100, blank=True, verbose_name='رمز المنتج (SKU)')
    
    is_featured = models.BooleanField(default=False, verbose_name='منتج مميز (يظهر في الرئيسية)')
    is_best_seller = models.BooleanField(default=False, verbose_name='الأكثر مبيعاً')
    is_new = models.BooleanField(default=True, verbose_name='وصل حديثاً')
    is_active = models.BooleanField(default=True, verbose_name='نشط ومعروض للبيع')
    
    # المواصفات الذكية حسب نوع المنتج بتنسيق JSON
    specifications = models.JSONField(
        default=dict, 
        blank=True, 
        verbose_name='المواصفات الفنية التفصيلية (JSON)',
        help_text='للعطور: الهرم العطري والتركيز والحجم | للساعات: مقاس الميناء ونوع السوار والمحرك | للتجميل: درجات الألوان ونوع البشرة'
    )
    
    # خيارات الإشعار الترويجي للمشتركين عند الحفظ
    send_push_notification_on_save = models.BooleanField(
        default=False,
        verbose_name='📢 إرسال إشعار فوري لجميع المشتركين على هواتفهم الآن',
        help_text='فعّل هذا الخيار واضغط حفظ لإرسال إشعار فوري لجميع مستخدمي التطبيق والمشتركين بالتخفيض أو المنتج الجديد'
    )
    push_notification_title = models.CharField(
        max_length=200, 
        blank=True,
        verbose_name='عنوان مخصص للإشعار (اختياري)',
        help_text='إن تركته فارغاً، سيتم إنشاء عنوان تلقائي فاخر مثل: "🔥 تخفيض حصري على {الاسم}"'
    )
    push_notification_body = models.TextField(
        blank=True,
        verbose_name='نص مخصص للإشعار (اختياري)',
        help_text='إن تركته فارغاً، سيتم توليد نص تسويقي جذاب يشمل السعر ونسبة الخصم تلقائياً'
    )
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإضافة')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='آخر تعديل')

    class Meta:
        verbose_name = 'منتج'
        verbose_name_plural = 'المنتجات'
        ordering = ['-is_featured', '-created_at']

    def __str__(self):
        return f"{self.name_ar} ({self.brand_name})"

    def save(self, *args, **kwargs):
        if self.brand:
            self.brand_name = self.brand.name_ar or self.brand.name_en
        if self.has_grades:
            if self.price_master_yer and (not self.price_yer or self.price_yer == 0):
                self.price_yer = self.price_master_yer
            elif self.price_original_yer and (not self.price_yer or self.price_yer == 0):
                self.price_yer = self.price_original_yer
        if not self.slug:
            base = slugify(self.name_en or self.name_ar, allow_unicode=True)
            if not base:
                base = f"prod-{uuid.uuid4().hex[:6]}"
            self.slug = f"{base}-{uuid.uuid4().hex[:4]}"
        super().save(*args, **kwargs)

    @property
    def effective_brand_name(self):
        if self.brand:
            return self.brand.name_ar or self.brand.name_en
        return self.brand_name or ''

    @property
    def price_sar(self):
        """حساب السعر بالريال السعودي آلياً بناءً على سعر الصرف اليومي المعتمد بالمتجر مقرباً للأعلى بدون كسور"""
        rate = StoreSettings.get_exchange_rate()
        if rate and rate > 0:
            import math
            return int(math.ceil(self.price_yer / rate))
        return 0

    @property
    def price_original_sar(self):
        """سعر الأصلي بالريال السعودي مقرباً للأعلى بدون كسور"""
        if not self.price_original_yer:
            return None
        rate = StoreSettings.get_exchange_rate()
        if rate and rate > 0:
            import math
            return int(math.ceil(self.price_original_yer / rate))
        return None

    @property
    def price_master_sar(self):
        """سعر الماستر / طبق الأصل بالريال السعودي مقرباً للأعلى بدون كسور"""
        if not self.price_master_yer:
            return None
        rate = StoreSettings.get_exchange_rate()
        if rate and rate > 0:
            import math
            return int(math.ceil(self.price_master_yer / rate))
        return None

    @property
    def compare_at_price_original_sar(self):
        """سعر الأصلي قبل الخصم بالريال السعودي مقرباً للأعلى بدون كسور"""
        if not self.compare_at_price_original_yer:
            return None
        rate = StoreSettings.get_exchange_rate()
        if rate and rate > 0:
            import math
            return int(math.ceil(self.compare_at_price_original_yer / rate))
        return None

    @property
    def compare_at_price_master_sar(self):
        """سعر الماستر قبل الخصم بالريال السعودي مقرباً للأعلى بدون كسور"""
        if not self.compare_at_price_master_yer:
            return None
        rate = StoreSettings.get_exchange_rate()
        if rate and rate > 0:
            import math
            return int(math.ceil(self.compare_at_price_master_yer / rate))
        return None

    @property
    def discount_percentage_original(self):
        """نسبة خصم الأصلي إن وجدت"""
        if self.compare_at_price_original_yer and self.price_original_yer and self.compare_at_price_original_yer > self.price_original_yer:
            diff = self.compare_at_price_original_yer - self.price_original_yer
            return int((diff / self.compare_at_price_original_yer) * 100)
        return 0

    @property
    def discount_percentage_master(self):
        """نسبة خصم الماستر إن وجدت"""
        if self.compare_at_price_master_yer and self.price_master_yer and self.compare_at_price_master_yer > self.price_master_yer:
            diff = self.compare_at_price_master_yer - self.price_master_yer
            return int((diff / self.compare_at_price_master_yer) * 100)
        return 0

    @property
    def compare_at_price_sar(self):
        """حساب سعر الشطب بالسعودي آلياً مقرباً للأعلى بدون كسور"""
        if not self.compare_at_price_yer:
            return None
        rate = StoreSettings.get_exchange_rate()
        if rate and rate > 0:
            import math
            return int(math.ceil(self.compare_at_price_yer / rate))
        return None

    @property
    def discount_percentage(self):
        """نسبة الخصم إن وجد"""
        if self.compare_at_price_yer and self.compare_at_price_yer > self.price_yer:
            diff = self.compare_at_price_yer - self.price_yer
            return int((diff / self.compare_at_price_yer) * 100)
        return 0

    @property
    def primary_image_url(self):
        fallback = 'https://images.unsplash.com/photo-1592945403244-b3fbafd7f539?auto=format&fit=crop&w=800&q=80'
        if hasattr(self, '_prefetched_objects_cache') and 'images' in self._prefetched_objects_cache:
            imgs = self._prefetched_objects_cache['images']
            for img in imgs:
                if img.is_primary:
                    return img.get_image_url
            if imgs:
                return imgs[0].get_image_url
            return fallback
        first_img = self.images.filter(is_primary=True).first() or self.images.first()
        if first_img:
            return first_img.get_image_url
        return fallback



class ProductImage(models.Model):
    """صور المنتج المتعددة"""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images', verbose_name='المنتج')
    image = models.ImageField(upload_to='products/', null=True, blank=True, verbose_name='ملف الصورة')
    image_url_fallback = models.URLField(blank=True, verbose_name='رابط صورة خارجي')
    is_primary = models.BooleanField(default=False, verbose_name='الصورة الرئيسية')
    display_order = models.PositiveIntegerField(default=0, verbose_name='الترتيب')

    class Meta:
        verbose_name = 'صورة منتج'
        verbose_name_plural = 'صور المنتجات'
        ordering = ['-is_primary', 'display_order', 'id']

    @property
    def get_image_url(self):
        fallback = self.image_url_fallback or 'https://images.unsplash.com/photo-1592945403244-b3fbafd7f539?auto=format&fit=crop&w=800&q=80'
        if self.image:
            return sanitize_image_url(self.image.url, fallback)
        return fallback

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_primary and self.product_id:
            ProductImage.objects.filter(product_id=self.product_id, is_primary=True).exclude(pk=self.pk).update(is_primary=False)
        elif self.product_id and not ProductImage.objects.filter(product_id=self.product_id, is_primary=True).exists():
            ProductImage.objects.filter(pk=self.pk).update(is_primary=True)
            self.is_primary = True

    def delete(self, *args, **kwargs):
        was_primary = self.is_primary
        prod_id = self.product_id
        super().delete(*args, **kwargs)
        if was_primary and prod_id:
            first_rem = ProductImage.objects.filter(product_id=prod_id).first()
            if first_rem:
                ProductImage.objects.filter(pk=first_rem.pk).update(is_primary=True)


class GiftBundle(models.Model):
    """باقات الهدايا الجاهزة المنسقة مسبقاً من الإدارة مع إمكانية التخصيص أو الشراء المباشر"""
    title_ar = models.CharField(max_length=200, verbose_name='اسم الباقة بالعربي')
    title_en = models.CharField(max_length=200, blank=True, verbose_name='اسم الباقة بالإنجليزي')
    slug = models.SlugField(max_length=220, unique=True, allow_unicode=True, blank=True, verbose_name='الرابط الدائم (Slug)')
    subtitle = models.CharField(max_length=255, blank=True, verbose_name='وصف فرعي / مناسبة الباقة')
    description = models.TextField(blank=True, verbose_name='تفاصيل ومحتويات الباقة')
    
    cover_image = models.ImageField(upload_to='gift_bundles/', blank=True, null=True, verbose_name='صورة غلاف الباقة')
    cover_image_url_fallback = models.URLField(max_length=1000, blank=True, verbose_name='رابط صورة بديل (Cloudinary/URL)')
    
    price_yer = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='سعر الباقة الإجمالي بالريال اليمني')
    compare_at_price_yer = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='السعر قبل الخصم (ريال يمني - اختياري)')
    
    includes_luxury_packaging = models.BooleanField(default=True, verbose_name='تشمل تغليف ملكي فاخر مجاناً')
    includes_gift_card = models.BooleanField(default=True, verbose_name='تشمل كرت إهداء مخصص مجاناً')
    
    is_active = models.BooleanField(default=True, verbose_name='نشطة ومتاحة في المتجر')
    is_featured = models.BooleanField(default=True, verbose_name='عرض كباقة مميزة في الرئيسية وركن الإهداء')
    display_order = models.PositiveIntegerField(default=0, verbose_name='ترتيب العرض')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='تاريخ التحديث')

    class Meta:
        verbose_name = 'باقة هدايا جاهزة'
        verbose_name_plural = 'باقات الهدايا الجاهزة'
        ordering = ['display_order', '-created_at']

    def __str__(self):
        return self.title_ar

    def clean(self):
        super().clean()
        if self.price_yer is not None and self.price_yer <= 0:
            raise ValidationError({'price_yer': 'يجب أن يكون سعر الباقة أكبر من الصفر.'})
        if self.compare_at_price_yer and self.price_yer and self.compare_at_price_yer <= self.price_yer:
            raise ValidationError({'compare_at_price_yer': 'السعر قبل الخصم يجب أن يكون أكبر من السعر الحالي لظهور نسبة التوفير بشكل صحيح.'})

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title_en or self.title_ar, allow_unicode=True)
            if not base:
                base = f"bundle-{uuid.uuid4().hex[:6]}"
            curr_slug = base
            counter = 1
            while GiftBundle.objects.filter(slug=curr_slug).exclude(pk=self.pk).exists():
                curr_slug = f"{base}-{counter}"
                counter += 1
            self.slug = curr_slug
        super().save(*args, **kwargs)

    @property
    def primary_image_url(self):
        return self.get_image_url()

    def get_image_url(self):
        if self.cover_image:
            return sanitize_image_url(self.cover_image.url, self.cover_image_url_fallback)
        if self.cover_image_url_fallback:
            return self.cover_image_url_fallback
        first_item = self.items.select_related('product').first()
        if first_item and first_item.product:
            return first_item.product.primary_image_url
        return 'https://images.unsplash.com/photo-1549465220-1a8b9238cd48?auto=format&fit=crop&w=800&q=80'

    @property
    def price_sar(self):
        settings = StoreSettings.get_settings()
        rate = settings.yer_per_sar or Decimal('530.00')
        import math
        return int(math.ceil(self.price_yer / rate))

    @property
    def compare_at_price_sar(self):
        if not self.compare_at_price_yer:
            return None
        settings = StoreSettings.get_settings()
        rate = settings.yer_per_sar or Decimal('530.00')
        import math
        return int(math.ceil(self.compare_at_price_yer / rate))

    @property
    def discount_percentage(self):
        if self.compare_at_price_yer and self.compare_at_price_yer > self.price_yer:
            return int(round(((self.compare_at_price_yer - self.price_yer) / self.compare_at_price_yer) * 100))
        return 0

    @property
    def name_ar(self):
        return self.title_ar

    @property
    def brand_name(self):
        return 'Brand Veloura'

    @property
    def items_count(self):
        return self.items.count()


class GiftBundleItem(models.Model):
    """عنصر أو منتج مشمول داخل باقة الهدية الجاهزة (عطر، ساعة، ملحق، إلخ)"""
    GRADE_CHOICES = [
        ('master', 'ماستر تستر (Master)'),
        ('original', 'أصلي وكالة (Original)'),
        ('standard', 'قياسي / منتج عادي'),
    ]

    bundle = models.ForeignKey(GiftBundle, on_delete=models.CASCADE, related_name='items', verbose_name='الباقة التابع لها')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='bundle_inclusions', verbose_name='المنتج المشمول')
    grade = models.CharField(max_length=20, choices=GRADE_CHOICES, default='master', verbose_name='درجة المنتج (للعطور)')
    quantity = models.PositiveIntegerField(default=1, verbose_name='الكمية داخل الباقة')
    custom_note = models.CharField(max_length=150, blank=True, verbose_name='ملاحظة الصنف (مثلاً: 100 مل أو كرتون فاخر)')
    display_order = models.PositiveIntegerField(default=0, verbose_name='ترتيب الظهور داخل الباقة')

    class Meta:
        verbose_name = 'محتوى الباقة'
        verbose_name_plural = 'محتويات الباقة'
        ordering = ['display_order', 'id']

    def __str__(self):
        return f"{self.product.name_ar} ({self.get_grade_display()}) x {self.quantity}"


class Order(models.Model):
    """سجل الطلبات وإشعارات التحويل اليدوي"""
    STATUS_CHOICES = [
        ('pending_verification', 'بانتظار التحقق من التحويل'),
        ('payment_verified', 'تم تأكيد الدفع'),
        ('processing', 'قيد التجهيز'),
        ('out_for_delivery', 'قيد التوصيل'),
        ('delivered', 'تم التسليم'),
        ('cancelled', 'ملغي'),
    ]

    order_number = models.CharField(max_length=50, unique=True, verbose_name='رقم الطلب')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        verbose_name='حساب العميل المسجل'
    )
    customer_name = models.CharField(max_length=150, verbose_name='اسم العميل')
    customer_phone = models.CharField(max_length=50, verbose_name='رقم الهاتف / الواتساب')
    customer_email = models.EmailField(blank=True, verbose_name='البريد الإلكتروني للعميل')
    
    shipping_city = models.CharField(max_length=100, verbose_name='المدينة / المحافظة')
    shipping_address = models.TextField(verbose_name='العنوان التفصيلي للشارع والحي')
    shipping_fee_yer = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name='رسوم الشحن (ريال يمني)')
    
    subtotal_yer = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='المجموع الفرعي (يمني)')
    total_yer = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='المجموع الإجمالي (يمني)')
    total_sar = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='المعادل بالريال السعودي')
    exchange_rate_applied = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='سعر الصرف المطبق وقت الطلب')
    
    payment_method = models.ForeignKey(PaymentAccount, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='طريقة الدفع')
    payment_method_name = models.CharField(max_length=150, blank=True, verbose_name='اسم وسيلة الدفع المحددة')
    
    # العملة المعتمدة للدفع والمبلغ المطلوب
    payment_currency_selected = models.CharField(
        max_length=10, 
        choices=[('YER', 'ريال يمني'), ('SAR', 'ريال سعودي (مغتربين)')], 
        default='YER', 
        verbose_name='العملة المختارة للدفع'
    )
    amount_due_in_payment_currency = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'), 
        verbose_name='المبلغ المطلوب بالعملة المختارة'
    )
    
    # ميزة تدفق الهدايا والمغتربين
    is_gift = models.BooleanField(default=False, verbose_name='طلب كهدية؟')
    recipient_name = models.CharField(max_length=150, blank=True, verbose_name='اسم المستلم (صاحب الهدية)')
    recipient_phone = models.CharField(max_length=50, blank=True, verbose_name='هاتف المستلم')
    gift_card_sender = models.CharField(max_length=100, blank=True, verbose_name='اسم المُهدي (من)')
    gift_card_recipient = models.CharField(max_length=100, blank=True, verbose_name='اسم المهدى إليه (إلى)')
    gift_card_message = models.TextField(blank=True, verbose_name='نص كارت الإهداء')
    is_luxury_gift_wrapping = models.BooleanField(default=False, verbose_name='تغليف هدايا ملكي فاخر')
    gift_wrapping_fee_yer = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name='رسوم التغليف (يمني)')
    preferred_delivery_date = models.DateField(null=True, blank=True, verbose_name='تاريخ التسليم المفضل (المناسبة)')
    hide_invoice_prices = models.BooleanField(default=True, verbose_name='حجب أسعار الفاتورة عن المستلم')
    
    # إدارة المخزون وحالات الإلغاء
    stock_deducted = models.BooleanField(default=True, verbose_name='تم خصم كميات الطلب من المخزون؟')

    # سند / إشعار التحويل المرفوع من العميل
    payment_receipt = models.ImageField(upload_to='receipts/', null=True, blank=True, verbose_name='صورة سند / إشعار التحويل')
    payment_receipt_url = models.URLField(blank=True, verbose_name='رابط صورة السند الخارجي')
    payment_reference_no = models.CharField(max_length=150, blank=True, verbose_name='رقم الحوالة أو العملية')
    
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending_verification', verbose_name='حالة الطلب')
    admin_notes = models.TextField(blank=True, verbose_name='ملاحظات الإدارة الداخلية')
    customer_notes = models.TextField(blank=True, verbose_name='ملاحظات العميل')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الطلب')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='آخر تحديث')

    class Meta:
        verbose_name = 'طلب'
        verbose_name_plural = 'الطلبات والتحقق من السندات'
        ordering = ['-created_at']

    def __str__(self):
        gift_badge = " [🎁 هدية]" if self.is_gift else ""
        return f"طلب #{self.order_number}{gift_badge} — {self.customer_name} ({self.get_status_display()})"

    def restore_stock(self):
        """إرجاع كميات هذا الطلب للمخزون إذا كان مخصوماً سابقاً"""
        if self.stock_deducted:
            for item in self.items.all():
                if item.product:
                    item.product.stock_quantity += item.quantity
                    item.product.save(update_fields=['stock_quantity'])
            self.stock_deducted = False
            self.save(update_fields=['stock_deducted'])

    def deduct_stock(self):
        """خصم كميات هذا الطلب من المخزون"""
        if not self.stock_deducted:
            for item in self.items.all():
                if item.product:
                    item.product.stock_quantity = max(0, item.product.stock_quantity - item.quantity)
                    item.product.save(update_fields=['stock_quantity'])
            self.stock_deducted = True
            self.save(update_fields=['stock_deducted'])

    def save(self, *args, **kwargs):
        # معالجة استرجاع أو خصم المخزون آلياً عند تغيير حالة الطلب
        is_new = self.pk is None
        prev_status = None
        if not is_new:
            prev = Order.objects.filter(pk=self.pk).values('status', 'stock_deducted').first()
            if prev:
                prev_status = prev['status']
                if self.status == 'cancelled' and prev['stock_deducted']:
                    # تم إلغاء الطلب -> إرجاع الكميات للمخزون
                    self.stock_deducted = False
                    for item in self.items.all():
                        if item.product:
                            item.product.stock_quantity += item.quantity
                            item.product.save(update_fields=['stock_quantity'])
                elif self.status != 'cancelled' and not prev['stock_deducted']:
                    # تم إعادة تفعيل الطلب بعد الإلغاء -> خصم الكميات
                    self.stock_deducted = True
                    for item in self.items.all():
                        if item.product:
                            item.product.stock_quantity = max(0, item.product.stock_quantity - item.quantity)
                            item.product.save(update_fields=['stock_quantity'])
        super().save(*args, **kwargs)

        try:
            from django.core.cache import cache
            cache.delete('bv_admin_pending_orders')
        except Exception:
            pass

        # إرسال إشعار تلقائي للعميل عند تحديث حالة الطلب
        if not is_new and prev_status and prev_status != self.status and self.user:
            status_notifications = {
                'payment_verified': (
                    f"تم تأكيد استلام الدفع لطلبكم #{self.order_number}",
                    "تم التحقق من إشعار التحويل بنجاح، وطلبكم الآن معتمد وجاهز للتجهيز.",
                    'payment_verified'
                ),
                'processing': (
                    f"جاري تجهيز طلبكم #{self.order_number}",
                    "بدأ فريقنا بتجهيز وتغليف مشترياتكم الفاخرة بعناية فائقة.",
                    'processing'
                ),
                'out_for_delivery': (
                    f"طلبكم #{self.order_number} في الطريق إليكم",
                    f"تم تسليم شحنتكم لمندوب التوصيل في {self.shipping_city}.",
                    'out_for_delivery'
                ),
                'delivered': (
                    f"تم تسليم طلبكم #{self.order_number} بنجاح",
                    "شكراً لاختياركم براند فيلورا. نسعد دائماً بخدمتكم ونتمنى لكم تجربة تسوق مميزة.",
                    'delivered'
                ),
                'cancelled': (
                    f"تم إلغاء الطلب #{self.order_number}",
                    "تم إلغاء الطلب بناءً على التحديثات الأخيرة وإرجاع الكميات للمخزون.",
                    'cancelled'
                ),
            }
            if self.status in status_notifications:
                title, msg, n_type = status_notifications[self.status]
                Notification.notify_user(
                    user=self.user,
                    title=title,
                    message=msg,
                    notification_type=n_type,
                    order=self,
                    link=f"/order-success/{self.order_number}/"
                )

    def delete(self, *args, **kwargs):
        try:
            from django.core.cache import cache
            cache.delete('bv_admin_pending_orders')
        except Exception:
            pass
        return super().delete(*args, **kwargs)

    @property
    def get_receipt_url(self):
        if self.payment_receipt:
            return sanitize_image_url(self.payment_receipt.url, self.payment_receipt_url or '')
        return self.payment_receipt_url or None


class OrderItem(models.Model):
    """عناصر كل طلب"""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items', verbose_name='الطلب')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='المنتج')
    product_name = models.CharField(max_length=250, verbose_name='اسم المنتج')
    product_image_url = models.URLField(blank=True, verbose_name='صورة المنتج')
    variant_info = models.CharField(max_length=150, blank=True, verbose_name='المقاس / الحجم / اللون')
    unit_price_yer = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='سعر الوحدة باليمني')
    quantity = models.PositiveIntegerField(default=1, verbose_name='الكمية')
    total_price_yer = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='الإجمالي باليمني')

    class Meta:
        verbose_name = 'عنصر في الطلب'
        verbose_name_plural = 'عناصر الطلبات'

    def __str__(self):
        return f"{self.quantity}x {self.product_name}"


class UserProfile(models.Model):
    """الملف التعريفي والبيانات المحفوظة للعميل المسجل"""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='store_profile', 
        verbose_name='حساب المستخدم'
    )
    phone = models.CharField(max_length=50, blank=True, verbose_name='رقم الهاتف / الواتساب')
    preferred_city = models.CharField(max_length=100, blank=True, verbose_name='المدينة / المحافظة المفضلة')
    shipping_address = models.TextField(blank=True, verbose_name='عنوان التوصيل الافتراضي')
    avatar_url = models.URLField(blank=True, verbose_name='رابط الصورة الشخصية')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='آخر تحديث')

    class Meta:
        verbose_name = 'الملف الشخصي للعميل'
        verbose_name_plural = 'ملفات العملاء الشخصية'

    def __str__(self):
        name = self.user.get_full_name() or self.user.username
        return f"ملف {name}"


class Notification(models.Model):
    """سجل إشعارات وتنبيهات النظام للمستخدمين ولإدارة المتجر"""
    TYPE_CHOICES = [
        ('order_created', 'طلب جديد'),
        ('payment_verified', 'تم تأكيد الدفع'),
        ('processing', 'قيد التجهيز والتغليف'),
        ('out_for_delivery', 'مع مندوب التوصيل'),
        ('delivered', 'تم التسليم بنجاح'),
        ('cancelled', 'طلب ملغي'),
        ('low_stock', 'تنبيه انخفاض المخزون'),
        ('promotion', 'عروض وتخفيضات'),
        ('system', 'إشعار نظام / عام'),
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notifications',
        verbose_name='المستلم'
    )
    for_admin = models.BooleanField(
        default=False,
        verbose_name='إشعار لإدارة المتجر'
    )
    notification_type = models.CharField(
        max_length=30,
        choices=TYPE_CHOICES,
        default='system',
        verbose_name='نوع الإشعار'
    )
    title = models.CharField(
        max_length=200,
        verbose_name='عنوان الإشعار'
    )
    message = models.TextField(
        verbose_name='نص الإشعار'
    )
    link = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='رابط التوجيه'
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications',
        verbose_name='الطلب المرتبط'
    )
    is_read = models.BooleanField(
        default=False,
        verbose_name='تمت القراءة'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='تاريخ الإشعار'
    )

    class Meta:
        verbose_name = 'إشعار'
        verbose_name_plural = 'مركز الإشعارات والتنبيهات'
        ordering = ['-created_at']

    def _invalidate_unread_count_cache(self):
        try:
            from django.core.cache import cache
            if self.recipient_id:
                cache.delete(f'bv_unread_notifications_user_{self.recipient_id}')
            if self.for_admin:
                cache.delete('bv_admin_unread_notifications')
        except Exception:
            pass

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._invalidate_unread_count_cache()

    def delete(self, *args, **kwargs):
        self._invalidate_unread_count_cache()
        return super().delete(*args, **kwargs)

    def __str__(self):
        target = "الإدارة" if self.for_admin else (self.recipient.username if self.recipient else "عام")
        status = "مقروء" if self.is_read else "جديد"
        return f"[{status}] {self.title} ({target})"

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.save(update_fields=['is_read'])

    @classmethod
    def notify_user(cls, user, title, message, notification_type='system', order=None, link=''):
        """إنشاء إشعار لمستخدم مسجل"""
        if not user or not user.is_authenticated:
            return None
        return cls.objects.create(
            recipient=user,
            for_admin=False,
            title=title,
            message=message,
            notification_type=notification_type,
            order=order,
            link=link or (f"/order-success/{order.order_number}/" if order else "/account/"),
        )

    @classmethod
    def notify_admin(cls, title, message, notification_type='system', order=None, link=''):
        """إنشاء تنبيه لإدارة المتجر وطاقم العمل"""
        return cls.objects.create(
            recipient=None,
            for_admin=True,
            title=title,
            message=message,
            notification_type=notification_type,
            order=order,
            link=link or (f"/admin/store/order/{order.id}/change/" if order else "/admin/"),
        )


class WebPushSubscription(models.Model):
    """سجل أجهزة العملاء المشتركين في إشعارات الويب وتطبيق الهاتف PWA"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='push_subscriptions',
        verbose_name='العميل المسجل'
    )
    endpoint = models.URLField(max_length=500, unique=True, verbose_name='رابط نقطة النهاية (Endpoint)')
    p256dh = models.CharField(max_length=255, verbose_name='مفتاح التشفير (p256dh)')
    auth = models.CharField(max_length=255, verbose_name='رمز المصادقة (auth)')
    user_agent = models.CharField(max_length=255, blank=True, verbose_name='نوع الجهاز / المتصفح')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الاشتراك')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='آخر تحديث')

    class Meta:
        verbose_name = 'مشترك إشعارات (Push Subscriber)'
        verbose_name_plural = 'مشتركو الإشعارات وتطبيق الهاتف (Push Subscribers)'
        ordering = ['-created_at']

    def __str__(self):
        user_label = self.user.get_full_name() or self.user.username if self.user else 'عميل زائر'
        return f"{user_label} - {self.endpoint[:40]}..."
