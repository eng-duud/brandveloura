import logging
import random
import threading
import time

from django.conf import settings as django_settings
from django.core.cache import caches
from django.db import connection, transaction

logger = logging.getLogger('store.cache')

DEFAULT_ALIAS = 'default'
LOCK_TTL_DEFAULT = 8
NS_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days

_SERVICE_LOCK = threading.Lock()
_SERVICE_STATS = {'hits': 0, 'misses': 0, 'sets': 0, 'deletes': 0, 'errors': 0, 'stampede_waits': 0}

_MISS_SENTINEL = object()

HOME_CACHE_KEYS = [
    'bv_home_banners',
    'bv_home_categories',
    'bv_home_deferred_html_YER',
    'bv_home_deferred_html_SAR',
    'bv_home_deferred_html_USD',
    'bv_sitemap_xml',
]

CATEGORY_CACHE_KEYS = [
    'bv_active_categories',
    'bv_main_categories',
    'bv_home_categories',
]

SETTINGS_CACHE_KEYS = [
    'bv_store_settings',
    'bv_yer_per_sar',
]

ADMIN_METRIC_KEYS = [
    'bv_admin_dashboard_metrics',
    'bv_admin_pending_orders',
    'bv_admin_low_stock_count',
]

SHIPPING_CACHE_KEYS = [
    'bv_shipping_zones_active',
]


def _stat_inc(field, n=1):
    with _SERVICE_LOCK:
        _SERVICE_STATS[field] = _SERVICE_STATS.get(field, 0) + n


def get_service_metrics():
    """Return in-process cache service operation metrics including computed hit ratio."""
    with _SERVICE_LOCK:
        snap = dict(_SERVICE_STATS)
    total = snap['hits'] + snap['misses']
    snap['hit_ratio_pct'] = round((snap['hits'] / total) * 100, 2) if total else 0.0
    return snap


def reset_service_metrics():
    """Reset in-process service counters (for benchmarks and unit tests)."""
    with _SERVICE_LOCK:
        for k in _SERVICE_STATS:
            _SERVICE_STATS[k] = 0


def _get_backend(alias=DEFAULT_ALIAS):
    return caches[alias]


def cache_get(key, default=None, alias=DEFAULT_ALIAS):
    try:
        val = _get_backend(alias).get(key, default=_MISS_SENTINEL)
        if val is _MISS_SENTINEL:
            _stat_inc('misses')
            return default
        _stat_inc('hits')
        return val
    except Exception as exc:
        _stat_inc('errors')
        logger.warning("[CACHE_ERR] op=get key=%s exc=%s", key, type(exc).__name__)
        return default


def cache_set(key, value, timeout=300, alias=DEFAULT_ALIAS):
    try:
        _get_backend(alias).set(key, value, timeout=timeout)
        _stat_inc('sets')
        return True
    except Exception as exc:
        _stat_inc('errors')
        logger.warning("[CACHE_ERR] op=set key=%s exc=%s", key, type(exc).__name__)
        return False


def cache_add(key, value, timeout=300, alias=DEFAULT_ALIAS):
    try:
        added = bool(_get_backend(alias).add(key, value, timeout=timeout))
        if added:
            _stat_inc('sets')
        return added
    except Exception as exc:
        _stat_inc('errors')
        logger.warning("[CACHE_ERR] op=add key=%s exc=%s", key, type(exc).__name__)
        return False


def cache_delete(key, alias=DEFAULT_ALIAS):
    try:
        _get_backend(alias).delete(key)
        _stat_inc('deletes')
        return True
    except Exception as exc:
        _stat_inc('errors')
        logger.warning("[CACHE_ERR] op=delete key=%s exc=%s", key, type(exc).__name__)
        return False


def cache_delete_many(keys, alias=DEFAULT_ALIAS):
    key_list = [k for k in keys if k]
    if not key_list:
        return True
    try:
        _get_backend(alias).delete_many(key_list)
        _stat_inc('deletes', len(key_list))
        return True
    except Exception as exc:
        _stat_inc('errors')
        logger.warning("[CACHE_ERR] op=delete_many count=%s exc=%s", len(key_list), type(exc).__name__)
        return False


def _apply_jitter(timeout, jitter_ratio):
    if not timeout or timeout < 20 or not jitter_ratio or jitter_ratio <= 0:
        return timeout
    delta = timeout * min(jitter_ratio, 0.25)
    return max(1, int(timeout + random.uniform(-delta, delta)))


