# Security Audit Report — Brand Veloura

**Scope:** Full-stack Django 5.1.15 + HTMX + PostgreSQL + Redis e-commerce application (`brandveloura.com`)  
**Audit Method:** Complete source review of `config/settings.py`, `store/models.py`, `store/views.py`, `store/admin.py`, `store/context_processors.py`, `store/cache_backend.py`, `store/cache_service.py`, `store/signals.py`, `store/urls.py`, `templates/`, `Dockerfile`, `start.sh`, plus automated security tests in `store/tests/test_audit_suite.py` and `store/tests/test_security_and_hardening.py`.  
**Confidentiality Check:** No secrets, passwords, `SECRET_KEY`, VAPID keys, OAuth secrets, `DATABASE_URL`, or `REDIS_URL` values are exposed in this report.

---

## 1. Executive Security Summary

| Domain | Status | Key Controls Verified / Hardened |
|---|---|---|
| Transport & Proxy SSL | Pass | `SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')`, `SECURE_HSTS_SECONDS = 31536000`, `SESSION_COOKIE_SECURE = True`, `CSRF_COOKIE_SECURE = True` |
| CSRF & HTMX Safety | Pass | `#bv-csrf-token` injected via `htmx:configRequest` in `templates/base.html`; `@require_POST` + Django `CsrfViewMiddleware` verified blocking forged unauthenticated POSTs with HTTP `403` on `/cart/add/`, `/cart/update/`, `/cart/remove/`, `/notifications/mark-all-read/`, and `/api/push/subscribe/` |
| Open Redirect Defense | Fixed & Verified | `_get_safe_redirect()` uses `url_has_allowed_host_and_scheme`; `mark_notification_read_view()` in `store/views.py` updated to validate `notification.link` against `{request.get_host()}` before redirecting |
| Input Parsing & Error Resilience | Fixed & Verified | Added `_parse_int_id()` across `gift_builder_view`, `gift_calculate_live`, and `get_shipping_fee` in `store/views.py` to prevent `ValueError` HTTP `500` crashes on crafted non-integer IDs |
| Auth & Rate Limiting | Hardened | `login_view` (10 fails / 10 min per IP) and `register_view` (10 registrations / 15 min per IP) routed through safe `cache_get`/`cache_set` so Redis unavailability does not break authentication; Google OAuth checks `state`, `aud`, `iss`, `g_csrf_token`, and `email_verified` |
| Admin Access & Auditability | Hardened | Admin mounted on custom obscured prefix `/cpanel-0x110/`; unauthenticated and non-staff users receive `302` redirect to login; secret fields masked via `StoreSettingsAdminForm`; structured `[ADMIN_AUDIT]` logger added for privilege, settings, order status, product bulk, and print actions |
| Checkout & Inventory Integrity | Verified | Atomic `select_for_update()` locking across unified product quantities (including grade splits and bundle components) with `F('stock_quantity')` updates and live server-side DB pricing (`_live_unit_price`) |
| Container Hardening | Verified | `Dockerfile` executes Gunicorn workers under non-root `appuser` |

---

## 2. Detailed Vulnerability & Hardening Findings

### 2.1 Fixed in This Audit

1. **Open Redirect on `mark_notification_read_view` (`store/views.py`)**
   - **Risk:** `redirect(target_link)` redirected directly to `notification.link` without scheme/host allowlist checks. If a notification record ever held a third-party URL, clicking it would redirect the victim offsite.
   - **Remediation:** Enforced `url_has_allowed_host_and_scheme(url=target_link, allowed_hosts={request.get_host()})`, falling back safely to `reverse('store:account_profile')`.
   - **Verification:** Covered by `HTMXAndFunctionalSecurityTests.test_csrf_enforced_on_mutations_and_notification_open_redirect_blocked` (`302` to `/account/`).

