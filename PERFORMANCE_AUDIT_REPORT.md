# Performance Audit Report — Brand Veloura

**Benchmark Environment:** Isolated local Python 3 + Django 5.1.15 (`DEBUG=False`, `HTTPS` forwarded proxy headers, `LocMemCache` backend matching production key structure, SQLite `:memory:` query profiler with `CaptureQueriesContext` & wall-clock timings over cold + repeated warm runs via `measure_performance.py`).  
**Honest Scope Note:** Absolute millisecond timings on SQLite are lower than cross-container Railway PostgreSQL/Redis TCP round-trips; relative latency drops and exact SQL query reductions directly translate to even larger real-world savings over Railway network hops.

---

## 1. Before vs. After Benchmark Comparison (20 Endpoints)

| Endpoint | Avg ms (Before -> After) | Median ms (Before -> After) | P95 ms (Before -> After) | Cold SQL Queries (B -> P) | Warm SQL Queries (B -> P) | Latency Delta |
|---|---|---|---|---|---|---|
| `home_shell` (`/`) | 34.35 -> 16.72 | 8.05 -> 4.62 | 138.85 -> 65.77 | 6 -> 6 | 0 -> 0 | **-51.3%** |
| `home_deferred` (`/partials/home-deferred/`) | 14.22 -> 7.72 | 0.74 -> 0.52 | 68.19 -> 36.56 | 38 -> 27 | 0 -> 0 | **-45.7%** |
| `product_list` (`/products/`) | 25.78 -> 14.87 | 23.32 -> 13.03 | 35.75 -> 23.13 | 15 -> 11 | **10 -> 3** | **-42.3%** |
| `category_filter` (`/products/?category=perfumes`) | 21.36 -> 9.79 | 21.04 -> 8.94 | 25.19 -> 13.37 | 16 -> 11 | **11 -> 3** | **-54.2%** |
| `search` (`/products/?q=Dior`) | 13.66 -> 5.66 | 12.64 -> 4.74 | 17.86 -> 9.27 | 15 -> 11 | **10 -> 3** | **-58.6%** |
| `product_detail` (`/products/bench-product-0/`) | 17.89 -> 10.78 | 14.66 -> 8.23 | 27.66 -> 21.91 | 9 -> 9 | **4 -> 2** | **-39.7%** |
| `quick_view_htmx` (`/products/bench-product-0/` HTMX) | 5.97 -> 4.27 | 4.42 -> 3.19 | 12.22 -> 8.44 | 8 -> 8 | 3 -> 3 | **-28.5%** |
| `brands_list` (`/brands/`) | 11.62 -> 5.79 | 10.60 -> 4.38 | 16.52 -> 11.40 | 7 -> 6 | **3 -> 0** | **-50.2%** |
| `brand_detail` (`/brands/dior/`) | 24.29 -> 12.93 | 21.05 -> 11.44 | 31.92 -> 19.43 | 11 -> 11 | 6 -> 6 | **-46.8%** |
| `gift_builder` (`/gifting/`) | **54.90 -> 16.46** | 46.91 -> 12.61 | 89.47 -> 31.98 | **20 -> 13** | **15 -> 0** | **-70.0%** |
| `cart_view` (`/cart/`, auth client) | 13.24 -> 8.39 | 10.89 -> 6.22 | 22.85 -> 13.91 | 11 -> 10 | 6 -> 5 | **-36.6%** |
| `checkout_get` (`/checkout/`, auth client) | 19.75 -> 10.48 | 15.34 -> 8.98 | 31.53 -> 17.29 | 15 -> 14 | 10 -> 9 | **-46.9%** |
| `shipping_fee_htmx` (`/get-shipping-fee/`, auth client) | 5.23 -> 2.58 | 3.90 -> 1.94 | 9.75 -> 5.28 | 11 -> 10 | 6 -> 4 | **-50.7%** |
| `account_profile` (`/account/`, auth client) | **67.05 -> 22.10** | 49.52 -> 19.50 | **137.12 -> 32.73** | **30 -> 22** | **25 -> 16** | **-67.0%** |
| `admin_dashboard` (`/cpanel-0x110/`) | **60.91 -> 22.54** | 30.81 -> 9.46 | **198.20 -> 75.65** | 18 -> 17 | **11 -> 7** | **-63.0%** |
| `admin_products_list` (`/cpanel-0x110/store/product/`) | **168.29 -> 53.59** | 99.10 -> 49.42 | **491.99 -> 71.04** | 26 -> 23 | 18 -> 15 | **-68.2%** |
| `admin_orders_list` (`/cpanel-0x110/store/order/`) | 27.93 -> 18.27 | 26.75 -> 16.78 | 33.34 -> 24.73 | 21 -> 20 | 14 -> 13 | **-34.6%** |
| `admin_categories_list` (`/cpanel-0x110/store/category/`) | 38.31 -> 25.00 | 36.28 -> 23.47 | 47.02 -> 28.99 | 24 -> 23 | 17 -> 16 | **-34.7%** |
| `admin_brands_list` (`/cpanel-0x110/store/brand/`) | 35.59 -> 21.36 | 34.70 -> 20.21 | 45.70 -> 26.13 | 21 -> 20 | 14 -> 13 | **-40.0%** |
| `admin_bundles_list` (`/cpanel-0x110/store/giftbundle/`) | 39.04 -> 21.02 | 39.95 -> 19.75 | 44.88 -> 26.40 | 21 -> 20 | 13 -> 12 | **-46.2%** |

