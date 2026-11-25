import os
import sys
import time
import json
import base64
import logging
import threading
from django.db import close_old_connections, connection
from django.db.models import Q
from .cache_service import cache_get, cache_set
from .models import StoreSettings, WebPushSubscription, Notification

logger = logging.getLogger(__name__)

ORDER_PUSH_ENDPOINT_TTL = 86400 * 30  # 30 days


def bind_order_push_endpoint(order_number: str, endpoint: str) -> None:
    """
    ربط اشتراك إشعارات الجهاز برقم الطلب في Redis لمدة 30 يوماً
    حتى تصل إشعارات الشريط العلوي للعميل حتى لو طلب كزائر بدون حساب.
    """
    if not order_number or not endpoint:
        return
    cache_set(f"bv_order_push_ep:{order_number}", endpoint.strip(), timeout=ORDER_PUSH_ENDPOINT_TTL)


def get_order_push_endpoint(order_number: str) -> str:
    if not order_number:
        return ""
    return cache_get(f"bv_order_push_ep:{order_number}") or ""


def link_endpoint_to_user(endpoint: str, user) -> None:
    """
    ربط اشتراك إشعارات المتصفح/التطبيق بالمستخدم المسجل فور تسجيل الدخول أو إنشاء الحساب.
    """
    if not endpoint or not user or not getattr(user, "is_authenticated", False):
        return
    try:
        WebPushSubscription.objects.filter(endpoint=endpoint.strip()).exclude(user=user).update(user=user)
    except Exception as ex:
        logger.debug("Could not link push endpoint to user: %s", ex)


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


def send_web_push(
    subscription,
    title,
    body,
    url="/",
    icon=None,
    badge=None,
    image=None,
    tag=None,
    urgency="high",
    ttl=86400,
):
    """
    إرسال إشعار ويب / تطبيق أصلي مباشر للشريط العلوي في هاتف العميل (Android FCM / iOS APNs / Desktop)
    مع أولوية عالية (Urgency: high) ومدة بقاء (TTL: 24h) لضمان وصوله حتى لو كان الهاتف مقفلاً.
    """
    pub_key, priv_key, claims_email = get_or_create_vapid_keys()
    if not priv_key:
        logger.warning("VAPID private key is not configured. Skipping push notification.")
        return False

    now_ms = int(time.time() * 1000)
    payload_dict = {
        "title": title,
        "body": body,
        "url": url or "/",
        "icon": icon or "/static/icons/icon-192.png",
        "badge": badge or "/static/icons/icon-192.png",
        "tag": tag or f"bv-{now_ms}",
        "renotify": True,
        "timestamp": now_ms,
    }
    if image:
        payload_dict["image"] = image

    payload = json.dumps(payload_dict, ensure_ascii=False)

    try:
        from pywebpush import webpush

        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {
                    "p256dh": subscription.p256dh,
                    "auth": subscription.auth,
                },
            },
            data=payload,
            vapid_private_key=priv_key,
            vapid_claims={"sub": claims_email},
            ttl=ttl,
            headers={
                "Urgency": urgency,
                "Topic": (tag or f"bv-{now_ms}")[:32],
            },
        )
        return True
    except Exception as ex:
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


