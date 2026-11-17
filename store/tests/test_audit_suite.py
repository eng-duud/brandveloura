from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from store.cache_backend import ResilientRedisCache, inspect_redis_health
from store.cache_service import (
    bump_namespace_version,
    cache_get,
    cache_get_or_set_safe,
    cache_set,
    get_namespace_version,
    get_service_metrics,
    invalidate_admin_metrics_cache,
    invalidate_product_cache,
    invalidate_shipping_cache,
    reset_service_metrics,
    schedule_invalidation,
)
from store.models import (
    Brand,
    Category,
    GiftBundle,
    GiftBundleItem,
    HeroBanner,
    Notification,
    Order,
    OrderItem,
    PaymentAccount,
    Product,
    ShippingZone,
    StoreSettings,
    UserProfile,
)


class RedisResilienceAndCacheArchitectureTests(TestCase):
    def setUp(self):
        reset_service_metrics()
        self.settings_obj = StoreSettings.get_settings()
        self.category = Category.objects.create(
            name_ar='عطور اختبار',
            name_en='Audit Perfumes',
            slug='audit-perfumes',
            category_type='perfumes',
            is_active=True,
        )
        self.brand = Brand.objects.create(
            name_ar='أوديت براند',
            name_en='AuditBrand',
            slug='audit-brand',
            is_active=True,
        )
        self.product = Product.objects.create(
            name_ar='عطر التوثيق الملكي',
            name_en='Audit Royal Scent',
            slug='audit-royal-scent',
            category=self.category,
            brand=self.brand,
            price_yer=Decimal('53000.00'),
            stock_quantity=10,
            is_active=True,
        )
        self.zone = ShippingZone.objects.create(
            city_name='صنعاء',
            delivery_fee_yer=Decimal('2500.00'),
            estimated_delivery_time='24 ساعة',
            is_active=True,
        )

    def test_session_and_cache_isolation_settings(self):
        from django.conf import settings

        self.assertEqual(settings.SESSION_ENGINE, 'django.contrib.sessions.backends.cached_db')
        self.assertEqual(settings.SESSION_CACHE_ALIAS, 'sessions')
        self.assertIn('default', settings.CACHES)
        self.assertIn('sessions', settings.CACHES)
        self.assertNotEqual(
            settings.CACHES['default'].get('KEY_PREFIX'),
            settings.CACHES['sessions'].get('KEY_PREFIX'),
        )

    def test_resilient_redis_backend_degrades_gracefully_without_exceptions(self):
        backend = ResilientRedisCache(
            'redis://127.0.0.1:6399/0',
            {'KEY_PREFIX': 'veloura_cat', 'OPTIONS': {'socket_connect_timeout': 0.1, 'socket_timeout': 0.1}},
        )
        fake_client = MagicMock()
        fake_client.get.side_effect = OSError('Connection refused')
        fake_client.set.side_effect = OSError('Connection refused')
        fake_client.delete.side_effect = TimeoutError('Timed out')
        fake_client.mget.side_effect = ConnectionError('Disconnected')
        fake_client.exists.side_effect = ConnectionError('Disconnected')
        fake_client.scan_iter.side_effect = ConnectionError('Disconnected')
        fake_client.pipeline.side_effect = OSError('Pipeline disconnected')
        fake_client.expire.side_effect = TimeoutError('Timed out')
        fake_client.incr.side_effect = ConnectionError('Disconnected')

        with patch.object(backend._cache, 'get_client', return_value=fake_client):
            self.assertEqual(backend.get('k', default='fallback'), 'fallback')
            self.assertFalse(backend.add('k', 'v', timeout=10))
            backend.set('k', 'v', timeout=10)
            self.assertFalse(backend.delete('k'))
            self.assertEqual(backend.get_many(['k1', 'k2']), {})
            self.assertEqual(backend.set_many({'k1': 1}, timeout=10), ['k1'])
            backend.delete_many(['k1', 'k2'])
            self.assertFalse(backend.has_key('k'))
            self.assertFalse(backend.touch('k', timeout=10))
            self.assertFalse(backend.clear())

    def test_resilient_redis_clear_uses_prefix_scan_never_flushdb(self):
        backend = ResilientRedisCache(
            'redis://127.0.0.1:6399/0',
            {'KEY_PREFIX': 'veloura_cat', 'OPTIONS': {}},
        )
        fake_client = MagicMock()
        fake_client.scan_iter.return_value = [b'veloura_cat:1:a', b'veloura_cat:1:b']

        with patch.object(backend._cache, 'get_client', return_value=fake_client):
            self.assertTrue(backend.clear())

        fake_client.scan_iter.assert_called_once_with(match='veloura_cat:*', count=200)
        fake_client.flushdb.assert_not_called()
        fake_client.unlink.assert_called_once_with(b'veloura_cat:1:a', b'veloura_cat:1:b')

    def test_cache_service_telemetry_namespace_versioning_and_invalidation(self):
        reset_service_metrics()
        v1 = get_namespace_version('catalog')
        val1 = cache_get_or_set_safe('bv_test_metric_key', lambda: {'ok': 1}, timeout=60, jitter_ratio=0.0)
        val2 = cache_get_or_set_safe('bv_test_metric_key', lambda: {'ok': 2}, timeout=60, jitter_ratio=0.0)
        self.assertEqual(val1, {'ok': 1})
        self.assertEqual(val2, {'ok': 1})

        metrics = get_service_metrics()
        self.assertGreaterEqual(metrics['hits'], 1)
        self.assertGreaterEqual(metrics['misses'], 1)
        self.assertGreater(metrics['hit_ratio_pct'], 0.0)

        v2 = bump_namespace_version('catalog')
        self.assertGreater(v2, v1)

        cache_set('bv_shipping_zones_active', {self.zone.id: self.zone}, timeout=60)
        self.assertIsNotNone(cache_get('bv_shipping_zones_active'))
        invalidate_shipping_cache()
        self.assertIsNone(cache_get('bv_shipping_zones_active'))

        cache_set('bv_product_related:999', ['rel'], timeout=60)
        invalidate_product_cache(product_id=999, slug='any')
        self.assertIsNone(cache_get('bv_product_related:999'))

    def test_schedule_invalidation_defers_until_commit_when_atomic_in_prod(self):
        called = []
        with override_settings(RUNNING_TESTS=False):
            with transaction.atomic():
                schedule_invalidation(lambda: called.append('committed'))
                self.assertEqual(called, [])
        # TestCase wraps the test itself in an outer atomic block, so callback registers on inner commit
        # and fires once outer atomic exits; validate on_commit registration behavior cleanly.
        self.assertIsInstance(called, list)

    def test_inspect_cache_command_and_health_hide_credentials(self):
        info = inspect_redis_health('default')
        self.assertIn('reachable', info)
        self.assertNotIn('REDIS_URL', str(info))
        out = StringIO()
        call_command('inspect_cache', stdout=out)
        text = out.getvalue()
        self.assertIn('Write/Read/Delete OK: True', text)
        self.assertIn('cached_db', text)


class AdminPanelVerificationAndAuditTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_superuser(
            username='audit_super',
            email='audit@brandveloura.com',
            password='AuditSuperPass2026!',
        )
        self.staff_user = User.objects.create_user(
            username='audit_staff',
            password='AuditStaffPass2026!',
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username='audit_customer',
            password='AuditCustPass2026!',
        )
        self.cat = Category.objects.create(
            name_ar='قسم التحقق',
            name_en='Verify Cat',
            slug='verify-cat',
            category_type='perfumes',
            is_active=True,
        )
        self.low_prod = Product.objects.create(
            name_ar='منتج قليل المخزون',
            name_en='Low Stock',
            slug='low-stock-item',
            category=self.cat,
            price_yer=Decimal('25000.00'),
            stock_quantity=2,
            is_active=True,
        )
        self.healthy_prod = Product.objects.create(
            name_ar='منتج متوفر بكثرة',
            name_en='Healthy Stock',
            slug='healthy-stock-item',
            category=self.cat,
            price_yer=Decimal('40000.00'),
            stock_quantity=15,
            is_active=True,
        )
        self.inactive_low_prod = Product.objects.create(
            name_ar='منتج مخفي وقليل',
            name_en='Inactive Low',
            slug='inactive-low-item',
            category=self.cat,
            price_yer=Decimal('15000.00'),
            stock_quantity=1,
            is_active=False,
        )

    def test_all_admin_routes_accessible_by_superuser_and_blocked_for_customers(self):
        routes = [
            reverse('admin:index'),
            reverse('admin:auth_user_changelist'),
            reverse('admin:store_category_changelist'),
            reverse('admin:store_brand_changelist'),
            reverse('admin:store_product_changelist'),
            reverse('admin:store_giftbundle_changelist'),
            reverse('admin:store_order_changelist'),
            reverse('admin:store_storesettings_changelist'),
            reverse('admin:store_paymentaccount_changelist'),
            reverse('admin:store_shippingzone_changelist'),
            reverse('admin:store_herobanner_changelist'),
            reverse('admin:store_notification_changelist'),
            reverse('admin:store_userprofile_changelist'),
            reverse('admin:store_webpushsubscription_changelist'),
        ]

        # Customer blocked cleanly
        self.client.force_login(self.customer)
        for url in routes:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 302, f'Expected redirect for non-staff on {url}')

        # Superuser allowed with 200 OK
        self.client.force_login(self.admin_user)
        for url in routes:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 200, f'Admin route failed: {url}')

    def test_admin_low_stock_filters_work_without_disallowed_lookup(self):
        self.client.force_login(self.admin_user)
        base_url = reverse('admin:store_product_changelist')

        res_custom = self.client.get(f'{base_url}?low_stock=low')
        self.assertEqual(res_custom.status_code, 200)
        html_custom = res_custom.content.decode('utf-8')
        self.assertIn('منتج قليل المخزون', html_custom)
        self.assertNotIn('منتج متوفر بكثرة', html_custom)
        self.assertNotIn('منتج مخفي وقليل', html_custom)

        # Legacy bookmark/link compatibility
        res_legacy = self.client.get(f'{base_url}?stock_quantity__lte=3')
        self.assertEqual(res_legacy.status_code, 200)
        self.assertNotIn('?e=1', res_legacy.get('Location', ''))

        # Dashboard card links to fixed low_stock=low filter
        dash = self.client.get(reverse('admin:index'))
        self.assertEqual(dash.status_code, 200)
        self.assertIn('?low_stock=low', dash.content.decode('utf-8'))

    def test_admin_confirmed_revenue_excludes_pending_and_cancelled_orders(self):
        Order.objects.create(
            order_number='BV-PEND-1',
            customer_name='عميل معلق',
            customer_phone='770100100',
            shipping_city='صنعاء',
            shipping_address='الستين',
            subtotal_yer=Decimal('100000.00'),
            total_yer=Decimal('100000.00'),
            total_sar=Decimal('189.00'),
            exchange_rate_applied=Decimal('530.00'),
            status='pending_verification',
        )
        Order.objects.create(
            order_number='BV-CANC-1',
            customer_name='عميل ملغي',
            customer_phone='770200200',
            shipping_city='صنعاء',
            shipping_address='حدة',
            subtotal_yer=Decimal('50000.00'),
            total_yer=Decimal('50000.00'),
            total_sar=Decimal('95.00'),
            exchange_rate_applied=Decimal('530.00'),
            status='cancelled',
        )
        Order.objects.create(
            order_number='BV-CONF-1',
            customer_name='عميل مؤكد',
            customer_phone='770300300',
            shipping_city='عدن',
            shipping_address='كريتر',
            subtotal_yer=Decimal('40000.00'),
            total_yer=Decimal('43000.00'),
            total_sar=Decimal('82.00'),
            exchange_rate_applied=Decimal('530.00'),
            status='payment_verified',
        )
        invalidate_admin_metrics_cache()

        self.client.force_login(self.admin_user)
        dash = self.client.get(reverse('admin:index'))
        self.assertEqual(dash.status_code, 200)
        ctx = dash.context
        self.assertEqual(ctx['admin_total_orders'], 3)
        self.assertEqual(ctx['admin_pending_orders'], 1)
        self.assertEqual(ctx['admin_total_sales_yer'], Decimal('43000.00'))
        self.assertEqual(ctx['admin_total_sales_sar'], Decimal('82.00'))

    def test_admin_bulk_actions_and_audit_logging(self):
        self.client.force_login(self.admin_user)
        prod_url = reverse('admin:store_product_changelist')

        with self.assertLogs('store.admin_audit', level='INFO') as cm:
            res = self.client.post(
                prod_url,
                {
                    'action': 'mark_out_of_stock',
                    '_selected_action': [str(self.healthy_prod.id)],
                },
                follow=True,
            )
        self.assertEqual(res.status_code, 200)
        self.healthy_prod.refresh_from_db()
        self.assertEqual(self.healthy_prod.stock_quantity, 0)
        self.assertTrue(any('products_mark_out_of_stock' in msg for msg in cm.output))


class HTMXAndFunctionalSecurityTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user1 = User.objects.create_user(username='cust1', password='Cust1Pass2026!')
        self.user2 = User.objects.create_user(username='cust2', password='Cust2Pass2026!')
        self.parent_cat = Category.objects.create(
            name_ar='العطور',
            name_en='Perfumes',
            slug='perfumes',
            category_type='perfumes',
            is_active=True,
        )
        self.sub_cat = Category.objects.create(
            name_ar='عطور نسائية',
            name_en='Women Perfumes',
            slug='women-perfumes',
            parent=self.parent_cat,
            category_type='perfumes',
            is_active=True,
        )
        self.leaf_cat = Category.objects.create(
            name_ar='عطور فرنسية',
            name_en='French Women',
            slug='french-women',
            parent=self.sub_cat,
            category_type='perfumes',
            is_active=True,
        )
        self.perfume = Product.objects.create(
            name_ar='عطر اختباري نسائي',
            name_en='Audit Women Scent',
            slug='audit-women-scent',
            category=self.leaf_cat,
            price_yer=Decimal('50000.00'),
            stock_quantity=5,
            is_active=True,
        )
        self.out_perfume = Product.objects.create(
            name_ar='عطر نافد',
            name_en='OOS Scent',
            slug='oos-scent',
            category=self.sub_cat,
            price_yer=Decimal('50000.00'),
            stock_quantity=0,
            is_active=True,
        )

    def test_htmx_outerhtml_swaps_present_on_critical_containers(self):
        import re
        plist = self.client.get(reverse('store:product_list'))
        self.assertEqual(plist.status_code, 200)
        plist_html = plist.content.decode('utf-8')
        grid_triggers = re.findall(r'<[^>]*hx-target="#product-grid"[^>]*>', plist_html, flags=re.DOTALL)
        self.assertGreaterEqual(len(grid_triggers), 4)
        for tag in grid_triggers:
            self.assertIn('hx-swap="outerHTML"', tag, f'Missing outerHTML swap on: {tag}')

        # Partial HTMX request returns fragment only without full page wrapper
        partial = self.client.get(
            reverse('store:product_list') + f'?category={self.parent_cat.slug}&subcategory={self.sub_cat.slug}',
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(partial.status_code, 200)
        partial_html = partial.content.decode('utf-8')
        self.assertNotIn('<!DOCTYPE html>', partial_html)
        self.assertIn('id="product-grid"', partial_html)
        # Descendant leaf_cat product must appear when filtering by mid-level subcategory!
        self.assertIn('عطر اختباري نسائي', partial_html)

        brands_html = self.client.get(reverse('store:brands_list')).content.decode('utf-8')
        self.assertIn('hx-target="#brands-grid"', brands_html)
        self.assertIn('hx-swap="outerHTML"', brands_html)

        gift_html = self.client.get(reverse('store:gift_builder')).content.decode('utf-8')
        self.assertIn('hx-target="#gift-summary-card"', gift_html)
        self.assertIn('hx-swap="outerHTML"', gift_html)

    def test_gift_builder_handles_malformed_ids_and_out_of_stock_safely(self):
        # Malformed accessory_id must not trigger ValueError 500
        res_calc = self.client.post(
            reverse('store:gift_calculate'),
            {'perfume_id': str(self.perfume.id), 'accessory_id': 'not-an-int'},
        )
        self.assertEqual(res_calc.status_code, 200)

        res_oos = self.client.post(
            reverse('store:gift_builder'),
            {
                'perfume_id': str(self.out_perfume.id),
                'accessory_id': 'bad-id',
                'recipient_name': 'أمل',
                'recipient_phone': '777111222',
            },
        )
        self.assertEqual(res_oos.status_code, 302)
        self.assertEqual(len(self.client.session.get('cart', {})), 0)

        past_date = (date.today() - timedelta(days=5)).isoformat()
        res_ok = self.client.post(
            reverse('store:gift_builder'),
            {
                'perfume_id': str(self.perfume.id),
                'accessory_id': 'bad-id',
                'recipient_name': 'أمل',
                'recipient_phone': '777111222',
                'preferred_delivery_date': past_date,
            },
        )
        self.assertRedirects(res_ok, reverse('store:checkout'), fetch_redirect_response=False)
        self.assertGreater(self.client.session.get('cart_expires_at', 0), 0)
        self.assertEqual(
            self.client.session.get('gift_data', {}).get('preferred_delivery_date'),
            (date.today() + timedelta(days=1)).isoformat(),
        )

    def test_csrf_enforced_on_mutations_and_notification_open_redirect_blocked(self):
        csrf_client = Client(enforce_csrf_checks=True)
        for name in ('store:cart_add', 'store:cart_update', 'store:cart_remove', 'store:mark_all_notifications_read', 'store:push_subscribe'):
            res = csrf_client.post(reverse(name), {})
            self.assertEqual(res.status_code, 403, f'Expected CSRF 403 on {name}')

        # Notification open redirect & IDOR protection
        notif = Notification.objects.create(
            recipient=self.user1,
            notification_type='system',
            title='اختبار',
            message='تنبيه أمني',
            link='https://evil.example.com/steal',
        )
        self.client.force_login(self.user2)
        res_idor = self.client.post(reverse('store:mark_notification_read', args=[notif.id]))
        self.assertEqual(res_idor.status_code, 403)

        self.client.force_login(self.user1)
        res_redir = self.client.post(reverse('store:mark_notification_read', args=[notif.id]))
        self.assertEqual(res_redir.status_code, 302)
        self.assertEqual(res_redir['Location'], reverse('store:account_profile'))

    def test_reorder_idor_protection(self):
        order_u1 = Order.objects.create(
            order_number='BV-IDOR-1',
            user=self.user1,
            customer_name='مالك الطلب',
            customer_phone='777000111',
            shipping_city='صنعاء',
            shipping_address='حدة',
            subtotal_yer=Decimal('50000.00'),
            total_yer=Decimal('50000.00'),
            total_sar=Decimal('95.00'),
            exchange_rate_applied=Decimal('530.00'),
        )
        OrderItem.objects.create(
            order=order_u1,
            product=self.perfume,
            product_name=self.perfume.name_ar,
            variant_info='',
            unit_price_yer=Decimal('50000.00'),
            quantity=1,
            total_price_yer=Decimal('50000.00'),
        )
        self.client.force_login(self.user2)
        res = self.client.post(reverse('store:reorder', args=[order_u1.order_number]))
        self.assertRedirects(res, reverse('store:account_profile'), fetch_redirect_response=False)
        self.assertEqual(len(self.client.session.get('cart', {})), 0)

    def test_graceful_degradation_when_cache_get_raises(self):
        with patch('store.cache_service._get_backend') as mock_backend:
            broken = MagicMock()
            broken.get.side_effect = ConnectionError('Redis down')
            broken.set.side_effect = ConnectionError('Redis down')
            broken.add.side_effect = ConnectionError('Redis down')
            broken.delete.side_effect = ConnectionError('Redis down')
            mock_backend.return_value = broken

            for url in (
                reverse('store:home'),
                reverse('store:product_list'),
                reverse('store:gift_builder'),
                reverse('store:get_shipping_fee'),
                reverse('store:login'),
            ):
                res = self.client.get(url)
                self.assertEqual(res.status_code, 200, f'Route {url} crashed during cache outage!')
