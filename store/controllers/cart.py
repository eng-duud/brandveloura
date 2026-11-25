import time
from decimal import Decimal

from django.contrib import messages
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from ..models import GiftBundle, Product, ShippingZone, StoreSettings, UserProfile
from ..cache_service import cache_delete, cache_get_or_set_safe
from .helpers import _is_htmx_partial, _parse_int_id, _yer_to_sar


def sync_cart_to_profile(request):
    """مزامنة سلة الجلسة الحالية مع الملف التعريفي للعميل بقاعدة البيانات لمنع فقدان المنتجات نهائياً"""
    if request.user.is_authenticated:
        try:
            profile, _ = UserProfile.objects.get_or_create(user=request.user)
            cart = request.session.get('cart', {})
            profile.cart_data = cart
            profile.save(update_fields=['cart_data'])
        except Exception:
            pass


def check_and_expire_cart(request):
    """فحص توقيت حجز السلة وإلغائها تلقائياً لتحرير المخزون لبقية العملاء في حال انتهاء المهلة"""
    settings = StoreSettings.get_settings()
    res_minutes = getattr(settings, 'cart_reservation_minutes', 60)

    if res_minutes <= 0:
        return False

    cart = request.session.get('cart', {})
    if not cart:
        request.session.pop('cart_expires_at', None)
        return False

    expires_at = request.session.get('cart_expires_at')
    now_ts = int(time.time())

    if not expires_at:
        request.session['cart_expires_at'] = now_ts + (res_minutes * 60)
        request.session.modified = True
        return False

    if now_ts > expires_at:
        request.session['cart'] = {}
        request.session.pop('cart_expires_at', None)
        request.session.pop('gift_data', None)
        request.session.modified = True

        if request.user.is_authenticated:
            try:
                UserProfile.objects.filter(user=request.user).update(cart_data={})
                cache_delete(f'bv_user_profile_meta_{request.user.pk}')
            except Exception:
                pass

        messages.warning(
            request,
            f'انتهت مهلة حجز المنتجات في السلة ({res_minutes} دقيقة) وتم تحريرها لإتاحتها للمتسوقين الآخرين. يمكنك اختيار منتجاتك من جديد.',
        )
        return True

    return False


def refresh_cart_reservation(request):
    """تحديث أو بدء توقيت حجز السلة عند إضافة أو تعديل منتجات"""
    settings = StoreSettings.get_settings()
    res_minutes = getattr(settings, 'cart_reservation_minutes', 60)

    cart = request.session.get('cart', {})
    if not cart:
        request.session.pop('cart_expires_at', None)
        return

    if res_minutes > 0:
        now_ts = int(time.time())
        request.session['cart_expires_at'] = now_ts + (res_minutes * 60)
        request.session.modified = True


def get_cart_timing_context(request):
    """حساب الثواني المتبقية وتفاصيل المؤقت لتمريرها للقوالب والعداد التنازلي"""
    settings = StoreSettings.get_settings()
    res_minutes = getattr(settings, 'cart_reservation_minutes', 60)

    cart = request.session.get('cart', {})
    if not cart or res_minutes <= 0:
        return {
            'cart_remaining_seconds': 0,
            'cart_remaining_minutes': 0,
            'cart_remaining_seconds_str': '00',
            'cart_reservation_minutes': res_minutes,
        }

    expires_at = request.session.get('cart_expires_at')
    now_ts = int(time.time())
    if not expires_at:
        expires_at = now_ts + (res_minutes * 60)
        request.session['cart_expires_at'] = expires_at
        request.session.modified = True

    remaining = max(0, expires_at - now_ts)
    mins = remaining // 60
    secs = remaining % 60

    return {
        'cart_remaining_seconds': remaining,
        'cart_remaining_minutes': mins,
        'cart_remaining_seconds_str': f"{secs:02d}",
        'cart_reservation_minutes': res_minutes,
    }


