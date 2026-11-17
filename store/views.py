import os
import uuid
import logging
import math
import json
import base64
import re
import secrets
from io import BytesIO
from PIL import Image
from decimal import Decimal
from urllib.parse import urlencode, quote
from xml.sax.saxutils import escape as xml_escape
import requests

from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.middleware.csrf import get_token
from django.db import transaction
from django.db.models import Q, F
from django.core.cache import cache
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout, update_session_auth_hash
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.urls import reverse
from django.utils.encoding import iri_to_uri
from django.utils.html import format_html
from django.utils.http import url_has_allowed_host_and_scheme
from datetime import datetime, date, timedelta

from .models import (
    StoreSettings, PaymentAccount, ShippingZone, 
    Category, Brand, Product, 
    Order, OrderItem, HeroBanner, UserProfile, Notification,
    WebPushSubscription, GiftBundle, GiftBundleItem
)
from .cache_service import (
    cache_delete,
    cache_get,
    cache_get_or_set_safe,
    cache_set,
    invalidate_admin_metrics_cache,
    invalidate_notification_cache,
    invalidate_product_cache,
    make_brands_list_key,
    make_catalog_brands_key,
    make_gift_builder_catalog_key,
    make_product_gallery_key,
    make_product_related_key,
    schedule_invalidation,
)

audit_logger = logging.getLogger('store.admin_audit')


def _parse_int_id(raw_val):
    """Parse positive integer ID safely from user/query input without raising ValueError."""
    try:
        val = int(str(raw_val).strip())
        return val if val > 0 else None
    except (TypeError, ValueError):
        return None

logger = logging.getLogger(__name__)


def _get_safe_redirect(request, default='store:home', candidate=None):
    """التحقق من رابط التوجيه والتأكد من أمانه لمنع ثغرات Open Redirect"""
    next_url = candidate or request.POST.get('next') or request.GET.get('next') or request.META.get('HTTP_REFERER')
    if next_url and url_has_allowed_host_and_scheme(url=next_url, allowed_hosts={request.get_host()}):
        return next_url
    return reverse(default)


def _is_htmx_partial(request):
    """التحقق مما إذا كان الطلب استبدالاً جزئياً عبر HTMX وليس تنقلاً كاملاً معززاً بـ hx-boost"""
    return bool(
        request.headers.get('HX-Request')
        and not request.headers.get('HX-Boosted')
        and not request.GET.get('full_page')
    )


def _yer_to_sar(amount_yer, yer_per_sar):
    """تحويل المبلغ من الريال اليمني إلى الريال السعودي مقرباً للأعلى بدون كسور"""
    if not yer_per_sar:
        return 0
    return int(math.ceil(Decimal(str(amount_yer)) / Decimal(str(yer_per_sar))))


def _normalize_phone(phone_str):
    """تطبيع رقم الهاتف المحمول بإزالة الرموز ومفاتيح الدولة المتكررة للمقارنة الدقيقة"""
    digits = re.sub(r'\D', '', str(phone_str or ''))
    if digits.startswith('00967') and len(digits) >= 14:
        digits = digits[5:]
    elif digits.startswith('967') and len(digits) >= 12:
        digits = digits[3:]
    elif digits.startswith('0') and len(digits) == 10 and digits[1] == '7':
        digits = digits[1:]
    return digits


def _find_profile_by_phone(phone_str):
    """البحث عن ملف عميل برقم الهاتف مع احترام الصيغ الدولية والمحلية دون تطابق زائف"""
    raw = str(phone_str or '').strip()
    if not raw:
        return None
    exact = UserProfile.objects.select_related('user').filter(phone=raw).first()
    if exact:
        return exact
    norm = _normalize_phone(raw)
    if len(norm) < 8:
        return None
    candidates = UserProfile.objects.select_related('user').filter(phone__endswith=norm[-8:])
    for prof in candidates:
        if _normalize_phone(prof.phone) == norm:
            return prof
    return None


def _get_client_ip(request):
    """استخراج عنوان IP للعميل مع دعم ترويسة Cloudflare و Reverse Proxy"""
    cf_ip = request.META.get('HTTP_CF_CONNECTING_IP', '').strip()
    if cf_ip:
        return cf_ip
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '').strip()


def _admin_change_url(model_name, obj_id):
    """توليد رابط صفحة التعديل في لوحة التحكم ديناميكياً لدعم المسار السري المخصص"""
    try:
        return reverse(f'admin:store_{model_name}_change', args=[obj_id])
    except Exception:
        prefix = os.getenv('DJANGO_ADMIN_URL', 'admin').strip().strip('/') or 'admin'
        return f"/{prefix}/store/{model_name}/{obj_id}/change/"


def validate_receipt_file(uploaded_file):
    """التحقق الأمني الشامل من ملف إشعار التحويل البنكي (الحجم، الامتداد، وتوقيع المحتوى الثنائي)"""
    if uploaded_file.size > 10 * 1024 * 1024:
        return False, 'حجم ملف إشعار التحويل كبير جداً. الحد الأقصى المسموح به هو 10 ميجابايت.'
        
    ext = os.path.splitext(uploaded_file.name)[1].lower()
    allowed_exts = ['.jpg', '.jpeg', '.png', '.webp', '.pdf', '.heic', '.heif']
    if ext not in allowed_exts:
        return False, 'صيغة ملف الإشعار غير مقبولة. يرجى رفع صورة أو مستند PDF صالح.'
        
    try:
        initial_pos = uploaded_file.tell() if hasattr(uploaded_file, 'tell') else 0
        header = uploaded_file.read(1024)
        if hasattr(uploaded_file, 'seek'):
            uploaded_file.seek(initial_pos)
            
        if ext == '.pdf':
            if not header.startswith(b'%PDF-'):
                return False, 'ملف الـ PDF تالف أو غير صالح كإشعار تحويل.'
        elif ext in ['.heic', '.heif']:
            if b'ftyp' not in header[:32]:
                return False, 'ملف صورة HEIC غير صالح أو تالف.'
        else:
            from PIL import Image
            img = Image.open(uploaded_file)
            img.verify()
            if hasattr(uploaded_file, 'seek'):
                uploaded_file.seek(initial_pos)
    except Exception:
        return False, 'تعذر قراءة ملف الإشعار أو أنه ملف غير صالح كصورة إشعار.'
        
    return True, None



def get_home_deferred_context(request):
    """تجهيز سياق الأشرطة التفاعلية السفلية للصفحة الرئيسية مع استعلامات مُحسنة"""
    from django.db.models import Count, Q
    
    # 1. المنتجات المميزة لشريط التمرير الأفقي (بحد أقصى 8 منتجات)
    featured_products = Product.objects.filter(
        is_active=True, is_featured=True
    ).select_related('category', 'brand').prefetch_related('images').order_by('-created_at')[:8]
    if not featured_products.exists():
        featured_products = Product.objects.filter(
            is_active=True
        ).select_related('category', 'brand').prefetch_related('images').order_by('-created_at')[:8]

    # دالة مساعدة سريعة لجلب أفضل منتجات كل قسم هرمياً (القسم وفروعه) بحد أقصى 8
    def get_category_products(type_keys, limit=8):
        if isinstance(type_keys, str):
            type_keys = [type_keys]
        q_filter = Q(category_type__in=type_keys) | Q(parent__category_type__in=type_keys)
        for k in type_keys:
            q_filter |= Q(slug__icontains=k) | Q(parent__slug__icontains=k)
        
        cat_ids = list(Category.objects.filter(q_filter, is_active=True).values_list('id', flat=True))
        if not cat_ids:
            return Product.objects.none()
        return Product.objects.filter(
            category_id__in=cat_ids,
            is_active=True
        ).select_related('category', 'brand').prefetch_related('images').order_by(
            '-is_featured', '-is_best_seller', '-created_at'
        )[:limit]

    # 2. أشرطة الأقسام الرئيسية المحددة ديناميكياً من لوحة التحكم
    home_slider_cats = Category.objects.filter(
        is_active=True,
        show_in_home_slider=True
    ).order_by('home_slider_order', 'display_order')

    category_sliders = []
    for cat in home_slider_cats:
        cat_ids = cat.get_descendants_and_self_ids()
        cat_prods = Product.objects.filter(
            category_id__in=cat_ids,
            is_active=True
        ).select_related('category', 'brand').prefetch_related('images').order_by(
            '-is_featured', '-is_best_seller', '-created_at'
        )[:8]

        if cat_prods.exists():
            slider_title = cat.home_slider_title or cat.name_ar
            icon = 'gem'
            subtitle = 'تشكيلة راقية ومختارة بعناية فائقة'
            catalog_url = f"/products/?category={cat.slug}"
            slider_id = f"slider-cat-{cat.id}"

            if cat.category_type == 'perfumes':
                icon = 'sparkles'
                subtitle = 'عطور عالمية أصلية وماستر تستر بأعلى ثبات وفوحان'
                catalog_url = reverse('store:perfumes_catalog')
                slider_id = 'perfumes-scroll'
            elif cat.category_type == 'watches':
                icon = 'watch'
                subtitle = 'ساعات رجالية ونسائية بتصاميم عصرية وكلاسيكية راقية'
                catalog_url = reverse('store:watches_catalog')
                slider_id = 'watches-scroll'
            elif cat.category_type in ['cosmetics', 'care']:
                icon = 'heart'
                subtitle = 'منتجات عناية ومكياج أصلي من كبرى الماركات العالمية'
                catalog_url = reverse('store:cosmetics_catalog')
                slider_id = 'cosmetics-scroll'
            elif cat.description:
                subtitle = cat.description

            category_sliders.append({
                'category': cat,
                'title': slider_title,
                'subtitle': subtitle,
                'icon': icon,
                'catalog_url': catalog_url,
                'slider_id': slider_id,
                'products': cat_prods,
            })

    # للتوافقية الكاملة مع الاختبارات والقوالب
    perfume_products = get_category_products('perfumes', limit=8)
    watch_products = get_category_products('watches', limit=8)
    cosmetic_products = get_category_products(['cosmetics', 'care'], limit=8)

    if not category_sliders:
        default_types = [
            ('perfumes', 'قسم العطور الفاخرة', 'sparkles', 'عطور عالمية أصلية وماستر تستر بأعلى ثبات وفوحان', 'store:perfumes_catalog', 'perfumes-scroll'),
            ('watches', 'قسم الساعات الفاخرة', 'watch', 'ساعات رجالية ونسائية بتصاميم عصرية وكلاسيكية راقية', 'store:watches_catalog', 'watches-scroll'),
            (['cosmetics', 'care'], 'مستحضرات التجميل والعناية', 'heart', 'منتجات عناية ومكياج أصلي من كبرى الماركات العالمية', 'store:cosmetics_catalog', 'cosmetics-scroll')
        ]
        for type_keys, title, icon, subtitle, url_name, s_id in default_types:
            prods = get_category_products(type_keys, limit=8)
            if prods.exists():
                cat_obj = Category.objects.filter(category_type=type_keys if isinstance(type_keys, str) else type_keys[0]).first()
                category_sliders.append({
                    'category': cat_obj,
                    'title': title,
                    'subtitle': subtitle,
                    'icon': icon,
                    'catalog_url': reverse(url_name),
                    'slider_id': s_id,
                    'products': prods,
                })

    ready_gift_bundles = list(GiftBundle.objects.filter(is_active=True).prefetch_related('items__product__images').order_by('display_order', '-created_at')[:8])
    if ready_gift_bundles:
        gift_bundles = ready_gift_bundles
    else:
        gift_bundles = get_category_products('bundles', limit=8)
        
    # 3. الماركات والبراندات الفاخرة المسجلة في لوحة التحكم (بحد أقصى 8 براندات)
    featured_brands = Brand.objects.filter(is_active=True).annotate(
        products_count=Count('products', filter=Q(products__is_active=True))
    ).order_by('display_order', '-products_count', 'name_ar')[:8]

    # براندات العطور الفاخرة مع بيانات مخصصة لشريط التمرير
    brand_counts = dict(
        Product.objects.filter(category__category_type='perfumes', is_active=True)
        .exclude(brand_name='')
        .values('brand_name')
        .annotate(total=Count('id'))
        .values_list('brand_name', 'total')[:8]
    )
    
    brand_emblems = {
        'Dior': {'name': 'Christian Dior', 'country': 'Paris', 'icon': 'sparkles', 'badge': 'باريس 1946'},
        'Chanel': {'name': 'Chanel Paris', 'country': 'Paris', 'icon': 'gem', 'badge': 'باريس 1910'},
        'Tom Ford': {'name': 'Tom Ford Beauty', 'country': 'New York', 'icon': 'crown', 'badge': 'نيويورك 2005'},
        'Creed': {'name': 'House of Creed', 'country': 'London', 'icon': 'award', 'badge': 'لندن 1760'},
        'Yves Saint Laurent': {'name': 'YSL Beauté', 'country': 'Paris', 'icon': 'sparkle', 'badge': 'باريس 1961'},
        'Maison Francis Kurkdjian': {'name': 'MFK Paris', 'country': 'Paris', 'icon': 'flame', 'badge': 'باريس 2009'},
    }
    
    perfume_brands_data = []
    for b_name, count in brand_counts.items():
        meta = brand_emblems.get(b_name, {'name': b_name, 'country': 'Luxury Store', 'icon': 'sparkles', 'badge': 'فاخر'})
        perfume_brands_data.append({
            'brand_name': b_name,
            'display_name': meta['name'],
            'country': meta['country'],
            'icon': meta['icon'],
            'badge': meta['badge'],
            'count': count,
        })
    perfume_brands_data = perfume_brands_data[:8]

    return {
        'featured_products': featured_products,
        'category_sliders': category_sliders,
        'perfume_products': perfume_products,
        'watch_products': watch_products,
        'cosmetic_products': cosmetic_products,
        'gift_bundles': gift_bundles,
        'featured_brands': featured_brands,
        'perfume_brands': perfume_brands_data,
    }


