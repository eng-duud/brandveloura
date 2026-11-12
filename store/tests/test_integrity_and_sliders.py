from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.core.exceptions import ValidationError
from store.models import Category, Brand, Product, ProductImage, StoreSettings, Order


class ControlPanelIntegrityAndSliderTests(TestCase):
    def setUp(self):
        self.client = Client(SERVER_NAME='127.0.0.1')
        self.settings = StoreSettings.get_settings()
        self.admin_user = User.objects.create_superuser(
            username="admin_tester",
            email="admin_tester@brandveloura.com",
            password="AdminTesterPassword2026!"
        )
        self.category = Category.objects.create(
            name_ar="عطور النيش",
            name_en="Niche Perfumes",
            slug="niche-perfumes"
        )

    def test_product_add_with_grades_omitting_default_price(self):
        """فحص إضافة منتج بدرجات (أصلي/ماستر) بدون إدخال سعر افتراضي يدوي: يجب أن يعبأ تلقائياً ولا يُظهر خطأ مطلوب"""
        self.client.force_login(self.admin_user)
        post_data = {
            'name_ar': 'عطر كريد أفنتوس الفاخر',
            'category': self.category.id,
            'has_grades': 'on',
            'price_original_yer': '120000',
            'price_master_yer': '55000',
            'stock_quantity': '10',
            'images-TOTAL_FORMS': '0',
            'images-INITIAL_FORMS': '0',
            'images-MIN_NUM_FORMS': '0',
            'images-MAX_NUM_FORMS': '1000',
            '_save': 'Save'
        }
        res = self.client.post(reverse('admin:store_product_add'), post_data, secure=True, follow=True)
        self.assertEqual(res.status_code, 200)

        created_prod = Product.objects.filter(name_ar='عطر كريد أفنتوس الفاخر').first()
        self.assertIsNotNone(created_prod)
        self.assertEqual(created_prod.price_yer, Decimal('55000'))
        self.assertEqual(created_prod.price_original_yer, Decimal('120000'))
        self.assertEqual(created_prod.price_master_yer, Decimal('55000'))

    def test_product_invalid_discount_validation(self):
        """التحقق من رفض الأسعار الخاطئة التي تجعل سعر الشطب أقل من أو يساوي السعر الحالي"""
        self.client.force_login(self.admin_user)
        post_data = {
            'name_ar': 'عطر اختبار خطأ الخصم',
            'category': self.category.id,
            'price_yer': '50000',
            'compare_at_price_yer': '40000',
            'stock_quantity': '10',
            'images-TOTAL_FORMS': '0',
            'images-INITIAL_FORMS': '0',
            'images-MIN_NUM_FORMS': '0',
            'images-MAX_NUM_FORMS': '1000',
            '_save': 'Save'
        }
        res = self.client.post(reverse('admin:store_product_add'), post_data, secure=True, follow=True)
        self.assertIn('adminform', res.context_data)
        self.assertIn('compare_at_price_yer', res.context_data['adminform'].form.errors)

    def test_category_circular_parent_prevention(self):
        """التحقق من منع جعل القسم قسماً رئيسياً لنفسه أو تكرار هرمي دائري"""
        cat1 = Category.objects.create(name_ar="قسم 1", slug="cat-1")
        cat1.parent = cat1
        with self.assertRaises(ValidationError):
            cat1.clean()

    def test_product_image_single_primary_guarantee(self):
        """التحقق من ضبط صورة رئيسية واحدة تلقائياً ومنع تضارب الصور الرئيسية المتعددة"""
        prod = Product.objects.create(
            name_ar="ساعة رولكس ديتونا",
            price_yer=Decimal('250000')
        )
        img1 = ProductImage.objects.create(
            product=prod,
            image_url_fallback="https://example.com/1.jpg",
            is_primary=True
        )
        self.assertTrue(img1.is_primary)

        # إضافة صورة ثانية وتحديدها كرئيسية -> يجب إلغاء صفة الرئيسية عن الصورة الأولى تلقائياً
        img2 = ProductImage.objects.create(
            product=prod,
            image_url_fallback="https://example.com/2.jpg",
            is_primary=True
        )
        img1.refresh_from_db()
        self.assertFalse(img1.is_primary)
        self.assertTrue(img2.is_primary)

        # عند حذف الصورة الرئيسية، تصبح الصورة المتبقية رئيسية تلقائياً
        img2.delete()
        img1.refresh_from_db()
        self.assertTrue(img1.is_primary)

    def test_home_featured_slider_structure(self):
        """فحص تواجد شريط المنتجات المميزة بالهيكل الأفقي غير القابل للكسر bv-slider-strip وخصائص التمرير"""
        Product.objects.create(
            name_ar="عطر مميز 1",
            category=self.category,
            price_yer=Decimal('45000'),
            is_featured=True,
            is_active=True
        )
        res = self.client.get(reverse('store:home'))
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertIn('id="featured-scroll"', content)
        self.assertIn('bv-slider-strip', content)
        self.assertIn('flex-nowrap', content)
        self.assertIn('sliderStep(\'featured-scroll\', \'prev\')', content)
        self.assertIn('sliderStep(\'featured-scroll\', \'next\')', content)

    def test_home_departmental_sliders_and_trust_strip(self):
        """فحص تواجد كافة أشرطة الأقسام المنظمة (العطور، الساعات، التجميل، الأقسام، الماركات، وشريط الثقة)"""
        perfume_cat = Category.objects.create(name_ar="عطور رجالية", category_type="perfumes", slug="mens-perfumes")
        watch_cat = Category.objects.create(name_ar="ساعات فاخرة", category_type="watches", slug="luxury-watches")
        cosmetic_cat = Category.objects.create(name_ar="عناية بالبشرة", category_type="cosmetics", slug="skincare")
        
        Product.objects.create(name_ar="عطر ديور سوفاج", category=perfume_cat, price_yer=Decimal('80000'), is_active=True)
        Product.objects.create(name_ar="ساعة رولكس كلاسيك", category=watch_cat, price_yer=Decimal('350000'), is_active=True)
        Product.objects.create(name_ar="سيروم فيتامين سي", category=cosmetic_cat, price_yer=Decimal('15000'), is_active=True)

        res = self.client.get(reverse('store:home'))
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')

        # فحص شرائط الأقسام
        self.assertIn('id="categories-scroll"', content)
        self.assertIn('id="perfumes-scroll"', content)
        self.assertIn('id="watches-scroll"', content)
        self.assertIn('id="cosmetics-scroll"', content)

        # فحص شريط الثقة والضمانات
        self.assertIn('أصالة وجودة مضمونة', content)
        self.assertIn('توصيل لكافة المحافظات', content)
        self.assertIn('تغليف إهداء فاخر', content)
        self.assertIn('دفع ميسر بعدة عملات', content)

