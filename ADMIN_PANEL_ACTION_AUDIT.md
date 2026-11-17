# Admin Panel Verification & Action Audit — Brand Veloura

**Admin URL Prefix:** `/cpanel-0x110/` (`django-unfold` customized via `templates/admin/base_site.html` & `templates/admin/index.html`)  
**Total Registered Models:** 13 (`User`, `Category`, `Brand`, `Product`, `GiftBundle`, `Order`, `StoreSettings`, `PaymentAccount`, `ShippingZone`, `HeroBanner`, `Notification`, `UserProfile`, `WebPushSubscription`; `Group` intentionally unregistered).

---

## 1. Custom Admin Bugs Identified & Remediated

1. **Broken Dashboard Low-Stock Filter Link (`templates/admin/index.html:54` & `store/admin.py`)**
   - **Defect Found:** The dashboard KPI card linked to `?stock_quantity__lte=3`. Because `stock_quantity` was neither in `ProductAdmin.list_filter` nor allowed via `ProductAdmin.lookup_allowed`, Django Admin rejected the query parameter and redirected administrators to `?e=1` (filtered error state).
   - **Fix Implemented:** Added `LowStockListFilter(admin.SimpleListFilter)` (`parameter_name = 'low_stock'`) to `ProductAdmin.list_filter` with choices `'low'` (`stock_quantity__lte=3, is_active=True`), `'out'`, and `'healthy'`, updated the dashboard KPI card link to `?low_stock=low`, and overridden `ProductAdmin.lookup_allowed()` to also accept legacy `?stock_quantity__lte=...` links cleanly.
   - **Verified:** Tested HTTP `200` filtering for both `?low_stock=low` and `?stock_quantity__lte=3` in `AdminPanelVerificationAndAuditTests.test_admin_low_stock_filters_work_without_disallowed_lookup`.

2. **Misleading "Confirmed Sales" Revenue Metric (`store/admin.py` `custom_admin_each_context`)**
   - **Defect Found:** The dashboard card labeled *"إجمالي المبيعات المؤكدة"* (Total Confirmed Sales) computed `Sum('total_yer', filter=~Q(status='cancelled'))`, incorrectly counting unverified `'pending_verification'` orders as confirmed revenue, AND ran a duplicate `Order.objects.filter(status='pending_verification').count()` query on the dashboard.
   - **Fix Implemented:** Filtered revenue aggregates strictly on `CONFIRMED_ORDER_STATUSES = ('payment_verified', 'processing', 'out_for_delivery', 'delivered')` and cached the dashboard KPI block (`bv_admin_dashboard_metrics`, 30s TTL, explicitly invalidated on `Order` & `Product` writes).
   - **Verified:** `test_admin_confirmed_revenue_excludes_pending_and_cancelled_orders` confirms pending and cancelled totals are excluded accurately.

3. **Slow Admin Product Changelist Date Truncation (`store/admin.py` `ProductAdmin`)**
   - **Defect Found:** `date_hierarchy = 'created_at'` on `ProductAdmin` executed `SELECT MIN(...), MAX(...)` plus `DISTINCT django_datetime_trunc('day', ...)` on every `/cpanel-0x110/store/product/` load (measured `7.0 ms` slowest single SQL locally and `491.99 ms` P95 page latency).
   - **Fix Implemented:** Removed `date_hierarchy` from `ProductAdmin` (retaining it on `OrderAdmin` where daily order drill-down is operationally needed), cutting `/cpanel-0x110/store/product/` avg latency by **68.2%** (`168.29 ms` -> `53.59 ms`) and P95 by **85.6%** (`491.99 ms` -> `71.04 ms`).

4. **Missing Admin Audit Logging (`store/admin.py` & `store/views.py`)**
   - **Fix Implemented:** Added structured `[ADMIN_AUDIT]` logger (`store.admin_audit`) for privilege edits (`SimplifiedUserAdmin`), exchange rate/settings saves (`StoreSettingsAdmin`), order status edits/bulk actions (`OrderAdmin`), product bulk status/stock/duplicate/push actions (`ProductAdmin`), and official print views (`admin_print_gift_card`, `admin_print_recipient_slip`, `admin_print_invoice`).

---

## 2. Complete Admin Model, Inline, Filter & Action Inventory