def home_deferred_content_view(request):
    """استرجاع وعرض الأشرطة السفلية للصفحة الرئيسية مع كاشينج دجانغو فائق السرعة"""
    active_currency = request.session.get('active_currency', 'YER')
    cache_key = f'bv_home_deferred_html_{active_currency}'

    if not request.GET.get('nocache'):
        cached_html = cache_get(cache_key)
        if cached_html:
            return HttpResponse(cached_html, content_type='text/html; charset=utf-8')

    context = get_home_deferred_context(request)
    response = render(request, 'store/partials/home_deferred_content.html', context)

    cache_set(cache_key, response.content.decode('utf-8'), timeout=900)
    return response


def home_view(request):
    """الصفحة الرئيسية للمتجر — تفتح فورياً (Instant Paint Shell) بفضل الكاشينج والتحميل المتدرج الذكي"""
    from django.core.cache import cache
    
    # 1. قراءة البانرات الترويجية من الكاش
    banners = cache.get('bv_home_banners')
    if banners is None:
        banners = list(HeroBanner.objects.filter(is_active=True).order_by('display_order'))
        try:
            cache.set('bv_home_banners', banners, timeout=900)
        except Exception:
            pass

    # 2. قراءة الأقسام الرئيسية لشريط التصفح العلوي من الكاش
    categories = cache.get('bv_home_categories')
    if categories is None:
        categories = list(Category.objects.filter(is_active=True, parent__isnull=True).order_by('display_order')[:8])
        try:
            cache.set('bv_home_categories', categories, timeout=900)
        except Exception:
            pass

    context = {
        'banners': banners,
        'categories': categories,
    }

    # إذا تم طلب المحتوى كاملاً (كـ crawlers أو tests أو عبر معامل ?full=1)
    if request.GET.get('full') == '1':
        deferred_ctx = get_home_deferred_context(request)
        context.update(deferred_ctx)
        context['full_mode'] = True

    return render(request, 'store/home.html', context)




def perfumes_catalog_view(request):
    """إعادة توجيه ذكية لكتالوج العطور في صفحة الأقسام الموحدة لمنع تكرار الهيدر والفلاتر"""
    params = request.GET.copy()
    params['category'] = 'perfumes'
    return redirect(f"{reverse('store:product_list')}?{params.urlencode()}", permanent=False)


def watches_catalog_view(request):
    """إعادة توجيه ذكية لكتالوج الساعات في صفحة الأقسام الموحدة لمنع تكرار الهيدر والفلاتر"""
    params = request.GET.copy()
    params['category'] = 'watches'
    return redirect(f"{reverse('store:product_list')}?{params.urlencode()}", permanent=False)


def cosmetics_catalog_view(request):
    """إعادة توجيه ذكية لكتالوج مستحضرات التجميل والعناية في صفحة الأقسام الموحدة لمنع تكرار الهيدر والفلاتر"""
    params = request.GET.copy()
    params['category'] = 'cosmetics'
    return redirect(f"{reverse('store:product_list')}?{params.urlencode()}", permanent=False)


def brands_list_view(request):
    """دليل وتصنيف كافة الماركات والبراندات العالمية الفاخرة بالمتجر"""
    from django.db.models import Count
    search_query = request.GET.get('q', '').strip()

    if not search_query:
        brands = cache_get_or_set_safe(
            make_brands_list_key(),
            lambda: list(
                Brand.objects.filter(is_active=True)
                .annotate(products_count=Count('products', filter=Q(products__is_active=True)))
                .prefetch_related('categories')
                .order_by('display_order', '-products_count', 'name_ar')
            ),
            timeout=300,
        ) or []
    else:
        brands = list(
            Brand.objects.filter(is_active=True)
            .filter(
                Q(name_ar__icontains=search_query) |
                Q(name_en__icontains=search_query) |
                Q(description__icontains=search_query)
            )
            .annotate(products_count=Count('products', filter=Q(products__is_active=True)))
            .prefetch_related('categories')
            .order_by('display_order', '-products_count', 'name_ar')
        )
    
    context = {
        'brands': brands,
        'search_query': search_query,
        'total_count': len(brands),
    }
    
    if _is_htmx_partial(request):
        return render(request, 'store/partials/brands_grid.html', context)
        
    return render(request, 'store/brands_list.html', context)


def brand_detail_view(request, slug):
    """صفحة الماركة الفاخرة مع عرض منتجاتها وفلاتر التصفية الـ 4 وشبكة 2*2 للجوال"""
    brand = get_object_or_404(Brand, slug=slug, is_active=True)
    
    # ربط المنتجات بالبراند إما عبر حقل brand أو الاسم المتطابق (للتوافق العكسي التام)
    products = Product.objects.filter(
        Q(brand=brand) | Q(brand_name__iexact=brand.name_en) | Q(brand_name__iexact=brand.name_ar),
        is_active=True
    ).select_related('category', 'brand').prefetch_related('images')
    
    # معلمات الفلترة الأربعة (نفس تصميم صفحة العطور والساعات 4 أيقونات بصف واحد دون سكرول)
    category_filter = request.GET.get('category', '').strip()
    grade_filter = request.GET.get('grade', '').strip()     # original, master
    gender_filter = request.GET.get('gender', '').strip()   # men, women, unisex
    sort_by = request.GET.get('sort', 'newest')             # newest, price_low, price_high, best_sellers
    search_query = request.GET.get('q', '').strip()
    
    if category_filter:
        products = products.filter(category__slug=category_filter)
        
    if grade_filter == 'original':
        products = products.filter(
            Q(price_original_yer__isnull=False) |
            Q(specifications__grade='original')
        )
    elif grade_filter == 'master':
        products = products.filter(
            Q(has_grades=True) |
            Q(price_master_yer__isnull=False) |
            Q(specifications__grade='master')
        )
        
    if gender_filter:
        products = products.filter(
            Q(specifications__gender=gender_filter) |
            Q(description__icontains=gender_filter) |
            Q(name_ar__icontains='رجالي' if gender_filter == 'men' else ('نسائي' if gender_filter == 'women' else 'للجنسين'))
        )
        
    if search_query:
        products = products.filter(
            Q(name_ar__icontains=search_query) |
            Q(name_en__icontains=search_query) |
            Q(description__icontains=search_query)
        )
        
    if sort_by == 'price_low':
        products = products.order_by('price_yer')
    elif sort_by == 'price_high':
        products = products.order_by('-price_yer')
    elif sort_by == 'best_sellers':
        products = products.order_by('-is_best_seller', '-created_at')
    else:
        products = products.order_by('-created_at')
        
    # الأقسام المتاحة لمنتجات هذا البراند
    all_brand_products = Product.objects.filter(
        Q(brand=brand) | Q(brand_name__iexact=brand.name_en) | Q(brand_name__iexact=brand.name_ar),
        is_active=True
    )
    available_category_ids = all_brand_products.values_list('category_id', flat=True).distinct()
    available_categories = Category.objects.filter(id__in=available_category_ids, is_active=True).order_by('display_order', 'name_ar')
    
    # براندات أخرى مقترحة
    other_brands = Brand.objects.filter(is_active=True).exclude(id=brand.id).order_by('display_order')[:6]

    context = {
        'brand': brand,
        'products': products,
        'category_filter': category_filter,
        'grade_filter': grade_filter,
        'gender_filter': gender_filter,
        'sort_by': sort_by,
        'search_query': search_query,
        'available_categories': available_categories,
        'other_brands': other_brands,
        'total_count': products.count(),
    }
    
    if _is_htmx_partial(request):
        return render(request, 'store/partials/product_grid.html', context)
        
    return render(request, 'store/brand_detail.html', context)


