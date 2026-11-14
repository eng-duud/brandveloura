import math
import json
from datetime import date, timedelta
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from store.models import (
    Category, Product, GiftBundle, GiftBundleItem, 
    Order, OrderItem, PaymentAccount, ShippingZone, StoreSettings
)


class GiftingEngineOverhaulTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.settings = StoreSettings.get_settings()
        self.settings.yer_per_sar = Decimal('530.00')
        self.settings.gift_wrapping_fee_yer = Decimal('2000.00')
        self.settings.save()

        # Admin user
        self.staff_user = User.objects.create_superuser(
            username='admin_staff',
            email='admin@veloura.com',
            password='Password123!'
        )

        # Regular user
        self.customer_user = User.objects.create_user(
            username='customer1',
            email='customer@veloura.com',
            password='Password123!'
        )

        # Shipping & Payment
        self.zone = ShippingZone.objects.create(city_name='صنعاء', delivery_fee_yer=Decimal('1500.00'), is_active=True)
        self.payment = PaymentAccount.objects.create(
            provider_name='الكريمي',
            account_number='123456',
            account_holder_name='براند فيلورا',
            currency='YER',
            is_active=True
        )

        # Categories & Products
        self.cat_perfumes = Category.objects.create(name_ar='العطور الملكية', category_type='perfumes', slug='perfumes')
        self.cat_watches = Category.objects.create(name_ar='ساعات فاخرة', category_type='watches', slug='watches')

        self.perfume1 = Product.objects.create(
            name_ar='عطر سوفاج ديور',
            category=self.cat_perfumes,
            price_yer=Decimal('45000.00'),
            has_grades=True,
            price_original_yer=Decimal('50000.00'),
            price_master_yer=Decimal('25000.00'),
            stock_quantity=10,
            is_active=True
        )

        self.watch1 = Product.objects.create(
            name_ar='ساعة كارتير بالون بلو',
            category=self.cat_watches,
            price_yer=Decimal('35000.00'),
            stock_quantity=10,
            is_active=True
        )

        # Gift Bundle
        self.bundle = GiftBundle.objects.create(
            title_ar='باقة الفخامة الملكية',
            price_yer=Decimal('70000.00'),
            includes_luxury_packaging=True,
            includes_gift_card=True,
            is_active=True
        )
        GiftBundleItem.objects.create(bundle=self.bundle, product=self.perfume1, grade='master', quantity=1)
        GiftBundleItem.objects.create(bundle=self.bundle, product=self.watch1, grade='standard', quantity=1)

    def test_bundle_stock_restoration_on_order_cancellation(self):
        """التحقق من أن مخزون محتويات الباقة يُخصم عند الطلب ويُسترجع 100% عند إلغاء الطلب ويُخصم عند إعادة التفعيل"""
        self.client.login(username='customer1', password='Password123!')
        
        # 1. الطلب المباشر للباقة
        response = self.client.get(reverse('store:gift_bundle_order_direct', kwargs={'slug': self.bundle.slug}))
        self.assertEqual(response.status_code, 302)

        # 2. إتمام الطلب في صفحة checkout
        checkout_data = {
            'order_type': 'gift',
            'is_gift': 'true',
            'customer_name': 'أحمد العولقي',
            'customer_phone': '777111222',
            'shipping_city': self.zone.id,
            'shipping_address': 'حدة - جوار البنك المركزي',
            'payment_method': self.payment.id,
            'payment_currency_selected': 'YER',
            'recipient_name': 'سارة محمد',
            'recipient_phone': '777333444',
            'gift_card_sender': 'أحمد',
            'gift_card_recipient': 'سارة',
            'gift_card_message': 'ألف مبروك التخرج ومنها للأعلى يا رب',
            'is_luxury_gift_wrapping': 'true',
            'hide_invoice_prices': 'true',
        }
        res_post = self.client.post(reverse('store:checkout'), checkout_data)
        self.assertEqual(res_post.status_code, 302)

        # فحص المخزون بعد إتمام الطلب (يجب أن ينقص بمقدار 1)
        self.perfume1.refresh_from_db()
        self.watch1.refresh_from_db()
        self.assertEqual(self.perfume1.stock_quantity, 9)
        self.assertEqual(self.watch1.stock_quantity, 9)

        # التحقق من أن OrderItem مرتبط بالباقة
        order = Order.objects.latest('created_at')
        bundle_item = order.items.filter(bundle=self.bundle).first()
        self.assertIsNotNone(bundle_item)
        self.assertEqual(bundle_item.bundle, self.bundle)

        # 3. محاكاة إلغاء الطلب عبر الإدارة -> يجب أن تعود كميات الباقة للمخزون
        order.status = 'cancelled'
        order.save()

        self.perfume1.refresh_from_db()
        self.watch1.refresh_from_db()
        self.assertEqual(self.perfume1.stock_quantity, 10, "يجب استرجاع مخزون العطر داخل الباقة إلى 10 بعد الإلغاء")
        self.assertEqual(self.watch1.stock_quantity, 10, "يجب استرجاع مخزون الساعة داخل الباقة إلى 10 بعد الإلغاء")
        order.refresh_from_db()
        self.assertFalse(order.stock_deducted)

        # 4. محاكاة إعادة تفعيل الطلب -> يجب خصم كميات الباقة مجدداً
        order.status = 'processing'
        order.save()

        self.perfume1.refresh_from_db()
        self.watch1.refresh_from_db()
        self.assertEqual(self.perfume1.stock_quantity, 9, "يجب إعادة خصم مخزون العطر داخل الباقة إلى 9 بعد إعادة التفعيل")
        self.assertEqual(self.watch1.stock_quantity, 9, "يجب إعادة خصم مخزون الساعة داخل الباقة إلى 9 بعد إعادة التفعيل")
        order.refresh_from_db()
        self.assertTrue(order.stock_deducted)

    def test_gift_slip_view_price_masking(self):
        """التحقق من أن صفحة بوليصة المستلم /gift-slip/ خالية تماماً من الأرقام والأسعار المالية"""
        order = Order.objects.create(
            order_number='BV-GIFTTEST1',
            customer_name='فؤاد محمد',
            customer_phone='777999888',
            shipping_city='عدن',
            shipping_address='المنصورة - ريمي',
            subtotal_yer=Decimal('50000.00'),
            total_yer=Decimal('53500.00'),
            total_sar=Decimal('101.00'),
            exchange_rate_applied=Decimal('530.00'),
            is_gift=True,
            recipient_name='أم أحمد',
            recipient_phone='777555444',
            gift_card_sender='فؤاد',
            gift_card_recipient='الغالية أم أحمد',
            gift_card_message='كل عام وأنتِ تاج راسي وجنة قلبي',
            is_luxury_gift_wrapping=True,
            hide_invoice_prices=True
        )
        OrderItem.objects.create(
            order=order,
            product=self.perfume1,
            product_name=self.perfume1.name_ar,
            variant_info='أصلي 100%',
            unit_price_yer=Decimal('50000.00'),
            quantity=1,
            total_price_yer=Decimal('50000.00'),
        )

        response = self.client.get(reverse('store:gift_slip', kwargs={'order_number': order.order_number}))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        # يجب أن تتضمن أسماء الأشخاص ورسالة الإهداء
        self.assertIn('أم أحمد', content)
        self.assertIn('فؤاد', content)
        self.assertIn('كل عام وأنتِ تاج راسي', content)
        self.assertIn('عطر سوفاج ديور', content)

        # التحقق من هوية المتجر (الشعار، الخط الملكي، رابط الموقع)
        self.assertIn('brandveloura.com', content)
        self.assertIn('font-brand-logo', content)
        self.assertIn('logo.', content)
        self.assertIn('.webp', content)

        # يجب ألا تحتوي على أسعار أو أرقام مبالغ
        self.assertNotIn('53,500', content)
        self.assertNotIn('50,000', content)
        self.assertNotIn('101 ر.س', content)
        self.assertNotIn('المجموع الفرعي', content)
        self.assertNotIn('رسوم الشحن', content)

    def test_admin_print_gift_card_and_slip_views(self):
        """التحقق من عمل صفحات طباعة كروت الإهداء وبوالص التسليم الخاصة بالإدارة"""
        order = Order.objects.create(
            order_number='BV-PRINTCARD1',
            customer_name='طارق العمري',
            customer_phone='777444111',
            shipping_city='صنعاء',
            shipping_address='شارع بغداد',
            subtotal_yer=Decimal('40000.00'),
            total_yer=Decimal('42000.00'),
            total_sar=Decimal('80.00'),
            exchange_rate_applied=Decimal('530.00'),
            is_gift=True,
            recipient_name='ريم خالد',
            recipient_phone='777222333',
            gift_card_sender='طارق',
            gift_card_recipient='ريم',
            gift_card_message='إلى أجمل إنسانة في الكون، دمتِ لي نوراً وسعادة.',
            is_luxury_gift_wrapping=True
        )

        # 1. كزائر غير مسجل: يجب منعه
        res_anon = self.client.get(reverse('store:admin_print_gift_card', kwargs={'order_id': order.id}))
        self.assertEqual(res_anon.status_code, 302)

        # 2. كمسؤول إدارة: يجب فتح شاشة الطباعة بنجاح
        self.client.login(username='admin_staff', password='Password123!')
        res_card = self.client.get(reverse('store:admin_print_gift_card', kwargs={'order_id': order.id}))
        self.assertEqual(res_card.status_code, 200)
        card_content = res_card.content.decode('utf-8')
        self.assertIn('ريم', card_content)
        self.assertIn('طارق', card_content)
        self.assertIn('إلى أجمل إنسانة في الكون', card_content)
        self.assertIn('brandveloura.com', card_content)
        self.assertIn('font-brand-logo', card_content)
        self.assertIn('logo.', card_content)
        self.assertIn('.webp', card_content)

        # بوليصة وسند المستلم للإدارة
        res_slip = self.client.get(reverse('store:admin_print_recipient_slip', kwargs={'order_id': order.id}))
        self.assertEqual(res_slip.status_code, 200)
        slip_content = res_slip.content.decode('utf-8')
        self.assertIn('بوليصة تسليم باقة إهداء فاخرة', slip_content)
        self.assertIn('ريم خالد', slip_content)
        self.assertIn('brandveloura.com', slip_content)
        self.assertIn('font-brand-logo', slip_content)
        self.assertIn('logo.', slip_content)
        self.assertIn('.webp', slip_content)

    def test_past_preferred_delivery_date_correction(self):
        """التحقق من أن تاريخ التسليم في الماضي لا يسبب أخطاء ويتم تعديله تلقائياً لأقرب تاريخ متاح"""
        self.client.login(username='customer1', password='Password123!')
        # إضافة عطر للسلة
        self.client.post(reverse('store:cart_add'), {
            'product_id': self.perfume1.id,
            'quantity': 1,
            'grade': 'original'
        })

        past_date = (date.today() - timedelta(days=5)).strftime('%Y-%m-%d')
        checkout_data = {
            'order_type': 'gift',
            'is_gift': 'true',
            'customer_name': 'عمر سالم',
            'customer_phone': '777000111',
            'shipping_city': self.zone.id,
            'shipping_address': 'حدة',
            'payment_method': self.payment.id,
            'payment_currency_selected': 'YER',
            'recipient_name': 'صالح خالد',
            'recipient_phone': '777999000',
            'preferred_delivery_date': past_date,
        }
        res = self.client.post(reverse('store:checkout'), checkout_data)
        self.assertEqual(res.status_code, 302)

        order = Order.objects.latest('created_at')
        self.assertIsNotNone(order.preferred_delivery_date)
        self.assertGreaterEqual(order.preferred_delivery_date, date.today(), "تاريخ التسليم يجب ألا يكون في الماضي")

    def test_order_invoice_view_and_admin_print(self):
        """التحقق من عمل صفحة الفاتورة الرسمية A4 للعميل ولإدارة المتجر"""
        order = Order.objects.create(
            order_number='BV-INVOICE-TEST1',
            customer_name='سامي منصور',
            customer_phone='777112233',
            shipping_city='صنعاء',
            shipping_address='شارع بغداد',
            subtotal_yer=Decimal('45000.00'),
            total_yer=Decimal('48000.00'),
            total_sar=Decimal('90.50'),
            exchange_rate_applied=Decimal('530.00'),
            is_gift=False,
        )
        OrderItem.objects.create(
            order=order,
            product=self.perfume1,
            product_name='عطر رجالي ملكي',
            variant_info='أصلي 100%',
            unit_price_yer=Decimal('45000.00'),
            quantity=1,
            total_price_yer=Decimal('45000.00'),
        )

        # 1. التحقق من إلغاء الرابط العام للفاتورة للحماية من التخمين والحقن (404)
        res_public = self.client.get(f'/order/{order.order_number}/invoice/')
        self.assertEqual(res_public.status_code, 404, "يجب ألا يوجد مسار عام للفاتورة")

        # 2. طباعة الفاتورة للإدارة عبر لوحة التحكم
        self.client.login(username='admin_staff', password='Password123!')
        res_admin = self.client.get(reverse('store:admin_print_invoice', kwargs={'order_id': order.id}))
        self.assertEqual(res_admin.status_code, 200)
        admin_content = res_admin.content.decode('utf-8')
        self.assertIn('فاتورة مبيعات', admin_content)
        self.assertIn('Brand Veloura', admin_content)
        self.assertIn('48000', admin_content)
        self.assertIn('سامي منصور', admin_content)
        self.assertNotIn('بوتيك', admin_content, "يجب ألا تظهر كلمة بوتيك إطلاقاً في الفاتورة")

    def test_save_order_invoice_image_api(self):
        """التحقق من endpoint حفظ صورة الفاتورة المولدة كـ PNG وربطها بالطلب"""
        order = Order.objects.create(
            order_number='BV-INVOICE-IMG1',
            customer_name='ماجد علي',
            customer_phone='777223344',
            shipping_city='تعز',
            shipping_address='صالة',
            subtotal_yer=Decimal('30000.00'),
            total_yer=Decimal('30000.00'),
            total_sar=Decimal('56.60'),
            exchange_rate_applied=Decimal('530.00'),
        )

        sample_b64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="

        res = self.client.post(
            reverse('store:save_order_invoice_image', kwargs={'order_number': order.order_number}),
            data=json.dumps({'image_data': sample_b64}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get('status'), 'ok')

        order.refresh_from_db()
        self.assertTrue(bool(order.invoice_image))

    def test_gift_slip_celebration_animation_and_share_card(self):
        """التحقق من وجود كانفاس الاحتفال الملكي في صفحة المستلم وبطاقة المشاركة في صفحة النجاح"""
        order = Order.objects.create(
            order_number='BV-CELEBRATION1',
            customer_name='مرسل الهدية',
            customer_phone='777334455',
            shipping_city='حضرموت',
            shipping_address='المكلا',
            subtotal_yer=Decimal('25000.00'),
            total_yer=Decimal('25000.00'),
            total_sar=Decimal('47.00'),
            exchange_rate_applied=Decimal('530.00'),
            is_gift=True,
            recipient_name='سعيد بن مبارك',
            recipient_phone='777889900',
            gift_card_recipient='سعيد',
            gift_card_message='مبروك يا بطل'
        )

        # فحص صفحة المستلم
        res_slip = self.client.get(reverse('store:gift_slip', kwargs={'order_number': order.order_number}))
        self.assertEqual(res_slip.status_code, 200)
        slip_html = res_slip.content.decode('utf-8')
        self.assertIn('royal-celebration-canvas', slip_html)
        self.assertIn('startRoyalCelebration', slip_html)

        # فحص صفحة نجاح الطلب
        res_success = self.client.get(reverse('store:order_success', kwargs={'order_number': order.order_number}))
        self.assertEqual(res_success.status_code, 200)
        success_html = res_success.content.decode('utf-8')
        self.assertIn('shareGiftCard', success_html)
        self.assertIn('سعيد', success_html)
        self.assertIn('فاتورة الشراء الرسمية', success_html)
        self.assertNotIn('بوتيك', slip_html, "يجب عدم وجود كلمة بوتيك في صفحة المستلم")
        self.assertNotIn('بوتيك', success_html, "يجب عدم وجود كلمة بوتيك في صفحة النجاح")

    def test_gift_builder_grade_filter_controls_and_rendering(self):
        """التحقق من أن فلتر الماستر والأصلي في صانع الهدايا متوفر ويعمل بدقة مع أزرار الفلترة وبيانات البطاقات"""
        res_default = self.client.get(reverse('store:gift_builder'))
        self.assertEqual(res_default.status_code, 200)
        html_default = res_default.content.decode('utf-8')
        
        # التأكد من وجود أزرار الفلترة الثلاثة
        self.assertIn('global-grade-btn-all', html_default)
        self.assertIn('global-grade-btn-original', html_default)
        self.assertIn('global-grade-btn-master', html_default)
        self.assertIn('كل الجودات', html_default)
        self.assertIn('أصلي 100%', html_default)
        self.assertIn('ماستر طبق الأصل', html_default)
        self.assertIn('data-has-master="true"', html_default)
        self.assertIn('data-has-original="true"', html_default)
        self.assertIn('currentPerfumeGrade', html_default)

        # فحص تمرير معيار grade عبر الرابط
        res_master = self.client.get(reverse('store:gift_builder') + '?grade=master')
        self.assertEqual(res_master.status_code, 200)
        html_master = res_master.content.decode('utf-8')
        self.assertIn('value="master"', html_master)

        res_orig = self.client.get(reverse('store:gift_builder') + '?grade=original')
        self.assertEqual(res_orig.status_code, 200)
        html_orig = res_orig.content.decode('utf-8')
        self.assertIn('value="original"', html_orig)

