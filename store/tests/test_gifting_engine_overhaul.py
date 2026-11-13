import math
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

        # بوليصة المستلم للإدارة
        res_slip = self.client.get(reverse('store:admin_print_recipient_slip', kwargs={'order_id': order.id}))
        self.assertEqual(res_slip.status_code, 200)
        slip_content = res_slip.content.decode('utf-8')
        self.assertIn('بوليصة تسليم باقة إهداء فاخرة', slip_content)
        self.assertIn('ريم خالد', slip_content)

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