def product_list_view(request):
    """كتالوج المنتجات الديناميكي الشامل بهيكلية ثنائية الشريط (شريط الأقسام الرئيسية + شريط التصنيفات الفرعية وأيقونة الفلترة الواحدة)"""
    products = Product.objects.filter(is_active=True).select_related('category', 'brand').prefetch_related('images')
    
    category_slug = request.GET.get('category', '').strip()
    subcategory_slug = request.GET.get('subcategory', '').strip()
    search_query = request.GET.get('q', '').strip()
    sort_by = request.GET.get('sort', 'newest')
    brand_filter = request.GET.get('brand', '').strip()
    grade_filter = request.GET.get('grade', '').strip()
    gender_filter = request.GET.get('gender', '').strip()
    min_price = request.GET.get('min_price', '').strip()
    max_price = request.GET.get('max_price', '').strip()
    
    # استرجاع كافة الأقسام النشطة من الكاش (تجنب 4 استعلامات متكررة للأقسام في كل طلب)
    active_cats = cache_get_or_set_safe(
        'bv_active_categories',
        lambda: list(Category.objects.filter(is_active=True).order_by('display_order', 'id')),
        timeout=300,
    ) or []
    cats_by_id = {c.id: c for c in active_cats}
    cats_by_slug = {c.slug: c for c in active_cats}
    children_map = {}
    for c in active_cats:
        children_map.setdefault(c.parent_id, []).append(c)

    def _descendants_ids(root_id):
        res, queue = [], [root_id]
        while queue:
            cid = queue.pop(0)
            if cid not in res:
                res.append(cid)
                queue.extend(ch.id for ch in children_map.get(cid, []))
        return res

    all_main_categories = sorted(children_map.get(None, []), key=lambda c: (c.display_order, c.id))

    current_category = None
    main_category = None
    active_subcategory = None
    category_subcategories = []

    if category_slug:
        current_category = cats_by_slug.get(category_slug)
        if current_category:
            if current_category.parent_id is None:
                main_category = current_category
                category_subcategories = sorted(children_map.get(main_category.id, []), key=lambda c: (c.display_order, c.name_ar))
                if subcategory_slug:
                    sub_cand = cats_by_slug.get(subcategory_slug)
                    if sub_cand and sub_cand.parent_id == main_category.id:
                        active_subcategory = sub_cand
                target_cat_ids = _descendants_ids(active_subcategory.id if active_subcategory else main_category.id)
                products = products.filter(category_id__in=target_cat_ids)
            else:
                active_subcategory = current_category
                main_category = cats_by_id.get(current_category.parent_id) or current_category.parent
                category_subcategories = sorted(children_map.get(main_category.id, []), key=lambda c: (c.display_order, c.name_ar))
                products = products.filter(category_id__in=_descendants_ids(active_subcategory.id))

    # إذا لم يتم تحديد قسم، نعتمد القسم الافتراضي المحدد من قبل الإدارة من مكان واحد (إعدادات المتجر)
    if not main_category and all_main_categories:
        default_cat = None
        try:
            settings_obj = StoreSettings.get_settings()
            if settings_obj and settings_obj.default_category_id:
                default_cat = next((c for c in all_main_categories if c.id == settings_obj.default_category_id), None)
        except Exception:
            pass

        if not default_cat:
            default_cat = next((c for c in all_main_categories if getattr(c, 'is_default', False)), None)
        if not default_cat:
            default_cat = next((c for c in all_main_categories if c.slug == 'perfumes' or 'عطور' in c.name_ar), None)
        main_category = default_cat or all_main_categories[0]
        current_category = main_category
        category_subcategories = sorted(children_map.get(main_category.id, []), key=lambda c: (c.display_order, c.name_ar))
        products = products.filter(category_id__in=_descendants_ids(main_category.id))
    elif not main_category and not all_main_categories:
        category_subcategories = []

    if search_query:
        products = products.filter(
            Q(name_ar__icontains=search_query) | 
            Q(name_en__icontains=search_query) |
            Q(brand_name__icontains=search_query) |
            Q(description__icontains=search_query)
        )
        
    if brand_filter:
        products = products.filter(brand_name__iexact=brand_filter)

    if grade_filter == 'original':
        products = products.filter(
            Q(has_grades=True, price_original_yer__isnull=False) |
            Q(specifications__grade='original')
        )
    elif grade_filter == 'master':
        products = products.filter(
            Q(has_grades=True) |
            Q(price_master_yer__isnull=False) |
            Q(specifications__grade='master')
        )

    if gender_filter:
        products = products.filter(
            Q(specifications__gender=gender_filter) |
            Q(description__icontains=gender_filter) |
            Q(name_ar__icontains='رجالي' if gender_filter == 'men' else ('نسائي' if gender_filter == 'women' else 'للجنسين')) |
            Q(name_ar__icontains='رجالية' if gender_filter == 'men' else 'نسائية')
        )

    if min_price:
        try:
            products = products.filter(price_yer__gte=Decimal(min_price))
        except Exception:
            pass

    if max_price:
        try:
            products = products.filter(price_yer__lte=Decimal(max_price))
        except Exception:
            pass
        
    # خيارات الترتيب
    if sort_by == 'price_low':
        products = products.order_by('price_yer')
    elif sort_by == 'price_high':
        products = products.order_by('-price_yer')
    elif sort_by == 'best_sellers':
        products = products.order_by('-is_best_seller', '-created_at')
    else: # newest
        products = products.order_by('-created_at')
        
    # الماركات المتوفرة للفلترة في سياق هذا القسم (كاش مع إزالة ترتيب النموذج الافتراضي لمنع DISTINCT المكرر)
    if main_category:
        available_brands = cache_get_or_set_safe(
            make_catalog_brands_key(main_category.id),
            lambda: list(
                Product.objects.filter(
                    category_id__in=main_category.get_descendants_and_self_ids(),
                    is_active=True,
                )
                .exclude(brand_name='')
                .order_by('brand_name')
                .values_list('brand_name', flat=True)
                .distinct()
            ),
            timeout=300,
        ) or []
    else:
        available_brands = cache_get_or_set_safe(
            make_catalog_brands_key(None),
            lambda: list(
                Product.objects.filter(is_active=True)
                .exclude(brand_name='')
                .order_by('brand_name')
                .values_list('brand_name', flat=True)
                .distinct()
            ),
            timeout=300,
        ) or []

    # احتساب الفلاتر النشطة لعداد الأيقونة
    active_filters_count = 0
    if brand_filter:
        active_filters_count += 1
    if grade_filter:
        active_filters_count += 1
    if min_price or max_price:
        active_filters_count += 1
    if sort_by and sort_by != 'newest':
        active_filters_count += 1

    # رابط إعادة ضبط الفلاتر
    if main_category:
        catalog_reset_url = f"{reverse('store:product_list')}?category={main_category.slug}"
        if active_subcategory:
            catalog_reset_url += f"&subcategory={active_subcategory.slug}"
    else:
        catalog_reset_url = reverse('store:product_list')

    # ترقيم المنتجات لتسريع استجابة الصفحة وتفادي تضخم حجم الـ HTML
    paginator = Paginator(products, 24)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context = {
        'products': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'is_paginated': page_obj.has_other_pages(),
        'all_main_categories': all_main_categories,
        'current_category': current_category,
        'main_category': main_category,
        'active_subcategory': active_subcategory,
        'category_subcategories': category_subcategories,
        'search_query': search_query,
        'sort_by': sort_by,
        'brand_filter': brand_filter,
        'grade_filter': grade_filter,
        'min_price': min_price,
        'max_price': max_price,
        'available_brands': available_brands,
        'active_filters_count': active_filters_count,
        'catalog_reset_url': catalog_reset_url,
        'total_count': paginator.count,
    }
    
    # إذا كان الطلب جزئياً من HTMX لاستبدال شبكة المنتجات فقط (وليس hx-boost)
    if _is_htmx_partial(request):
        return render(request, 'store/partials/product_grid.html', context)
        
    return render(request, 'store/product_list.html', context)


def product_quick_view(request, slug):
    """عرض نافذة منبثقة تفاعلية للمنتج (Quick View Modal) دون مغادرة الصفحة"""
    product = get_object_or_404(
        Product.objects.select_related('category').prefetch_related('images'), 
        slug=slug, 
        is_active=True
    )
    images = product.images.all().order_by('display_order')
    settings = StoreSettings.get_settings()
    
    context = {
        'product': product,
        'images': images,
        'specifications': product.specifications or {},
        'store_settings': settings,
        'yer_per_sar': settings.yer_per_sar or Decimal('530.00'),
    }
    return render(request, 'store/partials/quick_view_modal.html', context)


def product_detail_view(request, slug):
    """صفحة تفاصيل المنتج الفاخر مع المواصفات الذكية"""
    if _is_htmx_partial(request):
        return product_quick_view(request, slug)

    product = get_object_or_404(
        Product.objects.select_related('category', 'brand').prefetch_related('images'),
        slug=slug,
        is_active=True
    )
    images = cache_get_or_set_safe(
        make_product_gallery_key(product.id),
        lambda: list(product.images.all()),
        timeout=180,
    ) or []

    related_products = cache_get_or_set_safe(
        make_product_related_key(product.id),
        lambda: list(
            Product.objects.filter(category=product.category, is_active=True)
            .exclude(id=product.id)
            .select_related('category', 'brand')
            .prefetch_related('images')[:4]
        ),
        timeout=180,
    ) or []
    
    context = {
        'product': product,
        'images': images,
        'related_products': related_products,
        'specifications': product.specifications or {},
    }
    return render(request, 'store/product_detail.html', context)


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
    import time
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
    
    # إذا كانت السلة تحتوي منتجات لكن لا يوجد موعد انتهاء، نحدده الآن
    if not expires_at:
        request.session['cart_expires_at'] = now_ts + (res_minutes * 60)
        request.session.modified = True
        return False
        
    if now_ts > expires_at:
        # انتهت مهلة الحجز! نقوم بتفريغ السلة لتحرير المخزون
        request.session['cart'] = {}
        request.session.pop('cart_expires_at', None)
        request.session.pop('gift_data', None)
        request.session.modified = True
        
        if request.user.is_authenticated:
            try:
                UserProfile.objects.filter(user=request.user).update(cart_data={})
            except Exception:
                pass
                
        messages.warning(
            request, 
            f'انتهت مهلة حجز المنتجات في السلة ({res_minutes} دقيقة) وتم تحريرها لإتاحتها للمتسوقين الآخرين. يمكنك اختيار منتجاتك من جديد.'
        )
        return True
        
    return False


