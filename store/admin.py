from decimal import Decimal
import urllib.parse
import uuid
from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Sum
from django.urls import reverse
from django.contrib.auth.models import Group, User
from django.contrib.auth.admin import UserAdmin as DefaultUserAdmin

# إلغاء تسجيل نموذج المجموعات البرمجية لتخفيف التعقيد عن المستخدم العادي
try:
    admin.site.unregister(Group)
except Exception:
    pass

# تخصيص واجهة وعناوين لوحة تحكم Brand Veloura
admin.site.site_header = "Brand Veloura | لوحة إدارة المتجر"
admin.site.site_title = "Brand Veloura الإدارة"
admin.site.index_title = "لوحة التحكم — إدارة العطور، الساعات، ومستحضرات التجميل"

from .models import (
    StoreSettings, PaymentAccount, ShippingZone, 
    Category, Brand, Product, ProductImage, 
    Order, OrderItem, HeroBanner, UserProfile, Notification,
    WebPushSubscription
)

# تزويد قوالب لوحة الإدارة بإحصائيات لوحة التحكم وسعر الصرف المباشر
original_admin_each_context = admin.site.each_context

def custom_admin_each_context(request):
    ctx = original_admin_each_context(request)
    try:
        settings_obj = StoreSettings.get_settings()
        ctx['store_settings'] = settings_obj
        ctx['yer_per_sar'] = settings_obj.yer_per_sar
        ctx['admin_total_orders'] = Order.objects.count()
        ctx['admin_pending_orders'] = Order.objects.filter(status='pending_verification').count()
        ctx['admin_total_sales_yer'] = Order.objects.exclude(status='cancelled').aggregate(s=Sum('total_yer'))['s'] or 0
        ctx['admin_total_sales_sar'] = Order.objects.exclude(status='cancelled').aggregate(s=Sum('total_sar'))['s'] or 0
        ctx['admin_low_stock_count'] = Product.objects.filter(stock_quantity__lte=3, is_active=True).count()
        ctx['admin_unread_notifications_count'] = Notification.objects.filter(for_admin=True, is_read=False).count()
        ctx['admin_recent_orders'] = Order.objects.order_by('-created_at')[:6]
    except Exception:
        pass
    return ctx

admin.site.each_context = custom_admin_each_context


# ==============================================================================
# 1. إدارة المستخدمين والمشرفين بشكل مبسط (Simplified User Admin)
# ==============================================================================

class SimplifiedUserAdmin(DefaultUserAdmin):
    """إدارة مبسطة للمستخدمين تخفي التعقيدات ومئات الصلاحيات البرمجية"""
    list_display = ['username', 'email', 'first_name', 'last_name', 'is_staff_badge', 'date_joined']
    list_filter = ['is_staff', 'is_active', 'date_joined']
    search_fields = ['username', 'first_name', 'last_name', 'email']
    ordering = ['-date_joined']
    list_per_page = 25
    
    fieldsets = (
        ('معلومات الحساب الأساسية', {
            'fields': ('username', 'password')
        }),
        ('البيانات الشخصية والبريد', {
            'fields': (('first_name', 'last_name'), 'email')
        }),
        ('صلاحيات لوحة الإدارة', {
            'description': 'حدد ما إذا كان هذا المستخدم مديراً أو مشرفاً لدخول لوحة التحكم',
            'fields': (('is_active', 'is_staff', 'is_superuser'),)
        }),
        ('بيانات النشاط (اختياري)', {
            'classes': ('collapse',),
            'fields': (('last_login', 'date_joined'),)
        }),
    )

    @admin.display(description='نوع الحساب')
    def is_staff_badge(self, obj):
        if obj.is_superuser:
            return format_html('<span style="background: #be123f; color: #fff; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">مدير رئيسي</span>')
        elif obj.is_staff:
            return format_html('<span style="background: #0284c7; color: #fff; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">مشرف متجر</span>')
        return format_html('<span style="color: #64748b; font-size: 11px;">عميل مسجل</span>')

try:
    admin.site.unregister(User)
    admin.site.register(User, SimplifiedUserAdmin)
except Exception:
    pass


# ==============================================================================
# 2. أقسام وفئات المتجر (Categories)
# ==============================================================================

