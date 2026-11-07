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

    def test_push_vapid_key_endpoint(self):
        """اختبار توفير المفتاح العام VAPID للأجهزة"""
        res = self.client.get(reverse('store:push_vapid_key'))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('publicKey', data)
        self.assertTrue(len(data['publicKey']) > 20)

    def test_push_subscribe_endpoint(self):
        """اختبار تسجيل اشتراك جهاز جديد في إشعارات الويب"""
        import json
        from store.models import WebPushSubscription
        payload = {
            'endpoint': 'https://fcm.googleapis.com/fcm/send/test-device-token-12345',
            'keys': {
                'p256dh': 'BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QT9t0Ppk6YsklTuW324gn9T4',
                'auth': 'tBHItJI5svbpez7KI4CCXg'
            }
        }
        res = self.client.post(
            reverse('store:push_subscribe'),
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('success'))
        self.assertTrue(WebPushSubscription.objects.filter(endpoint=payload['endpoint']).exists())

    def test_service_worker_contains_push_events(self):
        """اختبار أن ملف sw.js يحتوي على مستمعات إشعارات الدفع والنقر"""
        res = self.client.get('/sw.js')
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertIn("addEventListener('push'", content)
        self.assertIn("addEventListener('notificationclick'", content)

    def test_send_product_promotion_push(self):
        """اختبار إنشاء إشعار ترويجي عند عمل تخفيض على منتج"""
        from store.push_notifications import send_product_promotion_push
        from store.models import Notification
        self.product.compare_at_price_yer = Decimal('60000.00')
        self.product.save()

        count = send_product_promotion_push(self.product)
        # Should record a notification in Notification log
        notif = Notification.objects.filter(notification_type='promotion').latest('created_at')
        self.assertIn('تخفيض حصري', notif.title)
        self.assertIn(self.product.name_ar, notif.title)
        self.assertEqual(notif.link, f"/product/{self.product.slug}/")

    def test_pwa_notification_permission_prompt_persistence_and_events(self):
        """اختبار ثبات كارت إذن الإشعارات واستماعه لأحداث التثبيت والوضع المستقل PWA"""
        res = self.client.get(reverse('store:home'))
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')

        # 1. كارت إذن الإشعارات موجود في الصفحة
        self.assertIn('id="pwa-notif-card"', content)
        self.assertIn('تفعيل إشعارات المتجر', content)
        self.assertIn('requestPushPermission()', content)
        self.assertIn('dismissNotifPrompt()', content)

        # 2. الاستماع لحدث اكتمال التثبيت appinstalled
        self.assertIn("window.addEventListener('appinstalled'", content)

        # 3. التحقق من الوضع المستقل PWA standalone
        self.assertIn("display-mode: standalone", content)
        self.assertIn("checkStandaloneNotificationPrompt", content)

        # 4. عدم استخدام إخفاء دائم لمدة 7 أيام بل مؤقت للجلسة sessionStorage
        self.assertNotIn("7 * 24 * 60 * 60 * 1000", content)
        self.assertIn("sessionStorage.setItem('bv_notif_dismissed', 'true')", content)
        self.assertIn("sessionStorage.removeItem('bv_notif_dismissed')", content)

        # 5. الإخفاء الدائم يتم فقط بعد الموافقة Notification.permission === 'granted'
        self.assertIn("Notification.permission === 'granted'", content)
        self.assertIn("localStorage.setItem('bv_notif_granted', 'true')", content)
        self.assertIn("localStorage.getItem('bv_notif_granted')", content)
        self.assertIn("scheduleNotifPrompt", content)

    def test_push_subscribe_invalid_payload(self):
        """اختبار رفض البيانات غير المكتملة في اشتراك إشعارات الويب 400"""
        import json
        res = self.client.post(
            reverse('store:push_subscribe'),
            data=json.dumps({'endpoint': ''}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertIn('error', data)