def refresh_cart_reservation(request):
    """تحديث أو بدء توقيت حجز السلة عند إضافة أو تعديل منتجات"""
    import time
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
    import time
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

        # دمج السلتين: إذا تواجد نفس العنصر نعتمد الكمية الأنسب للعميل
        merged = dict(db_cart)
        for key, item in guest_cart.items():
            if key in merged:
                merged[key]['quantity'] = max(merged[key].get('quantity', 1), item.get('quantity', 1))
            else:
                merged[key] = item

        # استبعاد العناصر المحذوفة أو المعطلة من قاعدة البيانات
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
    grade = request.POST.get('grade', '').strip() # 'original' أو 'master'
    
    product = get_object_or_404(Product, id=product_id, is_active=True)
    
    # فحص المخزون
    if product.stock_quantity <= 0:
        cart = request.session.get('cart', {})
        cart_count = sum(item.get('quantity', 1) for item in cart.values())
        response = render(request, 'store/partials/cart_badge.html', {'cart_count': cart_count, 'oob_sync': True})
        response['HX-Trigger'] = 'outOfStock'
        return response

    # تحديد السعر ومسمى الدرجة المختارة
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
    
    # دمج معلومات المتغير والدرجة للعرض بالفاتورة والسلة
    parts = [p for p in [grade_label, variant_info] if p]
    combined_variant = ' | '.join(parts)
    
    cart = request.session.get('cart', {})
    item_key = f"{product_id}_{grade}_{variant_info}".strip('_')
    
    # احتساب إجمالي الكمية المضافة مسبقاً لنفس المنتج بجميع درجاته وخياراته
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
    action = request.POST.get('action') # 'increase' or 'decrease'
    
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
    
    # حساب الإجمالي الجديد مع الشحن والتغليف
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


def gift_bundle_detail_view(request, slug):
    """عرض تفاصيل باقة الإهداء الجاهزة ومحتوياتها ونسبة التوفير وزر الشراء المباشر أو التخصيص"""
    bundle = get_object_or_404(
        GiftBundle.objects.prefetch_related('items__product__images', 'items__product__category'),
        slug=slug, 
        is_active=True
    )
    settings = StoreSettings.get_settings()
    yer_per_sar = settings.yer_per_sar or Decimal('530.00')
    wrapping_fee = settings.gift_wrapping_fee_yer or Decimal('2500.00')

    # حساب إجمالي أسعار الأصناف الفردية في حال شراؤها منفصلة
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
    
    # حفظ بيانات الإهداء المرفقة إن وجدت في POST أو تعيين قيم افتراضية
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
                'price_yer': bundle_obj.price_yer
            })
            # حساب أي ملحقات إضافية مختارة مع الباقة بأمان وباستعلام واحد
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
                        'price_yer': a_obj.price_yer
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
                    'price_yer': p_price
                })

        for aid_int in parsed_acc_ids:
            a_obj = prod_map.get(aid_int)
            if a_obj:
                total_yer += a_obj.price_yer
                items_breakdown.append({
                    'title': a_obj.name_ar,
                    'type': a_obj.category.name_ar if a_obj.category else 'ملحق إضافي',
                    'price_yer': a_obj.price_yer
                })

    if is_wrapping:
        total_yer += wrapping_fee
        items_breakdown.append({
            'title': 'تغليف هدايا وبطاقة',
            'type': 'خدمة التغليف',
            'price_yer': wrapping_fee
        })

    total_sar = _yer_to_sar(total_yer, yer_per_sar)

    return render(request, 'store/partials/gift_builder_summary.html', {
        'total_yer': total_yer,
        'total_sar': total_sar,
        'items_breakdown': items_breakdown,
        'yer_per_sar': yer_per_sar,
    })


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
        
    payment_methods = PaymentAccount.objects.filter(is_active=True).order_by('display_order')
    shipping_zones = ShippingZone.objects.filter(is_active=True).order_by('city_name')
    
    gift_data = request.session.get('gift_data', {})
    is_gift_active = bool(gift_data.get('is_gift', False))
    is_luxury_wrapping_active = is_gift_active and bool(gift_data.get('is_luxury_gift_wrapping', False))
    gift_wrapping_fee_yer = settings.gift_wrapping_fee_yer if is_luxury_wrapping_active else Decimal('0.00')

    default_zone = shipping_zones.first()
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
        elif shipping_zones.exists():
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
        elif payment_methods.exists():
            messages.error(request, 'يرجى اختيار وسيلة الدفع.')
            return redirect('store:checkout')

        payment_receipt = request.FILES.get('payment_receipt')
        if payment_receipt:
            is_valid, err_msg = validate_receipt_file(payment_receipt)
            if not is_valid:
                messages.error(request, err_msg)
                return redirect('store:checkout')

        # 1. تدفق ومعالجة بيانات الإهداء بدقة
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
        
        payment_currency_selected = request.POST.get('payment_currency_selected', 'YER')
        if payment_currency_selected not in ('YER', 'SAR'):
            payment_currency_selected = 'YER'
        if selected_payment and selected_payment.currency in ('YER', 'SAR'):
            payment_currency_selected = selected_payment.currency
        
        # إنشاء رقم طلب مشفر عالي العشوائية والأمان ومنع التصادمات
        while True:
            order_number = f"BV-{secrets.token_hex(4).upper()}"
            if not Order.objects.filter(order_number=order_number).exists():
                break
        
        with transaction.atomic():
            # تجميع إجمالي الكميات المطلوبة لكل product_id عبر جميع الدرجات والباقات لمنع البيع الزائد
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

            # احتساب الأسعار الحية المطابقة لقاعدة البيانات داخل نفس المعاملة الذرية
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
                # الحقول الجديدة: الهدايا والدفع بالريال السعودي
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
            
            # حفظ عناصر الطلب بنفس السعر الحي المعتمد بالفاتورة
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

            # خصم ذري موحد للمخزون عبر F() لكل منتج وتنبيه الإدارة بانخفاض المخزون
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
                from .signals import invalidate_home_and_catalog_cache
                transaction.on_commit(invalidate_home_and_catalog_cache)

        # 1. إرسال إشعار تأكيد للعميل (إذا كان مسجلاً الدخول)
        if request.user.is_authenticated:
            Notification.notify_user(
                user=request.user,
                title=f"تم استلام طلبكم بنجاح #{order.order_number}",
                message=f"شكراً لتسوقكم من براند فيلورا. طلبكم بقيمة {order.total_yer:,.0f} ر.ي قيد التحقق من إشعار التحويل.",
                notification_type='order_created',
                order=order,
                link=f"/order-success/{order.order_number}/"
            )

        # 2. إرسال تنبيه لإدارة المتجر بوصول طلب جديد
        Notification.notify_admin(
            title=f"طلب جديد #{order.order_number}",
            message=f"طلب جديد من {customer_name} في {city_name} بقيمة {order.total_yer:,.0f} ر.ي بانتظار فحص السند والاعتماد.",
            notification_type='order_created',
            order=order,
            link=_admin_change_url('order', order.id),
        )

        # حفظ بيانات ملف العميل المسجل لتسهيل طلباته اللاحقة
        if request.user.is_authenticated:
            user_profile, _ = UserProfile.objects.get_or_create(user=request.user)
            if not user_profile.phone and customer_phone:
                user_profile.phone = customer_phone
            if not user_profile.shipping_address and shipping_address:
                user_profile.shipping_address = shipping_address
                user_profile.preferred_city = city_name
            user_profile.save()
                
        # حفظ رقم الطلب في الجلسة لتوثيق ملكية رفع الفواتير والعمليات
        request.session['last_order_number'] = order.order_number
        # تفريغ السلة وبيانات الهدية بعد إتمام الطلب وتصفيرها بحساب العميل
        request.session['cart'] = {}
        request.session.pop('gift_data', None)
        request.session.pop('cart_expires_at', None)
        request.session.modified = True
        if request.user.is_authenticated:
            UserProfile.objects.filter(user=request.user).update(cart_data={})

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
    """صفحة نجاح الطلب ورابط الواتساب وتفاصيل الإشعار وتفاصيل الهدية"""
    order = get_object_or_404(Order, order_number=order_number)
    settings = StoreSettings.get_settings()
    
    # قائمة المنتجات مع تحديد نوع العطر (أصلي / ماستر)
    items_lines = []
    for item in order.items.all():
        variant_desc = f" [{item.variant_info}]" if item.variant_info else ""
        items_lines.append(f"• {item.product_name}{variant_desc} × {item.quantity} = {item.total_price_yer:,.0f} ر.ي")
    items_text = "\n".join(items_lines)

    # تفاصيل الهدية إن وجدت
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

    # تجهيز رسالة واتساب منسقة بنقرة واحدة
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
    
    # رابط بوليصة المستلم خالية من الأسعار
    gift_slip_url = request.build_absolute_uri(reverse('store:gift_slip', kwargs={'order_number': order.order_number}))
    
    # رابط واتساب خاص بالمستلم لتهنئته ومشاركته كرت الإهداء وتتبع الشحنة بدون أسعار
    recipient_whatsapp_url = None
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
        
        # التحقق الأمني الصارم من الملكية:
        # يُسمح فقط للمستخدم المسجل المالك للطلب، أو للإدارة، أو للضيف في نفس جلسة المتصفح التي أتم فيها الطلب
        session_order = request.session.get('last_order_number')
        is_authorized = (session_order == order.order_number)
        if request.user.is_authenticated:
            if request.user.is_staff or (order.user and order.user == request.user):
                is_authorized = True
                
        if not is_authorized:
            return JsonResponse({'status': 'error', 'message': 'غير مصرح بالوصول لهذا الطلب'}, status=403)
            
        data = json.loads(request.body.decode('utf-8'))
        image_data = data.get('image_data', '')
        if not image_data or not image_data.startswith('data:image'):
            return JsonResponse({'status': 'error', 'message': 'بيانات الصورة غير صالحة'}, status=400)

        # الحد الأقصى لحجم حمولة Base64 هو 4 ميجابايت لمنع هجمات DoS واستنزاف الذاكرة
        if len(image_data) > 4 * 1024 * 1024:
            return JsonResponse({'status': 'error', 'message': 'حجم الصورة كبير جداً ويتجاوز الحد المسموح'}, status=400)
            
        format_prefix, b64_str = image_data.split(';base64,')
        decoded_bytes = base64.b64decode(b64_str)

        # التحقق من أن المحتوى الثنائي يمثل صورة صالحة بواسطة Pillow
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
            'message': 'تم حفظ ورفع الفاتورة بنجاح'
        })
    except Exception as e:
        logger.error(f"Error saving invoice image for order {order_number}: {e}")
        return JsonResponse({'status': 'error', 'message': 'حدث خطأ داخلي أثناء معالجة وحفظ صورة الفاتورة.'}, status=500)