def cache_get_or_set_safe(
    key,
    builder_fn,
    timeout=300,
    jitter_ratio=0.1,
    lock_timeout=LOCK_TTL_DEFAULT,
    alias=DEFAULT_ALIAS,
    cache_none=False,
):
    """Fetch from cache with single-flight lock protection and TTL jitter on rebuild."""
    cached = cache_get(key, default=_MISS_SENTINEL, alias=alias)
    if cached is not _MISS_SENTINEL:
        return cached

    lock_key = f"{key}:_lock"
    acquired = cache_add(lock_key, '1', timeout=lock_timeout, alias=alias)

    if not acquired:
        _stat_inc('stampede_waits')
        for _ in range(4):
            time.sleep(0.03)
            retry_val = cache_get(key, default=_MISS_SENTINEL, alias=alias)
            if retry_val is not _MISS_SENTINEL:
                return retry_val

    try:
        value = builder_fn()
        if value is not None or cache_none:
            effective_ttl = _apply_jitter(timeout, jitter_ratio)
            cache_set(key, value, timeout=effective_ttl, alias=alias)
        return value
    finally:
        if acquired:
            cache_delete(lock_key, alias=alias)


# ==============================================================================
# Versioned Namespace Helpers (Avoid FLUSHDB while supporting O(1) bulk bust)
# ==============================================================================

def get_namespace_version(namespace):
    ns_key = f"bv_ns_ver:{namespace}"
    val = cache_get(ns_key)
    if isinstance(val, int) and val >= 1:
        return val
    cache_add(ns_key, 1, timeout=NS_TTL_SECONDS)
    return 1


def bump_namespace_version(namespace):
    ns_key = f"bv_ns_ver:{namespace}"
    backend = _get_backend(DEFAULT_ALIAS)
    try:
        return backend.incr(ns_key)
    except ValueError:
        cache_set(ns_key, 2, timeout=NS_TTL_SECONDS)
        return 2
    except Exception as exc:
        _stat_inc('errors')
        logger.warning("[CACHE_ERR] op=bump_ns ns=%s exc=%s", namespace, type(exc).__name__)
        return 1


def make_product_related_key(product_id):
    ver = get_namespace_version('catalog')
    return f"bv_product_related_v{ver}:{product_id}"


def make_product_gallery_key(product_id):
    ver = get_namespace_version('catalog')
    return f"bv_product_gallery_v{ver}:{product_id}"


def make_catalog_brands_key(category_id):
    ver = get_namespace_version('catalog')
    return f"bv_catalog_brands_v{ver}:{category_id or 'all'}"


def make_brands_list_key():
    ver = get_namespace_version('brand')
    return f"bv_brands_list_v{ver}"


def make_gift_builder_catalog_key():
    ver = get_namespace_version('catalog')
    return f"bv_gift_builder_v{ver}"


# ==============================================================================
# Transaction-Safe Explicit Invalidation Functions
# ==============================================================================

def schedule_invalidation(fn):
    """Defer invalidation until PostgreSQL commits in atomic blocks during live traffic."""
    is_test_runner = getattr(django_settings, 'RUNNING_TESTS', False)
    if not is_test_runner and connection.in_atomic_block:
        transaction.on_commit(fn)
    else:
        fn()


def invalidate_homepage_cache():
    cache_delete_many(HOME_CACHE_KEYS)


def invalidate_category_cache():
    bump_namespace_version('catalog')
    cache_delete_many(CATEGORY_CACHE_KEYS + HOME_CACHE_KEYS)


def invalidate_brand_cache(slug=None):
    bump_namespace_version('brand')
    bump_namespace_version('catalog')
    keys = list(HOME_CACHE_KEYS)
    if slug:
        keys.append(f"bv_brand_meta:{slug}")
    cache_delete_many(keys)


def invalidate_product_cache(product_id=None, slug=None):
    bump_namespace_version('catalog')
    keys = list(HOME_CACHE_KEYS) + list(ADMIN_METRIC_KEYS)
    if product_id:
        keys.extend([f"bv_product_related:{product_id}", f"bv_product_gallery:{product_id}"])
    if slug:
        keys.append(f"bv_product_meta:{slug}")
    cache_delete_many(keys)


def invalidate_gift_builder_cache():
    bump_namespace_version('catalog')
    cache_delete_many(HOME_CACHE_KEYS + ['bv_gift_bundles_active'])


def invalidate_settings_cache():
    bump_namespace_version('catalog')
    cache_delete_many(SETTINGS_CACHE_KEYS + HOME_CACHE_KEYS + ADMIN_METRIC_KEYS + ['bv_shipping_zones_active'])


def invalidate_shipping_cache():
    cache_delete_many(SHIPPING_CACHE_KEYS)


def invalidate_admin_metrics_cache():
    cache_delete_many(ADMIN_METRIC_KEYS)


def invalidate_notification_cache(user_id=None, for_admin=False):
    keys = []
    if user_id:
        keys.append(f"bv_unread_notifications_user_{user_id}")
    if for_admin:
        keys.append('bv_admin_unread_notifications')
    if keys:
        cache_delete_many(keys)


def invalidate_home_and_catalog_cache():
    """Clear home, category, catalog, settings, and admin dashboard metrics safely."""
    bump_namespace_version('catalog')
    bump_namespace_version('brand')
    cache_delete_many(HOME_CACHE_KEYS + CATEGORY_CACHE_KEYS + SETTINGS_CACHE_KEYS + ADMIN_METRIC_KEYS)
    logger.info("Brand Veloura cache successfully invalidated for home and catalog keys.")
