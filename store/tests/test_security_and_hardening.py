import json
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.test import Client, TestCase
from django.urls import reverse

from store.models import (
    Brand,
    Category,
    GiftBundle,
    GiftBundleItem,
    HeroBanner,
    Notification,
    Order,
    PaymentAccount,
    Product,
    ShippingZone,
    StoreSettings,
)


class SecurityAndHardeningTests(TestCase):
    """اختبارات التحصين الأمني، توافق hx-boost، سلامة المخزون، واستقلالية صفحة 500"""

    def setUp(self):
        cache.clear()
        self.settings = StoreSettings.get_settings()
        self.settings.google_client_id = 'test-client-id.apps.googleusercontent.com'
        self.settings.google_client_secret = 'test-client-secret'
        self.settings.save()

        self.root_cat = Category.objects.create(
            name_ar='عطور',
            name_en='Perfumes',
            category_type='perfumes',
            is_active=True,
        )
        self.sub_cat = Category.objects.create(
            name_ar='عطور شرقية',
            name_en='Oriental Perfumes',
            category_type='perfumes',
            parent=self.root_cat,
            is_active=True,
        )
        self.leaf_cat = Category.objects.create(
            name_ar='دهن العود',
            name_en='Oud Oil',
            category_type='perfumes',
            parent=self.sub_cat,
            is_active=True,
        )
        self.brand = Brand.objects.create(
            name_ar='ديور',
            name_en='Dior',
            is_active=True,
        )
        self.product = Product.objects.create(
            name_ar="عطر سوفاج 'الإصدار الخاص'",
            brand=self.brand,
            category=self.root_cat,
            price_yer=Decimal('50000.00'),
            has_grades=True,
            price_original_yer=Decimal('80000.00'),
            price_master_yer=Decimal('40000.00'),
            stock_quantity=5,
            is_active=True,
        )
        self.bundle = GiftBundle.objects.create(
            title_ar='باقة الفخامة الملكية',
            price_yer=Decimal('35000.00'),
            is_active=True,
        )
        GiftBundleItem.objects.create(
            bundle=self.bundle,
            product=self.product,
            grade='master',
            quantity=3,
        )
        self.zone_active = ShippingZone.objects.create(
            city_name='صنعاء',
            delivery_fee_yer=Decimal('1500.00'),
            is_active=True,
        )
        self.zone_inactive = ShippingZone.objects.create(
            city_name='منطقة موقوفة',
            delivery_fee_yer=Decimal('9000.00'),
            is_active=False,
        )
        self.payment_active = PaymentAccount.objects.create(
            provider_name='بنك الكريمي',
            currency='YER',
            is_active=True,
        )
        self.payment_inactive = PaymentAccount.objects.create(
            provider_name='حساب متوقف',
            currency='YER',
            is_active=False,
        )

    def test_hx_boosted_requests_return_full_pages_while_partials_stay_partial(self):
        """التحقق من أن hx-boost يعيد الصفحة الكاملة، بينما طلبات HTMX الجزئية تعيد الجزء فقط"""
        boosted_headers = {'HTTP_HX_REQUEST': 'true', 'HTTP_HX_BOOSTED': 'true'}
        partial_headers = {'HTTP_HX_REQUEST': 'true'}

        # 1. الكتالوج
        res_boost_list = self.client.get(reverse('store:product_list'), **boosted_headers)
        self.assertEqual(res_boost_list.status_code, 200)
        self.assertContains(res_boost_list, 'id="bv-csrf-token"')

        res_partial_list = self.client.get(reverse('store:product_list'), **partial_headers)
        self.assertEqual(res_partial_list.status_code, 200)
        self.assertNotContains(res_partial_list, '<html')

        # 2. تفاصيل المنتج vs المعاينة السريعة
        detail_url = reverse('store:product_detail', kwargs={'slug': self.product.slug})
        res_boost_detail = self.client.get(detail_url, **boosted_headers)
        self.assertEqual(res_boost_detail.status_code, 200)
        self.assertContains(res_boost_detail, 'id="bv-csrf-token"')
        self.assertContains(res_boost_detail, 'id="grade-selector-container"')

        res_quick_view = self.client.get(detail_url, **partial_headers)
        self.assertEqual(res_quick_view.status_code, 200)
        self.assertContains(res_quick_view, 'id="modal-selected-grade"')
        self.assertNotContains(res_quick_view, '<html')

        # 3. الماركات وتفاصيل الماركة
        res_boost_brands = self.client.get(reverse('store:brands_list'), **boosted_headers)
        self.assertContains(res_boost_brands, 'id="bv-csrf-token"')
        res_partial_brands = self.client.get(reverse('store:brands_list'), **partial_headers)
        self.assertNotContains(res_partial_brands, '<html')

        brand_url = reverse('store:brand_detail', kwargs={'slug': self.brand.slug})
        res_boost_brand = self.client.get(brand_url, **boosted_headers)
        self.assertContains(res_boost_brand, 'id="bv-csrf-token"')
        res_partial_brand = self.client.get(brand_url, **partial_headers)
        self.assertNotContains(res_partial_brand, '<html')

        # 4. السلة: التحديث الجزئي عند انتهاء المهلة يعيد cart_table فقط بدون Base HTML
        res_boost_cart = self.client.get(reverse('store:cart_view'), **boosted_headers)
        self.assertContains(res_boost_cart, 'id="bv-csrf-token"')
        res_partial_cart = self.client.get(reverse('store:cart_view'), **partial_headers)
        self.assertNotContains(res_partial_cart, '<html')

    def test_checkout_uses_live_database_prices_for_order_items(self):
        """التحقق من تطابق سعر OrderItem مع السعر الحي بقاعدة البيانات حتى لو تغيرت قيم الجلسة"""
        self.client.post(reverse('store:cart_add'), {
            'product_id': self.product.id,
            'quantity': 1,
            'grade': 'master',
        })
        # محاكاة تعديل سعر قديم في الجلسة أو تغيير السعر من الإدارة قبل الدفع
        self.product.price_master_yer = Decimal('42000.00')
        self.product.save()

        res = self.client.post(reverse('store:checkout'), {
            'customer_name': 'سمير اليماني',
            'customer_phone': '771122334',
            'shipping_city': self.zone_active.id,
            'shipping_address': 'صنعاء، شارع حدة',
            'payment_method': self.payment_active.id,
            'payment_currency_selected': 'YER',
        })
        self.assertEqual(res.status_code, 302)
        order = Order.objects.latest('created_at')
        item = order.items.first()
        self.assertEqual(order.subtotal_yer, Decimal('42000.00'))
        self.assertEqual(item.unit_price_yer, Decimal('42000.00'))
        self.assertEqual(item.total_price_yer, Decimal('42000.00'))

    def test_cross_grade_and_bundle_stock_limits_cannot_oversell(self):
        """منع تجاوز مخزون المنتج عند الجمع بين درجتي الأصلي والماستر أو بين منتج وباقة"""
        # المخزون = 5: إضافة 3 أصلي ثم محاولة إضافة 3 ماستر يجب أن تحد إلى 2 فقط
        self.client.post(reverse('store:cart_add'), {
            'product_id': self.product.id,
            'quantity': 3,
            'grade': 'original',
        })
        self.client.post(reverse('store:cart_add'), {
            'product_id': self.product.id,
            'quantity': 3,
            'grade': 'master',
        })
        cart = self.client.session.get('cart', {})
        total_qty = sum(item['quantity'] for item in cart.values())
        self.assertEqual(total_qty, 5)

        # حتى لو تم حقن باقة تحتوي 3 قطع مع 3 قطع منفردة في الجلسة، checkout يرفض التجاوز
        session = self.client.session
        session['cart'][f'bundle_{self.bundle.id}'] = {
            'product_id': self.bundle.id,
            'bundle_id': self.bundle.id,
            'is_bundle': True,
            'name': self.bundle.title_ar,
            'brand': 'Brand Veloura',
            'price_yer': float(self.bundle.price_yer),
            'image_url': self.bundle.get_image_url(),
            'quantity': 1,
            'variant_info': 'باقة',
        }
        session.save()

        orders_before = Order.objects.count()
        res = self.client.post(reverse('store:checkout'), {
            'customer_name': 'مشتري تجريبي',
            'customer_phone': '771122335',
            'shipping_city': self.zone_active.id,
            'shipping_address': 'صنعاء',
            'payment_method': self.payment_active.id,
            'payment_currency_selected': 'YER',
        }, follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Order.objects.count(), orders_before)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 5)

    def test_checkout_rejects_inactive_zone_inactive_payment_and_missing_address(self):
        """رفض المناطق أو حسابات الدفع المعطلة والحقول الإلزامية الناقصة في checkout"""
        self.client.post(reverse('store:cart_add'), {
            'product_id': self.product.id,
            'quantity': 1,
            'grade': 'master',
        })
        orders_before = Order.objects.count()

        # عنوان مفقود
        res_addr = self.client.post(reverse('store:checkout'), {
            'customer_name': 'أحمد',
            'customer_phone': '771234567',
            'shipping_city': self.zone_active.id,
            'shipping_address': '   ',
            'payment_method': self.payment_active.id,
        })
        self.assertEqual(res_addr.status_code, 302)
        self.assertEqual(Order.objects.count(), orders_before)

        # منطقة شحن معطلة
        res_zone = self.client.post(reverse('store:checkout'), {
            'customer_name': 'أحمد',
            'customer_phone': '771234567',
            'shipping_city': self.zone_inactive.id,
            'shipping_address': 'صنعاء، السبعين',
            'payment_method': self.payment_active.id,
        })
        self.assertEqual(res_zone.status_code, 302)
        self.assertEqual(Order.objects.count(), orders_before)

        # وسيلة دفع معطلة
        res_pay = self.client.post(reverse('store:checkout'), {
            'customer_name': 'أحمد',
            'customer_phone': '771234567',
            'shipping_city': self.zone_active.id,
            'shipping_address': 'صنعاء، السبعين',
            'payment_method': self.payment_inactive.id,
        })
        self.assertEqual(res_pay.status_code, 302)
        self.assertEqual(Order.objects.count(), orders_before)

    def test_google_oauth_state_and_token_validation(self):
        """التحقق من توليد state عشوائي في الجلسة ورفض OAuth عند التلاعب بـ state أو aud أو g_csrf_token"""
        # 1. google_login يجب أن يولد state عشوائي ويحفظه بالجلسة
        res_redirect = self.client.get(reverse('store:google_login') + '?next=/cart/')
        self.assertEqual(res_redirect.status_code, 302)
        saved_state = self.client.session.get('google_oauth_state')
        self.assertTrue(saved_state and saved_state != '/cart/')
        self.assertIn(f'state={saved_state}', res_redirect['Location'])

        # 2. إرسال state غير مطابق إلى callback يجب أن يُرفض
        res_bad_state = self.client.get(reverse('store:google_callback') + '?code=fake_code&state=forged_state')
        self.assertRedirects(res_bad_state, reverse('store:login'))
        self.assertNotIn('_auth_user_id', self.client.session)

        # 3. إرسال GIS credential بدون g_csrf_token يرفض الطلب
        res_no_csrf = self.client.post(reverse('store:google_callback'), {'credential': 'fake.jwt.token'})
        self.assertRedirects(res_no_csrf, reverse('store:login'))
        self.assertNotIn('_auth_user_id', self.client.session)

        # 4. إرسال GIS credential لعميل آخر (aud مختلف) يُرفض
        self.client.cookies['g_csrf_token'] = 'csrf-ok'
        mock_res = Mock(status_code=200)
        mock_res.json.return_value = {
            'aud': 'other-app.apps.googleusercontent.com',
            'iss': 'https://accounts.google.com',
            'email_verified': True,
            'email': 'attacker@example.com',
        }
        with patch('store.views.requests.post', return_value=mock_res):
            res_bad_aud = self.client.post(
                reverse('store:google_callback'),
                {'credential': 'fake.jwt.token', 'g_csrf_token': 'csrf-ok'},
            )
        self.assertRedirects(res_bad_aud, reverse('store:login'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_service_worker_cache_safety_and_500_standalone_rendering(self):
        """التحقق من استثناء المسارات الديناميكية والجزئية في Service Worker واستقلالية قالب 500"""
        sw_res = self.client.get('/sw.js')
        self.assertEqual(sw_res.status_code, 200)
        sw_text = sw_res.content.decode('utf-8')
        self.assertIn('brand-veloura-pwa-v7', sw_text)
        self.assertIn("'/partials/'", sw_text)
        self.assertIn("'/notifications/'", sw_text)
        self.assertIn('HX-Request', sw_text)
        self.assertIn("no-store", sw_text)
        self.assertIn("url.pathname.startsWith('/static/')", sw_text)

        # render_to_string بدون أي Request أو قاعدة بيانات (يحاكي تعطل DB وقت خطأ 500)
        html_500 = render_to_string('500.html', {})
        self.assertIn('500', html_500)
        self.assertIn('Brand Veloura', html_500)
        self.assertIn('<!DOCTYPE html>', html_500)

    def test_multilevel_category_descendants_herobanner_url_and_signal_invalidation(self):
        """فحص الأقسام متعددة المستويات، حماية روابط البانر، وكاش المخزون الذكي"""
        # 1. الأقسام متعددة المستويات
        desc_ids = self.root_cat.get_descendants_and_self_ids()
        self.assertEqual(set(desc_ids), {self.root_cat.id, self.sub_cat.id, self.leaf_cat.id})

        # 2. رفض javascript: في HeroBanner
        bad_banner = HeroBanner(title='Test', link_type='custom', custom_url='javascript:alert(1)')
        with self.assertRaises(ValidationError):
            bad_banner.clean()

        # 3. الإشارة الذكية: مجرد نقص المخزون مع بقائه > 0 لا يمسح كاش الرئيسية
        cache.set('bv_home_banners', ['cached'])
        self.product.stock_quantity = 4
        self.product.save(update_fields=['stock_quantity'])
        self.assertEqual(cache.get('bv_home_banners'), ['cached'])

        # أما نفاد المخزون فيفرغ الكاش فوراً
        self.product.stock_quantity = 0
        self.product.save(update_fields=['stock_quantity'])
        self.assertIsNone(cache.get('bv_home_banners'))

        # 4. notify_admin يستخدم reverse('admin:...') ديناميكياً
        notif = Notification.notify_admin(title='تست', message='رسالة')
        self.assertEqual(notif.link, reverse('admin:index'))

    def test_push_subscribe_requires_csrf_and_xss_escaped_in_templates(self):
        """التحقق من فرض CSRF على push_subscribe وهروب علامات الاقتباس داخل السمات البرمجية"""
        csrf_client = Client(enforce_csrf_checks=True)
        payload = {
            'endpoint': 'https://fcm.googleapis.com/fcm/send/csrf-test-123',
            'keys': {'p256dh': 'BTestKey12345', 'auth': 'AuthSecret123'},
        }
        res_forbidden = csrf_client.post(
            reverse('store:push_subscribe'),
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(res_forbidden.status_code, 403)

        # جلب CSRF Token وإرساله بالترويسة ينجح
        home_res = csrf_client.get(reverse('store:home'))
        self.assertContains(home_res, 'id="bv-csrf-token"')
        import re
        match = re.search(r'id="bv-csrf-token"[^>]*data-token="([^"]+)"', home_res.content.decode('utf-8'))
        self.assertIsNotNone(match)
        token = match.group(1)
        res_ok = csrf_client.post(
            reverse('store:push_subscribe'),
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(res_ok.status_code, 200)

        # التحقق من هروب علامة التنصيص المفردة في اسم المنتج بالبطاقة والتفاصيل
        detail_res = self.client.get(reverse('store:product_detail', kwargs={'slug': self.product.slug}))
        html = detail_res.content.decode('utf-8')
        self.assertNotIn("تمت إضافة عطر سوفاج 'الإصدار الخاص'", html)