def broadcast_web_push(
    title,
    body,
    url="/",
    icon=None,
    image=None,
    tag=None,
    user_filter=None,
    extra_endpoints=None,
    target_only=False,
    async_dispatch=None,
    record_in_db=True,
):
    """
    بث إشعار فوري عالي الأولوية لجميع الأجهزة المشتركة أو لعميل محدد (حساب مسجل أو زائر عبر endpoint)
    وحفظ الإشعار في مركز الإشعارات بالمتجر بشكل غير متزامن لتفادي حظر خادم الويب.
    """
    cleaned_endpoints = [ep.strip() for ep in (extra_endpoints or []) if ep and ep.strip()]

    if target_only and not user_filter and not cleaned_endpoints:
        return 0

    if async_dispatch is None:
        async_dispatch = ('test' not in sys.argv)

    def _do_push():
        if async_dispatch:
            close_old_connections()
        try:
            q = Q()
            if user_filter:
                q |= Q(user=user_filter)
            if cleaned_endpoints:
                q |= Q(endpoint__in=cleaned_endpoints)

            if target_only:
                if not q:
                    return 0
                subscriptions_qs = WebPushSubscription.objects.filter(q).distinct()
            elif q:
                subscriptions_qs = WebPushSubscription.objects.filter(q).distinct()
            else:
                subscriptions_qs = WebPushSubscription.objects.all()

            successful_sends = 0
            seen_endpoints = set()
            for sub in subscriptions_qs.iterator(chunk_size=100):
                if sub.endpoint in seen_endpoints:
                    continue
                seen_endpoints.add(sub.endpoint)
                if send_web_push(
                    sub,
                    title=title,
                    body=body,
                    url=url,
                    icon=icon,
                    image=image,
                    tag=tag,
                ):
                    successful_sends += 1

            if record_in_db:
                try:
                    Notification.objects.create(
                        recipient=user_filter,
                        for_admin=False,
                        title=title,
                        message=body,
                        notification_type='promotion' if not user_filter else 'system',
                        link=url or "/",
                    )
                except Exception as ex:
                    logger.warning(f"Failed to record notification log: {ex}")

            return successful_sends
        finally:
            if async_dispatch:
                try:
                    connection.close()
                except Exception:
                    pass

    if async_dispatch:
        thread = threading.Thread(target=_do_push, daemon=True)
        thread.start()
        return 1
    return _do_push()


def send_product_promotion_push(product, custom_title=None, custom_body=None):
    """
    إرسال إشعار تسويقي وترويجي لمنتج عند إضافته أو تعديل سعره / خصمه
    """
    if custom_title and custom_title.strip():
        title = custom_title.strip()
    elif product.compare_at_price_yer and product.compare_at_price_yer > product.price_yer:
        discount = product.discount_percentage
        title = f"🔥 تخفيض حصري: {product.name_ar} (خصم {discount}%)"
    elif product.is_new:
        title = f"✨ وصل حديثاً إلى المتجر: {product.name_ar}"
    else:
        title = f"⭐ متاح الآن: {product.name_ar}"

    if custom_body and custom_body.strip():
        body = custom_body.strip()
    elif product.compare_at_price_yer and product.compare_at_price_yer > product.price_yer:
        body = f"تسوق الآن بسعر {product.price_yer:,.0f} ر.ي بدلاً من {product.compare_at_price_yer:,.0f} ر.ي! اضغط هنا للتفاصيل والطلب الفوري."
    else:
        brand_info = f"من {product.brand_name} " if product.brand_name else ""
        body = f"منتج فاخر {brand_info}بسعر {product.price_yer:,.0f} ر.ي ({product.price_sar} ر.س). انقر للمعاينة والطلب."

    url = f"/products/{product.slug}/"
    img = product.primary_image_url

    return broadcast_web_push(
        title=title,
        body=body,
        url=url,
        icon="/static/icons/icon-192.png",
        image=img,
        tag=f"promo-prod-{product.id}-{int(time.time())}",
    )


def send_order_created_push(order, guest_endpoint=None):
    """
    إرسال إشعار فوري للشريط العلوي لهاتف العميل فور إتمام الطلب بنجاح.
    """
    ep = guest_endpoint or get_order_push_endpoint(order.order_number)
    if ep:
        bind_order_push_endpoint(order.order_number, ep)

    title = f"🎉 تم استلام طلبك #{order.order_number}"
    body = (
        f"شكراً لثقتك بـ Brand Veloura! طلبك بقيمة {order.total_yer:,.0f} ر.ي قيد المراجعة والاعتماد الآن."
    )
    url = f"/order-success/{order.order_number}/"

    return broadcast_web_push(
        title=title,
        body=body,
        url=url,
        tag=f"order-new-{order.order_number}",
        user_filter=order.user,
        extra_endpoints=[ep] if ep else None,
        target_only=True,
        record_in_db=False,
    )


def send_order_status_push(order, new_status):
    """
    إرسال إشعار فوري للشريط العلوي على هاتف العميل (مسجل أو زائر) عند تغيير حالة طلبه.
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
    url = f"/order-success/{order.order_number}/"
    guest_ep = get_order_push_endpoint(order.order_number)

    return broadcast_web_push(
        title=title,
        body=body,
        url=url,
        tag=f"order-{order.order_number}-{new_status}",
        user_filter=order.user,
        extra_endpoints=[guest_ep] if guest_ep else None,
        target_only=True,
        record_in_db=False,
    )
