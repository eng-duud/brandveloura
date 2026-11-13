from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User

from store.models import (
    StoreSettings, Category, Brand, Product, 
    GiftBundle, GiftBundleItem, Order, OrderItem
)


class GiftBundlesAndWizardTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.settings = StoreSettings.get_settings()
        self.settings.store_name = 'Brand Veloura'
        self.settings.yer_per_sar = Decimal('530.00')
        self.settings.gift_wrapping_fee_yer = Decimal('2500.00')
        self.settings.save()

        # Categories
        self.cat_perfumes = Category.objects.create(
            name_ar='عطور رجالية', name_en='Men Perfumes', slug='men-perfumes', category_type='perfumes', is_active=True
        )
        self.cat_watches = Category.objects.create(
            name_ar='ساعات فاخرة', name_en='Luxury Watches', slug='watches', category_type='watches', is_active=True
        )

        # Brand
        self.brand = Brand.objects.create(name_ar='ديور', name_en='Dior', slug='dior', is_active=True)

        # Products
        self.perfume = Product.objects.create(
            category=self.cat_perfumes,
            brand=self.brand,
            name_ar='عطر سوفاج ديور',
            name_en='Sauvage Dior',
            slug='sauvage-dior',
            price_yer=Decimal('50000.00'),
            price_original_yer=Decimal('50000.00'),
            price_master_yer=Decimal('35000.00'),
            has_grades=True,
            stock_quantity=10,
            is_active=True,
            is_featured=True
        )

        self.watch = Product.objects.create(
            category=self.cat_watches,
            brand=self.brand,
            name_ar='ساعة كلاسيكية راقية',
            name_en='Classic Luxury Watch',
            slug='classic-watch',
            price_yer=Decimal('30000.00'),
            stock_quantity=5,
            is_active=True
        )

        # Ready Gift Bundle
        self.bundle = GiftBundle.objects.create(
            title_ar='باقة الفخامة الملكية',
            title_en='Royal Luxury Bundle',
            slug='royal-luxury-bundle',
            subtitle='هدية مثالية للمناسبات الخاصة',
            description='تحتوي على عطر سوفاج ديور وساعة راقية مع التغليف الملكي والكرت مجاناً.',
            price_yer=Decimal('75000.00'),
            compare_at_price_yer=Decimal('85000.00'),
            includes_luxury_packaging=True,
            includes_gift_card=True,
            is_active=True,
            is_featured=True,
            display_order=1
        )

        # Bundle items
        self.item1 = GiftBundleItem.objects.create(
            bundle=self.bundle,
            product=self.perfume,
            grade='original',
            quantity=1,
            custom_note='100 مل أصلي وكالة',
            display_order=1
        )
        self.item2 = GiftBundleItem.objects.create(
            bundle=self.bundle,
            product=self.watch,
            grade='standard',
            quantity=1,
            custom_note='ساعة مع علبة مخملية',
            display_order=2
        )

    def test_gift_bundle_properties(self):
        """التحقق من صحة دوال الحساب والخصائص في باقة الهدايا وتقريب السعر السعودي للأعلى كرقم صحيح"""
        import math
        self.assertEqual(self.bundle.items_count, 2)
        self.assertEqual(self.bundle.discount_percentage, 12)  # (85000-75000)/85000 = ~11.76% -> 12%
        expected_sar = int(math.ceil(Decimal('75000.00') / Decimal('530.00')))
        self.assertEqual(self.bundle.price_sar, expected_sar)
        self.assertIsInstance(self.bundle.price_sar, int)
        self.assertEqual(str(self.bundle), 'باقة الفخامة الملكية')
        self.assertIn('عطر سوفاج ديور', str(self.item1))

    def test_sar_prices_rounded_up_to_whole_integers(self):
        """التحقق من أن كافة أسعار الريال السعودي أرقام طبيعية مقربة للأعلى بدون كسور"""
        import math
        # سعر العطر: 50,000 / 530 = 94.3396 -> تقريب للأعلى = 95
        self.assertEqual(self.perfume.price_sar, 95)
        self.assertIsInstance(self.perfume.price_sar, int)

        # سعر الماستر: 35,000 / 530 = 66.0377 -> تقريب للأعلى = 67
        self.assertEqual(self.perfume.price_master_sar, 67)
        self.assertIsInstance(self.perfume.price_master_sar, int)

    def test_default_category_controlled_from_store_settings_only(self):
        """التحقق من أن القسم الافتراضي يتحدد من مكان واحد فقط (إعدادات المتجر)"""
        # تعيين قسم الساعات كقسم افتراضي من إعدادات المتجر
        self.settings.default_category = self.cat_watches
        self.settings.save()

        # عند فتح صفحة الأقسام بدون معلمات، يجب أن يفتح قسم الساعات تلقائياً
        response = self.client.get(reverse('store:product_list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['main_category'], self.cat_watches)

        # التحقق من أن CategoryAdmin لا يعرض is_default في حقول التعديل لمنع التضارب
        from store.admin import CategoryAdmin
        admin_instance = CategoryAdmin(Category, None)
        fieldset_fields = []
        for name, opts in admin_instance.fieldsets:
            for f in opts.get('fields', ()):
                if isinstance(f, (list, tuple)):
                    fieldset_fields.extend(f)
                else:
                    fieldset_fields.append(f)
        self.assertNotIn('is_default', fieldset_fields)
        self.assertNotIn('is_default', admin_instance.list_display)
        self.assertNotIn('is_default', admin_instance.list_editable)

    def test_homepage_sliders_limited_to_8_items(self):
        """التحقق من أن جميع أشرطة الصفحة الرئيسية مقيدة بحد أقصى 8 عناصر"""
        # إضافة 10 منتجات عطور إضافية
        for i in range(10):
            Product.objects.create(
                category=self.cat_perfumes,
                brand=self.brand,
                name_ar=f'عطر إضافي {i}',
                slug=f'extra-perfume-{i}',
                price_yer=Decimal('40000.00'),
                stock_quantity=5,
                is_active=True,
                is_featured=True
            )

        response = self.client.get(reverse('store:home'))
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(response.context['featured_products']), 8)
        self.assertLessEqual(len(response.context['perfume_products']), 8)

    def test_home_view_includes_ready_gift_bundles(self):
        """التحقق من أن الصفحة الرئيسية تعرض الباقات الجاهزة المنسقة"""
        response = self.client.get(reverse('store:home'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('gift_bundles', response.context)
        self.assertContains(response, 'باقة الفخامة الملكية')

    def test_gift_bundle_detail_view(self):
        """التحقق من صفحة تفاصيل باقة الهدية الجاهزة وعرض محتوياتها وأزرار الطلب والتخصيص"""
        url = reverse('store:gift_bundle_detail', kwargs={'slug': self.bundle.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'باقة الفخامة الملكية')
        self.assertContains(response, 'عطر سوفاج ديور')
        self.assertContains(response, 'ساعة كلاسيكية راقية')
        self.assertContains(response, 'طلب الباقة مباشرة كهدية')
        self.assertContains(response, 'تعديل وتخصيص الباقة')

    def test_gift_bundle_order_direct(self):
        """التحقق من الشراء المباشر للباقة وتوجيه العميل إلى صفحة إتمام الطلب مباشرة"""
        url = reverse('store:gift_bundle_order_direct', kwargs={'slug': self.bundle.slug})
        response = self.client.post(url, {
            'recipient_name': 'سعيد اليماني',
            'recipient_phone': '771234567',
            'gift_card_sender': 'أحمد علي',
            'gift_card_message': 'ألف مبروك التخرج يا غالي!',
        })
        self.assertRedirects(response, reverse('store:checkout'))
        
        # التأكد من حفظ السلة وبيانات الإهداء في الجلسة
        session = self.client.session
        cart = session.get('cart', {})
        b_key = f"bundle_{self.bundle.id}"
        self.assertIn(b_key, cart)
        self.assertEqual(cart[b_key]['name'], 'باقة الفخامة الملكية')
        self.assertEqual(cart[b_key]['price_yer'], 75000.0)

        gift_data = session.get('gift_data', {})
        self.assertTrue(gift_data.get('is_gift'))
        self.assertEqual(gift_data.get('recipient_name'), 'سعيد اليماني')
        self.assertEqual(gift_data.get('gift_card_sender'), 'أحمد علي')
        self.assertTrue(gift_data.get('is_luxury_gift_wrapping'))

    def test_gift_builder_get_with_preselected_bundle(self):
        """التحقق من فتح صانع الهدايا مع باقة محددة مسبقاً وتمرير عناصرها"""
        url = f"{reverse('store:gift_builder')}?bundle_slug={self.bundle.slug}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'صانع الهدية الملكي')
        self.assertContains(response, 'باقة الفخامة الملكية')
        self.assertIn(self.perfume.id, response.context['preselected_perfume_ids'])
        self.assertIn(self.watch.id, response.context['preselected_accessory_ids'])

    def test_gift_builder_post_custom_box(self):
        """التحقق من إرسال نموذج صانع الهدايا المخصص مع عدة عطور وملحقات والتوجيه للدفع"""
        url = reverse('store:gift_builder')
        post_data = {
            'perfume_id': [str(self.perfume.id)],
            'grade_' + str(self.perfume.id): 'master',
            'accessory_id': [str(self.watch.id)],
            'recipient_name': 'عمر خالد',
            'recipient_phone': '778899000',
            'gift_card_sender': 'صديقك المخلص',
            'gift_card_message': 'هدية متواضعة لأغلى الناس',
            'is_luxury_gift_wrapping': 'true',
        }
        response = self.client.post(url, post_data)
        self.assertRedirects(response, reverse('store:checkout'))

        session = self.client.session
        cart = session.get('cart', {})
        p_key = f"{self.perfume.id}_master_gift"
        a_key = f"{self.watch.id}_acc_gift"
        self.assertIn(p_key, cart)
        self.assertIn(a_key, cart)
        self.assertEqual(cart[p_key]['price_yer'], 35000.0)  # master price

        gift_data = session.get('gift_data', {})
        self.assertTrue(gift_data.get('is_gift'))
        self.assertEqual(gift_data.get('recipient_name'), 'عمر خالد')
        self.assertTrue(gift_data.get('is_luxury_gift_wrapping'))

    def test_gift_calculate_live_htmx(self):
        """التحقق من حساب تكلفة الباقة وتحديث المعاينة المباشرة عبر HTMX"""
        url = reverse('store:gift_calculate')
        post_data = {
            'perfume_id': [str(self.perfume.id)],
            'grade_' + str(self.perfume.id): 'original',
            'accessory_id': [str(self.watch.id)],
            'is_luxury_gift_wrapping': 'true',
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 200)
        # 50,000 (عطر أصلي) + 30,000 (ساعة) + 2,500 (تغليف) = 82,500 ر.ي
        self.assertContains(response, '82500')

    def test_floating_gift_cta_rendered_on_home_and_hidden_on_gifting(self):
        """التحقق من ظهور الزر العائم في الرئيسية واختفائه تلقائياً في صفحات الإهداء لمنع التشتيت"""
        # 1. الرئيسية: يظهر الزر العائم
        home_resp = self.client.get(reverse('store:home'))
        self.assertContains(home_resp, 'id="floating-gift-cta"')
        self.assertContains(home_resp, 'bottom-20')

        # 2. صفحة صانع الإهداء: يختفي الزر العائم تلقائياً
        gifting_resp = self.client.get(reverse('store:gift_builder'))
        self.assertNotContains(gifting_resp, 'id="floating-gift-cta"')

    def test_admin_gift_bundle_quick_product_picker_and_sync(self):
        """التحقق من ظهور مربعات التحديد السريعة في لوحة الإدارة ومزامنتها التلقائية مع محتويات الباقة"""
        admin_user = User.objects.create_superuser('testsuperadmin', 'admin@brandveloura.com', 'pass1234')
        self.client.force_login(admin_user)

        # 1. فحص صفحة إضافة باقة جديدة: ظهور مربعات التحديد والقائمة المنسدلة
        add_url = reverse('admin:store_giftbundle_add')
        resp = self.client.get(add_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="bundle_products"')
        self.assertContains(resp, self.perfume.name_ar)
        self.assertContains(resp, self.watch.name_ar)

        # 2. حفظ باقة جديدة مع تحديد المنتجات عبر bundle_products
        post_data = {
            'title_ar': 'باقة الزهور الذهبية',
            'slug': 'golden-flowers-bundle',
            'price_yer': '65000.00',
            'display_order': '0',
            'bundle_products': [str(self.perfume.id), str(self.watch.id)],
            'items-TOTAL_FORMS': '0',
            'items-INITIAL_FORMS': '0',
            'items-MIN_NUM_FORMS': '0',
            'items-MAX_NUM_FORMS': '1000',
        }
        resp_post = self.client.post(add_url, post_data)
        self.assertEqual(resp_post.status_code, 302)

        created_bundle = GiftBundle.objects.filter(slug='golden-flowers-bundle').first()
        self.assertIsNotNone(created_bundle)
        self.assertEqual(created_bundle.items.count(), 2)
        included_product_ids = set(created_bundle.items.values_list('product_id', flat=True))
        self.assertIn(self.perfume.id, included_product_ids)
        self.assertIn(self.watch.id, included_product_ids)

    def test_gift_builder_explicit_toggle_buttons_and_badges(self):
        """التحقق من ظهور أزرار الإضافة الصريحة ومربعات الاختيار المرئية وفلاتر التصنيف في واجهة صانع الإهداء"""
        resp = self.client.get(reverse('store:gift_builder'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'toggle-btn')
        self.assertContains(resp, 'إضافة للصندوق')
        self.assertContains(resp, 'check-badge')
        self.assertContains(resp, 'تصنيف العطور:')
        self.assertContains(resp, 'كل العطور')
        self.assertContains(resp, 'عطور رجالية')

