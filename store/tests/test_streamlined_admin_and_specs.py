from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.contrib.admin.sites import AdminSite
from django.urls import reverse
from store.models import Category, Brand, Product, StoreSettings
from store.admin import ProductAdmin, CategoryAdmin


class StreamlinedProductAndCategoryTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.settings = StoreSettings.get_settings()
        self.admin_user = User.objects.create_superuser(
            username="streamline_admin",
            email="admin@test.com",
            password="AdminPassword2026!"
        )
        self.category = Category.objects.create(
            name_ar="عطور فاخرة",
            name_en="Luxury Perfumes",
            slug="luxury-perfumes",
            category_type="perfumes"
        )
        self.brand_chanel = Brand.objects.create(
            name_ar="شانيل",
            name_en="Chanel",
            slug="chanel"
        )
        self.brand_creed = Brand.objects.create(
            name_ar="",
            name_en="Creed",
            slug="creed"
        )

    def test_product_save_synchronizes_brand_name_from_brand(self):
        """التحقق من مزامنة brand_name تلقائياً من الماركة المحددة في Product.save()"""
        # عند اختيار ماركة لها اسم عربي وإنجليزي
        p1 = Product.objects.create(
            name_ar="بلو دي شانيل",
            category=self.category,
            brand=self.brand_chanel,
            price_yer=Decimal('75000')
        )
        self.assertEqual(p1.brand_name, "شانيل")
        self.assertEqual(p1.effective_brand_name, "شانيل")

        # عند اختيار ماركة لها اسم إنجليزي فقط
        p2 = Product.objects.create(
            name_ar="أفنتوس",
            category=self.category,
            brand=self.brand_creed,
            price_yer=Decimal('120000')
        )
        self.assertEqual(p2.brand_name, "Creed")
        self.assertEqual(p2.effective_brand_name, "Creed")

        # عند تعديل الماركة تتحدث الماركة النصية آلياً
        p1.brand = self.brand_creed
        p1.save()
        self.assertEqual(p1.brand_name, "Creed")

        # عند عدم تحديد ماركة خارجية، يبقى brand_name كما هو إذا حُدد يدوياً
        p3 = Product.objects.create(
            name_ar="عطر خاص",
            category=self.category,
            brand=None,
            brand_name="دار فيلورا",
            price_yer=Decimal('50000')
        )
        self.assertEqual(p3.brand_name, "دار فيلورا")

    def test_product_admin_fieldsets_no_duplicate_brand_and_no_specifications(self):
        """التحقق من إزالة حقل الماركة المكرر وحذف قسم المواصفات من ProductAdmin"""
        site = AdminSite()
        product_admin = ProductAdmin(Product, site)

        all_fields = []
        fieldset_titles = []
        for title, opts in product_admin.fieldsets:
            fieldset_titles.append(title)
            fields = opts.get('fields', ())
            for field in fields:
                if isinstance(field, (list, tuple)):
                    all_fields.extend(field)
                else:
                    all_fields.append(field)

        # التأكد من وجود brand وعدم وجود brand_name في fieldsets
        self.assertIn('brand', all_fields)
        self.assertNotIn('brand_name', all_fields)

        # التأكد من عدم وجود specifications في الحقول
        self.assertNotIn('specifications', all_fields)

        # التأكد من إزالة عنوان fieldset المواصفات
        for title in fieldset_titles:
            self.assertNotIn('المواصفات الفنية التفصيلية', title)
            self.assertNotIn('JSON Specifications', title)

    def test_category_choices_streamlined(self):
        """التحقق من أن خيارات أنواع الأقسام تقتصر على عطور، ساعات، وعام فقط"""
        expected_keys = {'perfumes', 'watches', 'general'}
        actual_keys = {choice[0] for choice in Category.CATEGORY_TYPES}
        self.assertEqual(actual_keys, expected_keys)

        # التأكد من إزالة الأقسام غير المستخدمة من الخيارات الأساسية
        self.assertNotIn('cosmetics', actual_keys)
        self.assertNotIn('care', actual_keys)
        self.assertNotIn('bundles', actual_keys)

    def test_category_admin_form_choices_and_legacy_compatibility(self):
        """التحقق من أن نموذج إضافة قسم جديد يقتصر على الأقسام المعتمدة، مع دعم الأقسام القديمة"""
        site = AdminSite()
        cat_admin = CategoryAdmin(Category, site)

        # عند إضافة قسم جديد (obj=None)
        form_class_add = cat_admin.get_form(None, obj=None)
        form_add = form_class_add()
        add_choices = [c[0] for c in form_add.fields['category_type'].choices]
        self.assertEqual(set(add_choices), {'perfumes', 'watches', 'general'})
        self.assertNotIn('cosmetics', add_choices)
        self.assertNotIn('care', add_choices)
        self.assertNotIn('bundles', add_choices)

        # عند تعديل قسم موجود مسبقاً بنوع قديم (backward compatibility)
        legacy_cat = Category.objects.create(
            name_ar="مستحضرات تجميل قديمة",
            slug="old-cosmetics",
            category_type="cosmetics"
        )
        form_class_edit = cat_admin.get_form(None, obj=legacy_cat)
        form_edit = form_class_edit(instance=legacy_cat)
        edit_choices = [c[0] for c in form_edit.fields['category_type'].choices]
        self.assertIn('cosmetics', edit_choices)

        # فحص إمكانية حفظ القسم القديم عبر لوحة الإدارة دون أخطاء تحقق
        self.client.force_login(self.admin_user)
        post_data = {
            'name_ar': 'مستحضرات تجميل محدثة',
            'name_en': 'Updated Cosmetics',
            'slug': 'old-cosmetics',
            'category_type': 'cosmetics',
            'description': 'وصف تجريبي',
            'display_order': '5',
            'is_featured': 'on',
            'is_active': 'on',
            '_save': 'Save'
        }
        res = self.client.post(f'/admin/store/category/{legacy_cat.id}/change/', post_data, follow=True)
        self.assertEqual(res.status_code, 200)
        legacy_cat.refresh_from_db()
        self.assertEqual(legacy_cat.name_ar, 'مستحضرات تجميل محدثة')

    def test_product_detail_and_quick_view_omit_specifications(self):
        """التحقق من حذف بلوك المواصفات الفنية والتركيز على وصف المنتج في صفحة المنتج ونافذة النظرة السريعة"""
        product = Product.objects.create(
            name_ar="عطر مسك الفخامة",
            slug="luxury-musk",
            category=self.category,
            brand=self.brand_chanel,
            description="عطر شرقي فاخر بنفحات المسك والورد الطائفي الأصيل.",
            price_yer=Decimal('60000'),
            specifications={
                "concentration": "Eau de Parfum",
                "volume_ml": "100",
                "top_notes": ["مسك", "ورد طائفي"]
            }
        )

        # 1. فحص صفحة المنتج الكاملة
        detail_url = reverse('store:product_detail', kwargs={'slug': product.slug})
        res_detail = self.client.get(detail_url)
        self.assertEqual(res_detail.status_code, 200)
        content_detail = res_detail.content.decode('utf-8')

        # يجب أن يظهر وصف المنتج
        self.assertIn("وصف المنتج", content_detail)
        self.assertIn("عطر شرقي فاخر بنفحات المسك والورد الطائفي الأصيل.", content_detail)
        # يجب ألا تظهر شبكة المواصفات الفنية
        self.assertNotIn("الوصف والمواصفات", content_detail)
        self.assertNotIn("المكونات العطرية", content_detail)

        # 2. فحص النافذة المنبثقة Quick View
        quick_view_url = reverse('store:product_modal', kwargs={'slug': product.slug})
        res_qv = self.client.get(quick_view_url)
        self.assertEqual(res_qv.status_code, 200)
        content_qv = res_qv.content.decode('utf-8')

        # يجب أن يظهر وصف المنتج
        self.assertIn("عطر شرقي فاخر بنفحات المسك والورد الطائفي الأصيل.", content_qv)
        # يجب ألا يظهر بلوك المواصفات الفنية
        self.assertNotIn("المواصفات الفنية", content_qv)
        self.assertNotIn("ورد طائفي", content_qv)

    def test_admin_product_add_post_synchronizes_brand_name(self):
        """التحقق من إنشاء وتعديل منتج عبر نموذج الإدارة ومزامنة اسم الماركة تلقائياً"""
        self.client.force_login(self.admin_user)
        post_data = {
            'category': self.category.id,
            'brand': self.brand_chanel.id,
            'name_ar': 'عطر شانيل الحصري',
            'name_en': 'Chanel Exclusive Perfume',
            'price_yer': '85000',
            'stock_quantity': '10',
            'images-TOTAL_FORMS': '0',
            'images-INITIAL_FORMS': '0',
            'images-MIN_NUM_FORMS': '0',
            'images-MAX_NUM_FORMS': '1000',
            '_save': 'Save'
        }
        res = self.client.post('/admin/store/product/add/', post_data, follow=True)
        self.assertEqual(res.status_code, 200)
        product = Product.objects.filter(name_ar='عطر شانيل الحصري').first()
        self.assertIsNotNone(product)
        self.assertEqual(product.brand_name, 'شانيل')
        self.assertEqual(product.effective_brand_name, 'شانيل')

        # تعديل المنتج وتغيير الماركة إلى ماركة أخرى
        post_data_edit = {
            'category': self.category.id,
            'brand': self.brand_creed.id,
            'name_ar': 'عطر شانيل الحصري',
            'name_en': 'Chanel Exclusive Perfume',
            'price_yer': '85000',
            'stock_quantity': '10',
            'slug': product.slug,
            'images-TOTAL_FORMS': '0',
            'images-INITIAL_FORMS': '0',
            'images-MIN_NUM_FORMS': '0',
            'images-MAX_NUM_FORMS': '1000',
            '_save': 'Save'
        }
        res_edit = self.client.post(f'/admin/store/product/{product.id}/change/', post_data_edit, follow=True)
        self.assertEqual(res_edit.status_code, 200)
        product.refresh_from_db()
        self.assertEqual(product.brand_name, 'Creed')
        self.assertEqual(product.effective_brand_name, 'Creed')
