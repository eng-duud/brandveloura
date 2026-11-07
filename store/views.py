import os
import uuid
import logging
from decimal import Decimal
from urllib.parse import urlencode, quote
import requests

from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.db.models import Q
from django.core.cache import cache
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout, update_session_auth_hash
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .models import (
    StoreSettings, PaymentAccount, ShippingZone, 
    Category, Brand, Product, 
    Order, OrderItem, HeroBanner, UserProfile, Notification,
    WebPushSubscription
)

logger = logging.getLogger(__name__)


def _get_safe_redirect(request, default='store:home'):
    """التحقق من رابط التوجيه والتأكد من أمانه لمنع ثغرات Open Redirect"""
    next_url = request.POST.get('next') or request.GET.get('next') or request.GET.get('state') or request.META.get('HTTP_REFERER')
    if next_url and url_has_allowed_host_and_scheme(url=next_url, allowed_hosts={request.get_host()}):
        return next_url
    return reverse(default)


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



def home_view(request):
    """الصفحة الرئيسية للمتجر بتصميم فاخر وقنوات أفقية تفاعلية"""
    from django.db.models import Count
    banners = HeroBanner.objects.filter(is_active=True).order_by('display_order')
    categories = Category.objects.filter(is_active=True).order_by('display_order')
    
    # المنتجات المميزة لشريط التمرير الأفقي
    featured_products = Product.objects.filter(
        is_active=True, is_featured=True
    ).select_related('category').prefetch_related('images').order_by('-created_at')[:12]
    if not featured_products.exists():
        featured_products = Product.objects.filter(
            is_active=True
        ).select_related('category').prefetch_related('images').order_by('-created_at')[:12]
        
    # الماركات والبراندات الفاخرة المسجلة في لوحة التحكم (مع استعلام تجميعي لعدد المنتجات)
    featured_brands = Brand.objects.filter(is_active=True).annotate(
        products_count=Count('products', filter=Q(products__is_active=True))
    ).order_by('display_order', '-products_count', 'name_ar')

    # براندات العطور الفاخرة مع بيانات مخصصة لشريط التمرير (استعلام تجميعي واحد سريع للتوافق)
    brand_counts = dict(
        Product.objects.filter(category__category_type='perfumes', is_active=True)
        .exclude(brand_name='')
        .values('brand_name')
        .annotate(total=Count('id'))
        .values_list('brand_name', 'total')
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
        meta = brand_emblems.get(b_name, {'name': b_name, 'country': 'Luxury Boutique', 'icon': 'sparkles', 'badge': 'فاخر'})
        perfume_brands_data.append({
            'brand_name': b_name,
            'display_name': meta['name'],
            'country': meta['country'],
            'icon': meta['icon'],
            'badge': meta['badge'],
            'count': count,
        })

    # باقات الهدايا والمناسبات الفاخرة
    gift_bundles = Product.objects.filter(
        category__category_type='bundles', is_active=True
    ).select_related('category').prefetch_related('images').order_by('-created_at')[:8]

    context = {
        'banners': banners,
        'categories': categories,
        'featured_products': featured_products,
        'featured_brands': featured_brands,
        'perfume_brands': perfume_brands_data,
        'gift_bundles': gift_bundles,
    }
    return render(request, 'store/home.html', context)



def perfumes_catalog_view(request):
    """الصفحة المخصصة للعطور الملكية مع فلاتر النوع (رجالي/نسائي/للجنسين) والدرجة (أصلي/ماستر) والبراند"""
    products = Product.objects.filter(
        category__category_type='perfumes', is_active=True
    ).select_related('category').prefetch_related('images')
    
    gender_filter = request.GET.get('gender', '').strip() # men, women, unisex
    grade_filter = request.GET.get('grade', '').strip()   # original, master
    brand_filter = request.GET.get('brand', '').strip()
    search_query = request.GET.get('q', '').strip()
    sort_by = request.GET.get('sort', 'newest')
    
    if gender_filter:
        products = products.filter(
            Q(specifications__gender=gender_filter) |
            Q(description__icontains=gender_filter) |
            Q(name_ar__icontains='رجالي' if gender_filter == 'men' else ('نسائي' if gender_filter == 'women' else 'للجنسين'))
        )
        
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
        
    if brand_filter:
        products = products.filter(brand_name__iexact=brand_filter)
        
    if search_query:
        products = products.filter(
            Q(name_ar__icontains=search_query) |
            Q(name_en__icontains=search_query) |
            Q(brand_name__icontains=search_query) |
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
        
    available_brands = Product.objects.filter(
        category__category_type='perfumes', is_active=True
    ).exclude(brand_name='').values_list('brand_name', flat=True).distinct()

    context = {
        'products': products,
        'gender_filter': gender_filter,
        'grade_filter': grade_filter,
        'brand_filter': brand_filter,
        'search_query': search_query,
        'sort_by': sort_by,
        'available_brands': available_brands,
        'total_count': products.count(),
    }
    
    if request.headers.get('HX-Request') and not request.GET.get('full_page'):
        return render(request, 'store/partials/product_grid.html', context)
        
    return render(request, 'store/perfumes_list.html', context)


def watches_catalog_view(request):
    """الصفحة المخصصة للساعات الفاخرة مع فلاتر الحركة ومقاومة الماء والماركة"""
    products = Product.objects.filter(
        category__category_type='watches', is_active=True
    ).select_related('category').prefetch_related('images')
    
    brand_filter = request.GET.get('brand', '').strip()
    movement_filter = request.GET.get('movement', '').strip()
    gender_filter = request.GET.get('gender', '').strip()
    search_query = request.GET.get('q', '').strip()
    sort_by = request.GET.get('sort', 'newest')
    
    if brand_filter:
        products = products.filter(brand_name__iexact=brand_filter)
    if movement_filter:
        products = products.filter(
            Q(specifications__movement__icontains=movement_filter) |
            Q(description__icontains=movement_filter)
        )
    if gender_filter:
        products = products.filter(
            Q(specifications__gender=gender_filter) |
            Q(description__icontains=gender_filter) |
            Q(name_ar__icontains='رجالية' if gender_filter == 'men' else 'نسائية')
        )
    if search_query:
        products = products.filter(
            Q(name_ar__icontains=search_query) |
            Q(name_en__icontains=search_query) |
            Q(brand_name__icontains=search_query) |
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
        
    available_brands = Product.objects.filter(
        category__category_type='watches', is_active=True
    ).exclude(brand_name='').values_list('brand_name', flat=True).distinct()

    context = {
        'products': products,
        'brand_filter': brand_filter,
        'movement_filter': movement_filter,
        'gender_filter': gender_filter,
        'search_query': search_query,
        'sort_by': sort_by,
        'available_brands': available_brands,
        'total_count': products.count(),
    }
    
    if request.headers.get('HX-Request') and not request.GET.get('full_page'):
        return render(request, 'store/partials/product_grid.html', context)
        
    return render(request, 'store/watches_list.html', context)


def cosmetics_catalog_view(request):
    """الصفحة المخصصة لمستحضرات التجميل والعناية بالبشرة مع فلاتر الماركة والتصنيف"""
    products = Product.objects.filter(
        category__category_type__in=['cosmetics', 'care'], is_active=True
    ).select_related('category').prefetch_related('images')
    
    subcat_filter = request.GET.get('subcat', '').strip()
    brand_filter = request.GET.get('brand', '').strip()
    search_query = request.GET.get('q', '').strip()
    sort_by = request.GET.get('sort', 'newest')
    
    if subcat_filter:
        products = products.filter(category__category_type=subcat_filter)
    if brand_filter:
        products = products.filter(brand_name__iexact=brand_filter)
    if search_query:
        products = products.filter(
            Q(name_ar__icontains=search_query) |
            Q(name_en__icontains=search_query) |
            Q(brand_name__icontains=search_query) |
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
        
    available_brands = Product.objects.filter(
        category__category_type__in=['cosmetics', 'care'], is_active=True
    ).exclude(brand_name='').values_list('brand_name', flat=True).distinct()

    context = {
        'products': products,
        'subcat_filter': subcat_filter,
        'brand_filter': brand_filter,
        'search_query': search_query,
        'sort_by': sort_by,
        'available_brands': available_brands,
        'total_count': products.count(),
    }
    
    if request.headers.get('HX-Request') and not request.GET.get('full_page'):
        return render(request, 'store/partials/product_grid.html', context)
        
    return render(request, 'store/cosmetics_list.html', context)


def brands_list_view(request):
    """دليل وتصنيف كافة الماركات والبراندات العالمية الفاخرة بالمتجر"""
    from django.db.models import Count
    search_query = request.GET.get('q', '').strip()
    
    brands = Brand.objects.filter(is_active=True).annotate(
        products_count=Count('products', filter=Q(products__is_active=True))
    ).prefetch_related('categories')
    
    if search_query:
        brands = brands.filter(
            Q(name_ar__icontains=search_query) |
            Q(name_en__icontains=search_query) |
            Q(description__icontains=search_query)
        )
        
    brands = brands.order_by('display_order', '-products_count', 'name_ar')
    
    context = {
        'brands': brands,
        'search_query': search_query,
        'total_count': brands.count(),
    }
    
    if request.headers.get('HX-Request') and not request.GET.get('full_page'):
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
    
    if request.headers.get('HX-Request') and not request.GET.get('full_page'):
        return render(request, 'store/partials/product_grid.html', context)
        
    return render(request, 'store/brand_detail.html', context)


def product_list_view(request):
    """كتالوج المنتجات مع الفلترة الذكية والبحث التفاعلي عبر HTMX"""
    products = Product.objects.filter(is_active=True).select_related('category').prefetch_related('images')
    
    category_slug = request.GET.get('category')
    search_query = request.GET.get('q', '').strip()
    sort_by = request.GET.get('sort', 'newest')
    brand_filter = request.GET.get('brand', '')
    
    current_category = None
    if category_slug:
        current_category = get_object_or_404(Category, slug=category_slug)
        cat_ids = current_category.get_descendants_and_self_ids()
        products = products.filter(category_id__in=cat_ids)
        
    if search_query:
        products = products.filter(
            Q(name_ar__icontains=search_query) | 
            Q(name_en__icontains=search_query) |
            Q(brand_name__icontains=search_query) |
            Q(description__icontains=search_query)
        )
        
    if brand_filter:
        products = products.filter(brand_name__iexact=brand_filter)
        
    # خيارات الترتيب
    if sort_by == 'price_low':
        products = products.order_by('price_yer')
    elif sort_by == 'price_high':
        products = products.order_by('-price_yer')
    elif sort_by == 'best_sellers':
        products = products.order_by('-is_best_seller', '-created_at')
    else: # newest
        products = products.order_by('-created_at')
        
    # الماركات المتوفرة للفلترة
    available_brands = Product.objects.filter(is_active=True).values_list('brand_name', flat=True).distinct()
    available_brands = [b for b in available_brands if b]

    context = {
        'products': products,
        'current_category': current_category,
        'search_query': search_query,
        'sort_by': sort_by,
        'brand_filter': brand_filter,
        'available_brands': available_brands,
    }
    
    # إذا كان الطلب من HTMX لاستبدال شبكة المنتجات فقط
    if request.headers.get('HX-Request') and not request.GET.get('full_page'):
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
    if request.headers.get('HX-Request') and not request.GET.get('full_page'):
        return product_quick_view(request, slug)

    product = get_object_or_404(
        Product.objects.select_related('category').prefetch_related('images'), 
        slug=slug, 
        is_active=True
    )
    images = product.images.all()
    
    # منتجات ذات صلة من نفس القسم مع تفادي N+1
    related_products = Product.objects.filter(
        category=product.category, is_active=True
    ).exclude(id=product.id).select_related('category').prefetch_related('images')[:4]
    
    context = {
        'product': product,
        'images': images,
        'related_products': related_products,
        'specifications': product.specifications or {},
    }
    return render(request, 'store/product_detail.html', context)


@require_POST
def cart_add(request):
    """إضافة منتج للسلة لحظياً عبر HTMX مع فحص المخزون ودعم درجتي الأصلي والماستر"""
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
        response = render(request, 'store/partials/cart_badge.html', {'cart_count': cart_count})
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
    
    current_cart_qty = cart.get(item_key, {}).get('quantity', 0)
    available_qty = max(0, product.stock_quantity - current_cart_qty)
    if available_qty <= 0:
        cart_count = sum(item.get('quantity', 1) for item in cart.values())
        response = render(request, 'store/partials/cart_badge.html', {'cart_count': cart_count})
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
            'brand': product.brand_name,
            'price_yer': unit_price,
            'image_url': product.primary_image_url,
            'quantity': quantity,
            'variant_info': combined_variant,
            'grade': grade,
        }
        
    request.session['cart'] = cart
    request.session.modified = True
    
    cart_count = sum(item.get('quantity', 1) for item in cart.values())
    
    response = render(request, 'store/partials/cart_badge.html', {'cart_count': cart_count})
    response['HX-Trigger'] = 'cartUpdated'
    return response


@require_POST
def cart_update_quantity(request):
    """تعديل كمية عنصر في السلة مع احترام رصيد المخزون"""
    item_key = request.POST.get('item_key')
    action = request.POST.get('action') # 'increase' or 'decrease'
    
    cart = request.session.get('cart', {})
    
    if item_key in cart:
        if action == 'increase':
            p_id = cart[item_key].get('product_id')
            prod = Product.objects.filter(id=p_id, is_active=True).first()
            if not prod:
                del cart[item_key]
            elif cart[item_key]['quantity'] >= prod.stock_quantity:
                pass  # لا يسمح بتجاوز الكمية المتوفرة بالمخزون
            else:
                cart[item_key]['quantity'] += 1
        elif action == 'decrease':
            cart[item_key]['quantity'] -= 1
            if cart[item_key]['quantity'] <= 0:
                del cart[item_key]

                
    request.session['cart'] = cart
    request.session.modified = True
    
    return _render_cart_response(request)


@require_POST
def cart_remove_item(request):
    """حذف عنصر من السلة"""
    item_key = request.POST.get('item_key')
    cart = request.session.get('cart', {})
    
    if item_key in cart:
        del cart[item_key]
        request.session['cart'] = cart
        request.session.modified = True
        
    return _render_cart_response(request)


def _render_cart_response(request):
    """دالة مساعدة لحساب إجماليات السلة وعرضها"""
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
        
        # حساب المعادل بالسعودي
        price_sar = round(price_yer / yer_per_sar, 1)
        line_total_sar = round(line_total_yer / yer_per_sar, 1)
        
        items.append({
            'key': key,
            'product_id': data.get('product_id'),
            'name': data.get('name'),
            'brand': data.get('brand'),
            'image_url': data.get('image_url'),
            'variant_info': data.get('variant_info'),
            'quantity': qty,
            'price_yer': price_yer,
            'price_sar': price_sar,
            'line_total_yer': line_total_yer,
            'line_total_sar': line_total_sar,
        })
        
    subtotal_sar = round(subtotal_yer / yer_per_sar, 1) if yer_per_sar else Decimal('0.00')
    
    context = {
        'cart_items': items,
        'subtotal_yer': subtotal_yer,
        'subtotal_sar': subtotal_sar,
        'cart_count': sum(item['quantity'] for item in items),
    }
    
    response = render(request, 'store/partials/cart_table.html', context)
    response['HX-Trigger'] = 'cartUpdated'
    return response


def cart_view(request):
    """صفحة سلة المشتريات الكاملة"""
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
            'price_sar': round(price_yer / yer_per_sar, 1),
            'line_total_yer': line_total_yer,
            'line_total_sar': round(line_total_yer / yer_per_sar, 1),
        })
        
    subtotal_sar = round(subtotal_yer / yer_per_sar, 1) if yer_per_sar else Decimal('0.00')
    
    context = {
        'cart_items': items,
        'subtotal_yer': subtotal_yer,
        'subtotal_sar': subtotal_sar,
    }
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

    response = HttpResponse(f"""
        <button 
            hx-post="{reverse('store:toggle_currency')}" 
            hx-headers='{{"X-CSRFToken": "{request.COOKIES.get("csrftoken", "")}"}}'
            hx-swap="outerHTML" 
            class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl bg-white hover:bg-pink-50 border border-pink-200 text-slate-800 text-xs font-bold transition-all shadow-2xs cursor-pointer min-h-[40px]"
            title="تبديل العملة المعروضة">
            <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
            <span>{'🇸🇦 ر.س' if new_currency == 'SAR' else '🇾🇪 ر.ي'}</span>
        </button>
    """)
    if request.headers.get('HX-Request'):
        response['HX-Refresh'] = 'true'
    return response



def get_shipping_fee(request):
    """حساب رسوم الشحن والتغليف عند اختيار المدينة أو خيار الهدية لحظياً عبر HTMX"""
    city_id = request.GET.get('shipping_city') or request.GET.get('city_id')
    order_type = request.GET.get('order_type', 'personal')
    is_gift = (order_type == 'gift') or (request.GET.get('is_gift') in ['true', '1', 'on'])
    is_gift_wrapping = (request.GET.get('is_luxury_gift_wrapping') in ['true', '1', 'on']) if is_gift else False
    
    shipping_fee = Decimal('0.00')
    delivery_time = 'خلال 24-48 ساعة'
    
    if city_id:
        try:
            zone = ShippingZone.objects.get(id=city_id)
            shipping_fee = zone.delivery_fee_yer
            delivery_time = zone.estimated_delivery_time
        except (ShippingZone.DoesNotExist, ValueError):
            pass
            
    settings = StoreSettings.get_settings()
    gift_wrapping_fee = settings.gift_wrapping_fee_yer if is_gift_wrapping else Decimal('0.00')
    
    # حساب الإجمالي الجديد مع الشحن والتغليف
    cart = request.session.get('cart', {})
    subtotal_yer = sum(Decimal(str(item.get('price_yer', 0))) * item.get('quantity', 1) for item in cart.values())
    total_yer = subtotal_yer + shipping_fee + gift_wrapping_fee
    
    yer_per_sar = settings.yer_per_sar or Decimal('530.00')
    total_sar = round(total_yer / yer_per_sar, 1)
    
    return render(request, 'store/partials/checkout_totals.html', {
        'shipping_fee': shipping_fee,
        'delivery_time': delivery_time,
        'subtotal_yer': subtotal_yer,
        'gift_wrapping_fee': gift_wrapping_fee,
        'is_luxury_gift_wrapping': is_gift_wrapping,
        'total_yer': total_yer,
        'total_sar': total_sar,
    })


def gift_builder_view(request):
    """ركن وصانع الهدية الملكي: معالج خطوات تفاعلي سريع ومدمج في شاشة واحدة عبر HTMX"""
    settings = StoreSettings.get_settings()
    yer_per_sar = settings.yer_per_sar or Decimal('530.00')
    wrapping_fee = settings.gift_wrapping_fee_yer or Decimal('2500.00')

    bundle_id = request.GET.get('bundle_id')
    selected_bundle = None
    if bundle_id:
        selected_bundle = Product.objects.filter(id=bundle_id, is_active=True).first()

    perfume_id = request.GET.get('perfume_id')
    selected_perfume = None
    if perfume_id:
        selected_perfume = Product.objects.filter(id=perfume_id, is_active=True).first()

    perfumes = Product.objects.filter(
        category__category_type='perfumes', is_active=True, stock_quantity__gt=0
    ).select_related('category').prefetch_related('images').order_by('-is_featured', '-is_best_seller')[:30]

    accessories = Product.objects.filter(
        category__category_type__in=['watches', 'cosmetics', 'care'], is_active=True, stock_quantity__gt=0
    ).select_related('category').prefetch_related('images').order_by('-is_featured')[:30]

    gift_bundles = Product.objects.filter(
        category__category_type='bundles', is_active=True
    ).select_related('category').prefetch_related('images').order_by('-created_at')[:10]


    if request.method == 'POST':
        perfume_ids = request.POST.getlist('perfume_id')
        if not perfume_ids and request.POST.get('perfume_id'):
            perfume_ids = [request.POST.get('perfume_id')]
        perfume_ids = [p for p in perfume_ids if p]

        perfume_grade_default = request.POST.get('perfume_grade', 'original')

        accessory_ids = request.POST.getlist('accessory_id')
        if not accessory_ids and request.POST.get('accessory_id'):
            accessory_ids = [request.POST.get('accessory_id')]
        accessory_ids = [a for a in accessory_ids if a]

        post_bundle_id = request.POST.get('bundle_id')
        
        recipient_name = request.POST.get('recipient_name', '').strip()
        recipient_phone = request.POST.get('recipient_phone', '').strip()
        gift_card_sender = request.POST.get('gift_card_sender', '').strip()
        gift_card_recipient = request.POST.get('gift_card_recipient', '').strip() or recipient_name
        gift_card_message = request.POST.get('gift_card_message', '').strip()
        preferred_delivery_date = request.POST.get('preferred_delivery_date', '').strip() or None
        is_luxury_gift_wrapping = request.POST.get('is_luxury_gift_wrapping') in ['true', '1', 'on']

        cart = request.session.get('cart', {})

        if post_bundle_id:
            bundle_obj = get_object_or_404(Product, id=post_bundle_id, is_active=True)
            b_key = f"bundle_{bundle_obj.id}"
            cart[b_key] = {
                'product_id': bundle_obj.id,
                'name': bundle_obj.name_ar,
                'brand': bundle_obj.brand_name or 'Brand Veloura',
                'price_yer': float(bundle_obj.price_yer),
                'image_url': bundle_obj.primary_image_url,
                'quantity': 1,
                'variant_info': 'باقة جاهزة',
                'grade': '',
            }
        else:
            if not perfume_ids:
                messages.warning(request, 'يرجى اختيار عطر واحد على الأقل لتجهيز باقة الإهداء.')
                return redirect('store:gift_builder')

            for pid in perfume_ids:
                perfume_obj = get_object_or_404(Product, id=pid, is_active=True)
                p_grade = request.POST.get(f'grade_{pid}') or perfume_grade_default
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

            for aid in accessory_ids:
                acc_obj = get_object_or_404(Product, id=aid, is_active=True)
                a_key = f"{acc_obj.id}_acc_gift"
                cart[a_key] = {
                    'product_id': acc_obj.id,
                    'name': acc_obj.name_ar,
                    'brand': acc_obj.brand_name,
                    'price_yer': float(acc_obj.price_yer),
                    'image_url': acc_obj.primary_image_url,
                    'quantity': 1,
                    'variant_info': acc_obj.category.name_ar if acc_obj.category else 'ملحق إضافي',
                    'grade': '',
                }

        request.session['cart'] = cart
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

    context = {
        'perfumes': perfumes,
        'accessories': accessories,
        'gift_bundles': gift_bundles,
        'selected_bundle': selected_bundle,
        'selected_perfume': selected_perfume,
        'wrapping_fee': wrapping_fee,
        'yer_per_sar': yer_per_sar,
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
        bundle_obj = Product.objects.filter(id=bundle_id, is_active=True).first()
        if bundle_obj:
            total_yer += bundle_obj.price_yer
            items_breakdown.append({
                'title': bundle_obj.name_ar,
                'type': 'باقة جاهزة',
                'price_yer': bundle_obj.price_yer
            })
    else:
        for pid in perfume_ids:
            p_obj = Product.objects.filter(id=pid, is_active=True).first()
            if p_obj:
                p_grade = request.POST.get(f'grade_{pid}') or perfume_grade_default
                p_price = p_obj.price_master_yer if p_grade == 'master' and p_obj.price_master_yer else (p_obj.price_original_yer or p_obj.price_yer)
                total_yer += p_price
                grade_name = 'ماستر' if p_grade == 'master' else 'أصلي'
                items_breakdown.append({
                    'title': p_obj.name_ar,
                    'type': f"عطر ({grade_name})",
                    'price_yer': p_price
                })

        for aid in accessory_ids:
            a_obj = Product.objects.filter(id=aid, is_active=True).first()
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

    total_sar = round(total_yer / yer_per_sar, 1)

    return render(request, 'store/partials/gift_builder_summary.html', {
        'total_yer': total_yer,
        'total_sar': total_sar,
        'items_breakdown': items_breakdown,
        'yer_per_sar': yer_per_sar,
    })


def checkout_view(request):
    """صفحة إتمام الطلب، تدفق الهدايا والمغتربين، اختيار المدينة، ورفع السند"""
    cart = request.session.get('cart', {})
    if not cart:
        messages.warning(request, 'سلة المشتريات فارغة، يرجى إضافة منتجات أولاً.')
        return redirect('store:product_list')
        
    settings = StoreSettings.get_settings()
    yer_per_sar = settings.yer_per_sar or Decimal('530.00')
    
    subtotal_yer = Decimal('0.00')
    items = []
    for key, data in cart.items():
        qty = data.get('quantity', 1)
        price_yer = Decimal(str(data.get('price_yer', 0)))
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
    total_sar = round(total_yer / yer_per_sar, 1)

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
            preferred_delivery_date = request.POST.get('preferred_delivery_date', '').strip() or None
            hide_invoice_prices = request.POST.get('hide_invoice_prices') in ['true', '1', 'on']
            gift_wrapping_fee_yer = settings.gift_wrapping_fee_yer if is_luxury_gift_wrapping else Decimal('0.00')
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
        
        selected_zone = ShippingZone.objects.filter(id=city_id).first()
        city_name = selected_zone.city_name if selected_zone else 'غير محدد'
        actual_shipping_fee = selected_zone.delivery_fee_yer if selected_zone else Decimal('0.00')
        
        selected_payment = PaymentAccount.objects.filter(id=payment_method_id).first()
        payment_name = selected_payment.provider_name if selected_payment else 'دفع يدوي'
        
        # 2. حساب العملة المحددة والمبلغ المستحق
        payment_currency_selected = request.POST.get('payment_currency_selected', 'YER')
        if selected_payment and selected_payment.currency == 'SAR':
            payment_currency_selected = 'SAR'
            
        order_total_yer = subtotal_yer + actual_shipping_fee + gift_wrapping_fee_yer
        order_total_sar = round(order_total_yer / yer_per_sar, 1)
        
        amount_due = order_total_sar if payment_currency_selected == 'SAR' else order_total_yer
        
        # إنشاء رقم طلب احترافي فريد
        order_number = f"BV-{uuid.uuid4().hex[:6].upper()}"
        
        with transaction.atomic():
            # فحص كفاية المخزون لجميع المنتجات وحجز الأسطر لمنع البيع الزائد (select_for_update)
            insufficient_items = []
            locked_products = []
            for item_data in cart.values():
                p_id = item_data.get('product_id')
                p_qty = int(item_data.get('quantity', 1))
                prod = Product.objects.select_for_update().filter(id=p_id, is_active=True).first()
                if not prod or prod.stock_quantity < p_qty:
                    avail = prod.stock_quantity if prod else 0
                    p_name = item_data.get('name', 'منتج')
                    insufficient_items.append(f"{p_name} (المتوفر: {avail})")
                else:
                    locked_products.append((prod, p_qty, item_data))

            if insufficient_items:
                items_str = '، '.join(insufficient_items)
                messages.error(request, f"نعتذر، نفدت الكمية المتوفرة من بعض المنتجات: {items_str}. يرجى تعديل السلة.")
                return redirect('store:checkout')

            order = Order.objects.create(
                order_number=order_number,
                user=request.user if request.user.is_authenticated else None,
                customer_name=customer_name,
                customer_phone=customer_phone,
                customer_email=customer_email,
                shipping_city=city_name,
                shipping_address=shipping_address,
                shipping_fee_yer=actual_shipping_fee,
                subtotal_yer=subtotal_yer,
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
            
            # حفظ عناصر الطلب وخصم المخزون
            for prod, p_qty, item_data in locked_products:
                p_price = Decimal(str(item_data.get('price_yer', 0)))
                OrderItem.objects.create(
                    order=order,
                    product=prod,
                    product_name=item_data.get('name', 'منتج'),
                    product_image_url=item_data.get('image_url', ''),
                    variant_info=item_data.get('variant_info', ''),
                    unit_price_yer=p_price,
                    quantity=p_qty,
                    total_price_yer=p_price * p_qty,
                )
                
                # خصم الكمية من المخزون
                prod.stock_quantity = max(0, prod.stock_quantity - p_qty)
                prod.save(update_fields=['stock_quantity'])
                # تنبيه انخفاض المخزون للإدارة عند وصول الرصيد إلى 3 قطع أو أقل
                if prod.stock_quantity <= 3:
                    Notification.notify_admin(
                        title=f"تنبيه انخفاض المخزون: {prod.name_ar}",
                        message=f"الكمية المتبقية من المنتج ({prod.name_ar}) أصبحت {prod.stock_quantity} فقط. يرجى مراجعة المخزون.",
                        notification_type='low_stock',
                        link=f"/admin/store/product/{prod.id}/change/"
                    )

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
            link=f"/admin/store/order/{order.id}/change/"
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
                
        # تفريغ السلة وبيانات الهدية بعد إتمام الطلب
        request.session['cart'] = {}
        request.session.pop('gift_data', None)
        request.session.modified = True
        
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
    
    context = {
        'order': order,
        'whatsapp_url': whatsapp_url,
    }
    return render(request, 'store/order_success.html', context)


def track_order_view(request):
    """تتبع حالة الطلب برقم الطلب أو الهاتف"""
    query = request.GET.get('q', '').strip()
    orders = []
    searched = False
    
    if query:
        searched = True
        orders = Order.objects.filter(
            Q(order_number__iexact=query) | Q(customer_phone__icontains=query)
        ).order_by('-created_at')[:5]
        
    context = {
        'query': query,
        'orders': orders,
        'searched': searched,
    }
    return render(request, 'store/track_order.html', context)


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
    const CACHE_NAME = 'brand-veloura-pwa-v4';
    const OFFLINE_URL = '/offline/';
    const PRECACHE_ASSETS = [
        '/',
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

    self.addEventListener('fetch', (event) => {
        if (event.request.method !== 'GET') return;
        const url = new URL(event.request.url);
        if (
            url.pathname.startsWith('/admin') || 
            url.pathname.startsWith('/api/') ||
            url.pathname.startsWith('/cart') ||
            url.pathname.startsWith('/checkout') ||
            url.pathname.startsWith('/account') ||
            url.pathname.startsWith('/order')
        ) return;

        if (event.request.mode === 'navigate') {
            event.respondWith(
                fetch(event.request)
                    .then((networkResponse) => {
                        if (networkResponse && networkResponse.status === 200) {
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


@csrf_exempt
def push_subscribe(request):
    """تسجيل وتحديث اشتراك جهاز العميل في إشعارات الويب وتطبيق الهاتف"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    import json
    try:
        data = json.loads(request.body.decode('utf-8'))
        endpoint = data.get('endpoint')
        keys = data.get('keys', {})
        p256dh = keys.get('p256dh')
        auth = keys.get('auth')

        if not endpoint or not p256dh or not auth:
            return JsonResponse({'error': 'Invalid subscription payload'}, status=400)

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
        return JsonResponse({'error': str(ex)}, status=400)


# ==============================================================================
# أنظمة المصادقة والحسابات الشخصية (Authentication & User Accounts)
# ==============================================================================

def login_view(request):
    """صفحة تسجيل الدخول الفاخرة للعملاء مع حماية ضد التخمين ودعم الدخول عبر Google"""
    if request.user.is_authenticated:
        return redirect('store:account_profile')
        
    next_url = request.GET.get('next', '')
    
    if request.method == 'POST':
        client_ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', '')).split(',')[0].strip()
        throttle_key = f"bv_login_fails_{client_ip}"
        failed_attempts = cache.get(throttle_key, 0)
        if failed_attempts >= 10:
            messages.error(request, 'تم تجاوز الحد الأقصى لمحاولات تسجيل الدخول. يرجى الانتظار 10 دقائق والمحاولة مجدداً.')
            return render(request, 'store/auth/login.html', {'identifier': request.POST.get('identifier', ''), 'next_url': request.POST.get('next', '')})

        identifier = request.POST.get('identifier', '').strip()
        password = request.POST.get('password', '')
        remember_me = request.POST.get('remember_me')
        next_url = request.POST.get('next', '')
        
        if not identifier or not password:
            messages.error(request, 'يرجى إدخال البريد الإلكتروني أو اسم المستخدم وكلمة المرور.')
            return render(request, 'store/auth/login.html', {'identifier': identifier, 'next_url': next_url})
            
        # التحقق إن كان المدخل بريداً إلكترونياً
        username = identifier
        if '@' in identifier:
            matched_user = User.objects.filter(email__iexact=identifier).first()
            if matched_user:
                username = matched_user.username
                
        user = authenticate(request, username=username, password=password)
        if user is not None:
            if user.is_active:
                cache.delete(throttle_key)
                auth_login(request, user)
                if remember_me:
                    request.session.set_expiry(60 * 60 * 24 * 30) # 30 يوماً
                else:
                    request.session.set_expiry(0) # حتى إغلاق المتصفح
                    
                display_name = user.first_name or user.username
                messages.success(request, f'تم تسجيل الدخول بنجاح. مرحباً {display_name}.')
                return redirect(_get_safe_redirect(request, default='store:home'))
            else:
                messages.error(request, 'هذا الحساب معطل حالياً. يرجى التواصل مع إدارة المتجر.')
        else:
            cache.set(throttle_key, failed_attempts + 1, timeout=600)
            messages.error(request, 'بيانات الدخول غير صحيحة. يرجى التحقق من البريد الإلكتروني وكلمة المرور.')
            
    return render(request, 'store/auth/login.html', {'next_url': next_url})


def register_view(request):
    """صفحة إنشاء حساب جديد"""
    if request.user.is_authenticated:
        return redirect('store:account_profile')
        
    next_url = request.GET.get('next', '')
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        phone = request.POST.get('phone', '').strip()
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')
        next_url = request.POST.get('next', '')
        
        # الفحوصات والتحقق من صحة المدخلات
        if not name:
            messages.error(request, 'يرجى إدخال الاسم.')
            return render(request, 'store/auth/register.html', locals())
            
        if not email or '@' not in email:
            messages.error(request, 'يرجى إدخال بريد إلكتروني صحيح.')
            return render(request, 'store/auth/register.html', locals())
            
        if User.objects.filter(email__iexact=email).exists():
            messages.error(request, 'البريد الإلكتروني مسجل مسبقاً. يرجى تسجيل الدخول.')
            return render(request, 'store/auth/register.html', locals())
            
        if len(password) < 6:
            messages.error(request, 'يجب ألا تقل كلمة المرور عن 6 خانات.')
            return render(request, 'store/auth/register.html', locals())
            
        if password != password_confirm:
            messages.error(request, 'كلمتا المرور غير متطابقتين.')
            return render(request, 'store/auth/register.html', locals())
            
        # إنشاء اسم مستخدم
        clean_prefix = ''.join(c for c in email.split('@')[0] if c.isalnum() or c in '_-') or 'user'
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
        
        # تسجيل الدخول
        auth_login(request, new_user)
        
        messages.success(request, f'تم إنشاء الحساب بنجاح. مرحباً {name}.')
        return redirect(_get_safe_redirect(request, default='store:home'))
        
    return render(request, 'store/auth/register.html', {'next_url': next_url})


def logout_view(request):
    """تسجيل الخروج"""
    auth_logout(request)
    messages.success(request, 'تم تسجيل الخروج بنجاح.')
    return redirect('store:home')


def google_login_redirect(request):
    """بدء تدفق المصادقة عبر Google OAuth 2.0"""
    settings = StoreSettings.get_settings()
    client_id = settings.effective_google_client_id
    next_url = request.GET.get('next', '')
    
    if not client_id:
        messages.info(
            request, 
            'لتفعيل الدخول عبر Google، يرجى حفظ معرف Google Client ID في إعدادات المتجر بلوحة الإدارة.'
        )
        return redirect(f"{reverse('store:login')}?next={next_url}")
        
    redirect_uri = request.build_absolute_uri(reverse('store:google_callback'))
    if not os.getenv('DJANGO_DEBUG', 'False').lower() in ('true', '1') and redirect_uri.startswith('http://'):
        redirect_uri = redirect_uri.replace('http://', 'https://', 1)

    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'access_type': 'online',
        'prompt': 'select_account',
        'state': next_url,
    }
    return redirect(f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}")


@csrf_exempt
def google_auth_callback(request):
    """
    استقبال التحقق من Google وتسجيل الدخول / إنشاء الحساب تلقائياً:
    1. عبر Google Identity Services (GIS) Token POST
    2. عبر OAuth 2.0 Authorization Code GET
    3. وضع التجربة السريع (Demo Mode) للاختبار
    """
    settings = StoreSettings.get_settings()
    next_url = _get_safe_redirect(request, default='store:home')
    
    credential = request.POST.get('credential')
    code = request.GET.get('code')
    is_demo = request.GET.get('demo') == '1' or request.POST.get('demo') == '1'
    
    user_email = None
    first_name = ''
    last_name = ''
    avatar_url = ''
    
    # 1. التحقق من التوكن القادم من Google Identity Services (GIS)
    if credential:
        try:
            verify_res = requests.get(
                f"https://oauth2.googleapis.com/tokeninfo?id_token={credential}", 
                timeout=8
            )
            if verify_res.status_code == 200:
                payload = verify_res.json()
                user_email = payload.get('email', '').strip().lower()
                first_name = payload.get('given_name') or payload.get('name', 'مستخدم')
                last_name = payload.get('family_name', '')
                avatar_url = payload.get('picture', '')
            else:
                messages.error(request, 'تعذر التحقق من رمز المصادقة المقدم من Google.')
                return redirect('store:login')
        except Exception as e:
            messages.error(request, f'تعذر الاتصال بخوادم Google: {e}')
            return redirect('store:login')
            
    # 2. التحقق من كود التفويض OAuth 2.0
    elif code:
        client_id = settings.effective_google_client_id
        client_secret = settings.effective_google_client_secret
        redirect_uri = request.build_absolute_uri(reverse('store:google_callback'))
        if not os.getenv('DJANGO_DEBUG', 'False').lower() in ('true', '1') and redirect_uri.startswith('http://'):
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
        except Exception as e:
            messages.error(request, f'تعذر استكمال الاتصال بخدمة Google: {e}')
            return redirect('store:login')
            
    # 3. وضع المعاينة في بيئة التطوير والاختبار
    elif is_demo:
        user_email = 'customer.verified@brandveloura.com'
        first_name = 'عميل فيلورا'
        last_name = ''
        avatar_url = ''
    else:
        messages.error(request, 'لم يتم تلقي بيانات مصادقة من Google.')
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
        
    # تسجيل الدخول
    auth_login(request, user)
    
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
            elif len(new_password) < 6:
                messages.error(request, 'يجب أن تتكون كلمة المرور الجديدة من 6 خانات على الأقل.')
            elif new_password != confirm_password:
                messages.error(request, 'كلمتا المرور غير متطابقتين.')
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
            
            profile.phone = phone
            profile.preferred_city = preferred_city
            profile.shipping_address = shipping_address
            profile.save()
            
            messages.success(request, 'تم حفظ البيانات بنجاح.')
            return redirect('store:account_profile')
        
    # جلب طلبات المستخدم
    order_query = Q(user=request.user)
    if request.user.email:
        order_query |= Q(customer_email__iexact=request.user.email)
    if profile.phone:
        order_query |= Q(customer_phone=profile.phone)
        
    orders = Order.objects.filter(order_query).distinct().select_related('payment_method').prefetch_related('items__product').order_by('-created_at')
    
    total_orders_count = orders.count()
    active_statuses = ['pending_verification', 'payment_verified', 'processing', 'out_for_delivery']
    active_orders_count = orders.filter(status__in=active_statuses).count()
    delivered_orders_count = orders.filter(status='delivered').count()
    
    total_spent_yer = sum(o.total_yer for o in orders.exclude(status='cancelled'))
    settings = StoreSettings.get_settings()
    yer_per_sar = settings.yer_per_sar or Decimal('530.00')
    total_spent_sar = round(total_spent_yer / yer_per_sar, 1) if yer_per_sar else Decimal('0.00')
    
    shipping_zones = ShippingZone.objects.filter(is_active=True).order_by('city_name')
    
    # إشعارات وتنبيهات العميل
    notifications = Notification.objects.filter(recipient=request.user).order_by('-created_at')
    notifications_unread_count = notifications.filter(is_read=False).count()

    context = {
        'profile': profile,
        'orders': orders,
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
    user_owns = (order.user == request.user) or (request.user.email and order.customer_email.lower() == request.user.email.lower())
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
        unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
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
        
    target_link = notification.link or reverse('store:account_profile')
    return redirect(target_link)


@require_POST
def mark_all_notifications_read_view(request):
    """تحديد كافة إشعارات العميل كمقروءة دفعة واحدة"""
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'unauthorized'}, status=401)
        
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    
    if request.user.is_staff and request.POST.get('admin_scope') == '1':
        Notification.objects.filter(for_admin=True, is_read=False).update(is_read=True)
        
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
        {'loc': f"{base_url}/track-order/", 'priority': '0.5', 'changefreq': 'monthly'},
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
        xml_lines.append('  <url>')
        xml_lines.append(f"    <loc>{u['loc']}</loc>")
        if 'lastmod' in u and u['lastmod']:
            xml_lines.append(f"    <lastmod>{u['lastmod']}</lastmod>")
        xml_lines.append(f"    <changefreq>{u['changefreq']}</changefreq>")
        xml_lines.append(f"    <priority>{u['priority']}</priority>")
        xml_lines.append('  </url>')
    xml_lines.append('</urlset>')
    
    response = HttpResponse('\n'.join(xml_lines), content_type="application/xml; charset=utf-8")
    response['Cache-Control'] = 'public, max-age=3600'
    return response


def llms_txt(request):
    """ملف llms.txt المعياري لتسهيل فهم محركات الذكاء الاصطناعي (GEO / AI Overviews) لكتالوج المتجر"""
    settings = StoreSettings.get_settings()
    base_url = request.build_absolute_uri('/')[:-1]
    
    content = f"""# {settings.store_name} — Luxury Boutique Knowledge File (llms.txt)

> {settings.store_tagline or 'بوتيك الفخامة الأول للعطور العالمية، الساعات الراقية، ومستحضرات التجميل الأصلية والماستر كواليتي.'}

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
        logger.error(f"Database health check failed: {e}", exc_info=True)
        db_status = "disconnected"
        http_status = 503
        service_status = "unhealthy"

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




