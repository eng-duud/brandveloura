import base64
import json
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from urllib.parse import quote
from PIL import Image

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..models import (
    GiftBundle,
    Notification,
    Order,
    OrderItem,
    PaymentAccount,
    Product,
    ShippingZone,
    StoreSettings,
    UserProfile,
)
from ..cache_service import (
    cache_delete,
    invalidate_admin_metrics_cache,
    invalidate_notification_cache,
    schedule_invalidation,
)
from ..push_notifications import bind_order_push_endpoint, send_order_created_push
from .cart import check_and_expire_cart, get_cart_timing_context
from .helpers import (
    _admin_change_url,
    _is_authorized_for_order,
    _yer_to_sar,
    audit_logger,
    logger,
    validate_receipt_file,
)


def checkout_view(request):
    """صفحة إتمام الطلب، تدفق الهدايا والمغتربين، اختيار المدينة، ورفع السند مع فحص انتهاء حجز السلة"""
    if check_and_expire_cart(request):
        return redirect('store:cart_view')

    cart = request.session.get('cart', {})
    if not cart:
        messages.warning(request, 'سلة المشتريات فارغة، يرجى إضافة منتجات أولاً.')
        return redirect('store:product_list')

    settings = StoreSettings.get_settings()
    yer_per_sar = settings.yer_per_sar or Decimal('530.00')

    def _live_unit_price(item_data, products_lookup, bundles_lookup):
        if item_data.get('is_bundle'):
            b_id = item_data.get('bundle_id') or item_data.get('product_id')
            b_obj = bundles_lookup.get(b_id)
            if b_obj:
                return b_obj.price_yer, True
            return Decimal(str(item_data.get('price_yer', 0))), False
        p_id = item_data.get('product_id')
        p_grade = item_data.get('grade')
        p_obj = products_lookup.get(p_id)
        if not p_obj:
            return Decimal(str(item_data.get('price_yer', 0))), False
        if p_grade == 'master' and p_obj.price_master_yer:
            return p_obj.price_master_yer, True
        if (p_grade == 'original' or not p_grade) and p_obj.price_original_yer:
            return p_obj.price_original_yer, True
        return (p_obj.price_yer or Decimal(str(item_data.get('price_yer', 0)))), True

    cart_prod_ids = {
        v.get('product_id') for v in cart.values()
        if not v.get('is_bundle') and v.get('product_id')
    }
    cart_bundle_ids = {
        (v.get('bundle_id') or v.get('product_id')) for v in cart.values()
        if v.get('is_bundle') and (v.get('bundle_id') or v.get('product_id'))
    }
    preview_products = {p.id: p for p in Product.objects.filter(id__in=cart_prod_ids, is_active=True)} if cart_prod_ids else {}
    preview_bundles = {b.id: b for b in GiftBundle.objects.filter(id__in=cart_bundle_ids, is_active=True)} if cart_bundle_ids else {}

    subtotal_yer = Decimal('0.00')
    items = []
    for key, data in cart.items():
        qty = max(1, int(data.get('quantity', 1)))
        price_yer, _ = _live_unit_price(data, preview_products, preview_bundles)
        line_total = price_yer * qty
        subtotal_yer += line_total
        items.append({
            'name': data.get('name'),
            'brand': data.get('brand'),
            'quantity': qty,
            'price_yer': price_yer,
            'line_total': line_total,
            'variant_info': data.get('variant_info', ''),
        })

    payment_methods = list(PaymentAccount.objects.filter(is_active=True).order_by('display_order'))
    shipping_zones = list(ShippingZone.objects.filter(is_active=True).order_by('city_name'))
    user_profile = getattr(request.user, 'store_profile', None) if request.user.is_authenticated else None

    gift_data = request.session.get('gift_data', {})
    is_gift_active = bool(gift_data.get('is_gift', False))
    is_luxury_wrapping_active = is_gift_active and bool(gift_data.get('is_luxury_gift_wrapping', False))
    gift_wrapping_fee_yer = settings.gift_wrapping_fee_yer if is_luxury_wrapping_active else Decimal('0.00')

    default_zone = None
    if user_profile and user_profile.preferred_city:
        default_zone = next((z for z in shipping_zones if z.city_name == user_profile.preferred_city), None)
    if not default_zone and shipping_zones:
        default_zone = shipping_zones[0]
    shipping_fee_yer = default_zone.delivery_fee_yer if default_zone else Decimal('0.00')
    total_yer = subtotal_yer + shipping_fee_yer + gift_wrapping_fee_yer
    total_sar = _yer_to_sar(total_yer, yer_per_sar)

    if request.method == 'POST':
        order_type = request.POST.get('order_type', 'personal')
        is_gift = (order_type == 'gift') or (request.POST.get('is_gift') in ['true', '1', 'on'])

        customer_name = request.POST.get('customer_name', '').strip()
        customer_phone = request.POST.get('customer_phone', '').strip()
        customer_email = request.POST.get('customer_email', '').strip()
        if not customer_email and request.user.is_authenticated and request.user.email:
            customer_email = request.user.email
        city_id = request.POST.get('shipping_city')
        shipping_address = request.POST.get('shipping_address', '').strip()
        payment_method_id = request.POST.get('payment_method')
        payment_reference_no = request.POST.get('payment_reference_no', '').strip()
        customer_notes = request.POST.get('customer_notes', '').strip()

        if not customer_name or not customer_phone or not shipping_address:
            messages.error(request, 'يرجى تعبئة الاسم الكامل ورقم الهاتف وعنوان التوصيل قبل تأكيد الطلب.')
            return redirect('store:checkout')

        selected_zone = None
        if city_id:
            try:
                selected_zone = ShippingZone.objects.filter(id=city_id, is_active=True).first()
            except (ValueError, TypeError):
                selected_zone = None
            if not selected_zone:
                messages.error(request, 'منطقة التوصيل المختارة غير متاحة حالياً. يرجى اختيار مدينة صالحة.')
                return redirect('store:checkout')
        elif shipping_zones:
            messages.error(request, 'يرجى اختيار مدينة التوصيل.')
            return redirect('store:checkout')

        selected_payment = None
        if payment_method_id:
            try:
                selected_payment = PaymentAccount.objects.filter(id=payment_method_id, is_active=True).first()
            except (ValueError, TypeError):
                selected_payment = None
            if not selected_payment:
                messages.error(request, 'وسيلة الدفع المختارة غير متاحة حالياً.')
                return redirect('store:checkout')
        elif payment_methods:
            messages.error(request, 'يرجى اختيار وسيلة الدفع.')
            return redirect('store:checkout')

        payment_receipt = request.FILES.get('payment_receipt')
        if payment_receipt:
            is_valid, err_msg = validate_receipt_file(payment_receipt)
            if not is_valid:
                messages.error(request, err_msg)
                return redirect('store:checkout')

        if is_gift:
            recipient_name = request.POST.get('recipient_name', '').strip()
            recipient_phone = request.POST.get('recipient_phone', '').strip()
            gift_card_sender = request.POST.get('gift_card_sender', '').strip() or customer_name
            gift_card_recipient = request.POST.get('gift_card_recipient', '').strip() or recipient_name
            gift_card_message = request.POST.get('gift_card_message', '').strip()
            is_luxury_gift_wrapping = request.POST.get('is_luxury_gift_wrapping') in ['true', '1', 'on']
            preferred_date_raw = request.POST.get('preferred_delivery_date', '').strip()
            hide_invoice_prices = request.POST.get('hide_invoice_prices') in ['true', '1', 'on']
            gift_wrapping_fee_yer = settings.gift_wrapping_fee_yer if is_luxury_gift_wrapping else Decimal('0.00')

            preferred_delivery_date = None
            if preferred_date_raw:
                try:
                    parsed_d = datetime.strptime(preferred_date_raw, '%Y-%m-%d').date()
                    today = date.today()
                    if parsed_d < today:
                        preferred_delivery_date = today + timedelta(days=1)
                        messages.info(request, 'تم تعديل موعد التسليم لأقرب تاريخ شحن متاح لتفادي التواريخ السابقة.')
                    else:
                        preferred_delivery_date = parsed_d
                except (ValueError, TypeError):
                    preferred_delivery_date = None
        else:
            recipient_name = ''
            recipient_phone = ''
            gift_card_sender = ''
            gift_card_recipient = ''
            gift_card_message = ''
            is_luxury_gift_wrapping = False
            preferred_delivery_date = None
            hide_invoice_prices = False
            gift_wrapping_fee_yer = Decimal('0.00')

        city_name = selected_zone.city_name if selected_zone else 'غير محدد'
        actual_shipping_fee = selected_zone.delivery_fee_yer if selected_zone else Decimal('0.00')
        payment_name = selected_payment.provider_name if selected_payment else 'دفع يدوي'

        raw_currency_post = request.POST.get('payment_currency_selected', '').strip().upper()
        payment_currency_selected = raw_currency_post if raw_currency_post in ('YER', 'SAR') else 'YER'
        if selected_payment:
            if selected_payment.currency in ('YER', 'SAR'):
                payment_currency_selected = selected_payment.currency
            elif selected_payment.bank_country == 'SA' and not raw_currency_post:
                payment_currency_selected = 'SAR'

        while True:
            order_number = f"BV-{secrets.token_hex(4).upper()}"
            if not Order.objects.filter(order_number=order_number).exists():
                break

        with transaction.atomic():
            bundles_map = {
                b.id: b
                for b in GiftBundle.objects.prefetch_related('items__product').filter(id__in=cart_bundle_ids, is_active=True)
            } if cart_bundle_ids else {}

            needed_by_pid = {}
            label_by_pid = {}
            insufficient_items = []

            for item_data in cart.values():
                p_qty = max(1, int(item_data.get('quantity', 1)))
                if item_data.get('is_bundle'):
                    b_id = item_data.get('bundle_id') or item_data.get('product_id')
                    bundle_obj = bundles_map.get(b_id)
                    if not bundle_obj:
                        insufficient_items.append("الباقة المختارة غير متوفرة")
                        continue
                    for b_item in bundle_obj.items.all():
                        if not b_item.product_id or not b_item.product.is_active:
                            insufficient_items.append(f"{getattr(b_item.product, 'name_ar', 'منتج')} (ضمن {bundle_obj.title_ar} غير متوفر)")
                        else:
                            needed_by_pid[b_item.product_id] = needed_by_pid.get(b_item.product_id, 0) + (b_item.quantity * p_qty)
                            label_by_pid.setdefault(b_item.product_id, f"{b_item.product.name_ar} (ضمن {bundle_obj.title_ar})")
                else:
                    p_id = item_data.get('product_id')
                    if p_id:
                        needed_by_pid[p_id] = needed_by_pid.get(p_id, 0) + p_qty
                        label_by_pid.setdefault(p_id, item_data.get('name', 'منتج'))
                    else:
                        insufficient_items.append("منتج غير صالح")

            locked_products_map = {
                p.id: p
                for p in Product.objects.select_for_update().filter(id__in=sorted(needed_by_pid.keys()), is_active=True)
            } if needed_by_pid else {}

            for pid, needed_total in needed_by_pid.items():
                locked_prod = locked_products_map.get(pid)
                if not locked_prod or locked_prod.stock_quantity < needed_total:
                    avail = locked_prod.stock_quantity if locked_prod else 0
                    insufficient_items.append(f"{label_by_pid.get(pid, 'منتج')} (المطلوب: {needed_total}، المتوفر: {avail})")

            if insufficient_items:
                items_str = '، '.join(insufficient_items)
                messages.error(request, f"نعتذر، نفدت الكمية المتوفرة من بعض المنتجات: {items_str}. يرجى تعديل السلة.")
                return redirect('store:checkout')

            order_lines = []
            verified_subtotal_yer = Decimal('0.00')
            for item_data in cart.values():
                p_qty = max(1, int(item_data.get('quantity', 1)))
                live_price, is_live = _live_unit_price(item_data, locked_products_map, bundles_map)
                if not is_live:
                    messages.error(request, 'بعض المنتجات في السلة لم تعد متوفرة حالياً.')
                    return redirect('store:checkout')
                line_total_yer = live_price * p_qty
                verified_subtotal_yer += line_total_yer
                if item_data.get('is_bundle'):
                    b_id = item_data.get('bundle_id') or item_data.get('product_id')
                    order_lines.append((None, p_qty, item_data, bundles_map.get(b_id), live_price, line_total_yer))
                else:
                    prod_obj = locked_products_map.get(item_data.get('product_id'))
                    order_lines.append((prod_obj, p_qty, item_data, None, live_price, line_total_yer))

            order_total_yer = verified_subtotal_yer + actual_shipping_fee + gift_wrapping_fee_yer
            order_total_sar = _yer_to_sar(order_total_yer, yer_per_sar)
            amount_due = order_total_sar if payment_currency_selected == 'SAR' else order_total_yer

            order = Order.objects.create(
                order_number=order_number,
                user=request.user if request.user.is_authenticated else None,
                customer_name=customer_name,
                customer_phone=customer_phone,
                customer_email=customer_email,
                shipping_city=city_name,
                shipping_address=shipping_address,
                shipping_fee_yer=actual_shipping_fee,
                subtotal_yer=verified_subtotal_yer,
                total_yer=order_total_yer,
                total_sar=order_total_sar,
                exchange_rate_applied=yer_per_sar,
                payment_method=selected_payment,
                payment_method_name=payment_name,
                payment_receipt=payment_receipt,
                payment_reference_no=payment_reference_no,
                customer_notes=customer_notes,
                status='pending_verification',
                is_gift=is_gift,
                recipient_name=recipient_name,
                recipient_phone=recipient_phone,
                gift_card_sender=gift_card_sender,
                gift_card_recipient=gift_card_recipient,
                gift_card_message=gift_card_message,
                is_luxury_gift_wrapping=is_luxury_gift_wrapping,
                gift_wrapping_fee_yer=gift_wrapping_fee_yer,
                preferred_delivery_date=preferred_delivery_date,
                hide_invoice_prices=hide_invoice_prices,
                payment_currency_selected=payment_currency_selected,
                amount_due_in_payment_currency=amount_due,
                stock_deducted=True,
            )

            for prod, p_qty, item_data, bundle_ref, live_price, line_total_yer in order_lines:
                OrderItem.objects.create(
                    order=order,
                    product=prod,
                    bundle=bundle_ref,
                    product_name=item_data.get('name', 'منتج'),
                    product_image_url=item_data.get('image_url', ''),
                    variant_info=item_data.get('variant_info', ''),
                    unit_price_yer=live_price,
                    quantity=p_qty,
                    total_price_yer=line_total_yer,
                )

            cache_needs_invalidation = False
            for pid, needed_total in needed_by_pid.items():
                prod = locked_products_map[pid]
                new_stock = max(0, prod.stock_quantity - needed_total)
                Product.objects.filter(pk=pid).update(stock_quantity=F('stock_quantity') - needed_total)
                if new_stock <= 0:
                    cache_needs_invalidation = True
                if new_stock <= 3:
                    Notification.notify_admin(
                        title=f"تنبيه انخفاض المخزون: {prod.name_ar}",
                        message=f"الكمية المتبقية من المنتج ({prod.name_ar}) أصبحت {new_stock} فقط. يرجى مراجعة المخزون.",
                        notification_type='low_stock',
                        link=_admin_change_url('product', prod.id),
                    )
            if cache_needs_invalidation:
                from ..signals import invalidate_home_and_catalog_cache
                transaction.on_commit(invalidate_home_and_catalog_cache)

        if request.user.is_authenticated:
            Notification.notify_user(
                user=request.user,
                title=f"تم استلام طلبكم بنجاح #{order.order_number}",
                message=f"شكراً لتسوقكم من براند فيلورا. طلبكم بقيمة {order.total_yer:,.0f} ر.ي قيد التحقق من إشعار التحويل.",
                notification_type='order_created',
                order=order,
                link=f"/order-success/{order.order_number}/",
            )

        Notification.notify_admin(
            title=f"طلب جديد #{order.order_number}",
            message=f"طلب جديد من {customer_name} في {city_name} بقيمة {order.total_yer:,.0f} ر.ي بانتظار فحص السند والاعتماد.",
            notification_type='order_created',
            order=order,
            link=_admin_change_url('order', order.id),
        )

        # ربط جهاز العميل بالطلب وإرسال إشعار فوري للشريط العلوي في هاتفه (سواء مسجل أو زائر)
        session_push_ep = request.session.get('push_endpoint', '')
        if session_push_ep:
            bind_order_push_endpoint(order.order_number, session_push_ep)
        send_order_created_push(order, guest_endpoint=session_push_ep)

        if request.user.is_authenticated:
            user_profile, _ = UserProfile.objects.get_or_create(user=request.user)
            if not user_profile.phone and customer_phone:
                user_profile.phone = customer_phone
            if not user_profile.shipping_address and shipping_address:
                user_profile.shipping_address = shipping_address
                user_profile.preferred_city = city_name
            user_profile.save()

        request.session['last_order_number'] = order.order_number
        recent_orders = list(request.session.get('recent_order_numbers', []))
        if order.order_number not in recent_orders:
            recent_orders.append(order.order_number)
        request.session['recent_order_numbers'] = recent_orders[-10:]
        request.session['cart'] = {}
        request.session.pop('gift_data', None)
        request.session.pop('cart_expires_at', None)
        request.session.modified = True
        if request.user.is_authenticated:
            UserProfile.objects.filter(user=request.user).update(cart_data={})
            cache_delete(f'bv_user_profile_meta_{request.user.pk}')

        schedule_invalidation(lambda: (
            invalidate_admin_metrics_cache(),
            invalidate_notification_cache(for_admin=True),
        ))

        return redirect('store:order_success', order_number=order.order_number)

    user_profile = getattr(request.user, 'store_profile', None) if request.user.is_authenticated else None
    gift_data = request.session.get('gift_data', {})

    context = {
        'items': items,
        'subtotal_yer': subtotal_yer,
        'shipping_fee_yer': shipping_fee_yer,
        'gift_wrapping_fee_yer': gift_wrapping_fee_yer,
        'is_gift_active': is_gift_active,
        'is_luxury_gift_wrapping': is_luxury_wrapping_active,
        'total_yer': total_yer,
        'total_sar': total_sar,
        'payment_methods': payment_methods,
        'shipping_zones': shipping_zones,
        'default_zone': default_zone,
        'store_settings': settings,
        'user_profile': user_profile,
        'gift_data': gift_data,
        **get_cart_timing_context(request),
    }
    return render(request, 'store/checkout.html', context)


