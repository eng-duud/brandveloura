from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from ..models import GiftBundle, Product, StoreSettings
from ..cache_service import cache_get_or_set_safe, make_gift_builder_catalog_key
from .cart import refresh_cart_reservation, sync_cart_to_profile
from .helpers import _parse_int_id, _yer_to_sar


def gift_bundle_detail_view(request, slug):
    """عرض تفاصيل باقة الإهداء الجاهزة ومحتوياتها ونسبة التوفير وزر الشراء المباشر أو التخصيص"""
    bundle = get_object_or_404(
        GiftBundle.objects.prefetch_related('items__product__images', 'items__product__category'),
        slug=slug,
        is_active=True,
    )
    settings = StoreSettings.get_settings()
    yer_per_sar = settings.yer_per_sar or Decimal('530.00')
    wrapping_fee = settings.gift_wrapping_fee_yer or Decimal('2500.00')

    items_total_yer = Decimal('0.00')
    for item in bundle.items.all():
        p = item.product
        p_price = p.price_master_yer if item.grade == 'master' and p.price_master_yer else (p.price_original_yer or p.price_yer)
        items_total_yer += (p_price * item.quantity)
    if bundle.includes_luxury_packaging:
        items_total_yer += wrapping_fee

    context = {
        'bundle': bundle,
        'items_total_yer': items_total_yer,
        'wrapping_fee': wrapping_fee,
        'yer_per_sar': yer_per_sar,
    }
    return render(request, 'store/gift_bundle_detail.html', context)


def gift_bundle_order_direct(request, slug):
    """شراء باقة الإهداء الجاهزة مباشرة وتوجيه العميل لصفحة إتمام الطلب"""
    bundle = get_object_or_404(GiftBundle, slug=slug, is_active=True)
    cart = request.session.get('cart', {})

    b_key = f"bundle_{bundle.id}"
    cart[b_key] = {
        'product_id': bundle.id,
        'is_bundle': True,
        'bundle_id': bundle.id,
        'name': bundle.title_ar,
        'brand': 'Brand Veloura',
        'price_yer': float(bundle.price_yer),
        'image_url': bundle.primary_image_url,
        'quantity': 1,
        'variant_info': f"باقة جاهزة ({bundle.items.count()} عناصر)",
        'grade': '',
    }
    request.session['cart'] = cart
    request.session.modified = True
    sync_cart_to_profile(request)
    refresh_cart_reservation(request)

    recipient_name = request.POST.get('recipient_name', '').strip() if request.method == 'POST' else ''
    recipient_phone = request.POST.get('recipient_phone', '').strip() if request.method == 'POST' else ''
    gift_card_sender = request.POST.get('gift_card_sender', '').strip() if request.method == 'POST' else ''
    gift_card_recipient = request.POST.get('gift_card_recipient', '').strip() or recipient_name
    gift_card_message = request.POST.get('gift_card_message', '').strip() if request.method == 'POST' else ''
    preferred_date = request.POST.get('preferred_delivery_date', '').strip() if request.method == 'POST' else None

    request.session['gift_data'] = {
        'is_gift': True,
        'recipient_name': recipient_name,
        'recipient_phone': recipient_phone,
        'gift_card_sender': gift_card_sender,
        'gift_card_recipient': gift_card_recipient,
        'gift_card_message': gift_card_message,
        'is_luxury_gift_wrapping': bundle.includes_luxury_packaging,
        'preferred_delivery_date': preferred_date or None,
        'hide_invoice_prices': True,
    }
    request.session.modified = True
    messages.success(request, f"تم اختيار ({bundle.title_ar}) كهدية، يرجى استكمال بيانات المستلم وتأكيد الطلب.")
    return redirect('store:checkout')