def merge_and_restore_user_cart(request, user):
    """دمج سلة الزائر السابقة مع السلة المحفوظة بحسابه في قاعدة البيانات واستعادتها كاملة مع تنظيف غير النشط"""
    try:
        profile, _ = UserProfile.objects.get_or_create(user=user)
        db_cart = profile.cart_data or {}
        guest_cart = request.session.get('cart', {})

        merged = dict(db_cart)
        for key, item in guest_cart.items():
            if key in merged:
                merged[key]['quantity'] = max(merged[key].get('quantity', 1), item.get('quantity', 1))
            else:
                merged[key] = item

        if merged:
            prod_ids = {
                v.get('product_id') for v in merged.values()
                if not v.get('is_bundle') and v.get('product_id')
            }
            bundle_ids = {
                (v.get('bundle_id') or v.get('product_id')) for v in merged.values()
                if v.get('is_bundle') and (v.get('bundle_id') or v.get('product_id'))
            }
            active_pids = set(Product.objects.filter(id__in=prod_ids, is_active=True).values_list('id', flat=True)) if prod_ids else set()
            active_bids = set(GiftBundle.objects.filter(id__in=bundle_ids, is_active=True).values_list('id', flat=True)) if bundle_ids else set()
            merged = {
                k: v for k, v in merged.items()
                if (
                    (v.get('is_bundle') and (v.get('bundle_id') or v.get('product_id')) in active_bids)
                    or (not v.get('is_bundle') and v.get('product_id') in active_pids)
                )
            }

        request.session['cart'] = merged
        request.session.modified = True
        profile.cart_data = merged
        profile.save(update_fields=['cart_data'])
        if merged:
            refresh_cart_reservation(request)
        else:
            request.session.pop('cart_expires_at', None)
        return merged
    except Exception:
        return request.session.get('cart', {})


@require_POST
def cart_add(request):
    """إضافة منتج للسلة لحظياً عبر HTMX مع فحص المخزون ودعم درجتي الأصلي والماستر"""
    check_and_expire_cart(request)
    product_id = request.POST.get('product_id')
    try:
        quantity = int(request.POST.get('quantity', 1))
        if quantity <= 0:
            quantity = 1
    except (ValueError, TypeError):
        quantity = 1

    variant_info = request.POST.get('variant_info', '').strip()
    grade = request.POST.get('grade', '').strip()

    product = get_object_or_404(Product, id=product_id, is_active=True)

    if product.stock_quantity <= 0:
        cart = request.session.get('cart', {})
        cart_count = sum(item.get('quantity', 1) for item in cart.values())
        response = render(request, 'store/partials/cart_badge.html', {'cart_count': cart_count, 'oob_sync': True})
        response['HX-Trigger'] = 'outOfStock'
        return response

    grade_label = ''
    unit_price = float(product.price_yer)

    if product.has_grades:
        if grade == 'master' and product.price_master_yer:
            unit_price = float(product.price_master_yer)
            grade_label = 'ماستر (طبق الأصل)'
        elif (grade == 'original' or not grade) and product.price_original_yer:
            unit_price = float(product.price_original_yer)
            grade_label = 'أصلي 100%'
            grade = 'original'

    parts = [p for p in [grade_label, variant_info] if p]
    combined_variant = ' | '.join(parts)

    cart = request.session.get('cart', {})
    item_key = f"{product_id}_{grade}_{variant_info}".strip('_')

    current_product_qty = sum(
        int(v.get('quantity', 0))
        for v in cart.values()
        if not v.get('is_bundle') and str(v.get('product_id')) == str(product.id)
    )
    available_qty = max(0, product.stock_quantity - current_product_qty)
    if available_qty <= 0:
        cart_count = sum(item.get('quantity', 1) for item in cart.values())
        response = render(request, 'store/partials/cart_badge.html', {'cart_count': cart_count, 'oob_sync': True})
        response['HX-Trigger'] = 'maxStockReached'
        return response

    if quantity > available_qty:
        quantity = available_qty

    if item_key in cart:
        cart[item_key]['quantity'] += quantity
    else:
        cart[item_key] = {
            'product_id': product.id,
            'name': product.name_ar,
            'brand': product.effective_brand_name,
            'price_yer': unit_price,
            'image_url': product.primary_image_url,
            'quantity': quantity,
            'variant_info': combined_variant,
            'grade': grade,
        }

    request.session['cart'] = cart
    request.session.modified = True
    sync_cart_to_profile(request)
    refresh_cart_reservation(request)

    cart_count = sum(item.get('quantity', 1) for item in cart.values())

    response = render(request, 'store/partials/cart_badge.html', {'cart_count': cart_count, 'oob_sync': True})
    response['HX-Trigger'] = 'cartUpdated'
    return response