class SubCategoryInline(admin.TabularInline):
    """إمكانية إضافة وإدارة التصنيفات الفرعية (مثل: رجالي، نسائي، شرقي) مباشرة من صفحة القسم الرئيسي"""
    model = Category
    extra = 1
    fk_name = 'parent'
    fields = ['name_ar', 'image', 'is_featured', 'is_active', 'display_order']
    verbose_name = 'تصنيف فرعي'
    verbose_name_plural = 'التصنيفات الفرعية التابعة لهذا القسم'
    show_change_link = True


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['image_preview', 'name_ar', 'hierarchy_badge', 'is_default', 'category_type_badge', 'products_count', 'is_featured', 'is_active', 'display_order']
    list_editable = ['is_default', 'is_featured', 'is_active', 'display_order']
    search_fields = ['name_ar', 'name_en']
    list_filter = ['parent', 'category_type', 'is_featured', 'is_active']
    autocomplete_fields = ['parent']
    prepopulated_fields = {'slug': ('name_ar',)}
    list_per_page = 25
    inlines = [SubCategoryInline]

    def get_inlines(self, request, obj=None):
        # تفعيل الإضافة الفرعية فقط عند تعديل قسم رئيسي موجود مسبقاً
        if obj is None or obj.parent:
            return []
        # إذا كان الطلب POST بدون حقول الـ formset للإضافات الفرعية (كالاختبارات الآلية أو الحفظ المباشر)، نتجاوز الـ inline
        if request.method == 'POST' and 'subcategories-TOTAL_FORMS' not in request.POST:
            return []
        return self.inlines

    fieldsets = (
        ('معلومات القسم وتصنيفه الهرمي', {
            'description': 'حدد اسم القسم. إن كان قسماً رئيسياً كـ (العطور أو البخور) اترك حقل القسم الرئيسي فارغاً. وإن كان صنفاً فرعياً (مثل: بخور عدني) اختر القسم الرئيسي التابع له.',
            'fields': (('name_ar', 'parent'), ('category_type', 'image'), ('is_default', 'is_featured', 'is_active', 'display_order'))
        }),
        ('بيانات إضافية ورابط SEO (اختياري)', {
            'classes': ('collapse',),
            'description': 'يتم إنشاء الرابط تلقائياً من الاسم، يمكنك ترك هذه الحقول فارغة إن أردت',
            'fields': (('name_en', 'slug'), 'description', 'image_url_fallback')
        }),
    )

    @admin.display(description='المستوى')
    def hierarchy_badge(self, obj):
        if obj.parent:
            return format_html(
                '<span style="background-color: #f1f5f9; color: #334155; border: 1px solid #cbd5e1; padding: 2px 8px; border-radius: 6px; font-size: 11px;">فرعي من: <strong style="color: #0f172a;">{}</strong></span>',
                obj.parent.name_ar
            )
        return format_html(
            '<span style="background-color: #fdf2f8; color: #be123f; border: 1px solid #fecdd3; padding: 2px 8px; border-radius: 6px; font-weight: 700; font-size: 11px;">⭐ قسم رئيسي</span>'
        )

    def get_form(self, request, obj=None, **kwargs):
        form_class = super().get_form(request, obj, **kwargs)

        class CustomCategoryAdminForm(form_class):
            def __init__(self, *args, **form_kwargs):
                super().__init__(*args, **form_kwargs)
                if 'category_type' in self.fields:
                    target_obj = obj or getattr(self, 'instance', None)
                    if target_obj and getattr(target_obj, 'pk', None) and target_obj.category_type and target_obj.category_type not in [c[0] for c in Category.CATEGORY_TYPES]:
                        legacy_dict = dict(getattr(Category, 'ALL_CATEGORY_TYPES', []))
                        legacy_label = legacy_dict.get(target_obj.category_type, target_obj.category_type)
                        self.fields['category_type'].choices = list(Category.CATEGORY_TYPES) + [(target_obj.category_type, f"{legacy_label} (سابق)")]
                    else:
                        self.fields['category_type'].choices = list(Category.CATEGORY_TYPES)

        return CustomCategoryAdminForm

    @admin.display(description='الصورة')
    def image_preview(self, obj):
        return format_html(
            '<img src="{}" style="width: 44px; height: 44px; object-fit: cover; border-radius: 8px; border: 1.5px solid #fecdd3;" />',
            obj.get_image_url
        )

    @admin.display(description='نوع القسم')
    def category_type_badge(self, obj):
        types_map = {
            'perfumes': ('عطور فاخرة', '#be185d', '#fdf2f8'),
            'watches': ('ساعات راقية', '#0369a1', '#f0f9ff'),
            'general': ('عام / أقسام أخرى', '#475569', '#f8fafc'),
            'cosmetics': ('مستحضرات تجميل', '#b45309', '#fffbeb'),
            'care': ('عناية بالبشرة', '#047857', '#ecfdf5'),
            'bundles': ('باقات هدايا', '#6d28d9', '#f5f3ff'),
        }
        title, color, bg = types_map.get(obj.category_type, ('عام / أقسام أخرى', '#475569', '#f8fafc'))
        return format_html(
            '<span style="background-color: {}; color: {}; border: 1px solid {}; padding: 2px 9px; border-radius: 6px; font-weight: 700; font-size: 11px;">{}</span>',
            bg, color, color + '33', title
        )

    def get_queryset(self, request):
        from django.db.models import Count
        return super().get_queryset(request).annotate(total_products=Count('products'))

    @admin.display(description='المنتجات التابعة')
    def products_count(self, obj):
        count = getattr(obj, 'total_products', None)
        if count is None:
            count = obj.products.count()
        url = reverse('admin:store_product_changelist') + f"?category__id__exact={obj.id}"
        return format_html(
            '<a href="{}" style="font-weight: 700; color: #be123f; text-decoration: underline;" title="عرض منتجات هذا القسم">{} منتج ↗</a>',
            url, count
        )


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ['logo_preview', 'name_ar', 'name_en', 'products_count', 'is_featured', 'is_active', 'display_order']
    list_filter = ['is_featured', 'is_active', 'categories']
    search_fields = ['name_ar', 'name_en', 'description']
    search_help_text = 'البحث باسم الماركة بالعربي أو الإنجليزي'
    prepopulated_fields = {'slug': ('name_en',)}
    list_editable = ['is_featured', 'is_active', 'display_order']
    filter_horizontal = ['categories']
    fieldsets = (
        ('1. بيانات الماركة والبراند الفاخر', {
            'description': 'أدخل اسم الماركة بالعربي والإنجليزي، وارفع الشعار الرسمي بدقة عالية.',
            'fields': (
                ('name_ar', 'name_en'),
                'slug',
                ('logo', 'logo_url_fallback'),
                'cover_image',
                'description',
                'website',
            )
        }),
        ('2. الأقسام المرتبطة وخيارات العرض', {
            'description': 'حدد الأقسام التي تتبع لها منتجات هذه الماركة (عطور، ساعات، تجميل...) وتفعيل ظهورها في شريط الرئيسية.',
            'fields': (
                'categories',
                ('is_featured', 'is_active', 'display_order'),
            )
        }),
    )

    @admin.display(description='الشعار')
    def logo_preview(self, obj):
        url = obj.get_logo_url
        if url:
            return format_html(
                '<img src="{}" style="width: 36px; height: 36px; object-fit: contain; border-radius: 8px; border: 1px solid #fecdd3; background: #ffffff; padding: 2px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);" />',
                url
            )
        return format_html('<span style="color: #94a3b8; font-size: 11px;">—</span>')

    @admin.display(description='المنتجات')
    def products_count(self, obj):
        count = obj.products.count()
        if count > 0:
            url = reverse('admin:store_product_changelist') + f"?brand__id__exact={obj.id}"
            return format_html(
                '<a href="{}" style="font-weight: 700; color: #be123f; font-family: var(--bv-font-num); text-decoration: underline;" title="عرض منتجات هذا البراند">{} منتج ↗</a>',
                url, count
            )
        return format_html('<span style="color: #94a3b8; font-size: 11px;">لا يوجد</span>')


# ==============================================================================
# 3. إدارة صور ومنتجات المتجر الفاخرة (Products)
# ==============================================================================