def gift_builder_view(request):
    """صانع الهدية الملكي: معالج 4 خطوات تفاعلي أنيق مع شريط تقدم وخيارات التخصيص الكاملة"""
    settings = StoreSettings.get_settings()
    yer_per_sar = settings.yer_per_sar or Decimal('530.00')
    wrapping_fee = settings.gift_wrapping_fee_yer or Decimal('2500.00')

    if request.method == 'POST':
        post_bundle_id = _parse_int_id(request.POST.get('bundle_id'))
        perfume_ids = request.POST.getlist('perfume_id')
        if not perfume_ids and request.POST.get('perfume_id'):
            perfume_ids = [request.POST.get('perfume_id')]
        perfume_ids = [p for p in perfume_ids if p]

        perfume_grade_default = request.POST.get('perfume_grade', 'original')

        accessory_ids = request.POST.getlist('accessory_id')
        if not accessory_ids and request.POST.get('accessory_id'):
            accessory_ids = [request.POST.get('accessory_id')]
        accessory_ids = [a for a in accessory_ids if a]

        recipient_name = request.POST.get('recipient_name', '').strip()
        recipient_phone = request.POST.get('recipient_phone', '').strip()
        gift_card_sender = request.POST.get('gift_card_sender', '').strip()
        gift_card_recipient = request.POST.get('gift_card_recipient', '').strip() or recipient_name
        gift_card_message = request.POST.get('gift_card_message', '').strip()
        preferred_delivery_date = request.POST.get('preferred_delivery_date', '').strip() or None
        is_luxury_gift_wrapping = request.POST.get('is_luxury_gift_wrapping') in ['true', '1', 'on']

        if preferred_delivery_date:
            try:
                parsed_d = datetime.strptime(preferred_delivery_date, '%Y-%m-%d').date()
                if parsed_d < date.today():
                    preferred_delivery_date = (date.today() + timedelta(days=1)).isoformat()
            except (ValueError, TypeError):
                preferred_delivery_date = None

        cart = request.session.get('cart', {})

        if post_bundle_id:
            bundle_obj = GiftBundle.objects.prefetch_related('items__product').filter(id=post_bundle_id, is_active=True).first()
            if bundle_obj:
                b_items = list(bundle_obj.items.all())
                if any((not bi.product or not bi.product.is_active or bi.product.stock_quantity < bi.quantity) for bi in b_items):
                    messages.error(request, f'عذراً، أحد منتجات الباقة ({bundle_obj.title_ar}) غير متوفر بالكمية المطلوبة.')
                    return redirect('store:gift_builder')
                b_key = f"bundle_{bundle_obj.id}"
                cart[b_key] = {
                    'product_id': bundle_obj.id,
                    'is_bundle': True,
                    'bundle_id': bundle_obj.id,
                    'name': bundle_obj.title_ar,
                    'brand': 'Brand Veloura',
                    'price_yer': float(bundle_obj.price_yer),
                    'image_url': bundle_obj.primary_image_url,
                    'quantity': 1,
                    'variant_info': f"باقة جاهزة ({len(b_items)} عناصر)",
                    'grade': '',
                }
                bundle_pids = {bi.product_id for bi in b_items}
                parsed_extra_acc = [
                    aid_int for aid in accessory_ids
                    for aid_int in [_parse_int_id(aid)]
                    if aid_int and aid_int not in bundle_pids
                ]
                extra_acc_map = Product.objects.filter(id__in=parsed_extra_acc, is_active=True).select_related('category').in_bulk() if parsed_extra_acc else {}
                for aid_int in parsed_extra_acc:
                    acc_obj = extra_acc_map.get(aid_int)
                    if acc_obj and acc_obj.stock_quantity > 0:
                        a_key = f"{acc_obj.id}_acc_gift"
                        cart[a_key] = {
                            'product_id': acc_obj.id,
                            'name': acc_obj.name_ar,
                            'brand': acc_obj.brand_name,
                            'price_yer': float(acc_obj.price_yer),
                            'image_url': acc_obj.primary_image_url,
                            'quantity': 1,
                            'variant_info': f"إضافة للباقة ({acc_obj.category.name_ar if acc_obj.category else 'ملحق'})",
                            'grade': '',
                        }
            else:
                bundle_prod = get_object_or_404(Product, id=post_bundle_id, is_active=True)
                if bundle_prod.stock_quantity <= 0:
                    messages.error(request, f'عذراً، ({bundle_prod.name_ar}) نفد من المخزون حالياً.')
                    return redirect('store:gift_builder')
                b_key = f"bundle_{bundle_prod.id}"
                cart[b_key] = {
                    'product_id': bundle_prod.id,
                    'name': bundle_prod.name_ar,
                    'brand': bundle_prod.brand_name or 'Brand Veloura',
                    'price_yer': float(bundle_prod.price_yer),
                    'image_url': bundle_prod.primary_image_url,
                    'quantity': 1,
                    'variant_info': 'باقة جاهزة',
                    'grade': '',
                }
        else:
            parsed_perfume_ids = [pid_int for pid in perfume_ids for pid_int in [_parse_int_id(pid)] if pid_int]
            if not parsed_perfume_ids:
                messages.warning(request, 'يرجى اختيار عطر واحد على الأقل لتجهيز باقة الإهداء.')
                return redirect('store:gift_builder')

            for pid_int in parsed_perfume_ids:
                perfume_obj = get_object_or_404(Product, id=pid_int, is_active=True)
                if perfume_obj.stock_quantity <= 0:
                    messages.error(request, f'عذراً، العطر ({perfume_obj.name_ar}) نفد من المخزون حالياً.')
                    return redirect('store:gift_builder')
                p_grade = request.POST.get(f'grade_{pid_int}') or perfume_grade_default
                p_price = float(perfume_obj.price_master_yer if p_grade == 'master' and perfume_obj.price_master_yer else (perfume_obj.price_original_yer or perfume_obj.price_yer))
                grade_name = 'ماستر' if p_grade == 'master' else 'أصلي'
                p_key = f"{perfume_obj.id}_{p_grade}_gift"
                cart[p_key] = {
                    'product_id': perfume_obj.id,
                    'name': perfume_obj.name_ar,
                    'brand': perfume_obj.brand_name,
                    'price_yer': p_price,
                    'image_url': perfume_obj.primary_image_url,
                    'quantity': 1,
                    'variant_info': f"باقة إهداء ({grade_name})",
                    'grade': p_grade,
                }

            parsed_acc_ids = [aid_int for aid in accessory_ids for aid_int in [_parse_int_id(aid)] if aid_int]
            acc_map = Product.objects.filter(id__in=parsed_acc_ids, is_active=True).select_related('category').in_bulk() if parsed_acc_ids else {}
            for aid_int in parsed_acc_ids:
                acc_obj = acc_map.get(aid_int)
                if acc_obj and acc_obj.stock_quantity > 0:
                    a_key = f"{acc_obj.id}_acc_gift"
                    cart[a_key] = {
                        'product_id': acc_obj.id,
                        'name': acc_obj.name_ar,
                        'brand': acc_obj.brand_name,
                        'price_yer': float(acc_obj.price_yer),
                        'image_url': acc_obj.primary_image_url,
                        'quantity': 1,
                        'variant_info': f"ملحق إهداء ({acc_obj.category.name_ar if acc_obj.category else 'إكسسوار'})",
                        'grade': '',
                    }

        request.session['cart'] = cart
        request.session.modified = True
        sync_cart_to_profile(request)
        refresh_cart_reservation(request)
        request.session['gift_data'] = {
            'is_gift': True,
            'recipient_name': recipient_name,
            'recipient_phone': recipient_phone,
            'gift_card_sender': gift_card_sender,
            'gift_card_recipient': gift_card_recipient,
            'gift_card_message': gift_card_message,
            'is_luxury_gift_wrapping': is_luxury_gift_wrapping,
            'preferred_delivery_date': preferred_delivery_date,
            'hide_invoice_prices': True,
        }
        request.session.modified = True
        return redirect('store:checkout')

    bundle_slug = request.GET.get('bundle_slug') or request.GET.get('bundle')
    bundle_id = _parse_int_id(request.GET.get('bundle_id'))
    selected_gift_bundle = None
    selected_bundle = None

    if bundle_slug:
        selected_gift_bundle = GiftBundle.objects.filter(slug=bundle_slug, is_active=True).prefetch_related('items__product__images').first()
    elif bundle_id:
        selected_gift_bundle = GiftBundle.objects.filter(id=bundle_id, is_active=True).prefetch_related('items__product__images').first()
        if not selected_gift_bundle:
            selected_bundle = Product.objects.filter(id=bundle_id, is_active=True).first()

    perfume_id = _parse_int_id(request.GET.get('perfume_id'))
    selected_perfume = Product.objects.filter(id=perfume_id, is_active=True).first() if perfume_id else None

    initial_grade = request.GET.get('grade', 'all').strip().lower()
    if initial_grade not in ['all', 'original', 'master']:
        initial_grade = 'all'

    def _build_gift_catalog():
        perfume_q = (
            Q(category__category_type='perfumes') |
            Q(category__parent__category_type='perfumes') |
            Q(category__slug__icontains='perfume') |
            Q(category__name_ar__icontains='عطر') |
            Q(category__name_ar__icontains='عطور') |
            Q(name_ar__icontains='عطر')
        )
        perfumes_base = Product.objects.filter(
            perfume_q, is_active=True
        ).exclude(category__category_type='bundles').select_related('category', 'brand').prefetch_related('images')

        perfumes_list = list(perfumes_base.filter(stock_quantity__gt=0).order_by('-is_featured', '-is_best_seller', '-created_at')[:48])
        if not perfumes_list:
            perfumes_list = list(perfumes_base.order_by('-is_featured', '-is_best_seller', '-created_at')[:48])
        if not perfumes_list:
            perfumes_list = list(Product.objects.filter(is_active=True).exclude(category__category_type='bundles').select_related('category', 'brand').prefetch_related('images').order_by('-is_featured', '-created_at')[:36])

        acc_q = (
            Q(category__category_type__in=['watches', 'cosmetics', 'care']) |
            Q(category__parent__category_type__in=['watches', 'cosmetics', 'care']) |
            Q(category__slug__in=['watches', 'cosmetics', 'care']) |
            Q(category__name_ar__icontains='ساع') |
            Q(category__name_ar__icontains='مكياج') |
            Q(category__name_ar__icontains='تجميل') |
            Q(category__name_ar__icontains='عناية')
        )
        selected_perfume_pids = {p.id for p in perfumes_list}
        accessories_base = Product.objects.filter(
            acc_q, is_active=True
        ).exclude(category__category_type='bundles').exclude(id__in=selected_perfume_pids).select_related('category', 'brand').prefetch_related('images')

        accessories_list = list(accessories_base.filter(stock_quantity__gt=0).order_by('-is_featured', '-created_at')[:36])
        if not accessories_list:
            accessories_list = list(accessories_base.order_by('-is_featured', '-created_at')[:36])
        if not accessories_list:
            accessories_list = list(Product.objects.filter(is_active=True).exclude(category__category_type='bundles').exclude(id__in=selected_perfume_pids).select_related('category', 'brand').prefetch_related('images')[:24])

        bundles_list = list(
            GiftBundle.objects.filter(is_active=True)
            .prefetch_related('items__product__images')
            .order_by('display_order', '-created_at')[:12]
        )
        if not bundles_list:
            bundles_list = list(Product.objects.filter(category__category_type='bundles', is_active=True).prefetch_related('images').order_by('-created_at')[:10])

        seen_b, brands_list = set(), []
        for p in perfumes_list:
            b_name = p.effective_brand_name
            if b_name and b_name not in seen_b:
                seen_b.add(b_name)
                brands_list.append(b_name)

        return {
            'perfumes': perfumes_list,
            'accessories': accessories_list,
            'ready_gift_bundles': bundles_list,
            'perfume_brands': brands_list,
        }

    gift_catalog = cache_get_or_set_safe(make_gift_builder_catalog_key(), _build_gift_catalog, timeout=300) or {}
    perfumes = gift_catalog.get('perfumes', [])
    accessories = gift_catalog.get('accessories', [])
    ready_gift_bundles = gift_catalog.get('ready_gift_bundles', [])
    perfume_brands = gift_catalog.get('perfume_brands', [])

    preselected_perfume_ids = []
    preselected_accessory_ids = []
    preselected_grades = {}
    if selected_gift_bundle:
        for b_item in selected_gift_bundle.items.all():
            p_obj = b_item.product
            c_type = getattr(p_obj.category, 'category_type', '')
            if c_type == 'perfumes':
                preselected_perfume_ids.append(p_obj.id)
                preselected_grades[str(p_obj.id)] = b_item.grade
            else:
                preselected_accessory_ids.append(p_obj.id)

    context = {
        'perfumes': perfumes,
        'perfume_brands': perfume_brands,
        'accessories': accessories,
        'gift_bundles': ready_gift_bundles,
        'selected_gift_bundle': selected_gift_bundle,
        'selected_bundle': selected_bundle,
        'selected_perfume': selected_perfume,
        'preselected_perfume_ids': preselected_perfume_ids,
        'preselected_accessory_ids': preselected_accessory_ids,
        'preselected_grades': preselected_grades,
        'wrapping_fee': wrapping_fee,
        'yer_per_sar': yer_per_sar,
        'initial_grade': initial_grade,
    }
    return render(request, 'store/gift_builder.html', context)