def pwa_manifest(request):
    """ملف manifest.json لدعم تثبيت المتجر كتطبيق هاتف PWA متكامل — محسّن لـ ASO"""
    settings = StoreSettings.get_settings()
    manifest_data = {
        "id": "/",
        "name": "veloura",
        "short_name": "veloura",
        "description": "متجر veloura الفاخر — عطور أصلية وماستر، ساعات راقية رجالية ونسائية، ومستحضرات تجميل عالمية مع توصيل سريع لكافة محافظات اليمن والسعودية",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#FFF5F7",
        "theme_color": "#E11D48",
        "lang": "ar",
        "dir": "rtl",
        "categories": ["shopping", "lifestyle", "beauty"],
        "prefer_related_applications": False,
        "launch_handler": {
            "client_mode": "navigate-existing"
        },
        "handle_links": "preferred",
        "icons": [
            {"src": "/static/icons/icon-48.png",  "sizes": "48x48",   "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-72.png",  "sizes": "72x72",   "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-96.png",  "sizes": "96x96",   "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-128.png", "sizes": "128x128", "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-144.png", "sizes": "144x144", "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-256.png", "sizes": "256x256", "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-384.png", "sizes": "384x384", "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/maskable-192.png", "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
            {"src": "/static/icons/maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "screenshots": [
            {
                "src": "/static/icons/screenshots/screenshot-mobile-1.png",
                "sizes": "1080x1920",
                "type": "image/png",
                "form_factor": "narrow",
                "label": "الصفحة الرئيسية — تشكيلة العطور والساعات الفاخرة"
            },
            {
                "src": "/static/icons/screenshots/screenshot-mobile-2.png",
                "sizes": "1080x1920",
                "type": "image/png",
                "form_factor": "narrow",
                "label": "تفاصيل المنتج — عرض الأسعار بالريال اليمني والسعودي"
            },
            {
                "src": "/static/icons/screenshots/screenshot-mobile-3.png",
                "sizes": "1080x1920",
                "type": "image/png",
                "form_factor": "narrow",
                "label": "إتمام الطلب — دفع عبر الكريمي وجوالي والدفع عند الاستلام"
            },
            {
                "src": "/static/icons/screenshots/screenshot-wide-1.png",
                "sizes": "1920x1080",
                "type": "image/png",
                "form_factor": "wide",
                "label": "متجر Brand Veloura — تصفح من الكمبيوتر"
            }
        ],
        "shortcuts": [
            {
                "name": "العطور الملكية",
                "short_name": "عطور",
                "url": "/perfumes/",
                "description": "تصفح العطور الأصلية والماستر",
                "icons": [{"src": "/static/icons/icon-96.png", "sizes": "96x96"}]
            },
            {
                "name": "الساعات الفاخرة",
                "short_name": "ساعات",
                "url": "/watches/",
                "description": "تشكيلة الساعات الراقية",
                "icons": [{"src": "/static/icons/icon-96.png", "sizes": "96x96"}]
            },
            {
                "name": "ركن الهدايا الملكي",
                "short_name": "هدايا",
                "url": "/gifting/",
                "description": "تجهيز باقات الإهداء والتغليف الفاخر",
                "icons": [{"src": "/static/icons/icon-96.png", "sizes": "96x96"}]
            },
            {
                "name": "سلة المشتريات",
                "short_name": "السلة",
                "url": "/cart/",
                "description": "معاينة السلة وإتمام الطلب",
                "icons": [{"src": "/static/icons/icon-96.png", "sizes": "96x96"}]
            }
        ]
    }
    return JsonResponse(manifest_data, content_type='application/manifest+json')


def service_worker(request):
    """ملف sw.js لإدارة الكاش، التصفح أوفلاين، واستقبال إشعارات PWA وتطبيق الهاتف"""
    sw_code = """
    const CACHE_NAME = 'brand-veloura-pwa-v5';
    const OFFLINE_URL = '/offline/';
    const PRECACHE_ASSETS = [
        OFFLINE_URL,
        '/manifest.json',
        '/static/icons/icon-48.png',
        '/static/icons/icon-72.png',
        '/static/icons/icon-96.png',
        '/static/icons/icon-128.png',
        '/static/icons/icon-144.png',
        '/static/icons/icon-192.png',
        '/static/icons/icon-256.png',
        '/static/icons/icon-384.png',
        '/static/icons/icon-512.png',
        '/static/icons/maskable-192.png',
        '/static/icons/maskable-512.png',
        '/static/icons/apple-touch-icon.png',
        '/static/images/logo.jpg'
    ];

    self.addEventListener('install', (event) => {
        event.waitUntil(
            caches.open(CACHE_NAME).then((cache) => {
                return cache.addAll(PRECACHE_ASSETS);
            })
        );
        self.skipWaiting();
    });

    self.addEventListener('activate', (event) => {
        event.waitUntil(
            caches.keys().then((keys) => {
                return Promise.all(
                    keys.map((key) => {
                        if (key !== CACHE_NAME) {
                            return caches.delete(key);
                        }
                    })
                );
            })
        );
        self.clients.claim();
    });

    const NO_CACHE_PREFIXES = [
        '/admin',
        '/api/',
        '/partials/',
        '/notifications/',
        '/cart',
        '/checkout',
        '/account',
        '/order',
        '/login',
        '/register',
        '/logout',
        '/auth/',
        '/set-currency',
        '/get-shipping-fee',
        '/gifting/calculate',
    ];

    self.addEventListener('fetch', (event) => {
        if (event.request.method !== 'GET') return;
        if (event.request.headers.get('HX-Request')) return;
        const url = new URL(event.request.url);
        if (url.origin !== self.location.origin) return;
        if (NO_CACHE_PREFIXES.some((prefix) => url.pathname.startsWith(prefix))) return;

        if (event.request.mode === 'navigate') {
            event.respondWith(
                fetch(event.request)
                    .then((networkResponse) => {
                        const cc = (networkResponse.headers.get('Cache-Control') || '').toLowerCase();
                        if (networkResponse && networkResponse.status === 200 && !cc.includes('no-store') && !cc.includes('private')) {
                            const copy = networkResponse.clone();
                            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
                        }
                        return networkResponse;
                    })
                    .catch(async () => {
                        const cachedResponse = await caches.match(event.request);
                        if (cachedResponse) return cachedResponse;
                        return caches.match(OFFLINE_URL);
                    })
            );
            return;
        }

        if (url.pathname.startsWith('/static/')) {
            event.respondWith(
                caches.match(event.request).then((cachedResponse) => {
                    if (cachedResponse) return cachedResponse;
                    return fetch(event.request).then((networkResponse) => {
                        if (networkResponse && networkResponse.status === 200) {
                            const copy = networkResponse.clone();
                            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
                        }
                        return networkResponse;
                    }).catch(() => {
                        return new Response('', { status: 408, statusText: 'Request timed out' });
                    });
                })
            );
        }
    });

    // الاستماع لإشعارات الويب وتطبيق الهاتف المباشرة (Push Notifications)
    self.addEventListener('push', (event) => {
        let payload = {
            title: 'Brand Veloura',
            body: 'إشعار جديد من المتجر',
            url: '/',
            icon: '/static/icons/icon-192.png',
            badge: '/static/icons/icon-192.png'
        };
        if (event.data) {
            try {
                payload = Object.assign(payload, event.data.json());
            } catch (err) {
                payload.body = event.data.text();
            }
        }
        const options = {
            body: payload.body,
            icon: payload.icon || '/static/icons/icon-192.png',
            badge: payload.badge || '/static/icons/icon-192.png',
            vibrate: [200, 100, 200],
            data: { url: payload.url || '/' },
            dir: 'rtl',
            lang: 'ar',
            tag: 'brand-veloura-notification'
        };
        event.waitUntil(
            self.registration.showNotification(payload.title, options)
        );
    });

    // التعامل مع النقر على الإشعار وتوجيه العميل للرابط المطلوب
    self.addEventListener('notificationclick', (event) => {
        event.notification.close();
        const targetUrl = (event.notification.data && event.notification.data.url) ? event.notification.data.url : '/';
        event.waitUntil(
            clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
                for (let i = 0; i < windowClients.length; i++) {
                    const client = windowClients[i];
                    if (client.url.includes(self.location.origin) && 'focus' in client) {
                        client.navigate(targetUrl);
                        return client.focus();
                    }
                }
                if (clients.openWindow) {
                    return clients.openWindow(targetUrl);
                }
            })
        );
    });
    """
    return HttpResponse(sw_code, content_type='application/javascript')



def push_vapid_key(request):
    """إرجاع المفتاح العام VAPID لاشتراك أجهزة العملاء في إشعارات PWA"""
    from .push_notifications import get_or_create_vapid_keys
    pub_key, _, _ = get_or_create_vapid_keys()
    return JsonResponse({'publicKey': pub_key})


@require_POST
def push_subscribe(request):
    """تسجيل وتحديث اشتراك جهاز العميل في إشعارات الويب وتطبيق الهاتف مع تحصين ضد الهجمات"""
    client_ip = _get_client_ip(request)
    push_throttle_key = f"bv_push_sub_rate_{client_ip}"
    req_count = cache.get(push_throttle_key, 0)
    if req_count >= 30:
        return JsonResponse({'error': 'Too many requests. Please try again later.'}, status=429)
    cache.set(push_throttle_key, req_count + 1, timeout=60)

    try:
        data = json.loads(request.body.decode('utf-8'))
        endpoint = str(data.get('endpoint', '')).strip()
        keys = data.get('keys', {})
        p256dh = str(keys.get('p256dh', '')).strip()
        auth = str(keys.get('auth', '')).strip()

        if not endpoint or not p256dh or not auth:
            return JsonResponse({'error': 'Invalid subscription payload'}, status=400)

        # التحقق من أن الرابط صالح ويستخدم بروتوكول HTTPS
        if not endpoint.startswith('https://') or len(endpoint) > 500:
            return JsonResponse({'error': 'Invalid endpoint protocol or length'}, status=400)

        if len(p256dh) > 255 or len(auth) > 255:
            return JsonResponse({'error': 'Invalid key parameters'}, status=400)

        user = request.user if request.user.is_authenticated else None
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:250]

        sub, created = WebPushSubscription.objects.update_or_create(
            endpoint=endpoint,
            defaults={
                'user': user,
                'p256dh': p256dh,
                'auth': auth,
                'user_agent': user_agent
            }
        )
        return JsonResponse({'success': True, 'id': sub.id, 'created': created})
    except Exception as ex:
        logger.warning(f"Push subscription error from {client_ip}: {ex}")
        return JsonResponse({'error': 'Failed to process subscription'}, status=400)


# ==============================================================================
# أنظمة المصادقة والحسابات الشخصية (Authentication & User Accounts)
# ==============================================================================

def login_view(request):
    """صفحة تسجيل الدخول الفاخرة للعملاء مع حماية ضد التخمين ودعم الدخول عبر Google"""
    if request.user.is_authenticated:
        return redirect('store:account_profile')
        
    next_url = request.GET.get('next', '')
    
    if request.method == 'POST':
        client_ip = _get_client_ip(request)
        throttle_key = f"bv_login_fails_{client_ip}"
        failed_attempts = cache_get(throttle_key, 0)
        if failed_attempts >= 10:
            messages.error(request, 'تم تجاوز الحد الأقصى لمحاولات تسجيل الدخول. يرجى الانتظار 10 دقائق والمحاولة مجدداً.')
            return render(request, 'store/auth/login.html', {'identifier': request.POST.get('identifier', ''), 'next_url': request.POST.get('next', '')})

        identifier = request.POST.get('identifier', '').strip()
        password = request.POST.get('password', '')
        remember_me = request.POST.get('remember_me')
        next_url = request.POST.get('next', '')
        
        if not identifier or not password:
            messages.error(request, 'يرجى إدخال رقم الهاتف أو البريد الإلكتروني والرمز السري.')
            return render(request, 'store/auth/login.html', {'identifier': identifier, 'next_url': next_url})
            
        # التحقق من نوع المدخل: رقم هاتف، بريد إلكتروني، أو اسم مستخدم
        username = identifier
        if '@' in identifier:
            matched_user = User.objects.filter(email__iexact=identifier).first()
            if matched_user:
                username = matched_user.username
        else:
            matched_user_by_name = User.objects.filter(username__iexact=identifier).first()
            if matched_user_by_name:
                username = matched_user_by_name.username
            else:
                matched_profile = _find_profile_by_phone(identifier)
                if matched_profile:
                    username = matched_profile.user.username
                
        user = authenticate(request, username=username, password=password)
        if user is not None:
            if user.is_active:
                cache_delete(throttle_key)
                auth_login(request, user)
                
                # تمديد الجلسة والكوكيز: سنة كاملة افتراضياً و 90 يوماً كحد أدنى (منع انتهاء الجلسة عند إغلاق المتصفح)
                expiry_seconds = 60 * 60 * 24 * 365 if remember_me else 60 * 60 * 24 * 90
                request.session.set_expiry(expiry_seconds)
                
                # دمج واستعادة سلة المشتريات المحفوظة بحساب العميل
                merge_and_restore_user_cart(request, user)
                
                display_name = user.first_name or user.username
                messages.success(request, f'تم تسجيل الدخول بنجاح. مرحباً {display_name}.')
                return redirect(_get_safe_redirect(request, default='store:home'))
            else:
                messages.error(request, 'هذا الحساب معطل حالياً. يرجى التواصل مع إدارة المتجر.')
        else:
            cache_set(throttle_key, failed_attempts + 1, timeout=600)
            messages.error(request, 'بيانات الدخول غير صحيحة. يرجى التحقق من رقم الهاتف أو البريد الإلكتروني والرمز السري.')
            
    return render(request, 'store/auth/login.html', {'next_url': next_url})


def register_view(request):
    """صفحة إنشاء حساب جديد برقم الهاتف والرمز السري"""
    if request.user.is_authenticated:
        return redirect('store:account_profile')
        
    next_url = request.GET.get('next', '')
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email_raw = request.POST.get('email', '').strip().lower()
        phone = request.POST.get('phone', '').strip()
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')
        next_url = request.POST.get('next', '')

        def _render_register_error(err_text):
            messages.error(request, err_text)
            return render(request, 'store/auth/register.html', {
                'next_url': next_url,
                'name': name,
                'email': email_raw,
                'phone': phone,
            })

        client_ip = _get_client_ip(request)
        reg_throttle_key = f"bv_register_rate_{client_ip}"
        reg_count = cache_get(reg_throttle_key, 0)
        if reg_count >= 10:
            return _render_register_error('تم تجاوز الحد المسموح لمحاولات إنشاء الحسابات من هذا الجهاز مؤقتاً. يرجى الانتظار 15 دقيقة.')

        if not name:
            return _render_register_error('يرجى إدخال الاسم.')

        if not phone:
            return _render_register_error('يرجى إدخال رقم الهاتف (مطلوب لتوثيق الحساب وتسجيل الدخول).')

        clean_phone_digits = _normalize_phone(phone)
        if len(clean_phone_digits) < 8:
            return _render_register_error('يرجى إدخال رقم هاتف صحيح لا يقل عن 8 أرقام.')

        if _find_profile_by_phone(phone):
            return _render_register_error('رقم الهاتف هذا مسجل مسبقاً بحساب آخر. يرجى تسجيل الدخول به.')
            
        email = email_raw
        if email:
            if '@' not in email:
                return _render_register_error('يرجى إدخال بريد إلكتروني صحيح أو ترك الحقل فارغاً.')
            if User.objects.filter(email__iexact=email).exists():
                return _render_register_error('البريد الإلكتروني مسجل مسبقاً. يرجى تسجيل الدخول.')
        else:
            email = f"u_{clean_phone_digits}@brandveloura.local"
            
        if password != password_confirm:
            return _render_register_error('الرمزان السريان غير متطابقين.')

        try:
            temp_user = User(username=f"u_{clean_phone_digits}", email=email, first_name=name)
            validate_password(password, user=temp_user)
        except ValidationError as exc:
            return _render_register_error(' '.join(exc.messages))
            
        # إنشاء اسم مستخدم فريد يعتمد على رقم الهاتف
        clean_prefix = f"u_{clean_phone_digits}" if clean_phone_digits else (''.join(c for c in email.split('@')[0] if c.isalnum() or c in '_-') or 'user')
        final_username = clean_prefix
        counter = 1
        while User.objects.filter(username=final_username).exists():
            final_username = f"{clean_prefix}_{counter}"
            counter += 1
            
        # إنشاء حساب المستخدم
        new_user = User.objects.create_user(
            username=final_username,
            email=email,
            password=password,
            first_name=name
        )
        
        # إنشاء الملف التعريفي المرتبط
        UserProfile.objects.create(
            user=new_user,
            phone=phone
        )
        
        # تسجيل الدخول وتمديد الجلسة لسنة ومزامنة السلة
        cache_set(reg_throttle_key, reg_count + 1, timeout=900)
        auth_login(request, new_user)
        request.session.set_expiry(60 * 60 * 24 * 365)
        sync_cart_to_profile(request)
        
        messages.success(request, f'تم إنشاء الحساب بنجاح. مرحباً {name}.')
        return redirect(_get_safe_redirect(request, default='store:home'))
        
    return render(request, 'store/auth/register.html', {'next_url': next_url})


def logout_view(request):
    """تسجيل الخروج"""
    auth_logout(request)
    messages.success(request, 'تم تسجيل الخروج بنجاح.')
    return redirect('store:home')


def google_login_redirect(request):
    """بدء تدفق المصادقة عبر Google OAuth 2.0 مع حماية state ضد هجمات Login CSRF"""
    settings = StoreSettings.get_settings()
    client_id = settings.effective_google_client_id
    next_url = request.GET.get('next', '')
    
    if not client_id:
        messages.info(
            request, 
            'لتفعيل الدخول عبر Google، يرجى حفظ معرف Google Client ID في إعدادات المتجر بلوحة الإدارة.'
        )
        return redirect(f"{reverse('store:login')}?next={quote(next_url)}")
        
    redirect_uri = request.build_absolute_uri(reverse('store:google_callback'))
    if os.getenv('DJANGO_DEBUG', 'False').lower() not in ('true', '1') and redirect_uri.startswith('http://'):
        redirect_uri = redirect_uri.replace('http://', 'https://', 1)

    oauth_state = secrets.token_urlsafe(24)
    request.session['google_oauth_state'] = oauth_state
    if next_url and url_has_allowed_host_and_scheme(url=next_url, allowed_hosts={request.get_host()}):
        request.session['google_oauth_next'] = next_url
    else:
        request.session.pop('google_oauth_next', None)
    request.session.modified = True

    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'access_type': 'online',
        'prompt': 'select_account',
        'state': oauth_state,
    }
    return redirect(f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}")


