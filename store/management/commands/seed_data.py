from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from store.models import (
    StoreSettings, PaymentAccount, ShippingZone, 
    Category, Product, ProductImage, HeroBanner
)


class Command(BaseCommand):
    help = 'تعبئة قاعدة البيانات ببيانات أولية واقعية وفاخرة للعطور والساعات ومستحضرات التجميل وحسابات الدفع اليمنية'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.NOTICE('بدء تجهيز البيانات الأولية لمتجر Brand Veloura...'))

        # 1. إعدادات المتجر وسعر الصرف
        settings = StoreSettings.get_settings()
        settings.store_name = 'Brand Veloura'
        settings.store_tagline = 'متجر الفخامة الأول للعطور والساعات ومستلزمات التجميل'
        settings.yer_per_sar = Decimal('530.00')
        settings.contact_phone = '+967 770 123 456'
        settings.contact_whatsapp = '967770123456'
        settings.contact_instagram = 'brandveloura.ye'
        settings.announcement_text = 'توصيل لكافة المحافظات — الدفع بالريال اليمني والسعودي'
        settings.is_announcement_active = True
        settings.save()
        self.stdout.write(self.style.SUCCESS('[OK] Store settings and exchange rate updated (1 SAR = 530 YER)'))

        # 2. إنشاء المستخدم المدير للوحة التحكم (Admin Superuser)
        import os
        admin_user = os.getenv('DJANGO_SUPERUSER_USERNAME', 'admin')
        admin_email = os.getenv('DJANGO_SUPERUSER_EMAIL', 'admin@brandveloura.com')
        admin_pass = os.getenv('DJANGO_SUPERUSER_PASSWORD', 'admin123456')

        if not User.objects.filter(username=admin_user).exists():
            User.objects.create_superuser(admin_user, admin_email, admin_pass)
            self.stdout.write(self.style.SUCCESS(f'[OK] Admin user created: {admin_user}'))
        else:
            self.stdout.write(self.style.WARNING(f'[INFO] Admin user {admin_user} already exists.'))

        # 3. وسائل الدفع وحسابات التحويل في اليمن والسعودية للمغتربين
        payment_methods_data = [
            {
                'provider_name': 'مصرف الراجحي — تحويل مباشر بالريال السعودي (للمغتربين)',
                'currency': 'SAR',
                'bank_country': 'SA',
                'account_number': '4580000123456789012345',
                'iban': 'SA4580000123456789012345',
                'account_holder_name': 'مؤسسة براند فيلورا للتجارة — حساب المغتربين',
                'instructions': 'للعملاء والمغتربين في المملكة العربية السعودية: يرجى التحويل مباشرة بالريال السعودي إلى حساب الراجحي الموضح عبر تطبيق الراجحي أو بنوك المملكة، ثم إرفاق صورة إشعار التحويل.',
                'is_cod': False,
                'display_order': 1,
            },
            {
                'provider_name': 'بنك الكريمي (حساب مميز - يمني وسعودي)',
                'currency': 'BOTH',
                'bank_country': 'YE',
                'account_number': '3001234567',
                'account_holder_name': 'مؤسسة براند فيلورا للتجارة',
                'instructions': 'يرجى التحويل إلى رقم الحساب أعلاه عبر تطبيق الكريمي جوال أو فروع البنك (يقبل الإيداع بالريال اليمني أو السعودي مباشرة)، ثم إرفاق صورة إشعار التحويل.',
                'is_cod': False,
                'display_order': 2,
            },
            {
                'provider_name': 'محفظة جوالي (YOU / MTN)',
                'currency': 'YER',
                'bank_country': 'YE',
                'account_number': '770123456',
                'account_holder_name': 'براند فيلورا - متجر العطور',
                'instructions': 'أرسل المبلغ لرقم المحفظة أعلاه عبر تطبيق جوالي أو رسائل SMS، ثم ارفع صورة الإشعار أو اكتب رقم العملية.',
                'is_cod': False,
                'display_order': 3,
            },
            {
                'provider_name': 'محفظة كاش / ون كاش',
                'currency': 'YER',
                'bank_country': 'YE',
                'account_number': '711987654',
                'account_holder_name': 'براند فيلورا',
                'instructions': 'حول المبلغ لحساب المحفظة الموضح وارفع لقطة شاشة للإشعار.',
                'is_cod': False,
                'display_order': 4,
            },
            {
                'provider_name': 'شبكات الحوالات (النجم / الامتياز / يمن إكسبرس)',
                'currency': 'BOTH',
                'bank_country': 'YE',
                'account_number': 'هاتف المستلم: 770123456',
                'account_holder_name': 'أحمد علي العولقي — صنعاء',
                'instructions': 'أرسل حوالة باسم المستلم الموضح عبر أي شبكة صرافة واكتب رقم الحوالة واسم المحول في خانة الملاحظات.',
                'is_cod': False,
                'display_order': 5,
            },
            {
                'provider_name': 'الدفع عند الاستلام (COD)',
                'currency': 'YER',
                'bank_country': 'YE',
                'account_number': '',
                'account_holder_name': 'التسليم يد بيد للمندوب',
                'instructions': 'متاح داخل أمانة العاصمة صنعاء ومدينة عدن. سلم قيمة الطلب نقداً للمندوب عند معاينة واستلام شحنتك.',
                'is_cod': True,
                'display_order': 6,
            },
        ]

        for p_data in payment_methods_data:
            PaymentAccount.objects.update_or_create(
                provider_name=p_data['provider_name'],
                defaults=p_data
            )
        self.stdout.write(self.style.SUCCESS('[OK] Payment accounts populated'))

        # 4. مناطق الشحن والمدن اليمنية
        zones_data = [
            {'city_name': 'أمانة العاصمة — صنعاء', 'delivery_fee_yer': Decimal('2000.00'), 'estimated_delivery_time': 'خلال 24 ساعة'},
            {'city_name': 'محافظة عدن', 'delivery_fee_yer': Decimal('4000.00'), 'estimated_delivery_time': 'خلال 24-48 ساعة'},
            {'city_name': 'محافظة تعز', 'delivery_fee_yer': Decimal('4000.00'), 'estimated_delivery_time': 'خلال 2-3 أيام'},
            {'city_name': 'حضرموت (المكلا / سيئون)', 'delivery_fee_yer': Decimal('5000.00'), 'estimated_delivery_time': 'خلال 2-3 أيام'},
            {'city_name': 'محافظة إب', 'delivery_fee_yer': Decimal('3500.00'), 'estimated_delivery_time': 'خلال 24-48 ساعة'},
            {'city_name': 'محافظة الحديدة', 'delivery_fee_yer': Decimal('4000.00'), 'estimated_delivery_time': 'خلال 2-3 أيام'},
            {'city_name': 'محافظة مأرب', 'delivery_fee_yer': Decimal('4500.00'), 'estimated_delivery_time': 'خلال 2-3 أيام'},
            {'city_name': 'محافظة ذمار', 'delivery_fee_yer': Decimal('3000.00'), 'estimated_delivery_time': 'خلال 24 ساعة'},
        ]

        for z in zones_data:
            ShippingZone.objects.update_or_create(
                city_name=z['city_name'],
                defaults=z
            )
        self.stdout.write(self.style.SUCCESS('[OK] Shipping zones populated'))

        # 5. البانرات الترويجية
        banners_data = [
            {
                'title': 'تشكيلة العطور الملكية 2026',
                'subtitle': 'نوتات عطرية نادرة وثبات لا يُنسى من أرقى الدور الفرنسية والعالمية بأسعار لا تُنافس.',
                'tag_badge': 'الأكثر طلباً وفخامة',
                'image_url_fallback': 'https://images.unsplash.com/photo-1547887537-6158d64c35b3?auto=format&fit=crop&w=1600&q=80',
                'button_text': 'تسوق قسم العطور الآن',
                'button_link': '/products/?category=perfumes',
                'display_order': 1,
            },
            {
                'title': 'ساعات سويسرية ويابانية راقية',
                'subtitle': 'تصاميم خالدة تجمع بين الدقة الفائقة والمظهر الاستثنائي المقاوم للماء مع ضمان أصلي.',
                'tag_badge': 'دقة وأناقة',
                'image_url_fallback': 'https://images.unsplash.com/photo-1522335789203-aabd1fc54bc9?auto=format&fit=crop&w=1600&q=80',
                'button_text': 'استكشف تشكيلة الساعات',
                'button_link': '/products/?category=watches',
                'display_order': 2,
            },
        ]

        for b in banners_data:
            HeroBanner.objects.update_or_create(
                title=b['title'],
                defaults=b
            )
        self.stdout.write(self.style.SUCCESS('[OK] Hero banners populated'))

        # 6. الأقسام والفئات
        categories_data = [
            {
                'name_ar': 'العطور الفاخرة',
                'name_en': 'Luxury Perfumes',
                'slug': 'perfumes',
                'category_type': 'perfumes',
                'description': 'عطور رجالية ونسائية أصلية 100% من أشهر الماركات العالمية.',
                'image_url_fallback': 'https://images.unsplash.com/photo-1592945403244-b3fbafd7f539?auto=format&fit=crop&w=800&q=80',
                'display_order': 1,
            },
            {
                'name_ar': 'الساعات الراقية',
                'name_en': 'Luxury Watches',
                'slug': 'watches',
                'category_type': 'watches',
                'description': 'ساعات كلاسيكية ورياضية أوتوماتيك وكوارتز بتشطيبات ممتازة.',
                'image_url_fallback': 'https://images.unsplash.com/photo-1524805444758-089113d48a6d?auto=format&fit=crop&w=800&q=80',
                'display_order': 2,
            },
            {
                'name_ar': 'مستحضرات التجميل',
                'name_en': 'Cosmetics & Makeup',
                'slug': 'cosmetics',
                'category_type': 'cosmetics',
                'description': 'أحدث صيحات المكياج وأحمر الشفاه والفاونديشن من دور التجميل العالمية.',
                'image_url_fallback': 'https://images.unsplash.com/photo-1512496015851-a90fb38ba796?auto=format&fit=crop&w=800&q=80',
                'display_order': 3,
            },
            {
                'name_ar': 'العناية بالبشرة',
                'name_en': 'Skincare & Beauty',
                'slug': 'care',
                'category_type': 'care',
                'description': 'سيرومات وكريمات مغذية للبشرة تمنحك إشراقة ونضارة طبيعية.',
                'image_url_fallback': 'https://images.unsplash.com/photo-1556228720-195a672e8a03?auto=format&fit=crop&w=800&q=80',
                'display_order': 4,
            },
            {
                'name_ar': 'باقات الهدايا والمناسبات',
                'name_en': 'Gift Bundles & Sets',
                'slug': 'bundles',
                'category_type': 'bundles',
                'description': 'صناديق وباقات هدايا ملكية متكاملة للأعراس والتخرج والمناسبات الخاصة.',
                'image_url_fallback': 'https://images.unsplash.com/photo-1549465220-1a8b9238cd48?auto=format&fit=crop&w=800&q=80',
                'display_order': 5,
            },
        ]

        cat_objects = {}
        for c in categories_data:
            cat, _ = Category.objects.update_or_create(
                slug=c['slug'],
                defaults=c
            )
            cat_objects[c['slug']] = cat
        self.stdout.write(self.style.SUCCESS('[OK] Categories populated'))

        # 7. المنتجات الفاخرة مع المواصفات الذكية
        products_data = [
            # العطور (مع سياسة الأصلي والماستر طبق الأصل)
            {
                'category': cat_objects['perfumes'],
                'name_ar': 'عطر ديور سوفاج إكسير المركز',
                'name_en': 'Dior Sauvage Elixir Parfum',
                'slug': 'dior-sauvage-elixir',
                'brand_name': 'Dior',
                'description': 'عطر سوفاج إكسير هو خلاصة العطر الأيقوني بتركيز فائق الكثافة والقوة. يبدأ بنفحات التوابل المنعشة مع قلب غني باللافندر الفاخر وقاعدة من الأخشاب الدافئة واللبان التي تمنحه فوحاناً استثنائياً يدوم لأيام.',
                'price_yer': Decimal('95000.00'),
                'compare_at_price_yer': Decimal('115000.00'),
                'has_grades': True,
                'price_original_yer': Decimal('95000.00'),
                'price_master_yer': Decimal('35000.00'),
                'stock_quantity': 15,
                'is_featured': True,
                'is_best_seller': True,
                'specifications': {
                    'top_notes': ['الجريب فروت', 'الهيل الفاخر', 'القرفة', 'جوزة الطيب'],
                    'heart_notes': ['اللافندر الفرنسي الفاخر'],
                    'base_notes': ['العنبر النقي', 'الباتشولي', 'نجيل الهند', 'خشب الصندل'],
                    'concentration': 'Parfum Extrême (فائق التركيز)',
                    'volume_ml': 60,
                    'gender': 'رجالي ملكي',
                },
                'image': 'https://images.unsplash.com/photo-1523293182086-7651a899d37f?auto=format&fit=crop&w=800&q=80',
            },
            {
                'category': cat_objects['perfumes'],
                'name_ar': 'عطر توم فورد توباكو فانيلا',
                'name_en': 'Tom Ford Tobacco Vanille',
                'slug': 'tom-ford-tobacco-vanille',
                'brand_name': 'Tom Ford',
                'description': 'عطر دافئ وأنيق يجمع بين أوراق التبغ الفاخرة والفانيليا الغنية والتوابل الدافئة. اختيار الملوك وعشاق الهيبة والرقي في المناسبات الكبرى.',
                'price_yer': Decimal('145000.00'),
                'compare_at_price_yer': Decimal('170000.00'),
                'has_grades': True,
                'price_original_yer': Decimal('145000.00'),
                'price_master_yer': Decimal('42000.00'),
                'stock_quantity': 10,
                'is_featured': True,
                'is_best_seller': True,
                'specifications': {
                    'top_notes': ['أوراق التبغ الكاريبي', 'التوابل الشرقية الدافئة'],
                    'heart_notes': ['فانيليا مدغشقر', 'الكاكاو الغني', 'حبوب التونكا'],
                    'base_notes': ['الفواكه المجففة', 'خشب الصندل العتيق'],
                    'concentration': 'Eau de Parfum',
                    'volume_ml': 100,
                    'gender': 'للجنسين (Unisex)',
                },
                'image': 'https://images.unsplash.com/photo-1594035910387-fea47794261f?auto=format&fit=crop&w=800&q=80',
            },
            {
                'category': cat_objects['perfumes'],
                'name_ar': 'عطر ميس ديور بلومينغ بوكيه النسائي',
                'name_en': 'Miss Dior Blooming Bouquet',
                'slug': 'miss-dior-blooming-bouquet',
                'brand_name': 'Dior',
                'description': 'قصيدة من الزهور الندية، يجمع بين الفاوانيا الوردية والورد الدمشقي مع لمسة ناعمة من المسك الأبيض. عطر يعبر عن الأنوثة والانتعاش المخملي.',
                'price_yer': Decimal('88000.00'),
                'compare_at_price_yer': Decimal('100000.00'),
                'has_grades': True,
                'price_original_yer': Decimal('88000.00'),
                'price_master_yer': Decimal('32000.00'),
                'stock_quantity': 12,
                'is_featured': True,
                'is_best_seller': False,
                'specifications': {
                    'top_notes': ['برغموت كالابريا المنعش'],
                    'heart_notes': ['الفاوانيا الوردية', 'الورد الدمشقي النقي'],
                    'base_notes': ['المسك الأبيض الناعم'],
                    'concentration': 'Eau de Toilette',
                    'volume_ml': 100,
                    'gender': 'نسائي ناعم',
                },
                'image': 'https://images.unsplash.com/photo-1588405748880-12d1d2a59f75?auto=format&fit=crop&w=800&q=80',
            },
            {
                'category': cat_objects['perfumes'],
                'name_ar': 'عطر كريد أفينتوس الأصلي الملكي',
                'name_en': 'Creed Aventus Eau de Parfum',
                'slug': 'creed-aventus-edp',
                'brand_name': 'Creed',
                'description': 'العطر الأكثر شهرة وتأثيراً في العالم. يحتفي بالقوة والرؤية والنجاح بمزيج مدهش من الأناناس المدخن والباتشولي وطحلب السنديان والمسك.',
                'price_yer': Decimal('180000.00'),
                'compare_at_price_yer': Decimal('210000.00'),
                'has_grades': True,
                'price_original_yer': Decimal('180000.00'),
                'price_master_yer': Decimal('48000.00'),
                'stock_quantity': 8,
                'is_featured': True,
                'is_best_seller': True,
                'specifications': {
                    'top_notes': ['الأناناس الملكي', 'الكشمش الأسود', 'التفاح الأخضر', 'البرغموت'],
                    'heart_notes': ['خشب البتولا المدخن', 'الياسمين المغربي', 'الباتشولي'],
                    'base_notes': ['المسك النقي', 'طحلب السنديان', 'العنبر', 'الفانيليا'],
                    'concentration': 'Millésime Eau de Parfum',
                    'volume_ml': 100,
                    'gender': 'رجالي فاخر',
                },
                'image': 'https://images.unsplash.com/photo-1523293182086-7651a899d37f?auto=format&fit=crop&w=800&q=80',
            },

            # الساعات
            {
                'category': cat_objects['watches'],
                'name_ar': 'ساعة رولكس صبمارينر ديت الأيقونية',
                'name_en': 'Rolex Submariner Date Ceramic',
                'slug': 'rolex-submariner-date',
                'brand_name': 'Rolex',
                'description': 'ساعة الغوص الأيقونية المصنوعة من فولاذ Oystersteel عالي المتانة ومقاوم للتآكل. إطار سيراكروم أسود دوار، وميناء مضيء بتقنية Chromalight تدوم لساعات.',
                'price_yer': Decimal('450000.00'),
                'compare_at_price_yer': Decimal('520000.00'),
                'stock_quantity': 5,
                'is_featured': True,
                'is_best_seller': True,
                'specifications': {
                    'dial_size_mm': 41,
                    'movement': 'أوتوماتيك سويسري فائق الدقة (Calibre 3235)',
                    'strap_material': 'ستانلس ستيل 904L مع قفل Glidelock',
                    'water_resistance': '300 متر / 1000 قدم',
                    'warranty_years': 5,
                },
                'image': 'https://images.unsplash.com/photo-1522335789203-aabd1fc54bc9?auto=format&fit=crop&w=800&q=80',
            },
            {
                'category': cat_objects['watches'],
                'name_ar': 'ساعة تيسوت بي آر إكس أوتوماتيك زرقاء',
                'name_en': 'Tissot PRX Powermatic 80',
                'slug': 'tissot-prx-powermatic-80',
                'brand_name': 'Tissot',
                'description': 'تصميم رترو فاخر من حقبة السبعينيات مع سوار مدمج وميناء أزرق بنقشة الوافل. مزودة بمحرك Powermatic 80 الذي يمنحك احتياطي طاقة يصل إلى 80 ساعة.',
                'price_yer': Decimal('165000.00'),
                'compare_at_price_yer': Decimal('190000.00'),
                'stock_quantity': 7,
                'is_featured': True,
                'is_best_seller': False,
                'specifications': {
                    'dial_size_mm': 40,
                    'movement': 'سويسري أوتوماتيك احتياطي 80 ساعة',
                    'strap_material': 'سوار فولاذي متكامل مريح',
                    'water_resistance': '100 متر (مقاومة للسباحة)',
                    'warranty_years': 2,
                },
                'image': 'https://images.unsplash.com/photo-1524805444758-089113d48a6d?auto=format&fit=crop&w=800&q=80',
            },
            {
                'category': cat_objects['watches'],
                'name_ar': 'ساعة كاسيو إيديفيس كرونوغراف الرياضية',
                'name_en': 'Casio Edifice Chronograph',
                'slug': 'casio-edifice-chronograph',
                'brand_name': 'Casio',
                'description': 'ساعة رياضية يابانية بمظهر فولاذي فخم وعدسات ياقوتية مقاومة للخدش مع عقارب كرونوغراف دقيقة ومقاومة للماء حتى 100 متر.',
                'price_yer': Decimal('55000.00'),
                'compare_at_price_yer': Decimal('65000.00'),
                'stock_quantity': 20,
                'is_featured': False,
                'is_best_seller': True,
                'specifications': {
                    'dial_size_mm': 44,
                    'movement': 'كوارتز ياباني دقيق',
                    'strap_material': 'ستانلس ستيل صلب',
                    'water_resistance': '100 متر',
                    'warranty_years': 2,
                },
                'image': 'https://images.unsplash.com/photo-1548036328-c9fa89d128fa?auto=format&fit=crop&w=800&q=80',
            },

            # مستحضرات التجميل والعناية
            {
                'category': cat_objects['cosmetics'],
                'name_ar': 'أحمر شفاه شارلوت تلبوري مات بيلو توك',
                'name_en': 'Charlotte Tilbury Matte Revolution Pillow Talk',
                'slug': 'charlotte-tilbury-pillow-talk',
                'brand_name': 'Charlotte Tilbury',
                'description': 'الدرجة الأيقونية الأكثر مبيعاً حول العالم. لون نود وردي مخملي يدوم طويلاً مع تركيبة مرطبة تمنح الشفاه امتلاءً ونعومة حريرية.',
                'price_yer': Decimal('26000.00'),
                'compare_at_price_yer': Decimal('32000.00'),
                'stock_quantity': 25,
                'is_featured': True,
                'is_best_seller': True,
                'specifications': {
                    'shade_name': 'Pillow Talk Original (وردي نود أيقوني)',
                    'shade_code': '#C97D7D',
                    'skin_type': 'مناسب لجميع ألوان وأنواع البشرة',
                    'volume_or_weight': '3.5 جرام',
                },
                'image': 'https://images.unsplash.com/photo-1586495777744-4413f21062fa?auto=format&fit=crop&w=800&q=80',
            },
            {
                'category': cat_objects['care'],
                'name_ar': 'سيروم نياسيناميد 10% + زنك 1% من ذا أورديناري',
                'name_en': 'The Ordinary Niacinamide 10% + Zinc 1%',
                'slug': 'the-ordinary-niacinamide',
                'brand_name': 'The Ordinary',
                'description': 'سيروم علاجي عالي التركيز لتنقية البشرة وتقليل مظهر المسام والشوائب وتفتيح آثار البقع وتوحيد لون البشرة.',
                'price_yer': Decimal('12500.00'),
                'compare_at_price_yer': Decimal('16000.00'),
                'stock_quantity': 40,
                'is_featured': True,
                'is_best_seller': True,
                'specifications': {
                    'skin_type': 'البشرة المختلطة، الدهنية، والمعرضة للحبوب',
                    'volume_or_weight': '30 مل (ml)',
                    'shade_name': 'شفاف مائي سريع الامتصاص',
                    'shade_code': '#F3F4F6',
                },
                'image': 'https://images.unsplash.com/photo-1620916566398-39f1143ab7be?auto=format&fit=crop&w=800&q=80',
            },
            {
                'category': cat_objects['cosmetics'],
                'name_ar': 'ماسكارا ديور شو بومب آند فوليوم لتكثيف الرموش',
                'name_en': "Diorshow Pump 'N' Volume XXL Mascara",
                'slug': 'diorshow-pump-volume-mascara',
                'brand_name': 'Dior',
                'description': 'ماسكارا ديور الثورية بأنبوب قابل للضغط لتليين التركيبة وتكثيف الرموش بحجم فوري مضاعف دون تكتل مع ثبات مقاوم للرطوبة.',
                'price_yer': Decimal('29000.00'),
                'compare_at_price_yer': Decimal('35000.00'),
                'stock_quantity': 18,
                'is_featured': False,
                'is_best_seller': False,
                'specifications': {
                    'shade_name': '090 Black (أسود فحمي كثيف)',
                    'shade_code': '#111827',
                    'skin_type': 'مناسبة للعيون الحساسة ومستخدمي العدسات',
                    'volume_or_weight': '6 مل',
                },
                'image': 'https://images.unsplash.com/photo-1512496015851-a90fb38ba796?auto=format&fit=crop&w=800&q=80',
            },
            # باقات الهدايا (Bundles)
            {
                'category': cat_objects['bundles'],
                'name_ar': 'باقة إهداء رجالية (عطر سوفاج + ساعة كلاسيكية)',
                'name_en': 'Men Gift Set (Sauvage + Classic Watch)',
                'slug': 'men-gift-set-sauvage',
                'brand_name': 'Brand Veloura',
                'description': 'باقة إهداء منسقة تشمل عطر ديور سوفاج إكسير مع ساعة ستيل، مع التغليف وبطاقة إهداء.',
                'price_yer': Decimal('115000.00'),
                'compare_at_price_yer': Decimal('145000.00'),
                'has_grades': False,
                'stock_quantity': 10,
                'is_featured': True,
                'is_best_seller': True,
                'specifications': {
                    'box_content': 'عطر سوفاج 60 مل + ساعة ستانلس ستيل + بطاقة إهداء',
                    'wrapping_style': 'صندوق هدايا مع شريط وبطاقة',
                },
                'image': 'https://images.unsplash.com/photo-1549465220-1a8b9238cd48?auto=format&fit=crop&w=800&q=80',
            },
            {
                'category': cat_objects['bundles'],
                'name_ar': 'باقة إهداء نسائية (شانيل كوكو + مسك)',
                'name_en': 'Women Gift Set (Chanel + Musk)',
                'slug': 'women-gift-set-chanel',
                'brand_name': 'Brand Veloura',
                'description': 'باقة إهداء نسائية تشمل عطر كوكو مادموزيل من شانيل مع تولة مسك ومرطب ديور مع التغليف وبطاقة إهداء.',
                'price_yer': Decimal('128000.00'),
                'compare_at_price_yer': Decimal('160000.00'),
                'has_grades': False,
                'stock_quantity': 8,
                'is_featured': True,
                'is_best_seller': True,
                'specifications': {
                    'box_content': 'عطر كوكو شانيل 100 مل + تولة مسك + مرطب ديور',
                    'wrapping_style': 'صندوق هدايا مع شريط وبطاقة',
                },
                'image': 'https://images.unsplash.com/photo-1513519245088-0e12902e5a38?auto=format&fit=crop&w=800&q=80',
            },
        ]

        for p in products_data:
            img_url = p.pop('image')
            product, created = Product.objects.update_or_create(
                slug=p['slug'],
                defaults=p
            )
            # إضافة الصورة كصورة رئيسية
            ProductImage.objects.get_or_create(
                product=product,
                image_url_fallback=img_url,
                defaults={'is_primary': True, 'display_order': 0}
            )

        self.stdout.write(self.style.SUCCESS(f'[OK] Inserted {len(products_data)} luxury products with notes and specs'))
        self.stdout.write(self.style.SUCCESS('[SUCCESS] Brand Veloura store is 100% ready and seeded!'))