def gift_calculate_live(request):
    """حساب أسعار صندوق الهدية وتحديث المعاينة المباشرة عبر HTMX مع دعم العناصر المتعددة"""
    settings = StoreSettings.get_settings()
    yer_per_sar = settings.yer_per_sar or Decimal('530.00')
    wrapping_fee = settings.gift_wrapping_fee_yer or Decimal('2500.00')

    perfume_ids = request.POST.getlist('perfume_id')
    if not perfume_ids and request.POST.get('perfume_id'):
        perfume_ids = [request.POST.get('perfume_id')]
    perfume_ids = [p for p in perfume_ids if p]

    perfume_grade_default = request.POST.get('perfume_grade', 'original')

    accessory_ids = request.POST.getlist('accessory_id')
    if not accessory_ids and request.POST.get('accessory_id'):
        accessory_ids = [request.POST.get('accessory_id')]
    accessory_ids = [a for a in accessory_ids if a]

    bundle_id = request.POST.get('bundle_id')
    is_wrapping = request.POST.get('is_luxury_gift_wrapping') in ['true', '1', 'on']

    total_yer = Decimal('0.00')
    items_breakdown = []

    if bundle_id:
        parsed_bundle_id = _parse_int_id(bundle_id)
        bundle_obj = GiftBundle.objects.prefetch_related('items').filter(id=parsed_bundle_id, is_active=True).first() if parsed_bundle_id else None
        if not bundle_obj and parsed_bundle_id:
            bundle_obj = Product.objects.filter(id=parsed_bundle_id, is_active=True).first()
        if bundle_obj:
            b_title = getattr(bundle_obj, 'title_ar', getattr(bundle_obj, 'name_ar', 'باقة جاهزة'))
            total_yer += bundle_obj.price_yer
            items_breakdown.append({
                'title': b_title,
                'type': 'باقة جاهزة',
                'price_yer': bundle_obj.price_yer,
            })
            bundle_pids = set(bundle_obj.items.values_list('product_id', flat=True)) if hasattr(bundle_obj, 'items') else set()
            extra_acc_ids = [
                aid_int for aid in accessory_ids
                for aid_int in [_parse_int_id(aid)]
                if aid_int and aid_int not in bundle_pids
            ]
            acc_map = Product.objects.filter(id__in=extra_acc_ids, is_active=True).in_bulk() if extra_acc_ids else {}
            for aid_int in extra_acc_ids:
                a_obj = acc_map.get(aid_int)
                if a_obj:
                    total_yer += a_obj.price_yer
                    items_breakdown.append({
                        'title': a_obj.name_ar,
                        'type': 'ملحق مضاف للباقة',
                        'price_yer': a_obj.price_yer,
                    })
    else:
        parsed_perfume_ids = [pid_int for pid in perfume_ids for pid_int in [_parse_int_id(pid)] if pid_int]
        parsed_acc_ids = [aid_int for aid in accessory_ids for aid_int in [_parse_int_id(aid)] if aid_int]
        all_ids = set(parsed_perfume_ids) | set(parsed_acc_ids)
        prod_map = Product.objects.filter(id__in=all_ids, is_active=True).select_related('category').in_bulk() if all_ids else {}

        for pid_int in parsed_perfume_ids:
            p_obj = prod_map.get(pid_int)
            if p_obj:
                p_grade = request.POST.get(f'grade_{pid_int}') or perfume_grade_default
                p_price = p_obj.price_master_yer if p_grade == 'master' and p_obj.price_master_yer else (p_obj.price_original_yer or p_obj.price_yer)
                total_yer += p_price
                grade_name = 'ماستر' if p_grade == 'master' else 'أصلي'
                items_breakdown.append({
                    'title': p_obj.name_ar,
                    'type': f"عطر ({grade_name})",
                    'price_yer': p_price,
                })

        for aid_int in parsed_acc_ids:
            a_obj = prod_map.get(aid_int)
            if a_obj:
                total_yer += a_obj.price_yer
                items_breakdown.append({
                    'title': a_obj.name_ar,
                    'type': a_obj.category.name_ar if a_obj.category else 'ملحق إضافي',
                    'price_yer': a_obj.price_yer,
                })

    if is_wrapping:
        total_yer += wrapping_fee
        items_breakdown.append({
            'title': 'تغليف هدايا وبطاقة',
            'type': 'خدمة التغليف',
            'price_yer': wrapping_fee,
        })

    total_sar = _yer_to_sar(total_yer, yer_per_sar)

    return render(request, 'store/partials/gift_builder_summary.html', {
        'total_yer': total_yer,
        'total_sar': total_sar,
        'items_breakdown': items_breakdown,
        'yer_per_sar': yer_per_sar,
    })