class ProductImageInline(admin.TabularInline):
    """معرض صور المنتج المتعددة بطريقة نظيفة ومبسطة"""
    model = ProductImage
    extra = 1
    fields = ['image', 'image_url_fallback', 'is_primary', 'preview', 'display_order']
    readonly_fields = ['preview']

    @admin.display(description='معاينة')
    def preview(self, instance):
        if instance and instance.pk and instance.get_image_url:
            badge = '<span style="display:block; font-size:10px; color:#be123f; font-weight:700; margin-top:2px;">⭐ رئيسية</span>' if instance.is_primary else ''
            return format_html(
                '<div style="text-align: center;"><img src="{}" style="width: 52px; height: 52px; object-fit: cover; border-radius: 8px; border: 1.5px solid #fecdd3; box-shadow: 0 2px 6px rgba(0,0,0,0.06);" />{}</div>',
                instance.get_image_url,
                format_html(badge)
            )
        return '—'


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        'image_preview', 'name_ar', 'brand_name_badge', 'category', 
        'formatted_price_yer', 'formatted_price_sar', 'grades_badge', 
        'stock_badge', 'is_featured', 'is_new', 'is_active'
    ]
    list_filter = [
        'is_active', 'is_featured', 'is_new', 'is_best_seller', 
        'has_grades', 'category', 'brand'
    ]
    search_fields = ['name_ar', 'name_en', 'brand__name_ar', 'brand__name_en', 'brand_name', 'sku']
    search_help_text = 'البحث باسم المنتج بالعربي أو الإنجليزي، الماركة (Brand)، أو رمز SKU'
    date_hierarchy = 'created_at'
    list_per_page = 25
    list_editable = ['is_featured', 'is_new', 'is_active']
    list_select_related = ['category', 'brand']
    autocomplete_fields = ['category', 'brand']
    prepopulated_fields = {'slug': ('name_ar',)}
    readonly_fields = ['currency_preview_info', 'created_at', 'updated_at']
    inlines = [ProductImageInline]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('category', 'brand').prefetch_related('images')

    actions = [
        'duplicate_products',
        'send_push_campaign',
        'make_active',
        'make_inactive',
        'make_featured',
        'unmake_featured',
        'mark_as_new',
        'unmark_as_new',
        'mark_out_of_stock'
    ]

    fieldsets = (
        ('1. القسم والماركة وهوية المنتج الفاخر', {
            'description': 'حدد القسم الرئيسي للمنتج، واختر الماركة (البراند) من القائمة أو أضف ماركة جديدة بالضغط على علامة +، واكتب اسم المنتج.',
            'fields': (
                ('category', 'brand'),
                ('name_ar', 'name_en'),
                'description',
            )
        }),
        ('2. التسعير الأساسي، التخفيض، والمخزون', {
            'description': 'حدد السعر بالريال اليمني (العملة الأساسية). يتم تحويل السعر للريال السعودي للعملاء والمغتربين تلقائياً وفق سعر الصرف اليومي المحدد في إعدادات المتجر.',
            'fields': (
                ('price_yer', 'compare_at_price_yer'),
                'stock_quantity',
                'currency_preview_info',
            )
        }),
        ('3. خيارات درجات العطور والمنتجات (أصلي 100% وماستر طبق الأصل مع التخفيضات)', {
            'classes': ('collapse',),
            'description': 'إذا كان المنتج يتوفر بخياري (أصلي 100% وماستر كواليتي طبق الأصل)، فعّل هذا الخيار وحدد السعر الحالي وسعر ما قبل التخفيض (اختياري) لكل درجة لتمكين العميل من الاختيار ومشاهدة الخصم.',
            'fields': (
                'has_grades',
                ('price_original_yer', 'compare_at_price_original_yer'),
                ('price_master_yer', 'compare_at_price_master_yer'),
            )
        }),
        ('4. إعدادات العرض والترويج والشارات في المتجر', {
            'description': 'تحكم في ظهور المنتج في واجهة المتجر، وإبرازه في قسم المميز، الأكثر مبيعاً، أو قسم وصل حديثاً.',
            'fields': (
                ('is_active', 'is_featured'),
                ('is_new', 'is_best_seller'),
            )
        }),
        ('5. رمز التخزين ورابط المتجر (SKU & SEO)', {
            'classes': ('collapse',),
            'description': 'رمز التخزين التعريفي ورابط المنتج (Slug) يتم توليده تلقائياً من اسم المنتج أو يمكنك تخصيصه.',
            'fields': (
                ('sku', 'slug'),
            )
        }),
        ('6. إرسال إشعار ترويجي فوري لهواتف العملاء (Web Push Broadcast)', {
            'classes': ('collapse',),
            'description': 'عند تفعيل خيار الإرسال والضغط على حفظ، سيتم إرسال إشعار فوري لهواتف جميع مشتركي التطبيق بالتخفيض أو بالمنتج الجديد مع تحويلهم مباشرة لصفحة المنتج عند النقر.',
            'fields': (
                'send_push_notification_on_save',
                ('push_notification_title', 'push_notification_body'),
            )
        }),
    )

    def save_model(self, request, obj, form, change):
        send_push = form.cleaned_data.get('send_push_notification_on_save', False)
        custom_title = form.cleaned_data.get('push_notification_title', '')
        custom_body = form.cleaned_data.get('push_notification_body', '')
        obj.send_push_notification_on_save = False
        super().save_model(request, obj, form, change)

        if send_push:
            from .push_notifications import send_product_promotion_push
            sent = send_product_promotion_push(obj, custom_title=custom_title, custom_body=custom_body)
            self.message_user(request, f"📢 تم إرسال الإشعار الترويجي لمنتج ({obj.name_ar}) بنجاح إلى {sent} من مشتركي التطبيق!")

    @admin.display(description='الماركة', ordering='brand_name')
    def brand_name_badge(self, obj):
        name = obj.effective_brand_name
        if name:
            return format_html(
                '<span style="background: #fdf2f8; color: #be123f; border: 1px solid #fecdd3; padding: 2px 8px; border-radius: 6px; font-weight: 700; font-size: 11px;">{}</span>',
                name
            )
        return format_html('<span style="color: #94a3b8; font-size: 11px;">—</span>')

    @admin.display(description='المخزون', ordering='stock_quantity')
    def stock_badge(self, obj):
        if obj.stock_quantity <= 0:
            return format_html('<span style="background-color: #fee2e2; color: #dc2626; border: 1px solid #fca5a5; padding: 2px 8px; border-radius: 6px; font-weight: bold; font-size: 11px;">نفد من المخزون ⚠️</span>')
        elif obj.stock_quantity <= 3:
            return format_html('<span style="background-color: #fef3c7; color: #d97706; border: 1px solid #fcd34d; padding: 2px 8px; border-radius: 6px; font-weight: bold; font-size: 11px;">متبقي {} فقط!</span>', obj.stock_quantity)
        return format_html('<span style="color: #059669; font-weight: bold; font-size: 11px;">{} قطعة</span>', obj.stock_quantity)

    @admin.display(description='أصلي / ماستر')
    def grades_badge(self, obj):
        if obj.has_grades:
            orig = f"{obj.price_original_yer:,.0f}" if obj.price_original_yer else "—"
            mast = f"{obj.price_master_yer:,.0f}" if obj.price_master_yer else "—"
            orig_disc = f" (-{obj.discount_percentage_original}%)" if obj.discount_percentage_original > 0 else ""
            mast_disc = f" (-{obj.discount_percentage_master}%)" if obj.discount_percentage_master > 0 else ""
            return format_html(
                '<span style="background-color: #fdf2f8; color: #be185d; border: 1px solid #fbcfe8; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: bold;">أصلي: {}{} | ماستر: {}{}</span>',
                orig, orig_disc, mast, mast_disc
            )
        return format_html('<span style="color: #94a3b8; font-size: 11px;">—</span>')

    @admin.display(description='الصورة')
    def image_preview(self, obj):
        url = obj.primary_image_url
        return format_html(
            '<img src="{}" style="width: 46px; height: 46px; object-fit: cover; border-radius: 8px; border: 1.5px solid #fecdd3; box-shadow: 0 2px 5px rgba(0,0,0,0.05);" />',
            url
        )

    @admin.display(description='السعر (يمني)', ordering='price_yer')
    def formatted_price_yer(self, obj):
        return format_html('<span style="font-weight: 700; color: #0f172a;">{}</span>', f"{obj.price_yer:,.0f} ر.ي")

    @admin.display(description='المعادل (سعودي)')
    def formatted_price_sar(self, obj):
        return format_html('<span style="color: #be123f; font-weight: 700;">{} ر.س</span>', obj.price_sar)

    @admin.display(description='ملخص التسعير وسعر الصرف المباشر')
    def currency_preview_info(self, obj):
        if not obj or not obj.pk or not obj.price_yer:
            return "احفظ المنتج لحساب المعادل بالريال السعودي ونسب الخصم آلياً."
        settings_obj = StoreSettings.get_settings()
        rate = settings_obj.yer_per_sar or Decimal('530')
        sar_price = obj.price_sar
        html = f"""
        <div style="background: #fff1f2; border: 1.5px solid #fecdd3; border-radius: 10px; padding: 12px 16px; margin-top: 6px; font-size: 13px; line-height: 1.6;">
            <div style="display: flex; gap: 20px; flex-wrap: wrap; align-items: center;">
                <div>
                    <span style="color: #64748b; font-size: 11px; display: block;">السعر الحالي بالريال اليمني:</span>
                    <strong style="color: #0f172a; font-size: 15px;">{obj.price_yer:,.0f} ر.ي</strong>
                </div>
                <div>
                    <span style="color: #64748b; font-size: 11px; display: block;">المعادل للعميل بالريال السعودي:</span>
                    <strong style="color: #be123f; font-size: 15px;">{sar_price} ر.س</strong>
                    <span style="color: #64748b; font-size: 11px;">(سعر الصرف: 1 ر.س = {rate} ر.ي)</span>
                </div>
        """
        if obj.compare_at_price_yer and obj.compare_at_price_yer > obj.price_yer:
            discount = obj.discount_percentage
            compare_sar = obj.compare_at_price_sar
            html += f"""
                <div>
                    <span style="color: #64748b; font-size: 11px; display: block;">نسبة الخصم المعروضة:</span>
                    <span style="background: #be123f; color: #fff; padding: 2px 8px; border-radius: 6px; font-weight: bold; font-size: 12px;">خصم {discount}%</span>
                    <span style="color: #64748b; font-size: 11px; text-decoration: line-through;">({obj.compare_at_price_yer:,.0f} ر.ي / {compare_sar} ر.س)</span>
                </div>
            """
        if obj.has_grades:
            orig_yer = f"{obj.price_original_yer:,.0f}" if obj.price_original_yer else "—"
            orig_sar = f"{obj.price_original_sar}" if obj.price_original_sar else "—"
            orig_comp_yer = f"{obj.compare_at_price_original_yer:,.0f} ر.ي" if obj.compare_at_price_original_yer else ""
            orig_disc = f'<span style="background:#be123f;color:#fff;padding:1px 6px;border-radius:4px;font-size:10px;margin-right:4px;">خصم {obj.discount_percentage_original}%</span>' if obj.discount_percentage_original > 0 else ""

            mast_yer = f"{obj.price_master_yer:,.0f}" if obj.price_master_yer else "—"
            mast_sar = f"{obj.price_master_sar}" if obj.price_master_sar else "—"
            mast_comp_yer = f"{obj.compare_at_price_master_yer:,.0f} ر.ي" if obj.compare_at_price_master_yer else ""
            mast_disc = f'<span style="background:#be123f;color:#fff;padding:1px 6px;border-radius:4px;font-size:10px;margin-right:4px;">خصم {obj.discount_percentage_master}%</span>' if obj.discount_percentage_master > 0 else ""

            html += f"""
                <div style="width: 100%; border-top: 1px dashed #fecdd3; padding-top: 8px; margin-top: 4px; display: flex; gap: 24px; flex-wrap: wrap;">
                    <div>
                        <strong style="color: #be123f;">الأصلي 100%:</strong> {orig_yer} ر.ي ({orig_sar} ر.س)
                        {orig_disc}
                        {f'<span style="color:#64748b;font-size:11px;text-decoration:line-through;margin-right:4px;">({orig_comp_yer})</span>' if orig_comp_yer else ''}
                    </div>
                    <div>
                        <strong style="color: #831843;">ماستر كواليتي:</strong> {mast_yer} ر.ي ({mast_sar} ر.س)
                        {mast_disc}
                        {f'<span style="color:#64748b;font-size:11px;text-decoration:line-through;margin-right:4px;">({mast_comp_yer})</span>' if mast_comp_yer else ''}
                    </div>
                </div>
            """
        html += "</div></div>"
        return format_html(html)

    @admin.action(description='📋 تكرار المنتج المحدد (عمل نسخة للمنتجات المشابهة)')
    def duplicate_products(self, request, queryset):
        count = 0
        for prod in queryset:
            images = list(prod.images.all())
            prod.pk = None
            prod.id = None
            prod.name_ar = f"{prod.name_ar} (نسخة)"
            if prod.name_en:
                prod.name_en = f"{prod.name_en} (Copy)"
            if prod.sku:
                prod.sku = f"{prod.sku}-COPY-{uuid.uuid4().hex[:4].upper()}"
            prod.slug = ""  # auto-generated on save
            prod.save()
            for img in images:
                ProductImage.objects.create(
                    product=prod,
                    image=img.image,
                    image_url_fallback=img.image_url_fallback,
                    is_primary=img.is_primary,
                    display_order=img.display_order
                )
            count += 1
        self.message_user(request, f"تم بنجاح تكرار {count} منتج مع كامل صورهم وتفاصيلهم.")

    @admin.action(description='✅ تفعيل وعرض المنتجات المحددة في المتجر')
    def make_active(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"تم تفعيل {updated} منتج بنجاح.")

    @admin.action(description='🚫 إلغاء تفعيل وإخفاء المنتجات المحددة')
    def make_inactive(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"تم إخفاء {updated} منتج من واجهة المتجر.")

    @admin.action(description='⭐ تمييز في الصفحة الرئيسية (Featured)')
    def make_featured(self, request, queryset):
        updated = queryset.update(is_featured=True)
        self.message_user(request, f"تم تمييز {updated} منتج في الصفحة الرئيسية.")

    @admin.action(description='✖ إلغاء التمييز من الصفحة الرئيسية')
    def unmake_featured(self, request, queryset):
        updated = queryset.update(is_featured=False)
        self.message_user(request, f"تم إلغاء تمييز {updated} منتج.")

    @admin.action(description='✨ إضافة لشارة "وصل حديثاً"')
    def mark_as_new(self, request, queryset):
        updated = queryset.update(is_new=True)
        self.message_user(request, f"تمت إضافة شارة وصل حديثاً لـ {updated} منتج.")

    @admin.action(description='✖ إزالة شارة "وصل حديثاً"')
    def unmark_as_new(self, request, queryset):
        updated = queryset.update(is_new=False)
        self.message_user(request, f"تمت إزالة شارة وصل حديثاً عن {updated} منتج.")

    @admin.action(description='📢 إرسال إشعار ترويجي فوري لهواتف المشتركين (Push Notification)')
    def send_push_campaign(self, request, queryset):
        from .push_notifications import send_product_promotion_push
        total_sent = 0
        for prod in queryset:
            total_sent += send_product_promotion_push(prod)
        self.message_user(request, f"تم بنجاح إرسال إشعار ترويجي لـ {queryset.count()} منتج إلى {total_sent} جهاز مشترك!")

    @admin.action(description='⚠️ تحديد كـ نفد من المخزون (المخزون = 0)')
    def mark_out_of_stock(self, request, queryset):
        updated = queryset.update(stock_quantity=0)
        self.message_user(request, f"تم تحديد المخزون إلى 0 لـ {updated} منتج.")