@csrf_exempt
def google_auth_callback(request):
    """
    استقبال التحقق من Google وتسجيل الدخول / إنشاء الحساب تلقائياً:
    1. عبر Google Identity Services (GIS) Token POST مع التحقق من g_csrf_token و aud و iss
    2. عبر OAuth 2.0 Authorization Code GET مع التحقق الصارم من state و email_verified
    """
    settings = StoreSettings.get_settings()
    saved_next = request.session.pop('google_oauth_next', '')
    next_url = _get_safe_redirect(request, default='store:home', candidate=saved_next)
    
    credential = request.POST.get('credential')
    code = request.GET.get('code')
    
    user_email = None
    first_name = ''
    last_name = ''
    avatar_url = ''
    
    # 1. التحقق من التوكن القادم من Google Identity Services (GIS)
    if credential:
        g_csrf_cookie = request.COOKIES.get('g_csrf_token', '')
        g_csrf_body = request.POST.get('g_csrf_token', '')
        if not g_csrf_cookie or not g_csrf_body or not secrets.compare_digest(g_csrf_cookie, g_csrf_body):
            messages.error(request, 'تعذر التحقق من رمز حماية CSRF الخاص بجلسة Google.')
            return redirect('store:login')

        client_id = settings.effective_google_client_id
        if not client_id:
            messages.error(request, 'تسجيل الدخول عبر Google غير مهيأ حالياً في المتجر.')
            return redirect('store:login')

        try:
            verify_res = requests.post(
                'https://oauth2.googleapis.com/tokeninfo',
                data={'id_token': credential},
                timeout=8,
            )
            if verify_res.status_code == 200:
                payload = verify_res.json()
                if payload.get('aud') != client_id:
                    messages.error(request, 'رمز المصادقة غير صالح أو صادر لتطبيق آخر.')
                    return redirect('store:login')
                if payload.get('iss') not in ('https://accounts.google.com', 'accounts.google.com'):
                    messages.error(request, 'مصدر رمز المصادقة غير موثوق.')
                    return redirect('store:login')
                if payload.get('email_verified') not in (True, 'true'):
                    messages.error(request, 'البريد الإلكتروني لحساب Google غير موثق.')
                    return redirect('store:login')
                user_email = payload.get('email', '').strip().lower()
                first_name = payload.get('given_name') or payload.get('name', 'مستخدم')
                last_name = payload.get('family_name', '')
                avatar_url = payload.get('picture', '')
            else:
                messages.error(request, 'تعذر التحقق من رمز المصادقة المقدم من Google.')
                return redirect('store:login')
        except Exception:
            messages.error(request, 'تعذر الاتصال بخوادم Google في الوقت الحالي.')
            return redirect('store:login')
            
    # 2. التحقق من كود التفويض OAuth 2.0
    elif code:
        expected_state = request.session.pop('google_oauth_state', None)
        received_state = request.GET.get('state', '')
        if not expected_state or not received_state or not secrets.compare_digest(str(expected_state), str(received_state)):
            messages.error(request, 'انتهت صلاحية جلسة المصادقة مع Google. يرجى المحاولة مرة أخرى.')
            return redirect('store:login')

        client_id = settings.effective_google_client_id
        client_secret = settings.effective_google_client_secret
        redirect_uri = request.build_absolute_uri(reverse('store:google_callback'))
        if os.getenv('DJANGO_DEBUG', 'False').lower() not in ('true', '1') and redirect_uri.startswith('http://'):
            redirect_uri = redirect_uri.replace('http://', 'https://', 1)
        
        try:
            token_res = requests.post(
                'https://oauth2.googleapis.com/token',
                data={
                    'code': code,
                    'client_id': client_id,
                    'client_secret': client_secret,
                    'redirect_uri': redirect_uri,
                    'grant_type': 'authorization_code',
                },
                timeout=8
            )
            token_json = token_res.json()
            access_token = token_json.get('access_token')
            if access_token:
                userinfo_res = requests.get(
                    'https://www.googleapis.com/oauth2/v3/userinfo',
                    headers={'Authorization': f'Bearer {access_token}'},
                    timeout=8
                )
                if userinfo_res.status_code == 200:
                    u_data = userinfo_res.json()
                    if u_data.get('email_verified') not in (True, 'true') and u_data.get('verified_email') is not True:
                        messages.error(request, 'البريد الإلكتروني لحساب Google غير موثق.')
                        return redirect('store:login')
                    user_email = u_data.get('email', '').strip().lower()
                    first_name = u_data.get('given_name') or u_data.get('name', 'مستخدم')
                    last_name = u_data.get('family_name', '')
                    avatar_url = u_data.get('picture', '')
                else:
                    messages.error(request, 'تعذر قراءة بيانات الملف الشخصي من Google.')
                    return redirect('store:login')
            else:
                err_desc = token_json.get('error_description') or token_json.get('error') or 'تعذر التحقق من كود المصادقة'
                messages.error(request, f'تعذر تسجيل الدخول عبر Google: {err_desc}')
                return redirect('store:login')
        except Exception:
            messages.error(request, 'تعذر استكمال الاتصال بخدمة Google في الوقت الحالي.')
            return redirect('store:login')
            
    else:
        messages.error(request, 'لم يتم تلقي بيانات مصادقة صالحة من Google.')
        return redirect('store:login')
        
    if not user_email:
        messages.error(request, 'لم نتمكن من قراءة البريد الإلكتروني من حساب Google.')
        return redirect('store:login')
        
    # البحث عن المستخدم أو إنشاء حساب جديد
    user = User.objects.filter(email__iexact=user_email).first()
    if not user:
        clean_prefix = ''.join(c for c in user_email.split('@')[0] if c.isalnum() or c in '_-') or 'google_user'
        final_username = clean_prefix
        counter = 1
        while User.objects.filter(username=final_username).exists():
            final_username = f"{clean_prefix}_{counter}"
            counter += 1
            
        user = User.objects.create_user(
            username=final_username,
            email=user_email,
            first_name=first_name,
            last_name=last_name,
        )
        user.set_unusable_password()
        user.save()
        
    # تحديث الملف الشخصي
    profile, _ = UserProfile.objects.get_or_create(user=user)
    if avatar_url and not profile.avatar_url:
        profile.avatar_url = avatar_url
        profile.save(update_fields=['avatar_url'])
        
    # تسجيل الدخول وتمديد الجلسة لسنة كاملة واستعادة السلة المدمجة
    auth_login(request, user)
    request.session.set_expiry(60 * 60 * 24 * 365)
    merge_and_restore_user_cart(request, user)
    
    display_name = user.first_name or user.username
    messages.success(request, f'تم تسجيل الدخول عبر Google بنجاح. مرحباً {display_name}.')
    return redirect(next_url)


