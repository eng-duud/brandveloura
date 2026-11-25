import copy
import os
import time
from decimal import Decimal
from django.db.models import Prefetch
from .cache_service import cache_get_or_set_safe
from .models import StoreSettings, Category


def store_context(request):
    """سياق عام يتم تمريره تلقائياً لكافة صفحات وقوالب المتجر"""
    settings = copy.copy(StoreSettings.get_settings())

    categories = cache_get_or_set_safe(
        'bv_active_categories',
        lambda: list(Category.objects.filter(is_active=True).order_by('display_order')),
        timeout=300,
    )

    main_categories = cache_get_or_set_safe(
        'bv_main_categories',
        lambda: list(
            Category.objects.filter(is_active=True, parent__isnull=True)
            .prefetch_related(
                Prefetch(
                    'subcategories',
                    queryset=Category.objects.filter(is_active=True).order_by('display_order', 'name_ar'),
                )
            )
            .order_by('display_order', 'name_ar')
        ),
        timeout=300,
    )
    
    # حساب عدد عناصر السلة واستعادتها تلقائياً للمستخدم المسجل عبر الكاش السريع (صفر استعلامات N+1)
    cart = request.session.get('cart')
    user_avatar_url = ''
    if request.user.is_authenticated:
        try:
            from .models import UserProfile
            prof_meta = cache_get_or_set_safe(
                f'bv_user_profile_meta_{request.user.pk}',
                lambda: (
                    UserProfile.objects.filter(user_id=request.user.pk)
                    .values('avatar_url', 'cart_data')
                    .first()
                    or {'avatar_url': '', 'cart_data': {}}
                ),
                timeout=300,
                jitter_ratio=0.05,
            ) or {'avatar_url': '', 'cart_data': {}}
            user_avatar_url = prof_meta.get('avatar_url') or ''
            if (cart is None or len(cart) == 0) and prof_meta.get('cart_data'):
                cart = dict(prof_meta['cart_data'])
                request.session['cart'] = cart
                request.session.modified = True
        except Exception:
            pass
    if not cart:
        cart = {}
    cart_count = sum(item.get('quantity', 1) for item in cart.values())
    
    # مدة حجز السلة بالدقائق والثواني المتبقية
    cart_remaining_seconds = 0
    res_minutes = getattr(settings, 'cart_reservation_minutes', 60)
    if cart and res_minutes > 0:
        now_ts = int(time.time())
        expires_at = request.session.get('cart_expires_at')
        if not expires_at:
            expires_at = now_ts + (res_minutes * 60)
            request.session['cart_expires_at'] = expires_at
            request.session.modified = True
        cart_remaining_seconds = max(0, expires_at - now_ts)
    
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
        user_cache_key = f'bv_unread_notifications_user_{request.user.pk}'
        unread_notifications_count = cache_get_or_set_safe(
            user_cache_key,
            lambda: Notification.objects.filter(recipient=request.user, is_read=False).count(),
            timeout=15,
            jitter_ratio=0.0,
        ) or 0
        if request.user.is_staff:
            admin_cache_key = 'bv_admin_unread_notifications'
            admin_unread_notifications_count = cache_get_or_set_safe(
                admin_cache_key,
                lambda: Notification.objects.filter(for_admin=True, is_read=False).count(),
                timeout=15,
                jitter_ratio=0.0,
            ) or 0

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
        'cart_remaining_seconds': cart_remaining_seconds,
        'cart_reservation_minutes': res_minutes,
        'active_currency': active_currency,
        'yer_per_sar': settings.yer_per_sar or Decimal('530.00'),
        'google_client_id': google_client_id,
        'google_callback_url': google_callback_url,
        'google_site_verification': os.getenv('GOOGLE_SITE_VERIFICATION', '').strip(),
        'unread_notifications_count': unread_notifications_count,
        'admin_unread_notifications_count': admin_unread_notifications_count,
        'user_avatar_url': user_avatar_url,
    }