2. **Unhandled Non-Integer Input (`ValueError` 500) in Gifting Flows (`store/views.py`)**
   - **Risk:** `gift_builder_view` and `gift_calculate_live` executed unguarded `int(aid)` / `.filter(id=bundle_id)` on user-controlled query and POST parameters (`accessory_id`, `bundle_id`, `perfume_id`), raising unhandled exceptions (HTTP `500`).
   - **Remediation:** Implemented `_parse_int_id(raw_val)` for positive integers and sanitized all lookups before ORM execution.

3. **Redis Dependency Failure / Cache Clear Namespace Bleeding (`store/context_processors.py`, `store/cache_backend.py`)**
   - **Risk:** Calling `cache.get()` outside `try/except` in context processors or `RedisCache.clear()` calling `FLUSHDB` across Redis DB 0 could crash pages on transient Redis loss or purge active login throttling (`bv_login_fails_*`) and session keys.
   - **Remediation:** Created `ResilientRedisCache` catching `(RedisError, OSError, TimeoutError, ConnectionError)` with throttled `[REDIS_FALLBACK]` logging, separated aliases (`veloura_cat` vs `veloura_sess`), and scoped `clear()` to `SCAN` + `UNLINK` on `self.key_prefix` only (`FLUSHDB` never invoked).

4. **Admin Privilege, Settings, and Bulk Action Audit Trail (`store/admin.py`, `store/views.py`)**
   - **Risk:** Sensitive back-office mutations (staff/superuser grants, YER/SAR exchange rate updates, out-of-stock/delete-like bulk actions, order cancellations, invoice/slip prints) emitted no structured audit logs.
   - **Remediation:** Added `[ADMIN_AUDIT]` logger (`store.admin_audit`) capturing actor username/ID, action, and target reference without logging PII, secrets, or tokens.

5. **CSRF & Mutation Hygiene Verification (`store/views.py`, `store/tests/test_audit_suite.py`)**
   - Verified with `Client(enforce_csrf_checks=True)` that POST endpoints (`/cart/add/`, `/cart/update/`, `/cart/remove/`, `/notifications/mark-all-read/`, `/api/push/subscribe/`) strictly reject missing CSRF tokens with HTTP `403`.

---

## 3. Residual Risks & Architectural Notes (Honest Disclosure)

1. **Bearer Capability Links for `/order-success/<order_number>/` and `/gift-slip/<order_number>/`**
   - **Current Behavior:** Both endpoints resolve orders via random hex `order_number` (`BV-` + `secrets.token_hex(4).upper()`) without requiring session login, enabling WhatsApp/gift-recipient sharing (`test_gifting_engine_overhaul.py` and `test_user_routes.py` rely directly on this contract). Mutating/invoice-upload routes (`save_order_invoice_image`) require matching session `last_order_number`, order owner, or staff.
   - **Mitigation / Future Recommendation:** `gift_slip` hides all monetary amounts (`hide_invoice_prices`). Keep high-entropy `order_number` unguessable or migrate share URLs to HMAC-signed tokens if customer phone/address masking on `order_success` is desired later.

2. **Public Cloudinary Receipt Storage (`Order.payment_receipt`)**
   - **Current Behavior:** `STORAGES['default']` uses `MediaCloudinaryStorage`, meaning uploaded transfer receipt images receive public Cloudinary delivery URLs (`upload` resource type) rather than authenticated/signed private Cloudinary delivery.
   - **Recommendation:** Before scaling sensitive financial receipt volume, configure private/authenticated Cloudinary resource storage + short-lived signed admin URLs for `Order.payment_receipt`.

3. **GET Logout Endpoint (`logout_view`)**
   - **Current Behavior:** `/logout/` accepts GET (`<a href="{% url 'store:logout' %}">` in `templates/store/auth/account.html`). While CSRF-less logout denial-of-service is low impact, converting UI logout triggers to POST `<form>` is a clean follow-up hardening step.

4. **Shared Process Cache Not Consulted on Real Live Railway Edge in Sandbox**
   - Redis failure resilience and prefix-scoped cleanup were verified in unit tests via mocked `redis-py` client errors and `LocMemCache` live test runner (`redis==8.1.0` installed); live Railway PostgreSQL & Railway Redis network TLS/ACL checks must run inside Railway runtime (`python manage.py inspect_cache`).