def order_success_view(request, order_number):
    """صفحة نجاح الطلب ورابط الواتساب وتفاصيل الإشعار مع حماية خصوصية بيانات العميل (PII)"""
    order = get_object_or_404(Order.objects.prefetch_related('items'), order_number=order_number)
    settings = StoreSettings.get_settings()
    is_order_owner = _is_authorized_for_order(request, order)

    items_lines = []
    for item in order.items.all():
        variant_desc = f" [{item.variant_info}]" if item.variant_info else ""
        items_lines.append(f"• {item.product_name}{variant_desc} × {item.quantity} = {item.total_price_yer:,.0f} ر.ي")
    items_text = "\n".join(items_lines)

    whatsapp_url = f"https://wa.me/{settings.contact_whatsapp}?text={quote(f'مرحباً {settings.store_name}، أود الاستفسار عن الطلب #{order.order_number}')}"
    gift_slip_url = request.build_absolute_uri(reverse('store:gift_slip', kwargs={'order_number': order.order_number}))
    recipient_whatsapp_url = None

    if is_order_owner:
        gift_msg_part = ""
        if order.is_gift:
            wrap_text = "تغليف هدايا" if order.is_luxury_gift_wrapping else "بدون تغليف"
            date_text = f"\n- تاريخ التسليم المطلوب: {order.preferred_delivery_date.strftime('%Y-%m-%d')}" if order.preferred_delivery_date else ""
            hide_price_text = "\n- حجب الأسعار في الفاتورة: نعم" if order.hide_invoice_prices else ""
            gift_msg_part = (
                f"\n*بيانات الإهداء:*\n"
                f"- المستلم: {order.recipient_name or 'المستلم'} (هاتف: {order.recipient_phone})\n"
                f"- التغليف: {wrap_text}"
                f"{date_text}"
                f"{hide_price_text}\n"
                f"- من: {order.gift_card_sender or order.customer_name} | إلى: {order.gift_card_recipient or order.recipient_name}\n"
                f"- نص البطاقة: \"{order.gift_card_message or ''}\"\n"
            )

        whatsapp_msg = (
            f"مرحباً {settings.store_name}، تم إرسال طلب جديد برقم #{order.order_number}:\n\n"
            f"الاسم: {order.customer_name}\n"
            f"المدينة: {order.shipping_city}\n"
            f"المنتجات:\n{items_text}\n"
            f"{gift_msg_part}\n"
            f"المبلغ الإجمالي: {order.total_yer:,.0f} ر.ي ({order.total_sar} ر.س)\n"
            f"طريقة الدفع: {order.payment_method_name} ({order.payment_currency_selected})\n"
            f"رقم الحوالة: {order.payment_reference_no or 'مرفق إشعار التحويل'}\n"
        )
        whatsapp_url = f"https://wa.me/{settings.contact_whatsapp}?text={quote(whatsapp_msg)}"

        if order.is_gift and order.recipient_phone:
            r_clean_phone = order.recipient_phone.replace('+', '').replace(' ', '')
            sender_disp = order.gift_card_sender or order.customer_name
            r_msg = (
                f"مرحباً {order.recipient_name or 'عزيزنا'}،\n"
                f"وصلتك هدية فاخرة من ({sender_disp}) عبر {settings.store_name} 🎁✨\n\n"
                f"يمكنك الاطلاع على بطاقة التهنئة وتتبع الشحنة عبر الرابط التالي:\n"
                f"{gift_slip_url}\n\n"
                f"نتمنى لك يوماً سعيداً ونسعد بخدمتك دائماً! 🌹"
            )
            recipient_whatsapp_url = f"https://wa.me/{r_clean_phone}?text={quote(r_msg)}"

    context = {
        'order': order,
        'is_order_owner': is_order_owner,
        'whatsapp_url': whatsapp_url,
        'gift_slip_url': gift_slip_url,
        'recipient_whatsapp_url': recipient_whatsapp_url,
    }
    return render(request, 'store/order_success.html', context)