@login_required(login_url='store:login')
def account_profile_view(request):
    """الملف الشخصي للمستخدم، سجل الطلبات، وتحديث بيانات التوصيل وكلمة المرور"""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        # 1. تغيير كلمة المرور
        if action == 'change_password':
            current_password = request.POST.get('current_password', '')
            new_password = request.POST.get('new_password', '')
            confirm_password = request.POST.get('confirm_password', '')
            
            if not request.user.has_usable_password():
                messages.info(request, 'تم تسجيل هذا الحساب عبر Google، ولا يتطلب كلمة مرور.')
                return redirect('store:account_profile')
                
            if not request.user.check_password(current_password):
                messages.error(request, 'كلمة المرور الحالية غير صحيحة.')
            elif new_password != confirm_password:
                messages.error(request, 'كلمتا المرور غير متطابقتين.')
            else:
                try:
                    validate_password(new_password, user=request.user)
                except ValidationError as exc:
                    messages.error(request, ' '.join(exc.messages))
                else:
                    request.user.set_password(new_password)
                    request.user.save()
                    update_session_auth_hash(request, request.user)
                    messages.success(request, 'تم تغيير كلمة المرور بنجاح.')
            return redirect('store:account_profile')
            
        # 2. تعديل البيانات وعنوان التوصيل
        else:
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            phone = request.POST.get('phone', '').strip()
            preferred_city = request.POST.get('preferred_city', '').strip()
            shipping_address = request.POST.get('shipping_address', '').strip()
            
            if first_name:
                request.user.first_name = first_name
            if last_name:
                request.user.last_name = last_name
            request.user.save(update_fields=['first_name', 'last_name'])
            
            # رقم الهاتف غير قابل للتعديل نهائياً لأسباب أمنية وتثبيت هوية الحساب
            if not profile.phone and phone:
                clean_phone_digits = _normalize_phone(phone)
                if len(clean_phone_digits) >= 8 and not _find_profile_by_phone(phone):
                    profile.phone = phone

            profile.preferred_city = preferred_city
            profile.shipping_address = shipping_address
            profile.save()
            
            messages.success(request, 'تم حفظ البيانات بنجاح.')
            return redirect('store:account_profile')
        
    # جلب طلبات المستخدم المالك فقط لمنع تسريب بيانات الحسابات الأخرى (IDOR Protection)
    order_query = Q(user=request.user)
    if request.user.email and not request.user.email.endswith('@brandveloura.local'):
        order_query |= Q(customer_email__iexact=request.user.email)
        
    orders = Order.objects.filter(order_query).distinct().select_related('payment_method').prefetch_related('items__product').order_by('-created_at')
    
    orders_list = list(orders)
    total_orders_count = len(orders_list)
    active_statuses = {'pending_verification', 'payment_verified', 'processing', 'out_for_delivery'}
    active_orders_count = sum(1 for o in orders_list if o.status in active_statuses)
    delivered_orders_count = sum(1 for o in orders_list if o.status == 'delivered')

    total_spent_yer = sum((o.total_yer for o in orders_list if o.status != 'cancelled'), Decimal('0.00'))
    settings = StoreSettings.get_settings()
    yer_per_sar = settings.yer_per_sar or Decimal('530.00')
    total_spent_sar = _yer_to_sar(total_spent_yer, yer_per_sar)

    shipping_zones = list(
        (
            cache_get_or_set_safe(
                'bv_shipping_zones_active',
                lambda: {z.id: z for z in ShippingZone.objects.filter(is_active=True).order_by('city_name')},
                timeout=300,
            ) or {}
        ).values()
    )

    # إشعارات وتنبيهات العميل في استعلام واحد
    notifications = list(Notification.objects.filter(recipient=request.user).order_by('-created_at'))
    notifications_unread_count = sum(1 for n in notifications if not n.is_read)

    context = {
        'profile': profile,
        'orders': orders_list,
        'shipping_zones': shipping_zones,
        'total_orders_count': total_orders_count,
        'active_orders_count': active_orders_count,
        'delivered_orders_count': delivered_orders_count,
        'total_spent_yer': total_spent_yer,
        'total_spent_sar': total_spent_sar,
        'notifications': notifications,
        'notifications_unread_count': notifications_unread_count,
    }
    return render(request, 'store/auth/account.html', context)


@login_required(login_url='store:login')
@require_POST
def reorder_view(request, order_number):
    """إعادة طلب منتجات من طلب سابق وإضافتها فوراً لسلة المشتريات"""
    order = get_object_or_404(Order.objects.prefetch_related('items__product'), order_number=order_number)

    
    # التحقق من ملكية الطلب للمستخدم المسجل
    user_owns = (order.user == request.user)
    if not user_owns and request.user.email and not request.user.email.endswith('@brandveloura.local'):
        user_owns = bool(order.customer_email and order.customer_email.lower() == request.user.email.lower())
    if not user_owns and not request.user.is_staff:
        messages.error(request, 'غير مصرح بالوصول إلى هذا الطلب.')
        return redirect('store:account_profile')
        
    cart = request.session.get('cart', {})
    added_count = 0
    
    for item in order.items.all():
        if item.product and item.product.is_active:
            grade = 'original' if 'أصلي' in item.variant_info else 'master' if 'ماستر' in item.variant_info else ''
            item_key = f"{item.product.id}_{item.variant_info or 'default'}"
            
            if item_key in cart:
                cart[item_key]['quantity'] += item.quantity
            else:
                cart[item_key] = {
                    'product_id': item.product.id,
                    'name': item.product.name_ar,
                    'brand': item.product.brand_name,
                    'price_yer': float(item.unit_price_yer),
                    'image_url': item.product_image_url or item.product.primary_image_url,
                    'quantity': item.quantity,
                    'variant_info': item.variant_info,
                    'grade': grade,
                }
            added_count += item.quantity
            
    request.session['cart'] = cart
    request.session.modified = True
    sync_cart_to_profile(request)
    refresh_cart_reservation(request)
    
    if added_count > 0:
        messages.success(request, f'تمت إضافة {added_count} قطعة من طلبكم السابق #{order.order_number} إلى سلة المشتريات بنجاح.')
        return redirect('store:cart_view')
    else:
        messages.warning(request, 'عفواً، منتجات هذا الطلب لم تعد متوفرة في المخزون حالياً.')
        return redirect('store:account_profile')


