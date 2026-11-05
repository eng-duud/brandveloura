from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from store.models import (
    Notification, Order, OrderItem, Product, Category,
    PaymentAccount, ShippingZone, StoreSettings
)


class NotificationSystemTests(TestCase):
    def setUp(self):
        self.client = Client()
        
        # إنشاء إعدادات المتجر
        self.settings = StoreSettings.objects.create(
            store_name='Brand Veloura Test',
            yer_per_sar=Decimal('530.00'),
            gift_wrapping_fee_yer=Decimal('2000.00')
        )
        
        # إنشاء مستخدم عادي ومستخدم مشرف
        self.user = User.objects.create_user(
            username='customer_user',
            password='Password123!',
            email='customer@example.com',
            first_name='فاطمة'
        )
        self.staff_user = User.objects.create_superuser(
            username='admin_staff',
            password='AdminPassword123!',
            email='admin@example.com'
        )
        
        # تصنيف ومنتج
        self.category = Category.objects.create(
            name_ar='عطور نسائية',
            name_en='Women Perfumes',
            category_type='perfumes',
            slug='women-perfumes'
        )
        self.product = Product.objects.create(
            category=self.category,
            name_ar='عطر لافندر فيلورا',
            name_en='Veloura Lavender',
            slug='veloura-lavender',
            brand_name='Veloura',
            price_yer=Decimal('45000.00'),
            stock_quantity=5,
            is_active=True
        )
        
        # منطقة شحن وطريقة دفع
        self.zone = ShippingZone.objects.create(
            city_name='صنعاء',
            delivery_fee_yer=Decimal('2500.00'),
            is_active=True
        )
        self.payment = PaymentAccount.objects.create(
            provider_name='كريمي جوال',
            account_holder_name='بوتيك فيلورا',
            account_number='12345678',
            currency='YER',
            is_active=True
        )

    def test_notification_creation_and_helper_methods(self):
        """اختبار إنشاء الإشعار والوظائف المساعدة"""
        notif = Notification.notify_user(
            user=self.user,
            title='مرحباً بكم في براند فيلورا',
            message='سعداء بانضمامكم إلينا',
            notification_type='system'
        )
        self.assertIsNotNone(notif)
        self.assertEqual(notif.recipient, self.user)
        self.assertFalse(notif.is_read)
        self.assertFalse(notif.for_admin)
        self.assertIn('مرحباً', str(notif))

        # اختبار تحديد كمقروء
        notif.mark_as_read()
        self.assertTrue(notif.is_read)

        # اختبار تنبيه الإدارة
        admin_notif = Notification.notify_admin(
            title='تنبيه أمان',
            message='تم تسجيل محاولة جديدة',
            notification_type='system'
        )
        self.assertTrue(admin_notif.for_admin)
        self.assertIsNone(admin_notif.recipient)

    def test_order_status_change_triggers_user_notification(self):
        """اختبار إرسال إشعار للعميل المسجل تلقائياً عند تحديث حالة طلبه"""
        order = Order.objects.create(
            order_number='BV-TEST01',
            user=self.user,
            customer_name='فاطمة',
            customer_phone='777123456',
            customer_email=self.user.email,
            shipping_city='صنعاء',
            shipping_address='شارع بغداد',
            shipping_fee_yer=Decimal('2500.00'),
            subtotal_yer=Decimal('45000.00'),
            total_yer=Decimal('47500.00'),
            total_sar=Decimal('89.6'),
            exchange_rate_applied=Decimal('530.00'),
            status='pending_verification',
            stock_deducted=True
        )

        initial_count = Notification.objects.filter(recipient=self.user).count()

        # تحديث الحالة إلى 'payment_verified'
        order.status = 'payment_verified'
        order.save()

        user_notifications = Notification.objects.filter(recipient=self.user)
        self.assertEqual(user_notifications.count(), initial_count + 1)
        latest = user_notifications.first()
        self.assertEqual(latest.notification_type, 'payment_verified')
        self.assertIn('BV-TEST01', latest.title)
        self.assertFalse(latest.is_read)

        # تحديث الحالة إلى 'out_for_delivery'
        order.status = 'out_for_delivery'
        order.save()
        self.assertEqual(Notification.objects.filter(recipient=self.user).count(), initial_count + 2)

    def test_checkout_creates_notifications_and_low_stock_alert(self):
        """اختبار إطلاق الإشعارات عند إتمام الشراء، وتنبيه الإدارة عند انخفاض المخزون"""
        self.client.force_login(self.user)
        
        # وضع المنتج في السلة بكمية 3 (مخزونه الأصلي 5، سيتبقى 2 مما يطلق تنبيه انخفاض المخزون)
        session = self.client.session
        session['cart'] = {
            f"{self.product.id}_default": {
                'product_id': self.product.id,
                'name': self.product.name_ar,
                'brand': self.product.brand_name,
                'price_yer': float(self.product.price_yer),
                'quantity': 3,
                'variant_info': 'حجم 100 مل'
            }
        }
        session.save()

        post_data = {
            'customer_name': 'فاطمة أحمد',
            'customer_phone': '777000111',
            'customer_email': 'fatima@example.com',
            'shipping_city': self.zone.id,
            'shipping_address': 'حدة - صنعاء',
            'payment_method': self.payment.id,
            'payment_reference_no': 'REF-998877',
        }

        response = self.client.post(reverse('store:checkout'), post_data)
        self.assertEqual(response.status_code, 302)

        # 1. التحقق من وصول إشعار للعميل
        user_notif = Notification.objects.filter(recipient=self.user, notification_type='order_created').first()
        self.assertIsNotNone(user_notif)
        self.assertIn('تم استلام طلبكم', user_notif.title)

        # 2. التحقق من وصول تنبيه طلب جديد للإدارة
        admin_order_notif = Notification.objects.filter(for_admin=True, notification_type='order_created').first()
        self.assertIsNotNone(admin_order_notif)
        self.assertIn('طلب جديد', admin_order_notif.title)

        # 3. التحقق من إطلاق تنبيه انخفاض المخزون لأن الكمية أصبحت 2 (<= 3)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 2)
        low_stock_notif = Notification.objects.filter(for_admin=True, notification_type='low_stock').first()
        self.assertIsNotNone(low_stock_notif)
        self.assertIn('انخفاض المخزون', low_stock_notif.title)

    def test_notification_endpoints(self):
        """اختبار نقاط النهاية التفاعلية (HTMX Endpoints)"""
        # إنشاء بعض الإشعارات للمستخدم
        n1 = Notification.notify_user(self.user, 'إشعار 1', 'محتوى 1')
        n2 = Notification.notify_user(self.user, 'إشعار 2', 'محتوى 2')

        # فحص الشارة بدون تسجيل الدخول
        res = self.client.get(reverse('store:notification_badge'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'hidden')

        # تسجيل الدخول وفحص الشارة
        self.client.force_login(self.user)
        res = self.client.get(reverse('store:notification_badge'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '2')

        # فحص القائمة المنسدلة (Dropdown)
        res = self.client.get(reverse('store:notifications_dropdown'), HTTP_HX_REQUEST='true')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'إشعار 1')
        self.assertContains(res, 'إشعار 2')

        # تحديد إشعار واحد كمقروء
        read_res = self.client.post(
            reverse('store:mark_notification_read', args=[n1.id]),
            HTTP_HX_REQUEST='true'
        )
        self.assertEqual(read_res.status_code, 200)
        n1.refresh_from_db()
        self.assertTrue(n1.is_read)

        # تحديد الكل كمقروء
        mark_all_res = self.client.post(
            reverse('store:mark_all_notifications_read'),
            HTTP_HX_REQUEST='true'
        )
        self.assertEqual(mark_all_res.status_code, 200)
        n2.refresh_from_db()
        self.assertTrue(n2.is_read)
        self.assertEqual(Notification.objects.filter(recipient=self.user, is_read=False).count(), 0)

    def test_account_notifications_tab(self):
        """اختبار ظهور الإشعارات في صفحة الحساب الشخصي"""
        Notification.notify_user(self.user, 'تحديث حسابك', 'تم تسجيل الدخول بنجاح')
        self.client.force_login(self.user)

        res = self.client.get(reverse('store:account_profile') + '?tab=notifications')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'مركز الإشعارات والتنبيهات')
        self.assertContains(res, 'تحديث حسابك')
