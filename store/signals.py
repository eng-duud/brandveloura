import logging
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .cache_service import (
    invalidate_admin_metrics_cache,
    invalidate_brand_cache,
    invalidate_category_cache,
    invalidate_gift_builder_cache,
    invalidate_home_and_catalog_cache,
    invalidate_homepage_cache,
    invalidate_notification_cache,
    invalidate_product_cache,
    invalidate_settings_cache,
    invalidate_shipping_cache,
    schedule_invalidation,
)
from .models import (
    Brand,
    Category,
    GiftBundle,
    GiftBundleItem,
    HeroBanner,
    Notification,
    Order,
    PaymentAccount,
    Product,
    ProductImage,
    ShippingZone,
    StoreSettings,
)

logger = logging.getLogger(__name__)


@receiver([post_save, post_delete], sender=Product)
def product_cache_invalidation(sender, instance, **kwargs):
    """إبطال كاش المنتج والصفحة الرئيسية والكتالوج عند التعديل أو نفاد المخزون بأمان بعد التثبيت"""
    update_fields = kwargs.get('update_fields')
    if (
        update_fields is not None
        and set(update_fields) == {'stock_quantity'}
        and (instance.stock_quantity or 0) > 0
    ):
        return
    schedule_invalidation(lambda: invalidate_product_cache(product_id=instance.id, slug=instance.slug))


@receiver([post_save, post_delete], sender=ProductImage)
def product_image_cache_invalidation(sender, instance, **kwargs):
    """إبطال كاش صور وتفاصيل المنتج فور تعديل المعرض"""
    schedule_invalidation(
        lambda: invalidate_product_cache(
            product_id=instance.product_id,
            slug=getattr(instance.product, 'slug', None) if instance.product_id else None,
        )
    )


@receiver([post_save, post_delete], sender=Category)
def category_cache_invalidation(sender, instance, **kwargs):
    """إبطال كاش الأقسام والصفحة الرئيسية عند حفظ أو حذف أي تصنيف"""
    schedule_invalidation(invalidate_category_cache)


@receiver([post_save, post_delete], sender=HeroBanner)
def herobanner_cache_invalidation(sender, instance, **kwargs):
    """إبطال كاش البانرات الترويجية والصفحة الرئيسية فور تعديلها"""
    schedule_invalidation(invalidate_homepage_cache)


@receiver([post_save, post_delete], sender=Brand)
def brand_cache_invalidation(sender, instance, **kwargs):
    """إبطال كاش الماركات والكتالوج عند تعديل أو حذف ماركة"""
    schedule_invalidation(lambda: invalidate_brand_cache(slug=instance.slug))


@receiver([post_save, post_delete], sender=GiftBundle)
def gift_bundle_cache_invalidation(sender, instance, **kwargs):
    """إبطال كاش باقات الهدايا وصانع الهدايا والصفحة الرئيسية"""
    schedule_invalidation(invalidate_gift_builder_cache)


@receiver([post_save, post_delete], sender=GiftBundleItem)
def gift_bundle_item_cache_invalidation(sender, instance, **kwargs):
    """إبطال كاش الباقات عند تعديل محتويات أي باقة"""
    schedule_invalidation(invalidate_gift_builder_cache)


@receiver([post_save, post_delete], sender=StoreSettings)
def store_settings_cache_invalidation(sender, instance, **kwargs):
    """إبطال كاش إعدادات المتجر وسعر الصرف والكتالوج فور الحفظ"""
    schedule_invalidation(invalidate_settings_cache)


@receiver([post_save, post_delete], sender=ShippingZone)
@receiver([post_save, post_delete], sender=PaymentAccount)
def shipping_and_payment_cache_invalidation(sender, instance, **kwargs):
    """إبطال كاش مناطق الشحن عند التحديث"""
    schedule_invalidation(invalidate_shipping_cache)


@receiver([post_save, post_delete], sender=Order)
def order_admin_metrics_invalidation(sender, instance, **kwargs):
    """إبطال مؤشرات وإحصائيات لوحة الإدارة فور إنشاء أو تحديث أي طلب"""
    schedule_invalidation(invalidate_admin_metrics_cache)


@receiver([post_save, post_delete], sender=Notification)
def notification_badge_cache_invalidation(sender, instance, **kwargs):
    """إبطال كاش عداد الإشعارات الخاصة بالمستلم أو الإدارة فور التغيير"""
    schedule_invalidation(
        lambda: invalidate_notification_cache(
            user_id=instance.recipient_id,
            for_admin=bool(instance.for_admin),
        )
    )
