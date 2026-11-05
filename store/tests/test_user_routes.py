from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from store.models import (
    StoreSettings, PaymentAccount, ShippingZone,
    Category, Product, Order, OrderItem, UserProfile
)


class UserRoutesAndOperationsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.settings = StoreSettings.get_settings()
        self.settings.store_name = "Brand Veloura"
        self.settings.yer_per_sar = Decimal('400.00')
        self.settings.gift_wrapping_fee_yer = Decimal('3000.00')
        self.settings.save()

        # أقسام تجريبية
        self.cat_perfumes = Category.objects.create(
            name_ar="العطور",
            name_en="Perfumes",
            slug="perfumes",
            category_type="perfumes"
        )
        self.cat_watches = Category.objects.create(
            name_ar="الساعات",
            name_en="Watches",
            slug="watches",
            category_type="watches"
        )
        self.cat_cosmetics = Category.objects.create(
            name_ar="مستحضرات التجميل",
            name_en="Cosmetics",
            slug="cosmetics",
            category_type="cosmetics"
        )

        # منتجات تجريبية
        self.perfume = Product.objects.create(
            category=self.cat_perfumes,
            name_ar="عطر عود ملكي فاخر",
            name_en="Oud Royal",
            slug="oud-royal",
            brand_name="Roja",
            price_yer=Decimal('60000'),
            has_grades=True,
            price_original_yer=Decimal('100000'),
            price_master_yer=Decimal('50000'),
            stock_quantity=15,
            is_featured=True,
            is_active=True,
            specifications={"gender": "unisex", "concentration": "Eau de Parfum"}
        )

        self.watch = Product.objects.create(
            category=self.cat_watches,
            name_ar="ساعة رولكس دايتونا ستيل",
            name_en="Rolex Daytona Steel",
            slug="rolex-daytona",
            brand_name="Rolex",
            price_yer=Decimal('120000'),
            stock_quantity=5,
            is_active=True,
            specifications={"water_resistance": "100m", "strap_material": "Stainless Steel", "gender": "men"}
        )

        # منطقة شحن
        self.zone_sanaa = ShippingZone.objects.create(
            city_name="أمانة العاصمة صنعاء",
            delivery_fee_yer=Decimal('2000'),
            estimated_delivery_time="نفس اليوم"
        )

        # حساب دفع
        self.payment_acc = PaymentAccount.objects.create(
            provider_name="بنك الكريمي",
            account_holder_name="شركة براند فيلورا",
            account_number="123456789",
            currency="YER",
            is_active=True
        )

        # مستخدم تجريبي
        self.user = User.objects.create_user(
            username="khaled",
            email="khaled@example.com",
            password="KhaledPassword2026!",
            first_name="خالد",
            last_name="اليمني"
        )

    # 1. اختبارات الصفحات الرئيسية والكتالوجات
    def test_home_page(self):
        """فحص الصفحة الرئيسية وعرض الأشرطة والمنتجات المميزة"""
        res = self.client.get(reverse('store:home'))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'store/home.html')
        self.assertIn('featured_products', res.context)
        self.assertIn('categories', res.context)

    def test_product_list_and_search(self):
        """فحص صفحة كافة المنتجات والبحث النصي"""
        res = self.client.get(reverse('store:product_list'), {'q': 'عود'})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'عطر عود ملكي')

    def test_perfumes_catalog_with_filters(self):
        """فحص كتالوج العطور مع فلترة الدرجة والماركة والترتيب"""
        res = self.client.get(reverse('store:perfumes_catalog'), {
            'brand': 'Roja',
            'grade': 'master',
            'sort': 'price_low'
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'عطر عود ملكي')

    def test_watches_catalog(self):
        """فحص كتالوج الساعات مع الفلاتر"""
        res = self.client.get(reverse('store:watches_catalog'), {'gender': 'men'})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'ساعة رولكس')

    def test_cosmetics_catalog(self):
        """فحص كتالوج مستحضرات التجميل"""
        res = self.client.get(reverse('store:cosmetics_catalog'))
        self.assertEqual(res.status_code, 200)

    def test_product_detail_page(self):
        """فحص صفحة تفاصيل المنتج المنفردة"""
        res = self.client.get(reverse('store:product_detail', kwargs={'slug': self.perfume.slug}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'عطر عود ملكي')

    def test_product_quick_view_modal_htmx(self):
        """فحص واجهة المعاينة المنبثقة (Popup Modal) عبر HTMX"""
        res = self.client.get(reverse('store:product_modal', kwargs={'slug': self.perfume.slug}))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'store/partials/quick_view_modal.html')
        self.assertContains(res, 'أصلي')
        self.assertContains(res, 'ماستر')

    # 2. اختبارات عمليات سلة المشتريات (Cart Lifecycle)
    def test_cart_operations(self):
        """فحص إضافة منتج بدرجة ماستر، تحديث الكمية، وحذفه من السلة"""
        # إضافة منتج
        add_res = self.client.post(reverse('store:cart_add'), {
            'product_id': self.perfume.id,
            'quantity': 2,
            'grade': 'master'
        })
        self.assertEqual(add_res.status_code, 200)
        session = self.client.session
        self.assertIn('cart', session)
        self.assertEqual(len(session['cart']), 1)

        # استعراض السلة
        cart_view_res = self.client.get(reverse('store:cart_view'))
        self.assertEqual(cart_view_res.status_code, 200)
        self.assertContains(cart_view_res, 'عطر عود ملكي')

        # تحديث الكمية
        cart_key = list(session['cart'].keys())[0]
        update_res = self.client.post(reverse('store:cart_update'), {
            'item_key': cart_key,
            'action': 'increase'
        })
        self.assertEqual(update_res.status_code, 200)

        # حذف المنتج
        remove_res = self.client.post(reverse('store:cart_remove'), {
            'item_key': cart_key
        })
        self.assertEqual(remove_res.status_code, 200)
        self.assertEqual(len(self.client.session['cart']), 0)

    # 3. اختبارات العملات والشحن
    def test_currency_toggle(self):
        """فحص تبديل العملة بين الريال السعودي واليمني"""
        res = self.client.post(reverse('store:toggle_currency'))
        self.assertEqual(res.status_code, 200)
        new_curr = self.client.session.get('active_currency')
        self.assertIn(new_curr, ['SAR', 'YER'])

    def test_get_shipping_fee(self):
        """فحص حساب تكلفة الشحن مع وبدون تغليف الهدايا"""
        res = self.client.get(reverse('store:get_shipping_fee'), {
            'city_id': self.zone_sanaa.id,
            'is_luxury_gift_wrapping': 'true'
        })
        self.assertEqual(res.status_code, 200)
        self.assertIn('total_yer', res.context)

    # 4. اختبارات إتمام الطلب والتحقق (Checkout & Order)
    def test_checkout_empty_cart_redirect(self):
        """السلة الفارغة يجب أن تعيد التوجيه إلى صفحة المنتجات"""
        res = self.client.get(reverse('store:checkout'))
        self.assertEqual(res.status_code, 302)

    def test_checkout_submission_success(self):
        """فحص إنشاء طلب نظامي واحتساب الإجماليات وتفريغ السلة"""
        # تجهيز السلة
        self.client.post(reverse('store:cart_add'), {
            'product_id': self.perfume.id,
            'quantity': 1,
            'grade': 'master'
        })

        checkout_data = {
            'customer_name': 'خالد أحمد',
            'customer_phone': '770001122',
            'customer_email': 'khaled@test.com',
            'shipping_city': self.zone_sanaa.id,
            'shipping_address': 'صنعاء، شارع الجزائر، عمارة الأمل',
            'payment_method': self.payment_acc.id,
            'payment_currency_selected': 'YER',
            'payment_reference_no': 'TRX-998877',
            'customer_notes': 'يرجى الاتصال قبل الوصول'
        }

        res = self.client.post(reverse('store:checkout'), checkout_data)
        self.assertEqual(res.status_code, 302)

        # التحقق من تسجيل الطلب في قاعدة البيانات
        order = Order.objects.filter(customer_phone='770001122').first()
        self.assertIsNotNone(order)
        self.assertEqual(order.customer_name, 'خالد أحمد')
        self.assertGreater(order.total_yer, Decimal('0'))
        self.assertGreater(order.total_sar, Decimal('0'))
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(len(self.client.session.get('cart', {})), 0)

        # فحص صفحة نجاح الطلب
        success_res = self.client.get(reverse('store:order_success', kwargs={'order_number': order.order_number}))
        self.assertEqual(success_res.status_code, 200)
        self.assertContains(success_res, order.order_number)

    def test_gift_order_submission(self):
        """فحص إنشاء طلب إهداء لشخص آخر مع بطاقة ورسالة إهداء وتغليف"""
        self.client.post(reverse('store:cart_add'), {
            'product_id': self.watch.id,
            'quantity': 1
        })

        gift_data = {
            'customer_name': 'محمد سعيد',
            'customer_phone': '771112233',
            'shipping_city': self.zone_sanaa.id,
            'shipping_address': 'حدة، صنعاء',
            'payment_method': self.payment_acc.id,
            'payment_currency_selected': 'SAR',
            'payment_reference_no': 'GIFT-1122',
            'is_gift': 'true',
            'recipient_name': 'عمر سعيد',
            'recipient_phone': '773334455',
            'gift_card_sender': 'محمد',
            'gift_card_recipient': 'عمر',
            'gift_card_message': 'هدية عيد ميلادك يا غالي',
            'is_luxury_gift_wrapping': 'true'
        }

        res = self.client.post(reverse('store:checkout'), gift_data)
        self.assertEqual(res.status_code, 302)
        order = Order.objects.filter(customer_phone='771112233').first()
        self.assertTrue(order.is_gift)
        self.assertTrue(order.is_luxury_gift_wrapping)
        self.assertEqual(order.recipient_name, 'عمر سعيد')

    def test_track_order(self):
        """فحص مسار تتبع الطلب بواسطة رقم الطلب ورقم الهاتف"""
        order = Order.objects.create(
            order_number="BV-TRACK-001",
            customer_name="ماجد",
            customer_phone="774445566",
            shipping_city=self.zone_sanaa.city_name,
            shipping_address="شارع الستين",
            subtotal_yer=Decimal('48000'),
            shipping_fee_yer=Decimal('2000'),
            total_yer=Decimal('50000'),
            total_sar=Decimal('125'),
            exchange_rate_applied=Decimal('400'),
            payment_currency_selected='YER',
            status='out_for_delivery'
        )

        # استعلام تتبع صحيح
        res = self.client.get(reverse('store:track_order'), {
            'q': order.order_number
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, order.order_number)

    # 5. اختبارات مصادقة المستخدم والملف الشخصي
    def test_user_register_and_login_flow(self):
        """فحص إنشاء حساب جديد، تسجيل الخروج، ثم الدخول مجدداً"""
        # إنشاء حساب جديد
        reg_res = self.client.post(reverse('store:register'), {
            'name': 'يوسف الهمداني',
            'email': 'yousef@test.com',
            'phone': '778899001',
            'password': 'StrongPassword2026!',
            'password_confirm': 'StrongPassword2026!'
        })
        self.assertEqual(reg_res.status_code, 302)
        new_user = User.objects.filter(email='yousef@test.com').first()
        self.assertIsNotNone(new_user)

        # تسجيل الخروج
        logout_res = self.client.get(reverse('store:logout'))
        self.assertEqual(logout_res.status_code, 302)

        # تسجيل الدخول
        login_res = self.client.post(reverse('store:login'), {
            'identifier': 'yousef@test.com',
            'password': 'StrongPassword2026!'
        })
        self.assertEqual(login_res.status_code, 302)

    def test_google_auth_demo_callback(self):
        """فحص مسار الدخول بحساب Google التجريبي"""
        res = self.client.get(reverse('store:google_callback') + '?demo=1')
        self.assertEqual(res.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_account_profile_view_and_update(self):
        """فحص استعراض وتحديث بيانات الملف الشخصي للمستخدم المسجل"""
        self.client.force_login(self.user)
        # عرض الصفحة
        res = self.client.get(reverse('store:account_profile'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, self.user.first_name)

        # تحديث العنوان والهاتف
        post_res = self.client.post(reverse('store:account_profile'), {
            'first_name': 'خالد',
            'last_name': 'المتوكل',
            'phone': '771122334',
            'preferred_city': 'صنعاء',
            'shipping_address': 'حي الأصبحي، صنعاء'
        })
        self.assertEqual(post_res.status_code, 302)
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.phone, '771122334')
        self.assertEqual(profile.shipping_address, 'حي الأصبحي، صنعاء')

    def test_reorder_view(self):
        """فحص زر إعادة الطلب وإعادة تعبئة السلة من طلب سابق"""
        order = Order.objects.create(
            order_number="BV-REORDER-001",
            user=self.user,
            customer_name="خالد",
            customer_phone="771234567",
            shipping_city=self.zone_sanaa.city_name,
            shipping_address="صنعاء",
            subtotal_yer=Decimal('50000'),
            shipping_fee_yer=Decimal('2000'),
            total_yer=Decimal('52000'),
            total_sar=Decimal('130'),
            exchange_rate_applied=Decimal('400'),
            payment_currency_selected='YER',
            status='delivered'
        )
        OrderItem.objects.create(
            order=order,
            product=self.perfume,
            product_name=self.perfume.name_ar,
            quantity=2,
            unit_price_yer=Decimal('50000'),
            total_price_yer=Decimal('100000')
        )

        self.client.force_login(self.user)
        reorder_res = self.client.post(reverse('store:reorder', kwargs={'order_number': order.order_number}))
        self.assertEqual(reorder_res.status_code, 302)
        # السلة أصبحت تحتوي على المنتج
        self.assertIn('cart', self.client.session)
        self.assertEqual(len(self.client.session['cart']), 1)

    # 6. اختبارات PWA
    def test_pwa_manifest_and_sw(self):
        """فحص ملفات الـ PWA (المانيفست وموزع الخدمة)"""
        res_manifest = self.client.get(reverse('store:pwa_manifest'))
        self.assertEqual(res_manifest.status_code, 200)
        self.assertEqual(res_manifest['Content-Type'], 'application/manifest+json')

        res_sw = self.client.get(reverse('store:service_worker'))
        self.assertEqual(res_sw.status_code, 200)
        self.assertEqual(res_sw['Content-Type'], 'application/javascript')

    # 7. اختبارات محركات البحث والذكاء الاصطناعي (SEO & GEO)
    def test_seo_robots_sitemap_and_llms(self):
        """فحص مسارات robots.txt و sitemap.xml و llms.txt"""
        # Robots.txt
        res_robots = self.client.get(reverse('store:robots_txt'))
        self.assertEqual(res_robots.status_code, 200)
        self.assertIn('text/plain', res_robots['Content-Type'])
        self.assertIn('User-agent: *', res_robots.content.decode('utf-8'))
        self.assertIn('Sitemap:', res_robots.content.decode('utf-8'))
        self.assertIn('Googlebot', res_robots.content.decode('utf-8'))

        # Sitemap.xml
        res_sitemap = self.client.get(reverse('store:sitemap_xml'))
        self.assertEqual(res_sitemap.status_code, 200)
        self.assertIn('application/xml', res_sitemap['Content-Type'])
        content = res_sitemap.content.decode('utf-8')
        self.assertIn('<urlset', content)
        self.assertIn(self.perfume.slug, content)
        self.assertIn('perfumes', content)

        # llms.txt
        res_llms = self.client.get(reverse('store:llms_txt'))
        self.assertEqual(res_llms.status_code, 200)
        self.assertIn('text/plain', res_llms['Content-Type'])
        llms_content = res_llms.content.decode('utf-8')
        self.assertIn('Brand Veloura', llms_content)
        self.assertIn('Perfumes', llms_content)

    # 8. اختبارات ركن الهدايا والمناسبات الفاخرة (Gifting & Occasions)
    def test_gifting_builder_page_render(self):
        """فحص صفحة صانع الهدية الملكي وعرض العطور والخيارات"""
        res = self.client.get(reverse('store:gift_builder'))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'store/gift_builder.html')
        content = res.content.decode('utf-8')
        self.assertIn('خدمة الإهداء', content)
        self.assertIn('توصيل للمحافظات', content)
        self.assertIn(self.perfume.name_ar, content)

    def test_gifting_live_calculation_htmx(self):
        """فحص الحساب اللحظي المباشر عبر HTMX للعملتين YER و SAR والتغليف الملكي"""
        data = {
            'perfume_id': self.perfume.id,
            'perfume_grade': 'original',
            'is_luxury_gift_wrapping': 'true',
        }
        res = self.client.post(reverse('store:gift_calculate'), data)
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'store/partials/gift_builder_summary.html')
        content = res.content.decode('utf-8')
        # السعر الأصلي 100,000 + التغليف 3,000 = 103,000 ر.ي
        self.assertIn('103000', content)
        self.assertIn('المعادل بالريال السعودي', content)
        self.assertIn('إخفاء السعر عن المستلم', content)

    def test_gifting_order_full_journey(self):
        """فحص مسار الإهداء الكامل: من المعالج، مروراً بالسلة إلى إنشاء الطلب بحجب الأسعار والجدولة"""
        # 1. إرسال خيارات الإهداء من المعالج
        post_data = {
            'perfume_id': self.perfume.id,
            'perfume_grade': 'original',
            'recipient_name': 'خالد المنصوري',
            'recipient_phone': '771234567',
            'gift_card_sender': 'صالح (جدة)',
            'gift_card_message': 'ألف مبروك التخرج والنجاح الباهر',
            'preferred_delivery_date': '2026-11-20',
            'is_luxury_gift_wrapping': 'true',
        }
        res = self.client.post(reverse('store:gift_builder'), post_data)
        self.assertRedirects(res, reverse('store:checkout'))

        # التحقق من أن الجلسة حفظت بيانات الهدية والسلة
        session = self.client.session
        self.assertTrue(session['gift_data']['is_gift'])
        self.assertEqual(session['gift_data']['recipient_name'], 'خالد المنصوري')

        # 2. إتمام الطلب في صفحة الدفع
        checkout_post = {
            'customer_name': 'صالح اليافعي',
            'customer_phone': '0550000000',
            'customer_email': 'saleh@example.com',
            'shipping_city': self.zone_sanaa.id,
            'shipping_address': 'صنعاء، حدة، بجوار البريد',
            'payment_method': self.payment_acc.id,
            'payment_reference_no': 'REF-GIFT-9988',
            'is_gift': 'true',
            'recipient_name': 'خالد المنصوري',
            'recipient_phone': '771234567',
            'gift_card_sender': 'صالح (جدة)',
            'gift_card_recipient': 'خالد المنصوري',
            'gift_card_message': 'ألف مبروك التخرج والنجاح الباهر',
            'preferred_delivery_date': '2026-11-20',
            'hide_invoice_prices': 'true',
            'is_luxury_gift_wrapping': 'true',
        }
        res_checkout = self.client.post(reverse('store:checkout'), checkout_post)
        order = Order.objects.filter(recipient_name='خالد المنصوري').first()
        self.assertIsNotNone(order)
        self.assertRedirects(res_checkout, reverse('store:order_success', kwargs={'order_number': order.order_number}))
        
        # التأكد من صحة بيانات الحقول الجديدة
        self.assertTrue(order.is_gift)
        self.assertTrue(order.hide_invoice_prices)
        self.assertEqual(str(order.preferred_delivery_date), '2026-11-20')
        self.assertEqual(order.gift_card_sender, 'صالح (جدة)')
        self.assertTrue(order.is_luxury_gift_wrapping)
        self.assertEqual(order.gift_wrapping_fee_yer, Decimal('3000.00'))

        # 3. فحص التتبع وإخفاء الأسعار عند تتبع الهدية
        res_track = self.client.get(reverse('store:track_order') + f"?q={order.order_number}")
        self.assertEqual(res_track.status_code, 200)
        track_html = res_track.content.decode('utf-8')
        self.assertIn('طلب إهداء (الأسعار محجوبة)', track_html)
        self.assertNotIn(f"{order.total_yer:,.0f} ر.ي", track_html)

    def test_get_shipping_fee_htmx_with_gifting(self):
        """فحص حساب الشحن والتغليف اللحظي عبر HTMX عند اختيار المدينة وتغليف الهدايا"""
        # تجهيز سلة
        session = self.client.session
        session['cart'] = {
            'item_1': {
                'product_id': self.perfume.id,
                'name': self.perfume.name_ar,
                'price_yer': 100000,
                'quantity': 1
            }
        }
        session.save()

        # طلب HTMX مع مدينة وتغليف هدايا
        get_params = {
            'shipping_city': self.zone_sanaa.id,
            'order_type': 'gift',
            'is_gift': 'true',
            'is_luxury_gift_wrapping': 'true',
        }
        res = self.client.get(reverse('store:get_shipping_fee'), get_params)
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'store/partials/checkout_totals.html')
        content = res.content.decode('utf-8')
        # subtotal: 100,000 + shipping: 2,000 + wrapping: 3,000 = 105,000
        self.assertIn('105000', content)
        self.assertIn('تغليف هدايا:', content)

        # طلب HTMX لنفس السلة كطلب شخصي بدون تغليف
        get_params_personal = {
            'shipping_city': self.zone_sanaa.id,
            'order_type': 'personal',
        }
        res_personal = self.client.get(reverse('store:get_shipping_fee'), get_params_personal)
        self.assertEqual(res_personal.status_code, 200)
        content_personal = res_personal.content.decode('utf-8')
        # subtotal: 100,000 + shipping: 2,000 = 102,000
        self.assertIn('102000', content_personal)
        self.assertNotIn('تغليف هدايا:', content_personal)

    def test_multi_item_gift_builder_and_live_calculate(self):
        """فحص تجهيز باقة إهداء متعددة العطور والملحقات وحساب التكلفة اللحظية"""
        # عطر ثانٍ
        perfume_2 = Product.objects.create(
            category=self.cat_perfumes,
            name_ar="عطر مسك روز فاخر",
            name_en="Musk Rose",
            slug="musk-rose",
            brand_name="Veloura Rose",
            price_yer=Decimal('45000'),
            has_grades=True,
            price_original_yer=Decimal('80000'),
            price_master_yer=Decimal('40000'),
            stock_quantity=10,
            is_active=True
        )

        # ملحق ثانٍ (مستحضر تجميل)
        cosmetic_item = Product.objects.create(
            category=self.cat_cosmetics,
            name_ar="سيروم العناية الذهبي",
            name_en="Golden Serum",
            slug="golden-serum",
            brand_name="Veloura Care",
            price_yer=Decimal('15000'),
            stock_quantity=8,
            is_active=True
        )

        # 1. اختبار الحساب اللحظي المباشر عبر HTMX مع عطرين وملحقين وتغليف
        calc_data = {
            'perfume_id': [str(self.perfume.id), str(perfume_2.id)],
            f'grade_{self.perfume.id}': 'original',  # 100,000 YER
            f'grade_{perfume_2.id}': 'master',       # 40,000 YER
            'accessory_id': [str(self.watch.id), str(cosmetic_item.id)],  # 120,000 + 15,000 YER
            'is_luxury_gift_wrapping': 'true',       # 3,000 YER
        }
        res_calc = self.client.post(reverse('store:gift_calculate'), calc_data)
        self.assertEqual(res_calc.status_code, 200)
        calc_html = res_calc.content.decode('utf-8')
        
        # مجموع: 100000 + 40000 + 120000 + 15000 + 3000 = 278,000
        self.assertIn('278000', calc_html)
        self.assertIn('عطر عود ملكي فاخر', calc_html)
        self.assertIn('عطر مسك روز فاخر', calc_html)
        self.assertIn('ساعة رولكس دايتونا ستيل', calc_html)
        self.assertIn('سيروم العناية الذهبي', calc_html)

        # 2. اختبار إرسال الفورم وحفظ كافة العطور والملحقات في السلة والجلسة
        post_data = {
            'perfume_id': [str(self.perfume.id), str(perfume_2.id)],
            f'grade_{self.perfume.id}': 'original',
            f'grade_{perfume_2.id}': 'master',
            'accessory_id': [str(self.watch.id), str(cosmetic_item.id)],
            'recipient_name': 'ياسر اليماني',
            'gift_card_sender': 'أحمد سعيد',
            'gift_card_message': 'مبارك الترقية ومنها للأعلى',
            'is_luxury_gift_wrapping': 'true',
        }
        res_submit = self.client.post(reverse('store:gift_builder'), post_data)
        self.assertRedirects(res_submit, reverse('store:checkout'))

        # فحص محتويات سلة الجلسة
        cart = self.client.session.get('cart', {})
        self.assertEqual(len(cart), 4)

        # التحقق من مفاتيح العطور ودرجاتها وأسعارها
        p1_key = f"{self.perfume.id}_original_gift"
        p2_key = f"{perfume_2.id}_master_gift"
        self.assertIn(p1_key, cart)
        self.assertIn(p2_key, cart)
        self.assertEqual(cart[p1_key]['price_yer'], 100000.0)
        self.assertEqual(cart[p1_key]['grade'], 'original')
        self.assertEqual(cart[p2_key]['price_yer'], 40000.0)
        self.assertEqual(cart[p2_key]['grade'], 'master')

        # التحقق من مفاتيح الملحقات وأسعارها
        acc1_key = f"{self.watch.id}_acc_gift"
        acc2_key = f"{cosmetic_item.id}_acc_gift"
        self.assertIn(acc1_key, cart)
        self.assertIn(acc2_key, cart)
        self.assertEqual(cart[acc1_key]['price_yer'], 120000.0)
        self.assertEqual(cart[acc2_key]['price_yer'], 15000.0)

        # فحص بيانات الهدية في الجلسة
        gift_data = self.client.session.get('gift_data', {})
        self.assertTrue(gift_data.get('is_gift'))
        self.assertEqual(gift_data.get('recipient_name'), 'ياسر اليماني')
        self.assertEqual(gift_data.get('gift_card_sender'), 'أحمد سعيد')

    def test_health_check_endpoint(self):
        """فحص مسار الفحص السحابي Railway Health Check"""
        res = self.client.get(reverse('health_check'))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get('status'), 'healthy')
        self.assertEqual(data.get('service'), 'brandveloura')

        # فحص المسار البديل healthz
        res_z = self.client.get(reverse('healthz_check'))
        self.assertEqual(res_z.status_code, 200)



