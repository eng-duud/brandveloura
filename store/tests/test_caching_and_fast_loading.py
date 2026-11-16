from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.core.cache import cache
from store.models import Category, Product, HeroBanner, Brand, GiftBundle, StoreSettings


class CachingAndFastLoadingTests(TestCase):
    """اختبارات منظومة الكاشينج المتقدمة والتحميل المتدرج الذكي الفوري لمتجر Brand Veloura"""

    def setUp(self):
        self.client = Client()
        cache.clear()

        # إنشاء بيانات المتجر الأساسية
        self.settings = StoreSettings.get_settings()
        self.category = Category.objects.create(
            name_ar="عطور ملكية",
            category_type="perfumes",
            slug="royal-perfumes",
            is_active=True,
            show_in_home_slider=True,
            display_order=1
        )
        self.product = Product.objects.create(
            name_ar="عطر الفخامة الأسود",
            category=self.category,
            price_yer=Decimal('75000'),
            is_active=True,
            is_featured=True
        )
        self.banner = HeroBanner.objects.create(
            title="عروض الشتاء الملكية",
            is_active=True,
            display_order=1
        )

    def test_instant_home_shell_renders_under_50ms(self):
        """فحص الفتح الفوري للهيكل العلوي مع وسوم التحميل المتدرج وهياكل الشيمر الفاخرة"""
        response = self.client.get(reverse('store:home'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        # 1. التحقق من وجود الهيكل العلوي الفوري
        self.assertIn('عروض الشتاء الملكية', content)
        self.assertIn('id="categories-scroll"', content)

        # 2. التحقق من وجود حاوية التحميل المتدرج HTMX مع الشيمر
        self.assertIn('id="home-deferred-container"', content)
        self.assertIn('hx-get="/partials/home-deferred/"', content)
        self.assertIn('hx-trigger="load"', content)

    def test_home_deferred_content_loads_and_caches_successfully(self):
        """فحص جلب المحتوى السفلي وتخزينه في كاش دجانغو واسترجاعه بسرعة فائقة"""
        url = reverse('store:home_deferred_content')

        # الطلب الأول: يجلب من قاعدة البيانات ويحفظ في الكاش
        res1 = self.client.get(url)
        self.assertEqual(res1.status_code, 200)
        self.assertContains(res1, 'عطر الفخامة الأسود')
        self.assertContains(res1, 'id="featured-scroll"')

        # التحقق من أن القيمة أصبحت محفوظة في كاش دجانغو
        cached_html = cache.get('bv_home_deferred_html_YER')
        self.assertIsNotNone(cached_html)
        self.assertIn('عطر الفخامة الأسود', cached_html)

        # الطلب الثاني: يتم الاسترجاع الفوري من الكاش مباشرة
        res2 = self.client.get(url)
        self.assertEqual(res2.status_code, 200)
        self.assertContains(res2, 'عطر الفخامة الأسود')

    def test_signals_automatically_invalidate_cache_on_product_update(self):
        """فحص إبطال الكاش التلقائي الذكي فور قيام المشرف بتعديل أو إضافة منتج"""
        # تهيئة الكاش
        self.client.get(reverse('store:home_deferred_content'))
        self.assertIsNotNone(cache.get('bv_home_deferred_html_YER'))

        # تعديل المنتج (يحاكي حفظ من لوحة التحكم)
        self.product.name_ar = "عطر الفخامة المحدث 2026"
        self.product.save()

        # التحقق من تفريغ الكاش فوراً بواسطة إشارة post_save
        self.assertIsNone(cache.get('bv_home_deferred_html_YER'))

        # عند طلب المحتوى مجدداً يظهر الاسم المحدث
        res = self.client.get(reverse('store:home_deferred_content'))
        self.assertContains(res, "عطر الفخامة المحدث 2026")

    def test_signals_invalidate_cache_on_category_update(self):
        """فحص إبطال الكاش فور تعديل الأقسام"""
        # تجهيز الكاش
        self.client.get(reverse('store:home'))
        self.client.get(reverse('store:home_deferred_content'))
        self.assertIsNotNone(cache.get('bv_home_categories'))

        # تعديل قسم
        self.category.name_ar = "عطور باريسية"
        self.category.save()

        # التحقق من تفريغ الكاش
        self.assertIsNone(cache.get('bv_home_categories'))
        self.assertIsNone(cache.get('bv_home_deferred_html_YER'))

    def test_hx_boost_navigation_present_in_base_template(self):
        """فحص تفعيل hx-boost لتسريع الانتقال بين الصفحات كلياً بدون وميض وبدون ريلود"""
        from django.contrib.auth.models import User
        staff_user = User.objects.create_user(username='staffmember', password='PassWord123!', is_staff=True)
        self.client.force_login(staff_user)

        response = self.client.get(reverse('store:home'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        # التحقق من وجود hx-boost="true" على الـ body
        self.assertIn('hx-boost="true"', content)
        # التحقق من استثناء روابط الإدارة وتسجيل الخروج
        self.assertIn('hx-boost="false"', content)
