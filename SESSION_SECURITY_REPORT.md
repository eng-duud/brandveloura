# Session Management & Security Report — Brand Veloura

**Reviewed Files:** `config/settings.py`, `store/views.py` (`login_view`, `register_view`, `logout_view`, `google_auth_callback`, `merge_and_restore_user_cart`, `sync_cart_to_profile`, `check_and_expire_cart`, `refresh_cart_reservation`), `store/context_processors.py`.

---

## 1. Session Engine Upgrade (`cached_db` with Redis Isolation)

| Parameter | Previous Configuration | Audited & Implemented Configuration | Security / Reliability Rationale |
|---|---|---|---|
| `SESSION_ENGINE` | `django.contrib.sessions.backends.db` | `django.contrib.sessions.backends.cached_db` | Serves warm session reads directly from Redis (`veloura_sess`) while writing through to PostgreSQL (`django_session`) as the durable system of record |
| `SESSION_CACHE_ALIAS` | `default` | `sessions` (`KEY_PREFIX = 'veloura_sess'`) | Isolates active logins and shopping carts from catalog cache invalidation or prefix cleanup |
| `SESSION_COOKIE_AGE` | `31536000` (365 days) | `31536000` (365 days; 90-day fallback if `remember_me` unchecked on login) | Preserves persistent Year-long shopping & auth continuity (`test_user_routes.py:856`) |
| `SESSION_SAVE_EVERY_REQUEST` | `True` | `True` | Preserved per explicit automated test contract (`test_user_routes.py:857`); sliding expiry stays active (note PostgreSQL write cost on authenticated GETs below) |
| `SESSION_EXPIRE_AT_BROWSER_CLOSE` | `False` | `False` | Carts & logins survive mobile app/browser restarts |
| `SESSION_COOKIE_HTTPONLY` | `True` | `True` | Prevents JS (`document.cookie`) exfiltration of `sessionid` |
| `SESSION_COOKIE_SAMESITE` | `'Lax'` | `'Lax'` | Mitigates cross-site request forgery while supporting top-level Google OAuth GET callback redirects |
| `SESSION_COOKIE_SECURE` | `True` (when HTTPS/non-debug) | `True` (`SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')`) | Cookie transmitted strictly over HTTPS on `brandveloura.com` |
| `CSRF_COOKIE_HTTPONLY` | `True` | `True` | Page HTMX requests read CSRF token from rendered DOM `#bv-csrf-token`, not JS-accessible cookie |

---

## 2. Session Lifecycle & Security Analysis

1. **Resilience Against Redis Eviction or Restart:**
   - Pure Redis cache sessions (`backends.cache`) lose all customer carts and admin sessions if Railway Redis restarts or evicts keys under `allkeys-lru`.
   - With `cached_db` + `ResilientRedisCache`, if Redis restarts or drops offline, `SessionStore.load()` automatically falls back to PostgreSQL (`django_session`) with **zero lost logins, zero lost carts, and zero HTTP 500s**.
2. **Cart Reservation Timer Integrity (`cart_expires_at`):**
   - Managed server-side inside the Django session (`cart_expires_at` UNIX epoch) via `check_and_expire_cart()`, `refresh_cart_reservation()`, and `get_cart_timing_context()`.
   - Client JavaScript displays the visual countdown only; tampering with client timer DOM attributes cannot bypass server expiry checks run before `/cart/add/`, `/cart/update/`, `/cart/`, `/checkout/`, or `/gifting/` POST (`refresh_cart_reservation()` fixed in `gift_builder_view`).
3. **Cart Persistence & Merge Across Logins (`merge_and_restore_user_cart`):**
   - Logged-in actions mirror session carts to `UserProfile.cart_data`. On login/OAuth sign-in, guest session cart items merge atomically into `UserProfile.cart_data` without overwriting prior saved items, then re-establish server reservation time.
4. **Google OAuth Session Hardening (`google_login_redirect`, `google_auth_callback`):**
   - Validates cryptographically random OAuth `state` stored in session (plus Google `g_csrf_token` cookie/body double-submit verification for One-Tap), verifies ID token `aud`, `iss`, and `email_verified`, preventing account takeover via unverified email collision or login CSRF.
5. **Known Operational Trade-Off (`SESSION_SAVE_EVERY_REQUEST = True`):**
   - Because `SESSION_SAVE_EVERY_REQUEST = True` is asserted by the existing suite, Django writes (`UPDATE django_session`) on every authenticated GET request (accounting for 3 SQL statements: `SAVEPOINT`, `UPDATE`, `RELEASE SAVEPOINT` on authenticated cart/checkout/admin GETs in our profiler). In future high-concurrency scaling phases, disabling sliding save-on-every-read (or refreshing expiry only when `age < 30 days`) would eliminate those GET write transactions completely once test expectations are updated alongside it.
   - **Expired Session Maintenance:** Run `python manage.py clearsessions` on a periodic weekly Railway cron task to keep `django_session` compact over 365-day cookies.