@require_POST
def cart_update_quantity(request):
    """تعديل كمية عنصر في السلة مع احترام رصيد المخزون ومزامنة الحساب"""
    check_and_expire_cart(request)
    item_key = request.POST.get('item_key')
    action = request.POST.get('action')

    cart = request.session.get('cart', {})

    if item_key in cart:
        if action == 'increase':
            if cart[item_key].get('is_bundle'):
                b_id = cart[item_key].get('bundle_id') or cart[item_key].get('product_id')
                bundle = GiftBundle.objects.prefetch_related('items__product').filter(id=b_id, is_active=True).first()
                if not bundle:
                    del cart[item_key]
                else:
                    can_add = all(
                        b_item.product and b_item.product.is_active and (
                            b_item.product.stock_quantity >= (cart[item_key]['quantity'] + 1) * b_item.quantity
                        )
                        for b_item in bundle.items.all()
                    )
                    if can_add:
                        cart[item_key]['quantity'] += 1
            else:
                p_id = cart[item_key].get('product_id')
                prod = Product.objects.filter(id=p_id, is_active=True).first()
                if not prod:
                    del cart[item_key]
                else:
                    total_for_prod = sum(
                        int(v.get('quantity', 0))
                        for v in cart.values()
                        if not v.get('is_bundle') and str(v.get('product_id')) == str(p_id)
                    )
                    if total_for_prod < prod.stock_quantity:
                        cart[item_key]['quantity'] += 1
        elif action == 'decrease':
            cart[item_key]['quantity'] -= 1
            if cart[item_key]['quantity'] <= 0:
                del cart[item_key]

    request.session['cart'] = cart
    request.session.modified = True
    sync_cart_to_profile(request)
    if cart:
        refresh_cart_reservation(request)
    else:
        request.session.pop('cart_expires_at', None)

    return _render_cart_response(request)


@require_POST
def cart_remove_item(request):
    """حذف عنصر من السلة ومزامنة الحساب"""
    item_key = request.POST.get('item_key')
    cart = request.session.get('cart', {})

    if item_key in cart:
        del cart[item_key]
        request.session['cart'] = cart
        request.session.modified = True
        sync_cart_to_profile(request)
        if cart:
            refresh_cart_reservation(request)
        else:
            request.session.pop('cart_expires_at', None)

    return _render_cart_response(request)


def _build_cart_context(request):
    """دالة مساعدة مشتركة لحساب عناصر السلة والإجماليات لكل من العرض الكامل والجزئي"""
    cart = request.session.get('cart', {})
    settings = StoreSettings.get_settings()
    yer_per_sar = settings.yer_per_sar or Decimal('530.00')

    items = []
    subtotal_yer = Decimal('0.00')

    for key, data in cart.items():
        qty = data.get('quantity', 1)
        price_yer = Decimal(str(data.get('price_yer', 0)))
        line_total_yer = price_yer * qty
        subtotal_yer += line_total_yer

        items.append({
            'key': key,
            'product_id': data.get('product_id'),
            'name': data.get('name'),
            'brand': data.get('brand'),
            'image_url': data.get('image_url'),
            'variant_info': data.get('variant_info'),
            'quantity': qty,
            'price_yer': price_yer,
            'price_sar': _yer_to_sar(price_yer, yer_per_sar),
            'line_total_yer': line_total_yer,
            'line_total_sar': _yer_to_sar(line_total_yer, yer_per_sar),
        })

    return {
        'cart_items': items,
        'subtotal_yer': subtotal_yer,
        'subtotal_sar': _yer_to_sar(subtotal_yer, yer_per_sar),
        'cart_count': sum(item['quantity'] for item in items),
        **get_cart_timing_context(request),
    }


def _render_cart_response(request):
    """إرجاع جدول السلة الجزئي مع تفعيل حدث تحديث السلة والمزامنة التلقائية لشارات الجوال وسطح المكتب"""
    context = _build_cart_context(request)
    context['oob_cart_badges'] = True
    response = render(request, 'store/partials/cart_table.html', context)
    response['HX-Trigger'] = 'cartUpdated'
    return response


