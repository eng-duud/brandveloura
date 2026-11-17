import logging
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache

from .models import (
    Product,
    Category,
    HeroBanner,
    Brand,
    GiftBundle,
    GiftBundleItem,
    StoreSettings,
)

logger = logging.getLogger(__name__)


def invalidate_home_and_catalog_cache():
    """تفريغ كاش الصفحة الرئيسية والكتالوج عند تعديل المنتجات أو الأقسام لضمان ظهور التحديثات فوراً"""
    keys_to_delete = [
        'bv_home_banners',
        'bv_home_categories',
        'bv_active_categories',
        'bv_main_categories',
        'bv_home_deferred_html_YER',
        'bv_home_deferred_html_SAR',
        'bv_home_deferred_html_USD',
        'bv_store_settings',
        'bv_yer_per_sar',
    ]
    try:
        cache.delete_many(keys_to_delete)
        logger.info("Brand Veloura cache successfully invalidated for home and catalog keys.")
    except Exception as e:
        logger.warning(f"Failed to clear cache keys: {e}")


@receiver([post_save, post_delete], sender=Product)
def product_cache_invalidation(sender, instance, **kwargs):
    """إبطال كاش الصفحة الرئيسية والكتالوج عند تعديل أو حذف المنتج (مع تجنب المسح عند مجرد خصم مخزون لم ينفد)"""
    update_fields = kwargs.get('update_fields')
    if (
        update_fields is not None
        and set(update_fields) == {'stock_quantity'}
        and (instance.stock_quantity or 0) > 0
    ):
        return
    invalidate_home_and_catalog_cache()


@receiver([post_save, post_delete], sender=Category)
def category_cache_invalidation(sender, instance, **kwargs):
    """إبطال كاش الأقسام والصفحة الرئيسية عند حفظ أو حذف أي تصنيف"""
    invalidate_home_and_catalog_cache()


@receiver([post_save, post_delete], sender=HeroBanner)
def herobanner_cache_invalidation(sender, instance, **kwargs):
    """إبطال كاش البانرات الترويجية فور تعديلها من لوحة التحكم"""
    try:
        cache.delete('bv_home_banners')
    except Exception:
        pass
    invalidate_home_and_catalog_cache()


@receiver([post_save, post_delete], sender=Brand)
def brand_cache_invalidation(sender, instance, **kwargs):
    """إبطال كاش الماركات عند إضافة أو تعديل ماركة"""
    invalidate_home_and_catalog_cache()


@receiver([post_save, post_delete], sender=GiftBundle)
def gift_bundle_cache_invalidation(sender, instance, **kwargs):
    """إبطال كاش باقات الهدايا عند التعديل"""
    invalidate_home_and_catalog_cache()


@receiver([post_save, post_delete], sender=GiftBundleItem)
def gift_bundle_item_cache_invalidation(sender, instance, **kwargs):
    """إبطال كاش باقات الهدايا عند تعديل عناصر الباقة"""
    invalidate_home_and_catalog_cache()


@receiver([post_save, post_delete], sender=StoreSettings)
def store_settings_cache_invalidation(sender, instance, **kwargs):
    """إبطال كاش إعدادات المتجر وأسعار الصرف فور الحفظ"""
    try:
        cache.delete_many(['bv_store_settings', 'bv_yer_per_sar'])
    except Exception:
        pass
    invalidate_home_and_catalog_cache()
