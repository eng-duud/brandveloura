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
    Category, Product, ProductImage, 
    Order, OrderItem, HeroBanner, UserProfile, Notification
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

    def is_staff_badge(self, obj):
        if obj.is_superuser:
            return format_html('<span style="background: #be123f; color: #fff; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">مدير رئيسي</span>')
        elif obj.is_staff:
            return format_html('<span style="background: #0284c7; color: #fff; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">مشرف متجر</span>')
        return format_html('<span style="color: #64748b; font-size: 11px;">عميل مسجل</span>')
    is_staff_badge.short_description = 'نوع الحساب'

try:
    admin.site.unregister(User)
    admin.site.register(User, SimplifiedUserAdmin)
except Exception:
    pass


# ==============================================================================
# 2. أقسام وفئات المتجر (Categories)
# ==============================================================================

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['image_preview', 'name_ar', 'category_type_badge', 'products_count', 'is_featured', 'is_active', 'display_order']
    list_editable = ['is_featured', 'is_active', 'display_order']
    search_fields = ['name_ar', 'name_en']
    list_filter = ['category_type', 'is_featured', 'is_active']
    prepopulated_fields = {'slug': ('name_ar',)}
    list_per_page = 25

    fieldsets = (
        ('معلومات القسم الأساسية', {
            'description': 'أدخل اسم وتصنيف القسم وصورته المعروضة في شريط الأقسام والصفحة الرئيسية',
            'fields': (('name_ar', 'category_type'), 'image', ('is_featured', 'is_active', 'display_order'))
        }),
        ('بيانات إضافية ورابط SEO (اختياري)', {
            'classes': ('collapse',),
            'description': 'يتم إنشاء الرابط تلقائياً من الاسم، يمكنك ترك هذه الحقول فارغة إن أردت',
            'fields': (('name_en', 'slug'), 'description', 'image_url_fallback')
        }),
    )

    def image_preview(self, obj):
        return format_html(
            '<img src="{}" style="width: 44px; height: 44px; object-fit: cover; border-radius: 8px; border: 1.5px solid #fecdd3;" />',
            obj.get_image_url
        )
    image_preview.short_description = 'الصورة'

    def category_type_badge(self, obj):
        types_map = {
            'perfumes': ('عطور فاخرة', '#be185d', '#fdf2f8'),
            'watches': ('ساعات راقية', '#0369a1', '#f0f9ff'),
            'cosmetics': ('مستحضرات تجميل', '#b45309', '#fffbeb'),
            'care': ('عناية بالبشرة', '#047857', '#ecfdf5'),
            'bundles': ('باقات هدايا', '#6d28d9', '#f5f3ff'),
            'general': ('عام', '#475569', '#f8fafc'),
        }
        title, color, bg = types_map.get(obj.category_type, ('عام', '#475569', '#f8fafc'))
        return format_html(
            '<span style="background-color: {}; color: {}; border: 1px solid {}; padding: 2px 9px; border-radius: 6px; font-weight: 700; font-size: 11px;">{}</span>',
            bg, color, color + '33', title
        )
    category_type_badge.short_description = 'نوع القسم'

    def products_count(self, obj):
        count = obj.products.count()
        url = reverse('admin:store_product_changelist') + f"?category__id__exact={obj.id}"
        return format_html(
            '<a href="{}" style="font-weight: 700; color: #be123f; text-decoration: underline;" title="عرض منتجات هذا القسم">{} منتج ↗</a>',
            url, count
        )
    products_count.short_description = 'المنتجات التابعة'


# ==============================================================================
# 3. إدارة صور ومنتجات المتجر الفاخرة (Products)
# ==============================================================================