def gift_slip_view(request, order_number):
    """عرض بوليصة الإهداء وبطاقة التهنئة للمستلم خالية تماماً من الأسعار والمبالغ المالية"""
    order = get_object_or_404(Order.objects.prefetch_related('items__product'), order_number=order_number)
    settings = StoreSettings.get_settings()
    return render(request, 'store/gift_slip.html', {
        'order': order,
        'store_settings': settings,
    })


@staff_member_required
def admin_print_gift_card(request, order_id):
    """صفحة طباعة كرت الإهداء الملكي الفاخر بقياس بطاقة الإهداء (10x15 سم) جاهزة للطباعة على ورق مقوى"""
    order = get_object_or_404(Order, id=order_id)
    audit_logger.info("[ADMIN_AUDIT] actor=%s action=print_gift_card order=%s", request.user.username, order.order_number)
    settings = StoreSettings.get_settings()
    return render(request, 'admin/print_gift_card.html', {
        'order': order,
        'store_settings': settings,
    })


@staff_member_required
def admin_print_recipient_slip(request, order_id):
    """صفحة طباعة بوليصة التوصيل للمستلم خالية 100% من الأسعار لمندوب الشحن والتسليم"""
    order = get_object_or_404(Order.objects.prefetch_related('items__product'), id=order_id)
    audit_logger.info("[ADMIN_AUDIT] actor=%s action=print_recipient_slip order=%s", request.user.username, order.order_number)
    settings = StoreSettings.get_settings()
    return render(request, 'admin/print_recipient_slip.html', {
        'order': order,
        'store_settings': settings,
    })


