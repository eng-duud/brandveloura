from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from store.models import (
    StoreSettings, PaymentAccount, ShippingZone,
    Category, Product, ProductImage, Order, OrderItem,
    HeroBanner, UserProfile
)


class ModelLogicTests(TestCase):
    def setUp(self):
        self.settings = StoreSettings.get_settings()
        self.category = Category.objects.create(
            name_ar="عطور النخبة",
            name_en="Elite Perfumes",
            slug="elite-perfumes",
            category_type="perfumes"
        )
        self.user = User.objects.create_user(
            username="testshopper",
            email="shopper@test.com",
            password="securepassword123",
            first_name="سامي",
            last_name="المتوكل"
        )

    def test_store_settings_singleton(self):
        """التحقق من أن إعدادات المتجر تطبق نمط Singleton وسعر الصرف سليم"""
        s1 = StoreSettings.get_settings()
        s2 = StoreSettings.get_settings()
        self.assertEqual(s1.pk, s2.pk)
        self.assertGreater(s1.yer_per_sar, 0)

    def test_category_creation_and_str(self):
        """التحقق من إنشاء الأقسام ومطابقة نص التسمية"""
        self.assertEqual(str(self.category), "عطور النخبة")
        self.assertEqual(self.category.category_type, "perfumes")

    def test_product_price_and_grades(self):
        """فحص حساب السعر بالريال السعودي وسياسة العطور (أصلي وماستر)"""
        product = Product.objects.create(
            category=self.category,
            name_ar="عطر رويال سابل",
            name_en="Royal Sable",
            brand_name="Veloura House",
            price_yer=Decimal('50000'),
            has_grades=True,
            price_original_yer=Decimal('80000'),
            price_master_yer=Decimal('40000'),
            stock_quantity=10,
            specifications={
                "concentration": "Extrait de Parfum",
                "gender": "unisex",
                "top_notes": ["عنبر", "توت"]
            }
        )
        # التحقق من أن السعر بالسعودي يحسب تلقائياً من اليمني
        self.assertGreater(product.price_sar, Decimal('0'))
        self.assertGreater(product.price_original_sar, Decimal('0'))
        self.assertGreater(product.price_master_sar, Decimal('0'))
        self.assertTrue(product.has_grades)
        self.assertEqual(product.specifications.get("concentration"), "Extrait de Parfum")

    def test_order_and_items_creation(self):
        """فحص إنشاء الطلب وترقيم الفاتورة BV-2026 وحساب الإجماليات والهدية"""
        shipping = ShippingZone.objects.create(
            city_name="صنعاء",
            delivery_fee_yer=Decimal('2000'),
            estimated_delivery_time="خلال 24 ساعة"
        )
        order = Order.objects.create(
            order_number="BV-2026-TEST01",
            user=self.user,
            customer_name="سامي المتوكل",
            customer_phone="771234567",
            shipping_city=shipping.city_name,
            shipping_address="شارع حدة، برج النعمان",
            subtotal_yer=Decimal('50000'),
            shipping_fee_yer=Decimal('2000'),
            total_yer=Decimal('52000'),
            total_sar=Decimal('130'),
            exchange_rate_applied=Decimal('530'),
            payment_currency_selected='YER',
            is_gift=True,
            recipient_name="صديق سامي",
            recipient_phone="779998888",
            gift_card_message="ألف مبروك التخرج يا غالي",
            status='pending_verification'
        )
        self.assertTrue(order.order_number.startswith("BV-"))
        self.assertTrue(order.is_gift)
        self.assertEqual(order.status, 'pending_verification')

        # إنشاء عنصر ضمن الطلب
        item = OrderItem.objects.create(
            order=order,
            product_name="عطر رويال سابل",
            variant_info="درجة ماستر (طبق الأصل)",
            quantity=1,
            unit_price_yer=Decimal('50000'),
            total_price_yer=Decimal('50000')
        )
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(item.product_name, "عطر رويال سابل")

    def test_user_profile_link(self):
        """فحص ارتباط الملف الشخصي بحساب المستخدم والبيانات الافتراضية"""
        profile, created = UserProfile.objects.get_or_create(user=self.user)
        profile.phone = "771234567"
        profile.shipping_address = "صنعاء - حدة"
        profile.save()
        self.assertEqual(profile.user.username, "testshopper")
        self.assertEqual(profile.phone, "771234567")
        self.assertEqual(profile.shipping_address, "صنعاء - حدة")
