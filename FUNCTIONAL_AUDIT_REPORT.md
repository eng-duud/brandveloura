# Functional & HTMX Audit Report — Brand Veloura

**Scope:** All customer-facing Django views (`store/views.py`), templates (`templates/store/`), HTMX partial swaps, cart reservation timer, dual-currency YER/SAR calculations, gifting engine, and authentication flows.

---

## 1. End-to-End Functional Flows Verified

| Flow | Entry URL / View | Verification Summary | Status |
|---|---|---|---|
| Progressive Home Shell & Deferred Sliders | `/` (`home_view`) -> `/partials/home-deferred/` (`home_deferred_content_view`) | `hx-get`, `hx-trigger="load"`, `hx-swap="outerHTML"` loads category sliders, gift bundles, and brands asynchronously per active currency (`YER`/`SAR`) | Verified |
| Multi-Level Catalog & Filters | `/products/`, `/perfumes/`, `/watches/`, `/cosmetics/` (`product_list_view`) | Subcategory pills, search (`?q=`), brand, grade (`original`/`master`), price bounds, sorting, and pagination verified. **Fixed** mid-level subcategory queries to include descendant subcategories (`get_descendants_and_self_ids()`) and fixed duplicate `DISTINCT` SQL ordering on `available_brands` | Fixed & Verified |
| Brand Directory & Brand Catalog | `/brands/` (`brands_list_view`), `/brands/<slug>/` (`brand_detail_view`) | 4-icon filter bar + expandable search + product grid + other brands discovery strip verified | Fixed & Verified |
| Quick View Modal & Detail Page | `/products/<slug>/` (`product_detail_view` / `product_quick_view`) | `HX-Request` (non-boosted) renders `partials/quick_view_modal.html`; full navigation / `HX-Boosted` renders `product_detail.html` | Verified |
| Cart & Reservation Timer | `/cart/`, `/cart/add/`, `/cart/update/`, `/cart/remove/` | Unified product stock validation across grades/bundles, synced to `UserProfile.cart_data` for logged-in accounts, server countdown (`cart_expires_at`), OOB desktop/mobile badge sync, timer auto-expiry release | Fixed & Verified |
| Gifting Engine (4-Step Wizard & Bundles) | `/gifting/`, `/gifting/calculate/`, `/bundles/<slug>/`, `/bundles/<slug>/order/` | **Fixed** non-integer ID crash in POST & live calculation, stock check before cart add, past `preferred_delivery_date` auto-adjustment, and reservation timer refresh (`refresh_cart_reservation`) | Fixed & Verified |
| Checkout & Live Shipping/Wrapping | `/checkout/`, `/get-shipping-fee/` | Live HTMX updates on shipping city change, order type toggle (`personal`/`gift`), and luxury wrapping checkbox; atomic order creation + stock deduction | Fixed & Verified |
| Customer Account & Reorder | `/account/`, `/reorder/<order_number>/` | Consolidated duplicate order/notification queries; verified strict owner authorization on reorder; verified cart restoration on login (`merge_and_restore_user_cart`) | Fixed & Verified |
| In-App Notifications | `/notifications/badge/`, `/notifications/dropdown/`, `/notifications/<id>/read/`, `/notifications/mark-all-read/` | Owner/staff RBAC verified (`403` cross-user); unread badge cached (`bv_unread_notifications_user_{id}`, invalidated on read/save); open redirect on `notification.link` remediated | Fixed & Verified |

---

## 2. Complete HTMX Interaction Audit Matrix

Inspection covered every `hx-*` trigger across `templates/store/**/*.html`:

