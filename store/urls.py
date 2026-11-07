from django.urls import path, register_converter
from . import views

class UnicodeSlugConverter:
    """محول مسارات الروابط ليدعم الحروف العربية واليونيكود في الـ slugs بدون أخطاء NoReverseMatch"""
    regex = r'[-\w]+'
    def to_python(self, value):
        return str(value)
    def to_url(self, value):
        return str(value)

register_converter(UnicodeSlugConverter, 'slug')

app_name = 'store'

urlpatterns = [
    # صفحات المتجر الرئيسية
    path('', views.home_view, name='home'),
    path('products/', views.product_list_view, name='product_list'),
    path('perfumes/', views.perfumes_catalog_view, name='perfumes_catalog'),
    path('watches/', views.watches_catalog_view, name='watches_catalog'),
    path('cosmetics/', views.cosmetics_catalog_view, name='cosmetics_catalog'),
    path('brands/', views.brands_list_view, name='brands_list'),
    path('brands/<slug:slug>/', views.brand_detail_view, name='brand_detail'),
    path('gifting/', views.gift_builder_view, name='gift_builder'),
    path('gifting/calculate/', views.gift_calculate_live, name='gift_calculate'),
    path('products/<slug:slug>/', views.product_detail_view, name='product_detail'),
    path('products/<slug:slug>/modal/', views.product_quick_view, name='product_modal'),
    
    # مسارات توافقية للمنتجات
    path('product/<slug:slug>/', views.product_detail_view, name='product_detail_alias'),
    
    # سلة المشتريات التفاعلية (HTMX)
    path('cart/', views.cart_view, name='cart_view'),
    path('cart/add/', views.cart_add, name='cart_add'),
    path('cart/update/', views.cart_update_quantity, name='cart_update'),
    path('cart/remove/', views.cart_remove_item, name='cart_remove'),
    
    # العملات والشحن
    path('set-currency/', views.toggle_currency, name='toggle_currency'),
    path('get-shipping-fee/', views.get_shipping_fee, name='get_shipping_fee'),
    
    # إتمام الطلب والتحقق والتتبع
    path('checkout/', views.checkout_view, name='checkout'),
    path('order-success/<str:order_number>/', views.order_success_view, name='order_success'),
    path('order/success/<str:order_number>/', views.order_success_view, name='order_success_alias'),
    path('track-order/', views.track_order_view, name='track_order'),
    
    # الحسابات والمصادقة (تسجيل الدخول، إنشاء حساب، ودخول Google)
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('auth/google/', views.google_login_redirect, name='google_login'),
    path('auth/google/callback/', views.google_auth_callback, name='google_callback'),
    path('account/', views.account_profile_view, name='account_profile'),
    path('account/orders/', views.account_profile_view, name='account_orders'),
    path('account/reorder/<str:order_number>/', views.reorder_view, name='reorder'),
    
    # مركز الإشعارات والتنبيهات التفاعلي (HTMX)
    path('notifications/badge/', views.notification_badge_view, name='notification_badge'),
    path('notifications/dropdown/', views.notifications_dropdown_view, name='notifications_dropdown'),
    path('notifications/<int:notification_id>/read/', views.mark_notification_read_view, name='mark_notification_read'),
    path('notifications/mark-all-read/', views.mark_all_notifications_read_view, name='mark_all_notifications_read'),

    # تطبيق الويب التقدمي (PWA) وإشعارات الهاتف ووضع أوفلاين
    path('manifest.json', views.pwa_manifest, name='pwa_manifest'),
    path('sw.js', views.service_worker, name='service_worker'),
    path('offline/', views.offline_view, name='offline'),
    path('api/push/vapid-key/', views.push_vapid_key, name='push_vapid_key'),
    path('api/push/subscribe/', views.push_subscribe, name='push_subscribe'),

    # مسارات الفهرسة والذكاء الاصطناعي (SEO / GEO / AI Overviews)
    path('robots.txt', views.robots_txt, name='robots_txt'),
    path('sitemap.xml', views.sitemap_xml, name='sitemap_xml'),
    path('llms.txt', views.llms_txt, name='llms_txt'),
    path('health/', views.health_check, name='health_check'),
    path('healthz/', views.health_check, name='healthz_check'),
]