# ==============================================================================
# 3. إدارة الطلبات وسندات التحويل والعملاء (Orders)
# ==============================================================================

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = ['product_image_preview', 'product_name', 'variant_info', 'unit_price_yer', 'quantity', 'total_price_yer']
    fields = ['product_image_preview', 'product_name', 'variant_info', 'unit_price_yer', 'quantity', 'total_price_yer']

    @admin.display(description='المنتج')
    def product_image_preview(self, instance):
        if instance and instance.product_image_url:
            return format_html(
                '<img src="{}" style="width: 45px; height: 45px; object-fit: cover; border-radius: 6px;" />',
                instance.product_image_url
            )
        return '—'


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        'order_number', 'gift_badge', 'customer_name', 'customer_whatsapp_btn', 
        'shipping_city', 'formatted_total_yer', 'currency_due_badge', 
        'payment_method_name', 'receipt_preview', 'status_badge', 'created_at'
    ]
    list_filter = ['status', 'is_gift', 'shipping_city', 'payment_currency_selected', 'created_at']
    search_fields = ['order_number', 'customer_name', 'customer_phone', 'recipient_name', 'payment_reference_no']
    search_help_text = 'البحث برقم الطلب (BV-...)، اسم العميل، رقم الهاتف، أو رقم الحوالة'
    date_hierarchy = 'created_at'
    list_per_page = 25
    list_select_related = ['user', 'payment_method']
    readonly_fields = [
        'order_number', 'created_at', 'updated_at', 
        'receipt_large_view', 'customer_whatsapp_link',
        'formatted_total_yer', 'formatted_total_sar', 'currency_due_badge',
        'formatted_subtotal', 'formatted_shipping_fee', 'stock_deducted', 'exchange_rate_applied', 'user'
    ]
    inlines = [OrderItemInline]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'payment_method').prefetch_related('items')


    fieldsets = (
        ('حالة الطلب وسند التحويل المرفوع', {
            'description': 'قم بمراجعة سند التحويل المرفوع من العميل وتحديث حالة الطلب (سيتم إرسال إشعار فوري للعميل عند تغيير الحالة)',
            'fields': ('status', 'receipt_large_view', 'customer_whatsapp_link')
        }),
        ('بيانات العميل والتوصيل', {
            'fields': (('customer_name', 'customer_phone'), ('shipping_city', 'shipping_address'), 'customer_notes')
        }),
        ('تفاصيل الدفع والمبالغ المستحقة', {
            'description': 'المبالغ المحتسبة تلقائياً حسب عملة الدفع المختارة',
            'fields': (('payment_method', 'payment_reference_no'), ('currency_due_badge', 'formatted_total_yer', 'formatted_total_sar'), 'payment_receipt')
        }),
        ('ملاحظات الإدارة الداخلية', {
            'description': 'ملاحظات خاصة بفريق العمل والمندوب (لا تظهر للعميل)',
            'fields': ('admin_notes',)
        }),
        ('🎁 بيانات الهدية وكارت الإهداء (خاص بطلبات الهدايا فقط)', {
            'classes': ('collapse',),
            'description': 'تُملأ فقط إذا طلب العميل إرسال الطلب كهدية لشخص آخر مع كارت إهداء وتغليف فاخر',
            'fields': ('is_gift', ('recipient_name', 'recipient_phone'), ('gift_card_sender', 'gift_card_recipient'), 'gift_card_message', ('is_luxury_gift_wrapping', 'gift_wrapping_fee_yer'))
        }),
        ('بيانات النظام والمخزون المتقدمة', {
            'classes': ('collapse',),
            'description': 'بيانات محاسبية وإحصائية مسجلة تلقائياً من النظام',
            'fields': (('formatted_subtotal', 'formatted_shipping_fee'), ('exchange_rate_applied', 'stock_deducted'), ('order_number', 'user'), ('created_at', 'updated_at'))
        }),
    )

    @admin.display(description='مراسلة العميل')
    def customer_whatsapp_link(self, obj):
        if not obj or not obj.customer_phone:
            return '—'
        phone = obj.customer_phone.replace('+', '').replace(' ', '')
        msg = f"مرحباً {obj.customer_name}، نتواصل معك من متجر Brand Veloura بخصوص طلبك رقم #{obj.order_number}."
        url = f"https://wa.me/{phone}?text={urllib.parse.quote(msg)}"
        return format_html(
            '<a href="{}" target="_blank" style="background-color: #25D366; color: white; padding: 6px 14px; border-radius: 8px; font-size: 12px; font-weight: bold; text-decoration: none; display: inline-flex; align-items: center; gap: 6px; box-shadow: 0 2px 6px rgba(37,211,102,0.3);">'
            '<span>💬 مراسلة العميل عبر واتساب ({})</span>'
            '</a>',
            url, obj.customer_phone
        )

    @admin.display(description='مجموع المنتجات الفرعي')
    def formatted_subtotal(self, obj):
        return f"{obj.subtotal_yer:,.0f} ر.ي" if obj.subtotal_yer else "0 ر.ي"

    @admin.display(description='رسوم التوصيل')
    def formatted_shipping_fee(self, obj):
        return f"{obj.shipping_fee_yer:,.0f} ر.ي" if obj.shipping_fee_yer else "0 ر.ي"

    @admin.display(description='النوع')
    def gift_badge(self, obj):
        if obj.is_gift:
            wrap = " + تغليف" if obj.is_luxury_gift_wrapping else ""
            return format_html(
                '<span style="background-color: #fdf2f8; color: #be185d; border: 1px solid #fbcfe8; padding: 2px 7px; border-radius: 6px; font-weight: bold; font-size: 11px;">🎁 هدية{}</span>',
                wrap
            )
        return '—'

    @admin.display(description='المستحق')
    def currency_due_badge(self, obj):
        if obj.payment_currency_selected == 'SAR':
            return format_html(
                '<span style="background-color: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; padding: 2px 7px; border-radius: 6px; font-weight: bold; font-size: 11px;">🇸🇦 {} ر.س</span>',
                obj.total_sar
            )
        formatted_yer = f"{obj.total_yer:,.0f}" if obj.total_yer else "0"
        return format_html(
            '<span style="color: #475569; font-weight: bold; font-size: 11px;">🇾🇪 {} ر.ي</span>',
            formatted_yer
        )

    @admin.display(description='تواصل')
    def customer_whatsapp_btn(self, obj):
        if not obj or not obj.customer_phone:
            return '—'
        phone = obj.customer_phone.replace('+', '').replace(' ', '')
        msg = f"مرحباً {obj.customer_name}، نتواصل معك من متجر Brand Veloura بخصوص طلبك #{obj.order_number}: حالة طلبك الحالية هي ({obj.get_status_display()})."
        url = f"https://wa.me/{phone}?text={urllib.parse.quote(msg)}"
        return format_html(
            '<a href="{}" target="_blank" style="background-color: #25D366; color: white; padding: 3px 8px; border-radius: 6px; font-size: 10px; font-weight: bold; text-decoration: none; display: inline-flex; align-items: center; gap: 3px;">واتساب</a>',
            url
        )

    @admin.display(description='الإجمالي (يمني)')
    def formatted_total_yer(self, obj):
        return f"{obj.total_yer:,.0f} ر.ي" if obj.total_yer else "0 ر.ي"

    @admin.display(description='الإجمالي (سعودي)')
    def formatted_total_sar(self, obj):
        return f"{obj.total_sar:,.1f} ر.س" if obj.total_sar else "0 ر.س"

    @admin.display(description='حالة الطلب')
    def status_badge(self, obj):
        colors = {
            'pending_verification': '#f59e0b',
            'payment_verified': '#10b981',
            'processing': '#3b82f6',
            'out_for_delivery': '#8b5cf6',
            'delivered': '#059669',
            'cancelled': '#ef4444',
        }
        color = colors.get(obj.status, '#6b7280')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: 500;">{}</span>',
            color,
            obj.get_status_display()
        )

    @admin.display(description='إشعار التحويل')
    def receipt_preview(self, obj):
        url = obj.get_receipt_url
        if url:
            return format_html(
                '<a href="{}" target="_blank" title="انقر لتكبير السند">'
                '<img src="{}" style="width: 45px; height: 45px; object-fit: cover; border-radius: 6px; border: 2px solid #be185d; cursor: pointer;" />'
                '</a>',
                url, url
            )
        return format_html('<span style="color: #9ca3af; font-size: 12px;">بدون إشعار</span>')

    @admin.display(description='فحص السند مكبراً')
    def receipt_large_view(self, obj):
        url = obj.get_receipt_url
        if url:
            return format_html(
                '<div style="margin-top: 10px;">'
                '<p style="font-weight: 600; margin-bottom: 8px;">معاينة سند / إشعار التحويل المرفوع من العميل:</p>'
                '<a href="{}" target="_blank">'
                '<img src="{}" style="max-width: 400px; max-height: 400px; border-radius: 12px; border: 2px solid #f43f5e; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);" />'
                '</a>'
                '<p style="color: #6b7280; font-size: 12px; margin-top: 4px;">اضغط على الصورة لفتحها بالحجم الكامل</p>'
                '</div>',
                url, url
            )
        return 'لا يوجد سند تحويل مرفوع لهذا الطلب بعد.'

    @admin.action(description='اعتماد الدفع للطلبات المحددة (تم التحقق)')
    def mark_as_verified(self, request, queryset):
        count = queryset.update(status='payment_verified')
        self.message_user(request, f'تم اعتماد وتأكيد الدفع لـ {count} طلب بنجاح.')

    @admin.action(description='تغيير الحالة إلى (قيد التجهيز والتغليف)')
    def mark_as_processing(self, request, queryset):
        count = queryset.update(status='processing')
        self.message_user(request, f'تم نقل {count} طلب إلى قيد التجهيز.')

    @admin.action(description='تغيير الحالة إلى (جاري التوصيل مع المندوب)')
    def mark_as_out_for_delivery(self, request, queryset):
        count = queryset.update(status='out_for_delivery')
        self.message_user(request, f'تم نقل {count} طلب إلى جاري التوصيل.')

    @admin.action(description='تأكيد استلام العميل للطلب (تم التسليم بنجاح)')
    def mark_as_delivered(self, request, queryset):
        count = queryset.update(status='delivered')
        self.message_user(request, f'تم تحديث {count} طلب إلى مكتمل ومسلم.')

    @admin.action(description='إلغاء الطلبات واسترجاع كمياتها للمخزون آلياً ♻️')
    def cancel_and_restore_stock_action(self, request, queryset):
        restored_count = 0
        for order in queryset:
            order.status = 'cancelled'
            order.restore_stock()
            order.save()
            restored_count += 1
        self.message_user(request, f'تم إلغاء {restored_count} طلب واسترجاع كميات منتجاتها إلى المخزون فوراً.')

    def save_model(self, request, obj, form, change):
        old_status = None
        if change and obj.pk:
            try:
                old_status = Order.objects.get(pk=obj.pk).status
            except Exception:
                pass
        super().save_model(request, obj, form, change)
        if old_status and old_status != obj.status:
            from .push_notifications import send_order_status_push
            sent = send_order_status_push(obj, obj.status)
            if sent:
                self.message_user(request, f"🔔 تم إرسال إشعار تحديث الحالة لهاتف العميل بنجاح!")