# ==============================================================================
# نظام الإشعارات والتنبيهات التفاعلي (HTMX Notification Center)
# ==============================================================================

def notification_badge_view(request):
    """مكون HTMX لشارة عدد الإشعارات غير المقروءة في الهيدر"""
    unread_count = 0
    if request.user.is_authenticated:
        user_cache_key = f'bv_unread_notifications_user_{request.user.pk}'
        unread_count = cache_get_or_set_safe(
            user_cache_key,
            lambda: Notification.objects.filter(recipient=request.user, is_read=False).count(),
            timeout=15,
            jitter_ratio=0.0,
        ) or 0
    return render(request, 'store/partials/notification_badge.html', {
        'unread_count': unread_count
    })


def notifications_dropdown_view(request):
    """مكون HTMX لقائمة الإشعارات المنبثقة من أيقونة الجرس"""
    if not request.user.is_authenticated:
        return render(request, 'store/partials/notifications_dropdown.html', {
            'is_guest': True,
            'notifications': [],
            'unread_count': 0
        })

    notifications = Notification.objects.filter(recipient=request.user).order_by('-created_at')[:8]
    unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    
    return render(request, 'store/partials/notifications_dropdown.html', {
        'is_guest': False,
        'notifications': notifications,
        'unread_count': unread_count
    })


@require_POST
def mark_notification_read_view(request, notification_id):
    """تحديد إشعار واحد كمقروء وتحديث الحالة أو التوجيه"""
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'unauthorized'}, status=401)
        
    notification = get_object_or_404(Notification, id=notification_id)
    # التحقق من الصلاحية: المستلم أو مشرف الإدارة
    if notification.recipient != request.user and not (notification.for_admin and request.user.is_staff):
        return JsonResponse({'status': 'forbidden'}, status=403)
        
    notification.mark_as_read()
    
    if request.headers.get('HX-Request'):
        notifications = Notification.objects.filter(recipient=request.user).order_by('-created_at')[:8]
        unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        return render(request, 'store/partials/notifications_dropdown.html', {
            'is_guest': False,
            'notifications': notifications,
            'unread_count': unread_count
        })
        
    target_link = notification.link
    if target_link and url_has_allowed_host_and_scheme(url=target_link, allowed_hosts={request.get_host()}):
        return redirect(target_link)
    return redirect('store:account_profile')


@require_POST
def mark_all_notifications_read_view(request):
    """تحديد كافة إشعارات العميل كمقروءة دفعة واحدة"""
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'unauthorized'}, status=401)

    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    invalidate_notification_cache(user_id=request.user.pk)

    if request.user.is_staff and request.POST.get('admin_scope') == '1':
        Notification.objects.filter(for_admin=True, is_read=False).update(is_read=True)
        invalidate_notification_cache(for_admin=True)
        
    if request.headers.get('HX-Request'):
        notifications = Notification.objects.filter(recipient=request.user).order_by('-created_at')[:8]
        return render(request, 'store/partials/notifications_dropdown.html', {
            'is_guest': False,
            'notifications': notifications,
            'unread_count': 0
        })
        
    messages.success(request, 'تم تحديد كافة التنبيهات كمقروءة بنجاح.')
    return redirect('store:account_profile')


# ==============================================================================
# SEO & GEO Infrastructure Views (robots.txt, sitemap.xml, llms.txt)
# ==============================================================================

def robots_txt(request):
    """ملف robots.txt الموجه لمحركات البحث وعناكب الذكاء الاصطناعي مع دعم كاش المتصفح"""
    base_url = request.build_absolute_uri('/')[:-1]
    content = f"""User-agent: *
Allow: /
Disallow: /admin/
Disallow: /cart/
Disallow: /checkout/
Disallow: /account/
Disallow: /login/
Disallow: /register/

# AI Crawlers & Search Engines (Allow indexing product catalog)
User-agent: Googlebot
Allow: /
User-agent: Bingbot
Allow: /
User-agent: GPTBot
Allow: /
User-agent: ClaudeBot
Allow: /
User-agent: PerplexityBot
Allow: /
User-agent: Applebot
Allow: /

Sitemap: {base_url}/sitemap.xml
"""
    response = HttpResponse(content.strip(), content_type="text/plain; charset=utf-8")
    response['Cache-Control'] = 'public, max-age=86400'
    return response


def sitemap_xml(request):
    """توليد خريطة الموقع XML الديناميكية المتوافقة مع معايير محركات البحث العالمية"""
    base_url = request.build_absolute_uri('/')[:-1]
    
    # Static & Catalog URL definitions (loc, priority, changefreq)
    urls = [
        {'loc': f"{base_url}/", 'priority': '1.0', 'changefreq': 'daily'},
        {'loc': f"{base_url}/products/", 'priority': '0.9', 'changefreq': 'daily'},
        {'loc': f"{base_url}/perfumes/", 'priority': '0.9', 'changefreq': 'daily'},
        {'loc': f"{base_url}/watches/", 'priority': '0.9', 'changefreq': 'daily'},
        {'loc': f"{base_url}/cosmetics/", 'priority': '0.9', 'changefreq': 'daily'},
        {'loc': f"{base_url}/brands/", 'priority': '0.9', 'changefreq': 'daily'},
        {'loc': f"{base_url}/gifting/", 'priority': '0.9', 'changefreq': 'daily'},
    ]
    
    # Categories
    categories = Category.objects.filter(is_active=True)
    for cat in categories:
        urls.append({
            'loc': f"{base_url}/products/?category={cat.slug}",
            'priority': '0.8',
            'changefreq': 'weekly',
        })
        
    # Brands
    brands = Brand.objects.filter(is_active=True)
    for b in brands:
        urls.append({
            'loc': f"{base_url}/brands/{b.slug}/",
            'priority': '0.85',
            'changefreq': 'weekly',
        })
        
    # Products
    products = Product.objects.filter(is_active=True).order_by('-updated_at')
    for prod in products:
        lastmod = prod.updated_at.strftime('%Y-%m-%d') if prod.updated_at else ''
        urls.append({
            'loc': f"{base_url}/products/{prod.slug}/",
            'priority': '0.8',
            'changefreq': 'weekly',
            'lastmod': lastmod,
        })
        
    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for u in urls:
        safe_loc = xml_escape(iri_to_uri(u['loc']))
        xml_lines.append('  <url>')
        xml_lines.append(f"    <loc>{safe_loc}</loc>")
        if 'lastmod' in u and u['lastmod']:
            xml_lines.append(f"    <lastmod>{xml_escape(u['lastmod'])}</lastmod>")
        xml_lines.append(f"    <changefreq>{xml_escape(u['changefreq'])}</changefreq>")
        xml_lines.append(f"    <priority>{xml_escape(u['priority'])}</priority>")
        xml_lines.append('  </url>')
    xml_lines.append('</urlset>')
    
    response = HttpResponse('\n'.join(xml_lines), content_type="application/xml; charset=utf-8")
    response['Cache-Control'] = 'public, max-age=3600'
    return response


def llms_txt(request):
    """ملف llms.txt المعياري لتسهيل فهم محركات الذكاء الاصطناعي (GEO / AI Overviews) لكتالوج المتجر"""
    settings = StoreSettings.get_settings()
    base_url = request.build_absolute_uri('/')[:-1]
    
    content = f"""# {settings.store_name} — Luxury Store Knowledge File (llms.txt)

> {settings.store_tagline or 'متجر الفخامة الأول للعطور العالمية، الساعات الراقية، ومستحضرات التجميل الأصلية والماستر كواليتي.'}

## Overview
- **Brand Name**: {settings.store_name}
- **Website**: {base_url}/
- **Main Catalog**: {base_url}/products/
- **Categories**:
  - Perfumes ({base_url}/perfumes/): عطور النخبة العالمية (أصلية 100% وإصدارات ماستر كواليتي طبق الأصل).
  - Luxury Watches ({base_url}/watches/): ساعات راقية رجالية ونسائية بحركات أوتوماتيكية ومحركات كوارتز.
  - Cosmetics & Care ({base_url}/cosmetics/): مستحضرات تجميل فاخرة وسيرومات العناية الفائقة بالبشرة.
  - Luxury Brands Directory ({base_url}/brands/): دليل الماركات ودور العطور والساعات ومستحضرات التجميل العالمية المعتمدة.
  - Luxury Gift Builder ({base_url}/gifting/): ركن تصميم باقات الإهداء مع التغليف الملكي وكروت الإهداء المخصصة.
- **Accepted Currencies**: الريال السعودي (SAR) والريال اليمني (YER) مع تحويل فوري شفاف.
- **Payment Methods**: تحويل مصرفي مباشر (الكريمي، التضامن، المحافظ الإلكترونية، ومصرف الراجحي للمغتربين بالسعودي) والدفع عند الاستلام.
- **Delivery Coverage**: توصيل سريع معتمد لكافة المحافظات والمدن اليمنية خلال 24-48 ساعة.
- **Customer Support**: WhatsApp: {settings.contact_whatsapp or 'متوفر'} | Phone: {settings.contact_phone or 'متوفر'}
"""
    response = HttpResponse(content.strip(), content_type="text/plain; charset=utf-8")
    response['Cache-Control'] = 'public, max-age=86400'
    return response


def health_check(request):
    """فحص سلامة وجاهزية التطبيق السحابي وقاعدة البيانات والكاش للاستضافة ومراقبة الخدمة (Railway Healthcheck)"""
    from django.db import connection
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
            cursor.fetchone()
        db_status = "connected"
        http_status = 200
        service_status = "healthy"
    except Exception as e:
        logger.error(f"Database health check warning: {e}")
        db_status = "disconnected"
        http_status = 200
        service_status = "degraded"

    cache_status = "connected"
    try:
        cache.set('bv_health_ping', 'ok', timeout=10)
        if cache.get('bv_health_ping') != 'ok':
            cache_status = "degraded"
    except Exception:
        cache_status = "unavailable"

    return JsonResponse({
        'status': service_status,
        'service': 'brandveloura',
        'database': db_status,
        'cache': cache_status,
    }, status=http_status)


def offline_view(request):
    """صفحة تصفح وضع عدم الاتصال الفاخرة لتطبيق PWA"""
    settings = StoreSettings.get_settings()
    return render(request, 'store/offline.html', {'store_settings': settings})


def custom_404_view(request, exception=None):
    """صفحة خطأ 404 مخصصة بهوية المتجر الفاخرة"""
    return render(request, '404.html', status=404)


def custom_500_view(request):
    """صفحة خطأ 500 مخصصة بهوية المتجر الفاخرة"""
    return render(request, '500.html', status=500)


def custom_403_view(request, exception=None):
    """صفحة خطأ 403 مخصصة بهوية المتجر الفاخرة"""
    return render(request, '403.html', status=403)