class ProductImageInline(admin.TabularInline):
    """معرض صور المنتج المتعددة بطريقة نظيفة ومبسطة"""
    model = ProductImage
    extra = 1
    fields = ['image', 'image_url_fallback', 'is_primary', 'preview', 'display_order']
    readonly_fields = ['preview']

    def preview(self, instance):
        if instance and instance.pk and instance.get_image_url:
            badge = '<span style="display:block; font-size:10px; color:#be123f; font-weight:700; margin-top:2px;">⭐ رئيسية</span>' if instance.is_primary else ''
            return format_html(
                '<div style="text-align: center;"><img src="{}" style="width: 52px; height: 52px; object-fit: cover; border-radius: 8px; border: 1.5px solid #fecdd3; box-shadow: 0 2px 6px rgba(0,0,0,0.06);" />{}</div>',
                instance.get_image_url,
                format_html(badge)
            )
        return '—'
    preview.short_description = 'معاينة'


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        'image_preview', 'name_ar', 'brand_name_badge', 'category', 
        'formatted_price_yer', 'formatted_price_sar', 'grades_badge', 
        'stock_badge', 'is_featured', 'is_new', 'is_active'
    ]
    list_filter = [
        'is_active', 'is_featured', 'is_new', 'is_best_seller', 
        'has_grades', 'category', 'brand_name'
    ]
    search_fields = ['name_ar', 'name_en', 'brand_name', 'sku']
    search_help_text = 'البحث باسم المنتج بالعربي أو الإنجليزي، الماركة (Brand)، أو رمز SKU'
    date_hierarchy = 'created_at'
    list_per_page = 25
    list_editable = ['is_featured', 'is_new', 'is_active']
    autocomplete_fields = ['category']
    prepopulated_fields = {'slug': ('name_ar',)}
    readonly_fields = ['currency_preview_info', 'created_at', 'updated_at']
    inlines = [ProductImageInline]
    actions = [
        'duplicate_products',
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
            'description': 'حدد القسم الرئيسي للمنتج (مع بحث ذكي وسريع)، واكتب اسم الماركة والاسم التجاري المعروض للعملاء في واجهة المتجر.',
            'fields': (
                ('category', 'brand_name'),
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
        ('3. خيارات درجات العطور (أصلي 100% وماستر طبق الأصل - اختياري)', {
            'classes': ('collapse',),
            'description': 'خاص بالعطور الفاخرة: إذا كان المنتج يتوفر بخياري (أصلي 100% وماستر كواليتي طبق الأصل)، فعّل هذا الخيار وحدد سعر كل درجة لتمكين العميل من الاختيار بينهما في صفحة المنتج.',
            'fields': (
                'has_grades',
                ('price_original_yer', 'price_master_yer'),
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
        ('6. المواصفات الفنية التفصيلية (JSON Specifications)', {
            'classes': ('collapse',),
            'description': 'مواصفات إضافية كالهرم العطري أو مقاس الساعة. يمكنك تركها أو كتابة كائن JSON مثل: {"حجم العبوة": "100 مل", "التركيز": "Eau de Parfum", "الجنس": "للجنسين"}',
            'fields': (
                'specifications',
            )
        }),
    )

    def brand_name_badge(self, obj):
        if obj.brand_name:
            return format_html(
                '<span style="background: #fdf2f8; color: #be123f; border: 1px solid #fecdd3; padding: 2px 8px; border-radius: 6px; font-weight: 700; font-size: 11px;">{}</span>',
                obj.brand_name
            )
        return format_html('<span style="color: #94a3b8; font-size: 11px;">—</span>')
    brand_name_badge.short_description = 'الماركة'
    brand_name_badge.admin_order_field = 'brand_name'

    def stock_badge(self, obj):
        if obj.stock_quantity <= 0:
            return format_html('<span style="background-color: #fee2e2; color: #dc2626; border: 1px solid #fca5a5; padding: 2px 8px; border-radius: 6px; font-weight: bold; font-size: 11px;">نفد من المخزون ⚠️</span>')
        elif obj.stock_quantity <= 3:
            return format_html('<span style="background-color: #fef3c7; color: #d97706; border: 1px solid #fcd34d; padding: 2px 8px; border-radius: 6px; font-weight: bold; font-size: 11px;">متبقي {} فقط!</span>', obj.stock_quantity)
        return format_html('<span style="color: #059669; font-weight: bold; font-size: 11px;">{} قطعة</span>', obj.stock_quantity)
    stock_badge.short_description = 'المخزون'
    stock_badge.admin_order_field = 'stock_quantity'

    def grades_badge(self, obj):
        if obj.has_grades:
            orig = f"{obj.price_original_yer:,.0f}" if obj.price_original_yer else "—"
            mast = f"{obj.price_master_yer:,.0f}" if obj.price_master_yer else "—"
            return format_html(
                '<span style="background-color: #fdf2f8; color: #be185d; border: 1px solid #fbcfe8; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: bold;">أصلي: {} | ماستر: {}</span>',
                orig, mast
            )
        return format_html('<span style="color: #94a3b8; font-size: 11px;">—</span>')
    grades_badge.short_description = 'أصلي / ماستر'

    def image_preview(self, obj):
        url = obj.primary_image_url
        return format_html(
            '<img src="{}" style="width: 46px; height: 46px; object-fit: cover; border-radius: 8px; border: 1.5px solid #fecdd3; box-shadow: 0 2px 5px rgba(0,0,0,0.05);" />',
            url
        )
    image_preview.short_description = 'الصورة'

    def formatted_price_yer(self, obj):
        return format_html('<span style="font-weight: 700; color: #0f172a;">{}</span>', f"{obj.price_yer:,.0f} ر.ي")
    formatted_price_yer.short_description = 'السعر (يمني)'
    formatted_price_yer.admin_order_field = 'price_yer'

    def formatted_price_sar(self, obj):
        return format_html('<span style="color: #be123f; font-weight: 700;">{} ر.س</span>', obj.price_sar)
    formatted_price_sar.short_description = 'المعادل (سعودي)'

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
            mast_yer = f"{obj.price_master_yer:,.0f}" if obj.price_master_yer else "—"
            mast_sar = f"{obj.price_master_sar}" if obj.price_master_sar else "—"
            html += f"""
                <div style="width: 100%; border-top: 1px dashed #fecdd3; padding-top: 8px; margin-top: 4px; display: flex; gap: 20px;">
                    <div>
                        <strong style="color: #be123f;">الأصلي 100%:</strong> {orig_yer} ر.ي ({orig_sar} ر.س)
                    </div>
                    <div>
                        <strong style="color: #831843;">ماستر كواليتي:</strong> {mast_yer} ر.ي ({mast_sar} ر.س)
                    </div>
                </div>
            """
        html += "</div></div>"
        return format_html(html)
    currency_preview_info.short_description = 'ملخص التسعير وسعر الصرف المباشر'

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

    def product_image_preview(self, instance):
        if instance and instance.product_image_url:
            return format_html(
                '<img src="{}" style="width: 45px; height: 45px; object-fit: cover; border-radius: 6px;" />',
                instance.product_image_url
            )
        return '—'
    product_image_preview.short_description = 'المنتج'


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
    readonly_fields = [
        'order_number', 'created_at', 'updated_at', 
        'receipt_large_view', 'customer_whatsapp_link',
        'formatted_total_yer', 'formatted_total_sar', 'currency_due_badge',
        'formatted_subtotal', 'formatted_shipping_fee', 'stock_deducted', 'exchange_rate_applied', 'user'
    ]
    inlines = [OrderItemInline]

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
    customer_whatsapp_link.short_description = 'مراسلة العميل'

    def formatted_subtotal(self, obj):
        return f"{obj.subtotal_yer:,.0f} ر.ي" if obj.subtotal_yer else "0 ر.ي"
    formatted_subtotal.short_description = 'مجموع المنتجات الفرعي'

    def formatted_shipping_fee(self, obj):
        return f"{obj.shipping_fee_yer:,.0f} ر.ي" if obj.shipping_fee_yer else "0 ر.ي"
    formatted_shipping_fee.short_description = 'رسوم التوصيل'

    def gift_badge(self, obj):
        if obj.is_gift:
            wrap = " + تغليف" if obj.is_luxury_gift_wrapping else ""
            return format_html(
                '<span style="background-color: #fdf2f8; color: #be185d; border: 1px solid #fbcfe8; padding: 2px 7px; border-radius: 6px; font-weight: bold; font-size: 11px;">🎁 هدية{}</span>',
                wrap
            )
        return '—'
    gift_badge.short_description = 'النوع'

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
    currency_due_badge.short_description = 'المستحق'

    def customer_whatsapp_btn(self, obj):
        phone = obj.customer_phone.replace('+', '').replace(' ', '')
        msg = f"مرحباً {obj.customer_name}، نتواصل معك من متجر Brand Veloura بخصوص طلبك #{obj.order_number}: حالة طلبك الحالية هي ({obj.get_status_display()})."
        url = f"https://wa.me/{phone}?text={urllib.parse.quote(msg)}"
        return format_html(
            '<a href="{}" target="_blank" style="background-color: #25D366; color: white; padding: 3px 8px; border-radius: 6px; font-size: 10px; font-weight: bold; text-decoration: none; display: inline-flex; align-items: center; gap: 3px;">واتساب</a>',
            url
        )
    customer_whatsapp_btn.short_description = 'تواصل'

    def formatted_total_yer(self, obj):
        return f"{obj.total_yer:,.0f} ر.ي" if obj.total_yer else "0 ر.ي"
    formatted_total_yer.short_description = 'الإجمالي (يمني)'

    def formatted_total_sar(self, obj):
        return f"{obj.total_sar:,.1f} ر.س" if obj.total_sar else "0 ر.س"
    formatted_total_sar.short_description = 'الإجمالي (سعودي)'

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
    status_badge.short_description = 'حالة الطلب'

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
    receipt_preview.short_description = 'إشعار التحويل'

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
    receipt_large_view.short_description = 'فحص السند مكبراً'

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


# ==============================================================================
# 4. إعدادات المتجر وسعر الصرف اليومي (Store Settings)
# ==============================================================================

@admin.register(StoreSettings)
class StoreSettingsAdmin(admin.ModelAdmin):
    list_display = ['store_name', 'yer_per_sar', 'contact_phone', 'contact_whatsapp', 'updated_at']

    fieldsets = (
        ('هوية المتجر وسعر الصرف اليومي', {
            'description': 'أي تعديل على سعر الصرف هنا سينعكس فوراً وتلقائياً على كافة أسعار المنتجات المحسوبة بالريال السعودي',
            'fields': (('store_name', 'yer_per_sar'), 'store_tagline', 'store_logo')
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

    def currency_badge(self, obj):
        if obj.currency == 'SAR':
            return format_html('<span style="background-color: #ecfdf5; color: #047857; padding: 2px 8px; border-radius: 6px; font-weight: bold; font-size: 11px;">🇸🇦 ريال سعودي فقط</span>')
        elif obj.currency == 'YER':
            return format_html('<span style="background-color: #f8fafc; color: #475569; padding: 2px 8px; border-radius: 6px; font-weight: bold; font-size: 11px;">🇾🇪 ريال يمني فقط</span>')
        return format_html('<span style="background-color: #fdf2f8; color: #be185d; padding: 2px 8px; border-radius: 6px; font-weight: bold; font-size: 11px;">يقبل الريالين</span>')
    currency_badge.short_description = 'العملة'

    def country_badge(self, obj):
        if obj.bank_country == 'SA':
            return '🇸🇦 السعودية (مغتربين)'
        return '🇾🇪 اليمن (محلي)'
    country_badge.short_description = 'الدولة'


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

    def formatted_fee(self, obj):
        return f"{obj.delivery_fee_yer:,.0f} ر.ي"
    formatted_fee.short_description = 'رسوم التوصيل'


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

    def banner_preview(self, obj):
        return format_html(
            '<img src="{}" style="width: 70px; height: 35px; object-fit: cover; border-radius: 4px;" />',
            obj.get_image_url
        )
    banner_preview.short_description = 'المعاينة'


# ==============================================================================
# 9. مركز الإشعارات والتنبيهات (Notifications)
# ==============================================================================

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['title', 'target_badge', 'notification_type_badge', 'is_read_badge', 'created_at', 'link_action']
    list_filter = ['is_read', 'for_admin', 'notification_type', 'created_at']
    search_fields = ['title', 'message', 'recipient__username', 'recipient__email', 'order__order_number']
    list_per_page = 30
    actions = ['mark_as_read', 'mark_as_unread']

    def target_badge(self, obj):
        if obj.for_admin:
            return format_html('<span style="background: #be123f; color: #fff; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">إدارة المتجر</span>')
        if obj.recipient:
            return format_html('<span style="background: #0284c7; color: #fff; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">{}</span>', obj.recipient.username)
        return format_html('<span style="background: #64748b; color: #fff; padding: 2px 8px; border-radius: 12px; font-size: 11px;">عام</span>')
    target_badge.short_description = 'الجهة'

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
    notification_type_badge.short_description = 'النوع'

    def is_read_badge(self, obj):
        if obj.is_read:
            return format_html('<span style="color: #10b981; font-weight: bold;">✓ مقروء</span>')
        return format_html('<span style="background: #f43f5e; color: #fff; padding: 1px 7px; border-radius: 10px; font-size: 11px; font-weight: bold;">● جديد</span>')
    is_read_badge.short_description = 'الحالة'

    def link_action(self, obj):
        if obj.link:
            return format_html('<a href="{}" style="color: #e11d48; font-weight: bold; text-decoration: underline;">فتح الرابط ↗</a>', obj.link)
        return '-'
    link_action.short_description = 'الرابط'

    @admin.action(description='تحديد كمقروء')
    def mark_as_read(self, request, queryset):
        count = queryset.update(is_read=True)
        self.message_user(request, f"تم تحديد {count} إشعار كمقروء بنجاح.")

    @admin.action(description='تحديد كغير مقروء')
    def mark_as_unread(self, request, queryset):
        count = queryset.update(is_read=False)
        self.message_user(request, f"تم تحديد {count} إشعار كغير مقروء.")


# ==============================================================================
# 10. ملفات العملاء المسجلين (User Profiles)
# ==============================================================================

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user_name', 'user_email', 'phone', 'preferred_city', 'created_at']
    search_fields = ['user__username', 'user__first_name', 'user__last_name', 'user__email', 'phone', 'preferred_city']
    readonly_fields = ['created_at', 'updated_at']

    def user_name(self, obj):
        return obj.user.get_full_name() or obj.user.username
    user_name.short_description = 'اسم العميل'

    def user_email(self, obj):
        return obj.user.email or '—'
    user_email.short_description = 'البريد الإلكتروني'