# ==============================================================================
# 4. إعدادات المتجر وسعر الصرف اليومي (Store Settings)
# ==============================================================================

@admin.register(StoreSettings)
class StoreSettingsAdmin(admin.ModelAdmin):
    list_display = ['store_name', 'yer_per_sar', 'contact_phone', 'contact_whatsapp', 'updated_at']

    fieldsets = (
        ('هوية المتجر وسعر الصرف اليومي', {
            'description': 'أي تعديل على سعر الصرف هنا سينعكس فوراً وتلقائياً على كافة أسعار المنتجات المحسوبة بالريال السعودي',
            'fields': (('store_name', 'yer_per_sar'), 'default_category', 'store_tagline', 'store_logo')
        }),
        ('أرقام التواصل وشريط الإعلانات', {
            'description': 'أرقام التواصل الظاهرة في واجهة المتجر للمحادثات السريعة',
            'fields': (('contact_whatsapp', 'contact_phone'), 'contact_instagram', 'announcement_text', 'is_announcement_active')
        }),
        ('خدمة التغليف الملكي للهدايا', {
            'classes': ('collapse',),
            'fields': ('gift_wrapping_fee_yer',)
        }),
        ('ربط تسجيل الدخول السريع عبر Google OAuth (إعداد تقني)', {
            'classes': ('collapse',),
            'description': 'خاص بالمطورين: أدخل معرف العميل والمفتاح السري لتفعيل تسجيل دخول جوجل بنقرة واحدة',
            'fields': ('google_client_id', 'google_client_secret')
        }),
    )

    def has_add_permission(self, request):
        if self.model.objects.exists():
            return False
        return True