@staff_member_required
def admin_print_invoice(request, order_id):
    """صفحة طباعة الفاتورة الرسمية A4 الخاصة بلوحة الإدارة"""
    order = get_object_or_404(Order.objects.prefetch_related('items__product'), id=order_id)
    audit_logger.info("[ADMIN_AUDIT] actor=%s action=print_invoice order=%s", request.user.username, order.order_number)
    settings = StoreSettings.get_settings()
    return render(request, 'store/print_invoice.html', {
        'order': order,
        'store_settings': settings,
    })


@require_POST
def save_order_invoice_image(request, order_number):
    """استلام صورة الفاتورة المولدة كـ PNG ورفعها وتخزينها سحابياً على Cloudinary وربطها بالطلب مع تحقق أمني صارم"""
    try:
        order = get_object_or_404(Order, order_number=order_number)

        if not _is_authorized_for_order(request, order):
            return JsonResponse({'status': 'error', 'message': 'غير مصرح بالوصول لهذا الطلب'}, status=403)

        data = json.loads(request.body.decode('utf-8'))
        image_data = data.get('image_data', '')
        if not image_data or not image_data.startswith('data:image'):
            return JsonResponse({'status': 'error', 'message': 'بيانات الصورة غير صالحة'}, status=400)

        if len(image_data) > 4 * 1024 * 1024:
            return JsonResponse({'status': 'error', 'message': 'حجم الصورة كبير جداً ويتجاوز الحد المسموح'}, status=400)

        format_prefix, b64_str = image_data.split(';base64,')
        decoded_bytes = base64.b64decode(b64_str)

        try:
            img = Image.open(BytesIO(decoded_bytes))
            img.verify()
            if img.format not in ('PNG', 'JPEG', 'WEBP'):
                return JsonResponse({'status': 'error', 'message': 'صيغة الصورة غير مدعومة (PNG/JPEG/WEBP فقط)'}, status=400)
        except Exception:
            return JsonResponse({'status': 'error', 'message': 'ملف الصورة تالف أو غير صالح'}, status=400)

        file_name = f"invoice_{order.order_number}.png"
        order.invoice_image.save(file_name, ContentFile(decoded_bytes), save=True)

        return JsonResponse({
            'status': 'ok',
            'url': order.invoice_image.url,
            'message': 'تم حفظ ورفع الفاتورة بنجاح',
        })
    except Exception as e:
        logger.error(f"Error saving invoice image for order {order_number}: {e}")
        return JsonResponse({'status': 'error', 'message': 'حدث خطأ داخلي أثناء معالجة وحفظ صورة الفاتورة.'}, status=500)