| Model Admin | Inlines & Tools | Filters (`list_filter`) | Search Fields | Custom Actions / Endpoints | RBAC & Verification |
|---|---|---|---|---|---|
| `SimplifiedUserAdmin` (`auth.User`) | Audited staff/superuser save hook | `is_staff`, `is_active`, `date_joined` | `username`, `first_name`, `last_name`, `email` | Standard user CRUD + `[ADMIN_AUDIT]` on privilege changes | Verified `200` superuser / `302` non-staff |
| `CategoryAdmin` | `SubCategoryInline` (tabular) | `show_in_home_slider`, `parent`, `is_featured`, `is_active` | `name_ar`, `name_en` | Inline edit (`show_in_home_slider`, `home_slider_order`, `is_featured`, `is_active`, `display_order`) | Verified `200` list + add POST in `test_admin_routes.py` |
| `BrandAdmin` | Products count deep link | `is_featured`, `is_active`, `categories` | `name_ar`, `name_en`, `description` | Annotated `products_count` without N+1 | Verified `200` |
| `ProductAdmin` (`ProductAdminForm`) | `ProductImageInline` | `LowStockListFilter`, `is_active`, `is_featured`, `is_new`, `is_best_seller`, `has_grades`, `category`, `brand` | `name_ar`, `name_en`, `brand__name_ar`, `brand__name_en`, `brand_name`, `sku` | `duplicate_products`, `make_active`, `make_inactive`, `make_featured`, `unmake_featured`, `mark_as_new`, `unmark_as_new`, `send_push_campaign`, `mark_out_of_stock` | Form validation (`stock_quantity >= 0`, `compare_at > price`), cache invalidation + `[ADMIN_AUDIT]` verified |
| `GiftBundleAdmin` (`GiftBundleAdminForm`) | `GiftBundleItemInline` + checkbox picker | `is_active`, `is_featured`, `includes_luxury_packaging`, `includes_gift_card`, `created_at` | `title_ar`, `title_en`, `subtitle`, `description` | `save_related` checkbox sync | Prefetched `items__product__images`; verified `200` |
| `OrderAdmin` | `OrderItemInline`, WhatsApp link, Cloudinary receipt, gift & invoice print actions | `status`, `is_gift`, `shipping_city`, `payment_currency_selected`, `created_at` (`date_hierarchy`) | `order_number`, `customer_name`, `customer_phone`, `recipient_name`, `payment_reference_no` | `mark_as_verified`, `mark_as_processing`, `mark_as_out_for_delivery`, `mark_as_delivered`, `cancel_and_restore_stock_action` + `/cpanel-order-card/<id>/`, `/cpanel-order-slip/<id>/`, `/cpanel-order-invoice/<id>/` | Verified status/stock transitions, push notifications, & `403`/redirect non-staff guard |
| `StoreSettingsAdmin` (`StoreSettingsAdminForm`) | Singleton guard (`has_add_permission = False` once created), masked `PasswordInput` for secrets | — | — | Live exchange-rate conversion, cart timer, default category | Verified `200` + cache bust + `[ADMIN_AUDIT]` |
| `PaymentAccountAdmin` | — | `currency`, `bank_country`, `is_cod`, `is_active` | `provider_name`, `account_number`, `account_holder_name` | Inline toggle (`is_active`, `display_order`) | Verified `200` |
| `ShippingZoneAdmin` | — | — | `city_name` | Zone fee & delivery SLA updates bust shipping cache | Verified `200` |
| `HeroBannerAdmin` | Banner thumbnail preview | `link_type`, `is_active` | — | Target destination selector | Verified `200` |
| `NotificationAdmin` | Order/recipient links | `is_read`, `for_admin`, `notification_type`, `created_at` | `title`, `message`, `recipient__username`, `recipient__email`, `order__order_number` | `mark_as_read`, `mark_as_unread`, `broadcast_push` | Verified `200` |
| `UserProfileAdmin` | — | — | `user__username`, `user__first_name`, `user__last_name`, `user__email`, `phone`, `preferred_city` | Read/edit customer profiles | Verified `200` |
| `WebPushSubscriptionAdmin` | — | `created_at` | `user__username`, `user__first_name`, `user__email`, `endpoint` | `send_test_push` | Verified `200` |