# ==============================================================================
# 5. الحسابات البنكية والمحافظ (Payment Accounts)
# ==============================================================================

@admin.register(PaymentAccount)
class PaymentAccountAdmin(admin.ModelAdmin):
    list_display = ['provider_name', 'currency_badge', 'country_badge', 'account_number', 'account_holder_name', 'is_cod', 'is_active', 'display_order']
    list_editable = ['is_active', 'display_order']
    list_filter = ['currency', 'bank_country', 'is_cod', 'is_active']
    search_fields = ['provider_name', 'account_number', 'account_holder_name']
    list_per_page = 25

    fieldsets = (
        ('بيانات الحساب البنكي أو المحفظة', {
            'description': 'تظهر هذه البيانات للعميل في صفحة إتمام الطلب ليقوم بالتحويل إليها ورفع إشعار السند',
            'fields': (('provider_name', 'account_holder_name'), ('account_number', 'currency', 'bank_country'), 'instructions')
        }),
        ('خيارات العرض والدفع عند الاستلام', {
            'fields': (('is_active', 'is_cod', 'display_order'),)
        }),
        ('بيانات مصرفية متقدمة (اختياري)', {
            'classes': ('collapse',),
            'fields': ('iban',)
        }),
    )

    @admin.display(description='العملة')
    def currency_badge(self, obj):
        if obj.currency == 'SAR':
            return format_html('<span style="background-color: #ecfdf5; color: #047857; padding: 2px 8px; border-radius: 6px; font-weight: bold; font-size: 11px;">🇸🇦 ريال سعودي فقط</span>')
        elif obj.currency == 'YER':
            return format_html('<span style="background-color: #f8fafc; color: #475569; padding: 2px 8px; border-radius: 6px; font-weight: bold; font-size: 11px;">🇾🇪 ريال يمني فقط</span>')
        return format_html('<span style="background-color: #fdf2f8; color: #be185d; padding: 2px 8px; border-radius: 6px; font-weight: bold; font-size: 11px;">يقبل الريالين</span>')

    @admin.display(description='الدولة')
    def country_badge(self, obj):
        if obj.bank_country == 'SA':
            return '🇸🇦 السعودية (مغتربين)'
        return '🇾🇪 اليمن (محلي)'


