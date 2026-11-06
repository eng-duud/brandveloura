import io
from decimal import Decimal
from django.test import TestCase, Client, RequestFactory
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from store.models import (
    StoreSettings, PaymentAccount, ShippingZone,
    Category, Product, Order
)
from store.views import custom_404_view, custom_500_view, custom_403_view


class EnhancementSystemTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.factory = RequestFactory()
        self.settings = StoreSettings.get_settings()

        self.category = Category.objects.create(
            name_ar="عطور فاخرة",
            name_en="Luxury Perfumes",
            slug="luxury-perfumes-test",
            category_type="perfumes"
        )
        self.product = Product.objects.create(
            name_ar="عطر لافندر فيلورا الفاخر",
            name_en="Veloura Lavender Noir",
            slug="veloura-lavender-noir",
            category=self.category,
            price_yer=Decimal('45000.00'),
            stock_quantity=5,
            is_active=True
        )
        self.zone_sanaa = ShippingZone.objects.create(
            city_name="صنعاء",
            delivery_fee_yer=Decimal('2000.00'),
            estimated_delivery_time="خلال 24 ساعة"
        )
        self.payment_acc = PaymentAccount.objects.create(
            provider_name="بنك الكريمي المميز",
            account_number="3001234567",
            account_holder_name="شركة فيلورا للتجارة",
            instructions="يرجى إرفاق إشعار التحويل البنكي أو السداد",
            currency="YER",
            is_active=True
        )

    def test_health_check_healthy(self):
        """فحص جاهزية التطبيق وقاعدة البيانات للاستضافة السحابية"""
        res = self.client.get(reverse('store:health_check'))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get('status'), 'healthy')
        self.assertEqual(data.get('database'), 'connected')
        self.assertEqual(data.get('service'), 'brandveloura')

    def test_robots_txt_and_cache_headers(self):
        """فحص ملف robots.txt وترويسات التخزين ومحركات وبوتات الذكاء الاصطناعي"""
        res = self.client.get('/robots.txt')
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/plain', res.headers.get('Content-Type', ''))
        self.assertIn('max-age', res.headers.get('Cache-Control', ''))
        content = res.content.decode('utf-8')
        self.assertIn('Sitemap:', content)
        self.assertIn('ClaudeBot', content)
        self.assertIn('PerplexityBot', content)
        self.assertIn('Applebot', content)

    def test_sitemap_xml_caching_and_entries(self):
        """فحص خريطة الموقع XML وتضمين الأقسام الرئيسية وبناء الهدايا"""
        res = self.client.get('/sitemap.xml')
        self.assertEqual(res.status_code, 200)
        self.assertIn('application/xml', res.headers.get('Content-Type', ''))
        self.assertIn('max-age', res.headers.get('Cache-Control', ''))
        content = res.content.decode('utf-8')
        self.assertIn('/gifting/', content)
        self.assertIn('/perfumes/', content)
        self.assertIn('/watches/', content)
        self.assertIn('/cosmetics/', content)

    def test_llms_txt_structure(self):
        """فحص ملف llms.txt لإتاحة معلومات المتجر والعملات لنماذج الذكاء الاصطناعي"""
        res = self.client.get('/llms.txt')
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/plain', res.headers.get('Content-Type', ''))
        content = res.content.decode('utf-8')
        self.assertIn('Brand Veloura', content)
        self.assertIn('Perfumes', content)
        self.assertIn('SAR', content)
        self.assertIn('YER', content)

    def test_pwa_manifest_enhancements(self):
        """فحص بيانات PWA Manifest والاختصارات والاتجاه RTL"""
        res = self.client.get('/manifest.json')
        self.assertEqual(res.status_code, 200)
        self.assertIn('application/manifest+json', res.headers.get('Content-Type', ''))
        manifest = res.json()
        self.assertEqual(manifest.get('dir'), 'rtl')
        self.assertEqual(manifest.get('lang'), 'ar')
        self.assertIn('id', manifest)
        self.assertIn('shortcuts', manifest)
        self.assertGreater(len(manifest['shortcuts']), 0)

    def test_service_worker_offline_support(self):
        """فحص ملف service worker واحتوائه على استراتيجية وضع عدم الاتصال"""
        res = self.client.get('/sw.js')
        self.assertEqual(res.status_code, 200)
        self.assertIn('application/javascript', res.headers.get('Content-Type', ''))
        content = res.content.decode('utf-8')
        self.assertIn('/offline/', content)
        self.assertIn('brand-veloura-pwa', content)

    def test_offline_page_view(self):
        """فحص صفحة وضع عدم الاتصال الفاخرة المخصصة لـ PWA"""
        res = self.client.get(reverse('store:offline'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'وضع عدم الاتصال')

    def test_custom_error_handlers(self):
        """فحص صفحات الأخطاء المخصصة 404 و 500 و 403 بهوية المتجر الفاخرة"""
        from django.contrib.auth.models import AnonymousUser
        from django.contrib.messages.storage.fallback import FallbackStorage
        
        req = self.factory.get('/non-existent-page/')
        req.session = {}
        req.user = AnonymousUser()
        setattr(req, '_messages', FallbackStorage(req))

        res_404 = custom_404_view(req)
        self.assertEqual(res_404.status_code, 404)
        self.assertIn('404', res_404.content.decode('utf-8'))

        res_500 = custom_500_view(req)
        self.assertEqual(res_500.status_code, 500)
        self.assertIn('500', res_500.content.decode('utf-8'))

        res_403 = custom_403_view(req)
        self.assertEqual(res_403.status_code, 403)
        self.assertIn('403', res_403.content.decode('utf-8'))

    def test_checkout_disallowed_receipt_extension(self):
        """التحقق من رفض رفع الملفات التنفيذية أو غير المسموحة كإشعار تحويل بنكي"""
        self.client.post(reverse('store:cart_add'), {
            'product_id': self.product.id,
            'quantity': 1
        })
        bad_file = SimpleUploadedFile("receipt.exe", b"fake binary executable content", content_type="application/octet-stream")
        checkout_data = {
            'customer_name': 'عميل تجريبي',
            'customer_phone': '771234567',
            'shipping_city': self.zone_sanaa.id,
            'shipping_address': 'صنعاء، شارع الزبيري',
            'payment_method': self.payment_acc.id,
            'payment_currency_selected': 'YER',
            'payment_reference_no': 'REF-001122',
            'payment_receipt': bad_file
        }
        res = self.client.post(reverse('store:checkout'), checkout_data, follow=True)
        # Should stay on checkout page with an error, not redirect to success
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'صيغة ملف الإشعار غير مقبولة')
        self.assertFalse(Order.objects.filter(customer_phone='771234567').exists())

    def test_checkout_oversized_receipt(self):
        """التحقق من رفض رفع ملف إشعار أكبر من 10 ميغابايت لمنع استنزاف موارد الخادم"""
        self.client.post(reverse('store:cart_add'), {
            'product_id': self.product.id,
            'quantity': 1
        })
        large_file = SimpleUploadedFile("big_receipt.jpg", b"0" * (11 * 1024 * 1024), content_type="image/jpeg")
        checkout_data = {
            'customer_name': 'عميل تجريبي كبير',
            'customer_phone': '771234568',
            'shipping_city': self.zone_sanaa.id,
            'shipping_address': 'صنعاء، شارع الزبيري',
            'payment_method': self.payment_acc.id,
            'payment_currency_selected': 'YER',
            'payment_reference_no': 'REF-001123',
            'payment_receipt': large_file
        }
        res = self.client.post(reverse('store:checkout'), checkout_data, follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'حجم ملف إشعار التحويل كبير جداً')
        self.assertFalse(Order.objects.filter(customer_phone='771234568').exists())

    def test_cart_inventory_boundary_capping(self):
        """التحقق من عدم تجاوز المخزون المتوفر عند إضافة كميات كبيرة للسلة"""
        # Product stock is 5. Adding 10 should cap to 5.
        self.client.post(reverse('store:cart_add'), {
            'product_id': self.product.id,
            'quantity': 10
        })
        cart = self.client.session.get('cart', {})
        item_qty = list(cart.values())[0]['quantity']
        self.assertEqual(item_qty, 5)

        # Adding again when stock is exhausted triggers maxStockReached
        res = self.client.post(reverse('store:cart_add'), {
            'product_id': self.product.id,
            'quantity': 1
        })
        self.assertEqual(res.headers.get('HX-Trigger'), 'maxStockReached')
        cart_after = self.client.session.get('cart', {})
        self.assertEqual(list(cart_after.values())[0]['quantity'], 5)

    def test_currency_toggle_htmx(self):
        """التحقق من تبديل العملة عبر طلب HTMX وإرجاع HX-Refresh للتحديث الشامل"""
        res = self.client.post(
            reverse('store:toggle_currency'),
            HTTP_HX_REQUEST='true'
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get('HX-Refresh'), 'true')
        self.assertEqual(self.client.session.get('active_currency'), 'SAR')

    def test_currency_toggle_get_with_param(self):
        """التحقق من تبديل العملة عبر رابط مباشر GET وإعادة التوجيه"""
        res = self.client.get(
            f"{reverse('store:toggle_currency')}?toggle=1",
            HTTP_REFERER='/perfumes/'
        )
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, '/perfumes/')
        self.assertEqual(self.client.session.get('active_currency'), 'SAR')

    def test_url_compatibility_routes(self):
        """التحقق من سلامة مسارات التوافق الخلفي للطلبات والمنتجات وحساب المستخدم"""
        # 1. Product detail compatibility path /product/<slug>/
        res_prod = self.client.get(f"/product/{self.product.slug}/")
        self.assertEqual(res_prod.status_code, 200)
        self.assertContains(res_prod, self.product.name_ar)

        # 2. Account orders route /account/orders/
        res_orders = self.client.get("/account/orders/")
        # Redirects to login if unauthenticated or renders if authenticated
        self.assertIn(res_orders.status_code, [200, 302])

    def test_checkout_disguised_fake_receipt_rejected(self):
        """التحقق من فحص التوقيع الثنائي ورفض الملفات الخبيثة المتخفية بامتداد صورة"""
        self.client.post(reverse('store:cart_add'), {
            'product_id': self.product.id,
            'quantity': 1
        })
        fake_image = SimpleUploadedFile("exploit.jpg", b"<?php echo 'malicious payload'; ?>", content_type="image/jpeg")
        checkout_data = {
            'customer_name': 'عميل هجوم',
            'customer_phone': '771239999',
            'shipping_city': self.zone_sanaa.id,
            'shipping_address': 'صنعاء',
            'payment_method': self.payment_acc.id,
            'payment_currency_selected': 'YER',
            'payment_reference_no': 'REF-FAKE',
            'payment_receipt': fake_image
        }
        res = self.client.post(reverse('store:checkout'), checkout_data, follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'تعذر قراءة ملف الإشعار')
        self.assertFalse(Order.objects.filter(customer_phone='771239999').exists())

    def test_checkout_valid_image_receipt_accepted(self):
        """التحقق من قبول الصور السليمة المنشأة بتوقيع صورة حقيقي"""
        from PIL import Image
        img_io = io.BytesIO()
        img = Image.new('RGB', (10, 10), color='pink')
        img.save(img_io, format='JPEG')
        img_io.seek(0)
        valid_file = SimpleUploadedFile("real_receipt.jpg", img_io.read(), content_type="image/jpeg")

        self.client.post(reverse('store:cart_add'), {
            'product_id': self.product.id,
            'quantity': 1
        })
        checkout_data = {
            'customer_name': 'عميل حقيقي',
            'customer_phone': '775556677',
            'shipping_city': self.zone_sanaa.id,
            'shipping_address': 'صنعاء، حدة',
            'payment_method': self.payment_acc.id,
            'payment_currency_selected': 'YER',
            'payment_reference_no': 'REF-REAL-001',
            'payment_receipt': valid_file
        }
        res = self.client.post(reverse('store:checkout'), checkout_data, follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(Order.objects.filter(customer_phone='775556677').exists())

    def test_checkout_insufficient_stock_rejection(self):
        """التحقق من رفض إتمام الطلب ومنع البيع الزائد عندما ينفد المخزون أثناء الشراء"""
        # Add 3 items to cart
        self.client.post(reverse('store:cart_add'), {
            'product_id': self.product.id,
            'quantity': 3
        })
        # Simulate inventory reduction by another customer concurrently
        self.product.stock_quantity = 1
        self.product.save(update_fields=['stock_quantity'])

        checkout_data = {
            'customer_name': 'عميل متزامن',
            'customer_phone': '778899001',
            'shipping_city': self.zone_sanaa.id,
            'shipping_address': 'صنعاء',
            'payment_method': self.payment_acc.id,
            'payment_currency_selected': 'YER',
            'payment_reference_no': 'REF-RACE',
        }
        res = self.client.post(reverse('store:checkout'), checkout_data, follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'نفدت الكمية المتوفرة')
        # Ensure order was NOT created and stock remains 1
        self.assertFalse(Order.objects.filter(customer_phone='778899001').exists())
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 1)

    def test_currency_toggle_open_redirect_protection(self):
        """التحقق من حظر التوجيه المفتوح Open Redirect عند تزويد Referer خارجي خبيث"""
        res = self.client.get(
            f"{reverse('store:toggle_currency')}?toggle=1",
            HTTP_REFERER='https://attacker-phishing-site.com/steal'
        )
        self.assertEqual(res.status_code, 302)
        # Must redirect safely to internal home /
        self.assertEqual(res.url, reverse('store:home'))

    def test_currency_toggle_non_htmx_post(self):
        """التحقق من أن طلب POST بدون HTMX يرجع زر التبديل برمز الحالة 200 ويغير العملة"""
        res = self.client.post(reverse('store:toggle_currency'))
        self.assertEqual(res.status_code, 200)
        self.assertIn('button', res.content.decode('utf-8'))
        self.assertEqual(self.client.session.get('active_currency'), 'SAR')

    def test_store_settings_exchange_rate_caching_and_eviction(self):
        """التحقق من كفاءة كاش سعر الصرف وتفريغ الكاش عند تعديل الإعدادات"""
        from django.core.cache import cache
        cache.delete('bv_yer_per_sar')

        # First call calculates and sets cache
        rate1 = StoreSettings.get_exchange_rate()
        self.assertGreater(rate1, Decimal('0'))
        self.assertEqual(cache.get('bv_yer_per_sar'), rate1)

        # Modifying store settings should invalidate the cache
        self.settings.yer_per_sar = Decimal('600.00')
        self.settings.save()
        self.assertIsNone(cache.get('bv_yer_per_sar'))

        # Next call fetches new rate
        rate2 = StoreSettings.get_exchange_rate()
        self.assertEqual(rate2, Decimal('600.00'))

    def test_order_admin_whatsapp_btn_with_null_phone(self):
        """التحقق من مناعة OrderAdmin ضد الانهيار عند وجود طلبات بدون رقم هاتف"""
        from django.contrib.admin.sites import AdminSite
        from store.admin import OrderAdmin

        order_no_phone = Order.objects.create(
            order_number="BV-NOPHONE-01",
            customer_name="عميل بدون هاتف",
            customer_phone="",
            shipping_city="صنعاء",
            shipping_address="حي الجامعة",
            subtotal_yer=Decimal('10000'),
            total_yer=Decimal('12000'),
            total_sar=Decimal('22.6'),
            exchange_rate_applied=Decimal('530')
        )
        admin = OrderAdmin(Order, AdminSite())
        rendered_btn = admin.customer_whatsapp_btn(order_no_phone)
        self.assertEqual(rendered_btn, '—')

    def test_cart_add_invalid_quantity_handling(self):
        """التحقق من تعامل cart_add بمرونة مع المدخلات غير الرقمية والسالبة دون خطأ 500"""
        res_bad = self.client.post(reverse('store:cart_add'), {
            'product_id': self.product.id,
            'quantity': 'not_a_number'
        })
        self.assertEqual(res_bad.status_code, 200)

        res_neg = self.client.post(reverse('store:cart_add'), {
            'product_id': self.product.id,
            'quantity': -5
        })
        self.assertEqual(res_neg.status_code, 200)

    def test_service_worker_excludes_private_routes(self):
        """التحقق من أن Service Worker يستبعد المسارات الحساسة والسلة من الكاش"""
        res = self.client.get('/sw.js')
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertIn('/cart', content)
        self.assertIn('/checkout', content)
        self.assertIn('/account', content)
        self.assertIn('/order', content)

