import os
import json
import base64
import logging
from decimal import Decimal
from django.conf import settings
from .models import StoreSettings, WebPushSubscription, Notification

logger = logging.getLogger(__name__)


def get_or_create_vapid_keys():
    """
    استرجاع مفاتيح VAPID أو توليدها وحفظها تلقائياً إن لم تكن متوفرة
    يعيد (public_key, private_key, claims_email)
    """
    env_pub = os.getenv('VAPID_PUBLIC_KEY', '').strip()
    env_priv = os.getenv('VAPID_PRIVATE_KEY', '').strip()
    env_email = os.getenv('VAPID_CLAIMS_EMAIL', 'mailto:support@brandveloura.com').strip()

    if env_pub and env_priv:
        return env_pub, env_priv, env_email

    try:
        store_settings = StoreSettings.get_settings()
        if store_settings.vapid_public_key and store_settings.vapid_private_key:
            return (
                store_settings.vapid_public_key,
                store_settings.vapid_private_key,
                store_settings.vapid_claims_email or env_email
            )

        # Generate fresh VAPID keypair
        from py_vapid import Vapid
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

        vapid = Vapid()
        vapid.generate_keys()

        raw_pub = vapid.public_key.public_bytes(
            encoding=Encoding.X962,
            format=PublicFormat.UncompressedPoint
        )
        b64_pub = base64.urlsafe_b64encode(raw_pub).decode('utf-8').rstrip('=')

        raw_priv = vapid.private_key.private_numbers().private_value.to_bytes(32, 'big')
        b64_priv = base64.urlsafe_b64encode(raw_priv).decode('utf-8').rstrip('=')

        store_settings.vapid_public_key = b64_pub
        store_settings.vapid_private_key = b64_priv
        store_settings.vapid_claims_email = env_email
        store_settings.save(update_fields=['vapid_public_key', 'vapid_private_key', 'vapid_claims_email'])

        return b64_pub, b64_priv, env_email
    except Exception as ex:
        logger.warning(f"Error resolving VAPID keys: {ex}")
        return "", "", env_email


def send_web_push(subscription, title, body, url="/", icon=None, badge=None):
    """
    إرسال إشعار ويب / تطبيق مباشر لجهاز معين
    """
    pub_key, priv_key, claims_email = get_or_create_vapid_keys()
    if not priv_key:
        logger.warning("VAPID private key is not configured. Skipping push notification.")
        return False

    payload = json.dumps({
        "title": title,
        "body": body,
        "url": url or "/",
        "icon": icon or "/static/icons/icon-192.png",
        "badge": badge or "/static/icons/icon-192.png"
    })

    try:
        from pywebpush import webpush, WebPushException

        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {
                    "p256dh": subscription.p256dh,
                    "auth": subscription.auth
                }
            },
            data=payload,
            vapid_private_key=priv_key,
            vapid_claims={"sub": claims_email}
        )
        return True
    except Exception as ex:
        # Check if the subscription has expired (HTTP 404 or 410)
        resp = getattr(ex, 'response', None)
        if resp is not None and getattr(resp, 'status_code', None) in (404, 410):
            try:
                subscription.delete()
                logger.info(f"Deleted expired push subscription: {subscription.endpoint}")
            except Exception:
                pass
        else:
            logger.warning(f"Web push dispatch failed: {ex}")
        return False


def broadcast_web_push(title, body, url="/", icon=None, user_filter=None):
    """
    بث إشعار ويب فوري لجميع الأجهزة المشتركة (أو لمستخدم معين)
    وحفظ الإشعار في مركز الإشعارات بالمتجر
    """
    subscriptions_qs = WebPushSubscription.objects.all()
    if user_filter:
        subscriptions_qs = subscriptions_qs.filter(user=user_filter)

    successful_sends = 0
    for sub in subscriptions_qs:
        if send_web_push(sub, title=title, body=body, url=url, icon=icon):
            successful_sends += 1

    # Save to notification center in database
    try:
        Notification.objects.create(
            recipient=user_filter,
            for_admin=False,
            title=title,
            message=body,
            notification_type='promotion' if not user_filter else 'system',
            link=url or "/"
        )
    except Exception as ex:
        logger.warning(f"Failed to record notification log: {ex}")

    return successful_sends


def send_product_promotion_push(product, custom_title=None, custom_body=None):
    """
    إرسال إشعار تسويقي وترويجي لمنتج عند إضافته أو تعديل سعره / خصمه
    """
    # 1. Generate smart title
    if custom_title and custom_title.strip():
        title = custom_title.strip()
    elif product.compare_at_price_yer and product.compare_at_price_yer > product.price_yer:
        discount = product.discount_percentage
        title = f"🔥 تخفيض حصري: {product.name_ar} (خصم {discount}%)"
    elif product.is_new:
        title = f"✨ وصل حديثاً إلى البوتيك: {product.name_ar}"
    else:
        title = f"⭐ متاح الآن: {product.name_ar}"

    # 2. Generate smart body text
    if custom_body and custom_body.strip():
        body = custom_body.strip()
    elif product.compare_at_price_yer and product.compare_at_price_yer > product.price_yer:
        body = f"تسوق الآن بسعر {product.price_yer:,.0f} ر.ي بدلاً من {product.compare_at_price_yer:,.0f} ر.ي! اضغط هنا للتفاصيل والطلب الفوري."
    else:
        brand_info = f"من {product.brand_name} " if product.brand_name else ""
        body = f"منتج فاخر {brand_info}بسعر {product.price_yer:,.0f} ر.ي ({product.price_sar} ر.س). انقر للمعاينة والطلب."

    url = f"/product/{product.slug}/"
    icon = product.primary_image_url

    return broadcast_web_push(title=title, body=body, url=url, icon=icon)


def send_order_status_push(order, new_status):
    """
    إرسال إشعار فوري للعميل على هاتفه عند تغيير حالة طلبه
    """
    status_messages = {
        'payment_verified': (
            "✅ تم تأكيد الدفع لطلبك",
            f"تم التحقق من حوالتك بنجاح لطلبك رقم #{order.order_number}. بدأ فريقنا تجهيز طلبك الفاخر فوراً."
        ),
        'processing': (
            "🎁 طلبك قيد التجهيز والتغليف",
            f"طلبك #{order.order_number} يتم تجهيزه وتغليفه حالياً بعناية تليق بك."
        ),
        'out_for_delivery': (
            "🚗 طلبك مع مندوب التوصيل الآن",
            f"خرج طلبك #{order.order_number} للتوصيل إلى {order.shipping_city}. يرجى إبقاء هاتفك متاحاً للاستلام."
        ),
        'delivered': (
            "✨ تم تسليم طلبك بنجاح",
            f"سعدنا بخدمتك وتسليم طلبك #{order.order_number}. نتمنى لك تجربة ممتعة مع Brand Veloura!"
        ),
        'cancelled': (
            "⚠️ إشعار بخصوص طلبك",
            f"تم إلغاء الطلب #{order.order_number}. إذا كان لديك استفسار يسعدنا تواصلك معنا مباشرة عبر الواتساب."
        ),
    }

    if new_status not in status_messages:
        return 0

    title, body = status_messages[new_status]
    url = f"/account/orders/"

    if order.user:
        return broadcast_web_push(title=title, body=body, url=url, user_filter=order.user)

    return 0
