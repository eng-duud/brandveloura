# Redis Cache Architecture — Brand Veloura

**Installed Library:** `redis>=5.0.0` (verified `redis==8.1.0` in virtualenv) with Django 5.1.15 built-in `RedisCache` (`store.cache_backend.ResilientRedisCache`).  
**Railway Configuration:** Driven strictly by environment variables (`REDIS_URL` or `REDIS_TLS_URL`), zero hardcoded credentials, never printed in logs or management commands.

---

## 1. Cache Backend & Connection Architecture (`config/settings.py`, `store/cache_backend.py`)

When `REDIS_URL` or `REDIS_TLS_URL` is configured (outside `manage.py test`):

| Setting / Option | `default` Alias (Storefront & Catalog) | `sessions` Alias (User & Cart Sessions) | Purpose |
|---|---|---|---|
| `BACKEND` | `store.cache_backend.ResilientRedisCache` | `store.cache_backend.ResilientRedisCache` | Resilient wrapper over Django's `RedisCache` |
| `LOCATION` | `REDIS_URL` (env) | `REDIS_URL` (env) | Shares Railway Redis `ConnectionPool` safely |
| `KEY_PREFIX` | `veloura_cat` | `veloura_sess` | Strict namespace isolation even in Redis DB `0` |
| `VERSION` | `1` | `1` | Supports atomic version bumps across deploys |
| `TIMEOUT` | `300` s (5 min default) | `604800` s (7 days cache horizon) | Balances catalog freshness and session warm hits |
| `OPTIONS` | `socket_connect_timeout: 2.0`, `socket_timeout: 2.0`, `retry_on_timeout: True`, `health_check_interval: 30` | Same | Prevents slow Redis TCP stalls from hanging Gunicorn threads; optional `REDIS_SSL_CERT_REQS=none` only for self-signed `rediss://` |

**Local / Test Fallback:** Two separated `LocMemCache` instances (`veloura-default-cache` / `veloura_cat` and `veloura-sessions-cache` / `veloura_sess`).

### Key Failure & Isolation Safeguards

1. **Graceful Degradation on Redis Outage (`ResilientRedisCache`):**
   - Catches `(RedisError, OSError, TimeoutError, ConnectionError)` across `add`, `get`, `set`, `touch`, `delete`, `get_many`, `has_key`, `incr`, `set_many`, `delete_many`, and `clear`.
   - Emits rate-limited warnings (`[REDIS_FALLBACK] cache_bucket=... operation=... exc_type=...`, cooldown 60s, never logging URLs or secrets) and falls back cleanly to PostgreSQL/queryset computation with HTTP `200` availability (verified via automated outage tests in `store/tests/test_audit_suite.py`).
2. **Scoped `clear()` (`SCAN` + `UNLINK`, Zero `FLUSHDB`):**
   - Django's default `RedisCache.clear()` executes `FLUSHDB` on the entire Redis database, which would destroy sessions and login throttling counters if run on DB 0.
   - `ResilientRedisCache.clear()` iterates `client.scan_iter(match=f"{self.key_prefix}:*", count=200)` and deletes batches with `UNLINK` (falling back to `DELETE`), leaving `veloura_sess:*` and throttling keys untouched.

---

## 2. Deliberate Key Inventory, TTL Policy & Privacy Boundaries (`store/cache_service.py`)

Only safe public data or strictly user-scoped tiny notification counters are cached:

| Key / Pattern | Alias | TTL | Contents | Never Cached in Shared Cache |
|---|---|---|---|---|
| `bv_store_settings` | `default` | 120 s | Singleton `StoreSettings` | — |
| `bv_yer_per_sar` | `default` | 300 s | Decimal exchange rate | — |
| `bv_active_categories` | `default` | 300 s | Active `Category` list | — |
| `bv_main_categories` | `default` | 300 s | Top-level categories + active subcategories | — |
| `bv_home_banners`, `bv_home_categories` | `default` | 300–900 s | Home banners & top-level categories | — |
| `bv_home_deferred_html_{YER\|SAR\|USD}` | `default` | 900 s | Public home deferred HTML segmented per currency | Auth header badges, carts |
| `bv_catalog_brands_v{ver}:{cat_id}` | `default` | 300 s | Distinct sorted brand names for filter drawer | — |
| `bv_brands_list_v{ver}` | `default` | 300 s | Active `Brand` directory with product counts | Search `?q=` queries |
| `bv_product_gallery_v{ver}:{id}` & `bv_product_related_v{ver}:{id}` | `default` | 180 s | Product gallery images & 4 related products | — |
| `bv_gift_builder_v{ver}` | `default` | 300 s | Gift wizard perfumes, accessories, bundles | Session `gift_data`, user carts |
| `bv_shipping_zones_active` | `default` | 300 s | Active `ShippingZone` map for checkout/HTMX | Customer addresses |
| `bv_admin_pending_orders` / `bv_admin_dashboard_metrics` | `default` | 15 s / 30 s | Admin KPI counts & confirmed totals | CSRF tokens, staff credentials |
| `bv_unread_notifications_user_{id}` / `bv_admin_unread_notifications` | `default` | 15 s | Scalar integer unread badge count | Notification message bodies |

*Never cached:* `/cart/`, `/checkout/`, `/account/`, `/order-success/`, `/gift-slip/`, CSRF tokens, OAuth tokens, and search queries.

---

## 3. Stampede Protection & Transaction-Safe Invalidation (`store/signals.py`, `store/cache_service.py`)

- **Single-Flight Stampede Lock & Jitter (`cache_get_or_set_safe`):** Acquires non-blocking `cache_add(f"{key}:_lock", '1', timeout=8)`. Concurrent cache misses wait briefly (`25 ms`) to read the refreshed cache key; TTL receives ±10% jitter (`_apply_jitter`) for TTL >= 20s to spread expirations.
- **Namespace Versioning:** Modifying categories, brands, products, or bundles bumps `bv_ns_ver:catalog` / `bv_ns_ver:brand` (`O(1)` atomic `INCR`) so all stale derived catalog/brand keys become unreachable immediately without wildcard scans.
- **Commit-Ordered Signals:** `schedule_invalidation()` registers `transaction.on_commit(...)` inside production atomic blocks so worker B cannot repopulate stale data from an uncommitted transaction before worker A commits to PostgreSQL.
- **Diagnostic CLI:** Run `python manage.py inspect_cache` in Railway shell to verify live `PING` latency, `used_memory_human`, `maxmemory_policy`, `connected_clients`, hit/miss ratio, and safe round-trip write/read/delete without exposing `REDIS_URL`.