def cart_view(request):
    """صفحة سلة المشتريات الكاملة مع دعم التحديث الجزئي عند انتهاء المهلة"""
    expired = check_and_expire_cart(request)
    if expired:
        if _is_htmx_partial(request):
            return _render_cart_response(request)
        return redirect('store:cart_view')

    context = _build_cart_context(request)
    if _is_htmx_partial(request):
        return _render_cart_response(request)
    return render(request, 'store/cart.html', context)


def toggle_currency(request):
    """تبديل العملة المعروضة بين ريال يمني (YER) وريال سعودي (SAR) مع دعم HTMX والتوجيه الآمن"""
    if request.method == 'POST' or request.GET.get('toggle') == '1':
        current = request.session.get('active_currency', 'YER')
        new_currency = 'SAR' if current == 'YER' else 'YER'
        request.session['active_currency'] = new_currency
        request.session.modified = True
    else:
        new_currency = request.session.get('active_currency', 'YER')

    if request.method == 'GET' and not request.headers.get('HX-Request'):
        referer = request.META.get('HTTP_REFERER')
        if referer and url_has_allowed_host_and_scheme(url=referer, allowed_hosts={request.get_host()}):
            return redirect(referer)
        return redirect('store:home')

    csrf_tok = get_token(request)
    label = '🇸🇦 ر.س' if new_currency == 'SAR' else '🇾🇪 ر.ي'
    btn_html = format_html(
        '<button hx-post="{}" hx-headers=\'{{"X-CSRFToken": "{}"}}\' hx-swap="outerHTML" '
        'class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl bg-white hover:bg-pink-50 border border-pink-200 text-slate-800 text-xs font-bold transition-all shadow-2xs cursor-pointer min-h-[40px]" '
        'title="تبديل العملة المعروضة">'
        '<span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>'
        '<span>{}</span></button>',
        reverse('store:toggle_currency'),
        csrf_tok,
        label,
    )
    response = HttpResponse(btn_html)
    if request.headers.get('HX-Request'):
        response['HX-Refresh'] = 'true'
    return response


def get_shipping_fee(request):
    """حساب رسوم الشحن والتغليف عند اختيار المدينة أو خيار الهدية لحظياً عبر HTMX"""
    city_id = _parse_int_id(request.GET.get('shipping_city') or request.GET.get('city_id'))
    order_type = request.GET.get('order_type', 'personal')
    is_gift = (order_type == 'gift') or (request.GET.get('is_gift') in ['true', '1', 'on'])
    is_gift_wrapping = (request.GET.get('is_luxury_gift_wrapping') in ['true', '1', 'on']) if is_gift else False

    shipping_fee = Decimal('0.00')
    delivery_time = 'خلال 24-48 ساعة'

    if city_id:
        zones_map = cache_get_or_set_safe(
            'bv_shipping_zones_active',
            lambda: {z.id: z for z in ShippingZone.objects.filter(is_active=True)},
            timeout=300,
        ) or {}
        zone = zones_map.get(city_id)
        if zone:
            shipping_fee = zone.delivery_fee_yer
            delivery_time = zone.estimated_delivery_time

    settings = StoreSettings.get_settings()
    gift_wrapping_fee = settings.gift_wrapping_fee_yer if is_gift_wrapping else Decimal('0.00')

    cart = request.session.get('cart', {})
    subtotal_yer = sum(Decimal(str(item.get('price_yer', 0))) * item.get('quantity', 1) for item in cart.values())
    total_yer = subtotal_yer + shipping_fee + gift_wrapping_fee

    yer_per_sar = settings.yer_per_sar or Decimal('530.00')
    total_sar = _yer_to_sar(total_yer, yer_per_sar)

    return render(request, 'store/partials/checkout_totals.html', {
        'shipping_fee': shipping_fee,
        'delivery_time': delivery_time,
        'subtotal_yer': subtotal_yer,
        'gift_wrapping_fee': gift_wrapping_fee,
        'is_luxury_gift_wrapping': is_gift_wrapping,
        'total_yer': total_yer,
        'total_sar': total_sar,
    })
