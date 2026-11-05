from decimal import Decimal
from .models import StoreSettings, Category


def store_context(request):
    """سياق عام يتم تمريره تلقائياً لكافة صفحات وقوالب المتجر"""
    settings = StoreSettings.get_settings()
    categories = Category.objects.filter(is_active=True).order_by('display_order')
    
    # حساب عدد عناصر السلة من الجلسة (Session-based cart)
    cart = request.session.get('cart', {})
    cart_count = sum(item.get('quantity', 1) for item in cart.values())
    
    # العملة النشطة الحالية (الافتراضي YER، مع إمكانية التبديل إلى SAR)
    active_currency = request.session.get('active_currency', 'YER')
    
    # معرف عميل Google لتسجيل الدخول السريع
    google_client_id = settings.effective_google_client_id
    
    # إحصائيات الإشعارات والتنبيهات
    unread_notifications_count = 0
    admin_unread_notifications_count = 0
    if request.user.is_authenticated:
        from .models import Notification
        unread_notifications_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        if request.user.is_staff:
            admin_unread_notifications_count = Notification.objects.filter(for_admin=True, is_read=False).count()

    return {
        'store_settings': settings,
        'global_categories': categories,
        'cart_count': cart_count,
        'active_currency': active_currency,
        'yer_per_sar': settings.yer_per_sar or Decimal('530.00'),
        'google_client_id': google_client_id,
        'unread_notifications_count': unread_notifications_count,
        'admin_unread_notifications_count': admin_unread_notifications_count,
    }