| Template / Component | Trigger & Endpoint | `hx-target` | Before Audit (`hx-swap`) | Issue Found & Action Taken | Verified |
|---|---|---|---|---|---|
| `home.html:236` | `GET /partials/home-deferred/` (`load`) | self placeholder | `outerHTML` | Correct | Yes |
| `product_list.html:106` | `GET /products/?category=...` (`الكل` pill) | `#product-grid` | *(omitted -> `innerHTML`)* | **Bug:** Nested duplicate `<div id="product-grid">` inside itself on click. Added `hx-swap="outerHTML"` | Yes |
| `product_list.html:118` | `GET /products/?category=...&subcategory=...` | `#product-grid` | *(omitted -> `innerHTML`)* | **Bug:** Same duplicate `#product-grid` nesting. Added `hx-swap="outerHTML"` | Yes |
| `product_list.html:130` | `GET /products/` (root pill) | `#product-grid` | *(omitted -> `innerHTML`)* | **Bug:** Nested `#product-grid`. Added `hx-swap="outerHTML"` | Yes |
| `product_list.html:196, 368` | `GET {{ catalog_reset_url }}` (clear/reset filters) | `#product-grid` | *(omitted -> `innerHTML`)* | **Bug:** Nested `#product-grid`. Added `hx-swap="outerHTML"` | Yes |
| `product_list.html:235` | `GET /products/` (`#filter-drawer-form`) | `#product-grid` | `outerHTML` | Correct | Yes |
| `brands_list.html:51` | `GET /brands/?q=...` (live search) | `#brands-grid` | *(omitted -> `innerHTML`)* | **Bug:** `partials/brands_grid.html` opens `<div id="brands-grid">`; default `innerHTML` nested duplicate IDs. Added `hx-swap="outerHTML"` | Yes |
| `brand_detail.html:109, 261` | `GET /brands/<slug>/` (filters & reset) | `#brand-products-grid` | `innerHTML` (wrapper around `#product-grid`) | Wrapper `<div id="brand-products-grid">` surrounds `#product-grid` cleanly; pagination inside `product_grid` uses `#product-grid` + `outerHTML` | Yes |
| `checkout.html:186, 337, 451` | `GET /get-shipping-fee/` (city & wrapping change) | `#checkout-totals` | *(omitted -> `innerHTML`)* | **Bug:** `partials/checkout_totals.html` root element is `<div id="checkout-totals" data-total-yer="...">`, so `innerHTML` left stale outer `data-total-*` wrapper in DOM. Added `hx-swap="outerHTML"` on all 3 triggers | Yes |
| `gift_builder.html:192` | `POST /gifting/calculate/` (`change`) | `#gift-summary-card` | *(omitted -> `innerHTML`)* | **Bug:** `partials/gift_builder_summary.html` root element is `<div id="gift-summary-card">`, causing nested duplicate IDs. Added `hx-swap="outerHTML"` | Yes |
| `partials/cart_table.html:86, 94, 110` | `POST /cart/update/`, `POST /cart/remove/` | `#cart-container` | *(omitted -> `innerHTML`)* | **Bug:** `partials/cart_table.html` root is `<div id="cart-container">`; `innerHTML` nested duplicate `#cart-container` and missed `hx-disabled-elt` on double click. Added `hx-swap="outerHTML"` + `hx-disabled-elt="this"` | Yes |
| `partials/cart_table.html:230` | `htmx.ajax('GET', '/cart/')` on timer `00:00` | `#cart-container` | `{target: '#cart-container'}` | **Fixed** to `{target: '#cart-container', swap: 'outerHTML'}` | Yes |
| `partials/quick_view_modal.html:172` | `POST /cart/add/` | `#cart-badge-container` | `innerHTML` (receives `<span>` + OOB mobile badge) | Added `hx-disabled-elt="find button[type='submit']"` to guard against double submissions | Yes |
| `product_detail.html:314` | `POST /cart/add/` | `#cart-badge-container` | `innerHTML` (receives `<span>` + OOB mobile badge) | Added `hx-disabled-elt="find button[type='submit']"` | Yes |
| `partials/notifications_dropdown.html:16, 83` | `POST /notifications/...` | `#notifications-dropdown-content` | `outerHTML` | Added `hx-disabled-elt="find button[type='submit']"` | Yes |

---

## 3. Logic Fixes Summary

1. **Subcategory Descendant Resolution (`store/views.py` `product_list_view`):**
   Filtering by a mid-level parent subcategory previously matched `category=active_subcategory`, omitting products in nested grandchild categories. Updated to `category_id__in=_descendants_ids(active_subcategory.id)`.
2. **Invalid `DISTINCT` Brand Extraction (`store/views.py` `product_list_view`):**
   `Product.Meta.ordering` (`['-is_featured', '-created_at']`) injected ordering columns into SQL `SELECT DISTINCT` when `.values_list('brand_name', flat=True).distinct()` was called without clearing order. Added `.order_by('brand_name')` before `.values_list(...).distinct()`.
3. **Gift Builder Reservation & Validation Parity (`store/views.py` `gift_builder_view`):**
   Now checks `stock_quantity` on bundle items/perfumes, normalizes past `preferred_delivery_date` to tomorrow (`date.today() + timedelta(days=1)`), and calls `refresh_cart_reservation(request)` identical to `/cart/add/`.
