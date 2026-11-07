import os
from decimal import Decimal
from .models import StoreSettings, Category


def store_context(request):
    """سياق عام يتم تمريره تلقائياً لكافة صفحات وقوالب المتجر"""
    from django.core.cache import cache
    settings = StoreSettings.get_settings()
    
    categories = cache.get('bv_active_categories')
    if categories is None:
        categories = list(Category.objects.filter(is_active=True).order_by('display_order'))
        try:
            cache.set('bv_active_categories', categories, timeout=300)
        except Exception:
            pass

    main_categories = cache.get('bv_main_categories')
    if main_categories is None:
        from django.db.models import Prefetch
        sub_prefetch = Prefetch(
            'subcategories',
            queryset=Category.objects.filter(is_active=True).order_by('display_order', 'name_ar')
        )
        main_categories = list(
            Category.objects.filter(is_active=True, parent__isnull=True)
            .prefetch_related(sub_prefetch)
            .order_by('display_order', 'name_ar')
        )
        try:
            cache.set('bv_main_categories', main_categories, timeout=300)
        except Exception:
            pass
    
    # حساب عدد عناصر السلة من الجلسة (Session-based cart)
    cart = request.session.get('cart', {})
    cart_count = sum(item.get('quantity', 1) for item in cart.values())
    
    # العملة النشطة الحالية (الافتراضي YER، مع إمكانية التبديل إلى SAR)
    active_currency = request.session.get('active_currency', 'YER')
    
    # معرف عميل Google ورابط الاستجابة المعتمد للمصادقة
    google_client_id = settings.effective_google_client_id
    try:
        from django.urls import reverse
        google_callback_url = request.build_absolute_uri(reverse('store:google_callback'))
        if not os.getenv('DJANGO_DEBUG', 'False').lower() in ('true', '1') and google_callback_url.startswith('http://'):
            google_callback_url = google_callback_url.replace('http://', 'https://', 1)
    except Exception:
        google_callback_url = ''
    
    # إحصائيات الإشعارات والتنبيهات
    unread_notifications_count = 0
    admin_unread_notifications_count = 0
    if request.user.is_authenticated:
        from .models import Notification
        unread_notifications_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        if request.user.is_staff:
            admin_unread_notifications_count = Notification.objects.filter(for_admin=True, is_read=False).count()

    # ضمان انعكاس متغيرات البيئة فورياً في المتجر (WhatsApp, Phone, Instagram)
    env_phone = os.getenv('STORE_PHONE', '').strip()
    env_wa = os.getenv('STORE_WHATSAPP', '').strip()
    env_insta = os.getenv('STORE_INSTAGRAM', '').strip()
    if env_phone:
        settings.contact_phone = env_phone
    if env_wa:
        settings.contact_whatsapp = env_wa
    if env_insta:
        settings.contact_instagram = env_insta

    return {
        'store_settings': settings,
        'global_categories': categories,
        'main_categories': main_categories,
        'cart_count': cart_count,
        'active_currency': active_currency,
        'yer_per_sar': settings.yer_per_sar or Decimal('530.00'),
        'google_client_id': google_client_id,
        'google_callback_url': google_callback_url,
        'google_site_verification': os.getenv('GOOGLE_SITE_VERIFICATION', '').strip(),
        'unread_notifications_count': unread_notifications_count,
        'admin_unread_notifications_count': admin_unread_notifications_count,
    }

