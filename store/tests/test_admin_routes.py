from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from store.models import (
    StoreSettings, PaymentAccount, ShippingZone,
    Category, Product, Order, OrderItem, HeroBanner
)


class AdminRoutesAndOperationsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.settings = StoreSettings.get_settings()

        # إنشاء مستخدم عادي و مستخدم مدير لوحة التحكم
        self.regular_user = User.objects.create_user(
            username="normaluser",
            password="NormalPassword123!"
        )
        self.admin_user = User.objects.create_superuser(
            username="brandadmin",
            email="admin@brandveloura.com",
            password="AdminSecretPass2026!"
        )

        self.category = Category.objects.create(
            name_ar="عطور",
            name_en="Perfumes",
            slug="perfumes-test",
            category_type="perfumes"
        )
        self.zone = ShippingZone.objects.create(
            city_name="عدن",
            delivery_fee_yer=Decimal('3000'),
            estimated_delivery_time="24-48 ساعة"
        )

    def test_admin_access_control(self):
        """فحص أمان لوحة الإدارة: منع المستخدم العادي والسماح للمدير فقط"""
        # مستخدم غير مسجل
        res_anon = self.client.get('/admin/')
        self.assertEqual(res_anon.status_code, 302)

        # مستخدم عادي ليس لديه صلاحية staff
        self.client.force_login(self.regular_user)
        res_user = self.client.get('/admin/')
        self.assertEqual(res_user.status_code, 302)

        # المدير العام (Superuser)
        self.client.force_login(self.admin_user)
        res_admin = self.client.get('/admin/')
        self.assertEqual(res_admin.status_code, 200)

    def test_admin_category_add_and_list(self):
        """فحص إنشاء قسم جديد من لوحة الإدارة وعرض جدول الأقسام"""
        self.client.force_login(self.admin_user)

        # عرض جدول الأقسام
        list_res = self.client.get('/admin/store/category/')
        self.assertEqual(list_res.status_code, 200)

        # إضافة قسم جديد
        post_data = {
            'name_ar': 'ساعات سويسرية راقية',
            'name_en': 'Swiss Luxury Watches',
            'slug': 'swiss-luxury-watches',
            'category_type': 'watches',
            'description': 'أحدث الساعات',
            'display_order': '1',
            'is_featured': 'on',
            'is_active': 'on',
            '_save': 'Save'
        }
        add_res = self.client.post('/admin/store/category/add/', post_data, follow=True)
        self.assertEqual(add_res.status_code, 200)
        self.assertTrue(Category.objects.filter(slug='swiss-luxury-watches').exists())

    def test_admin_product_add_and_edit(self):
        """فحص إضافة منتج جديد مع تسعير الأصلي والماستر والمواصفات من لوحة الإدارة"""
        self.client.force_login(self.admin_user)

        # عرض جدول المنتجات
        list_res = self.client.get('/admin/store/product/')
        self.assertEqual(list_res.status_code, 200)

        # إضافة منتج جديد
        product_data = {
            'name_ar': 'عطر سوفاج ديور إكسير',
            'name_en': 'Sauvage Elixir Dior',
            'slug': 'sauvage-elixir-dior',
            'brand_name': 'Dior',
            'category': self.category.id,
            'price_yer': '65000',
            'compare_at_price_yer': '85000',
            'stock_quantity': '20',
            'sku': 'DIOR-ELIX-001',
            'has_grades': 'on',
            'price_original_yer': '90000',
            'price_master_yer': '45000',
            'is_featured': 'on',
            'is_active': 'on',
            'images-TOTAL_FORMS': '0',
            'images-INITIAL_FORMS': '0',
            'images-MIN_NUM_FORMS': '0',
            'images-MAX_NUM_FORMS': '1000',
            '_save': 'Save'
        }
        add_res = self.client.post('/admin/store/product/add/', product_data, follow=True)
        self.assertEqual(add_res.status_code, 200)

        created_prod = Product.objects.filter(slug='sauvage-elixir-dior').first()
        self.assertIsNotNone(created_prod)
        self.assertEqual(created_prod.price_master_yer, Decimal('45000'))
        self.assertTrue(created_prod.has_grades)

        # تعديل المنتج
        edit_url = f'/admin/store/product/{created_prod.id}/change/'
        product_data['stock_quantity'] = '35'
        edit_res = self.client.post(edit_url, product_data, follow=True)
        self.assertEqual(edit_res.status_code, 200)
        created_prod.refresh_from_db()
        self.assertEqual(created_prod.stock_quantity, 35)

    def test_admin_order_management(self):
        """فحص جدول الطلبات وتحديث حالة الطلب واعتماد الدفع"""
        self.client.force_login(self.admin_user)

        order = Order.objects.create(
            order_number="BV-2026-TESTADMIN",
            customer_name="فيصل الشامي",
            customer_phone="771239999",
            shipping_city="عدن",
            shipping_address="عدن، كريتر",
            subtotal_yer=Decimal('45000'),
            shipping_fee_yer=Decimal('3000'),
            total_yer=Decimal('48000'),
            total_sar=Decimal('120'),
            exchange_rate_applied=Decimal('400.00'),
            payment_currency_selected='YER',
            amount_due_in_payment_currency=Decimal('48000'),
            payment_method_name="تحويل بنكي",
            status='pending_verification'
        )

        # استعراض قائمة الطلبات في الإدارة
        list_res = self.client.get('/admin/store/order/')
        self.assertEqual(list_res.status_code, 200)
        self.assertContains(list_res, order.order_number)

        # استعراض صفحة تعديل الطلب
        change_url = f'/admin/store/order/{order.id}/change/'
        detail_res = self.client.get(change_url)
        self.assertEqual(detail_res.status_code, 200)

        # تحديث حالة الطلب إلى تم التحقق من الدفع
        order_post_data = {
            'customer_name': 'فيصل الشامي',
            'customer_phone': '771239999',
            'shipping_city': 'عدن',
            'shipping_address': 'عدن، كريتر',
            'subtotal_yer': '45000',
            'shipping_fee_yer': '3000',
            'gift_wrapping_fee_yer': '0',
            'total_yer': '48000',
            'total_sar': '120',
            'exchange_rate_applied': '400.00',
            'payment_currency_selected': 'YER',
            'amount_due_in_payment_currency': '48000',
            'payment_method_name': 'تحويل بنكي',
            'status': 'payment_verified',
            'admin_notes': 'تم التحقق من حوالة الكريمي بنجاح',
            'items-TOTAL_FORMS': '0',
            'items-INITIAL_FORMS': '0',
            'items-MIN_NUM_FORMS': '0',
            'items-MAX_NUM_FORMS': '1000',
            '_save': 'Save'
        }
        update_res = self.client.post(change_url, order_post_data, follow=True)
        self.assertEqual(update_res.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, 'payment_verified')

    def test_admin_payment_account_and_shipping_zone(self):
        """فحص إضافة حساب بنكي ومحافظ ومنطقة شحن جديدة من لوحة الإدارة"""
        self.client.force_login(self.admin_user)

        # إضافة حساب بنكي
        acc_data = {
            'provider_name': 'بنك التضامن الإسلامي',
            'account_holder_name': 'براند فيلورا للتجارة',
            'account_number': '5544332211',
            'currency': 'YER',
            'bank_country': 'YE',
            'display_order': '1',
            'is_active': 'on',
            '_save': 'Save'
        }
        res_acc = self.client.post('/admin/store/paymentaccount/add/', acc_data, follow=True)
        self.assertEqual(res_acc.status_code, 200)
        self.assertTrue(PaymentAccount.objects.filter(account_number='5544332211').exists())

        # إضافة منطقة شحن
        zone_data = {
            'city_name': 'حضرموت - المكلا',
            'delivery_fee_yer': '4500',
            'estimated_delivery_time': 'خلال 48 ساعة',
            'is_active': 'on',
            '_save': 'Save'
        }
        res_zone = self.client.post('/admin/store/shippingzone/add/', zone_data, follow=True)
        self.assertEqual(res_zone.status_code, 200)
        self.assertTrue(ShippingZone.objects.filter(city_name='حضرموت - المكلا').exists())

    def test_admin_store_settings_update(self):
        """فحص تحديث إعدادات المتجر وسعر الصرف من لوحة الإدارة"""
        self.client.force_login(self.admin_user)

        settings_obj = StoreSettings.get_settings()
        change_url = f'/admin/store/storesettings/{settings_obj.id}/change/'
        settings_data = {
            'store_name': 'Brand Veloura Boutique',
            'store_tagline': 'بوتيك الفخامة الأول للعطور والساعات ومستلزمات التجميل',
            'yer_per_sar': '410.00',
            'contact_phone': '+967 770 000 000',
            'contact_whatsapp': '967770000000',
            'contact_instagram': 'brandveloura',
            'announcement_text': 'عروض تشكيلة 2026 متوفرة الآن',
            'is_announcement_active': 'on',
            '_save': 'Save'
        }
        res = self.client.post(change_url, settings_data, follow=True)
        self.assertEqual(res.status_code, 200)
        settings_obj.refresh_from_db()
        self.assertEqual(settings_obj.yer_per_sar, Decimal('410.00'))
        self.assertEqual(settings_obj.store_name, 'Brand Veloura Boutique')

    def test_admin_hero_banner_add(self):
        """فحص إضافة بانر ترويجي للرئيسية من لوحة الإدارة"""
        self.client.force_login(self.admin_user)

        banner_data = {
            'title': 'تشكيلة العطور الخاصة 2026',
            'subtitle': 'إصدارات أصلية وماستر كواليتي',
            'tag_badge': 'تشكيلة حصرية 2026',
            'image_url_fallback': 'https://example.com/banner.jpg',
            'button_text': 'تصفح العطور',
            'button_link': '/perfumes/',
            'display_order': '1',
            'is_active': 'on',
            '_save': 'Save'
        }
        res = self.client.post('/admin/store/herobanner/add/', banner_data, follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(HeroBanner.objects.filter(title='تشكيلة العطور الخاصة 2026').exists())

    def test_admin_dynamic_url_and_honeypot(self):
        """التحقق من أن مسارات لوحة الإدارة تستخدم reverse('admin:index') ديناميكياً"""
        admin_index_url = reverse('admin:index')
        self.client.force_login(self.admin_user)
        res = self.client.get(admin_index_url)
        self.assertEqual(res.status_code, 200)