# ==============================================================================
# 6. مناطق ومدن التوصيل (Shipping Zones)
# ==============================================================================

@admin.register(ShippingZone)
class ShippingZoneAdmin(admin.ModelAdmin):
    list_display = ['city_name', 'formatted_fee', 'estimated_delivery_time', 'is_active']
    list_editable = ['is_active']
    search_fields = ['city_name']
    list_per_page = 25

    fieldsets = (
        ('بيانات المدينة ورسوم التوصيل', {
            'fields': (('city_name', 'delivery_fee_yer'), ('estimated_delivery_time', 'is_active'))
        }),
    )

    @admin.display(description='رسوم التوصيل')
    def formatted_fee(self, obj):
        return f"{obj.delivery_fee_yer:,.0f} ر.ي"


# ==============================================================================
# 8. البانرات الترويجية (Hero Banners)
# ==============================================================================

@admin.register(HeroBanner)
class HeroBannerAdmin(admin.ModelAdmin):
    list_display = ['banner_preview', 'title', 'tag_badge', 'button_text', 'display_order', 'is_active']
    list_editable = ['display_order', 'is_active']
    list_per_page = 25

    fieldsets = (
        ('محتوى البانر الإعلاني', {
            'description': 'يظهر هذا البانر في شريط العرض المتحرك في أعلى الصفحة الرئيسية',
            'fields': (('title', 'tag_badge'), 'subtitle', 'image', ('button_text', 'button_link'), ('display_order', 'is_active'))
        }),
        ('خيارات متقدمة', {
            'classes': ('collapse',),
            'fields': ('image_url_fallback',)
        }),
    )

    @admin.display(description='المعاينة')
    def banner_preview(self, obj):
        return format_html(
            '<img src="{}" style="width: 70px; height: 35px; object-fit: cover; border-radius: 4px;" />',
            obj.get_image_url
        )