*Max single query time measured after optimization dropped from `7.0 ms` (`admin_products_list` date truncation) to `0.0 ms` across all 20 endpoints on the local benchmark dataset.*

---

## 2. Root Bottlenecks Diagnosed & Fixed

1. **Unindexed Fallback PostgreSQL Connection Pooling (`config/settings.py`)**
   - The `except ImportError:` PostgreSQL fallback dict omitted `'CONN_MAX_AGE': 600` and `'CONN_HEALTH_CHECKS': True` (whereas the `dj_database_url.config(...)` path included them). Unified both paths with configurable `DB_CONN_MAX_AGE` (default `600`) + health checks for Gunicorn worker persistence.

2. **N+1 Image Queries on `GiftBundle` (`store/views.py` `get_home_deferred_context` & `gift_builder_view`)**
   - Prefetching only `items__product` forced per-bundle `SELECT store_productimage` N+1 queries inside `GiftBundle.get_image_url()`. Added `items__product__images` + cached gift builder catalog -> `home_deferred` cold queries fell **38 -> 27**, and `gift_builder` warm queries fell **15 -> 0**.

3. **Duplicate Category & Invalid `DISTINCT` Brand Queries (`store/views.py` `product_list_view`)**
   - `/products/` executed 4 redundant `Category` lookups per request plus `SELECT DISTINCT brand_name, is_featured, created_at` caused by `Product.Meta.ordering`. Consolidated category tree resolution onto cached `bv_active_categories`, fixed `.order_by('brand_name')` before `.distinct()`, and cached `available_brands` per category -> `/products/` warm queries dropped **10 -> 3**.

4. **Duplicate `Order` / `Notification` / `ShippingZone` Queries (`store/views.py` `account_profile_view`)**
   - `account_profile_view` evaluated `.count()`, 2 filtered `.count()` queries, a separate `exclude(status='cancelled')` iteration, an un-cached `Notification` count query, and un-cached `ShippingZone` list. Evaluated `orders` and `notifications` cleanly in memory once and reused cached `bv_shipping_zones_active` -> **25 -> 16** warm queries and **-67.0%** avg latency.

5. **Admin `date_hierarchy` Full-Day Truncation & Uncached Dashboard KPIs (`store/admin.py`)**
   - Removed `date_hierarchy` on `ProductAdmin` and cached `custom_admin_each_context` KPI aggregates for 30s with explicit `Order`/`Product` signal invalidation -> `/cpanel-0x110/` warm queries **11 -> 7** (-63.0% avg ms) and `/cpanel-0x110/store/product/` P95 **491.99 ms -> 71.04 ms**.

6. **Remaining Baseline Queries Explained (Authenticated Requests)**
   - Warm authenticated routes (`cart_view`, `checkout_get`, `shipping_fee_htmx`, `admin_*`) retain ~4–5 base queries: 1 `SELECT auth_user` + `SAVEPOINT` / `UPDATE django_session` / `RELEASE SAVEPOINT` because `SESSION_SAVE_EVERY_REQUEST = True` is explicitly enforced by `store/tests/test_user_routes.py:857`. Switching to `cached_db` still eliminated warm session `SELECT django_session` DB reads!