# ==============================================================================
# 9. مركز الإشعارات والتنبيهات (Notifications)
# ==============================================================================

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['title', 'target_badge', 'notification_type_badge', 'is_read_badge', 'created_at', 'link_action']
    list_filter = ['is_read', 'for_admin', 'notification_type', 'created_at']
    search_fields = ['title', 'message', 'recipient__username', 'recipient__email', 'order__order_number']
    list_per_page = 30
    actions = ['mark_as_read', 'mark_as_unread', 'broadcast_push']

    @admin.display(description='الجهة')
    def target_badge(self, obj):
        if obj.for_admin:
            return format_html('<span style="background: #be123f; color: #fff; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">إدارة المتجر</span>')
        if obj.recipient:
            return format_html('<span style="background: #0284c7; color: #fff; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">{}</span>', obj.recipient.username)
        return format_html('<span style="background: #64748b; color: #fff; padding: 2px 8px; border-radius: 12px; font-size: 11px;">عام</span>')

    @admin.display(description='النوع')
    def notification_type_badge(self, obj):
        colors = {
            'order_created': '#d97706',
            'payment_verified': '#10b981',
            'processing': '#6366f1',
            'out_for_delivery': '#8b5cf6',
            'delivered': '#059669',
            'cancelled': '#e11d48',
            'low_stock': '#ea580c',
            'system': '#475569',
        }
        color = colors.get(obj.notification_type, '#64748b')
        return format_html('<span style="background: {}; color: #fff; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">{}</span>', color, obj.get_notification_type_display())

    @admin.display(description='الحالة')
    def is_read_badge(self, obj):
        if obj.is_read:
            return format_html('<span style="color: #10b981; font-weight: bold;">✓ مقروء</span>')
        return format_html('<span style="background: #f43f5e; color: #fff; padding: 1px 7px; border-radius: 10px; font-size: 11px; font-weight: bold;">● جديد</span>')

    @admin.display(description='الرابط')
    def link_action(self, obj):
        if obj.link:
            return format_html('<a href="{}" style="color: #e11d48; font-weight: bold; text-decoration: underline;">فتح الرابط ↗</a>', obj.link)
        return '-'

    @admin.action(description='تحديد كمقروء')
    def mark_as_read(self, request, queryset):
        count = queryset.update(is_read=True)
        self.message_user(request, f"تم تحديد {count} إشعار كمقروء بنجاح.")

    @admin.action(description='تحديد كغير مقروء')
    def mark_as_unread(self, request, queryset):
        count = queryset.update(is_read=False)
        self.message_user(request, f"تم تحديد {count} إشعار كغير مقروء.")

    @admin.action(description='📢 بث الإشعارات المحددة كهواتف (Web Push Broadcast)')
    def broadcast_push(self, request, queryset):
        from .push_notifications import broadcast_web_push
        total_sent = 0
        for notif in queryset:
            total_sent += broadcast_web_push(
                title=notif.title,
                body=notif.message,
                url=notif.link or "/",
                user_filter=notif.recipient
            )
        self.message_user(request, f"تم بنجاح بث {queryset.count()} إشعار إلى {total_sent} جهاز مشترك!")


# ==============================================================================
# 10. ملفات العملاء المسجلين (User Profiles)
# ==============================================================================

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user_name', 'user_email', 'phone', 'preferred_city', 'created_at']
    search_fields = ['user__username', 'user__first_name', 'user__last_name', 'user__email', 'phone', 'preferred_city']
    readonly_fields = ['created_at', 'updated_at']

    @admin.display(description='اسم العميل')
    def user_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    @admin.display(description='البريد الإلكتروني')
    def user_email(self, obj):
        return obj.user.email or '—'


# ==============================================================================
# 11. مشتركو إشعارات وتطبيق الهاتف (Web Push Subscribers)
# ==============================================================================

@admin.register(WebPushSubscription)
class WebPushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ['subscriber_label', 'user_agent_short', 'created_at', 'updated_at']
    search_fields = ['user__username', 'user__first_name', 'user__email', 'endpoint']
    list_filter = ['created_at']
    readonly_fields = ['created_at', 'updated_at', 'endpoint', 'p256dh', 'auth', 'user_agent']
    actions = ['send_test_push']

    @admin.display(description='المشترك')
    def subscriber_label(self, obj):
        if obj.user:
            return format_html(
                '<span style="font-weight: 700; color: #0284c7;">👤 {}</span>',
                obj.user.get_full_name() or obj.user.username
            )
        return format_html('<span style="color: #64748b;">📱 زائر مجهول (هاتف)</span>')

    @admin.display(description='الجهاز / المتصفح')
    def user_agent_short(self, obj):
        return obj.user_agent[:50] + ('...' if len(obj.user_agent) > 50 else '') if obj.user_agent else '—'

    @admin.action(description='🔔 إرسال إشعار تجريبي مباشر للأجهزة المحددة')
    def send_test_push(self, request, queryset):
        from .push_notifications import send_web_push
        count = 0
        for sub in queryset:
            if send_web_push(sub, title="Brand Veloura ✨", body="هذا إشعار تجريبي ناجح من لوحة إدارة المتجر!", url="/"):
                count += 1
        self.message_user(request, f"تم بنجاح إرسال الإشعار التجريبي لـ {count} جهاز.")
