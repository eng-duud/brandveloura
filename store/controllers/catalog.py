from decimal import Decimal

from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from ..models import Brand, Category, GiftBundle, HeroBanner, Product, StoreSettings
from ..cache_service import (
    cache_get,
    cache_get_or_set_safe,
    cache_set,
    make_brands_list_key,
    make_catalog_brands_key,
    make_product_gallery_key,
    make_product_related_key,
)
from .helpers import _is_htmx_partial


def get_home_deferred_context(request):
    """تجهيز سياق الأشرطة التفاعلية السفلية للصفحة الرئيسية باستعلامات مُحسنة وبدون N+1"""
    active_cats = cache_get_or_set_safe(
        'bv_active_categories',
        lambda: list(Category.objects.filter(is_active=True).order_by('display_order', 'id')),
        timeout=300,
    ) or []
    children_map = {}
    for c in active_cats:
        children_map.setdefault(c.parent_id, []).append(c)

    def _cat_descendants_ids(root_id):
        res, queue = [], [root_id]
        while queue:
            cid = queue.pop(0)
            if cid not in res:
                res.append(cid)
                queue.extend(ch.id for ch in children_map.get(cid, []))
        return res

    featured_products = list(
        Product.objects.filter(is_active=True, is_featured=True)
        .select_related('category', 'brand')
        .prefetch_related('images')
        .order_by('-created_at')[:8]
    )
    if not featured_products:
        featured_products = list(
            Product.objects.filter(is_active=True)
            .select_related('category', 'brand')
            .prefetch_related('images')
            .order_by('-created_at')[:8]
        )

    def get_category_products(type_keys, limit=8):
        if isinstance(type_keys, str):
            type_keys = [type_keys]
        type_set = set(type_keys)
        matched_roots = [
            c.id for c in active_cats
            if c.category_type in type_set
            or any(k in (c.slug or '').lower() for k in type_set)
        ]
        cat_ids = set()
        for rid in matched_roots:
            cat_ids.update(_cat_descendants_ids(rid))
        if not cat_ids:
            return []
        return list(
            Product.objects.filter(category_id__in=cat_ids, is_active=True)
            .select_related('category', 'brand')
            .prefetch_related('images')
            .order_by('-is_featured', '-is_best_seller', '-created_at')[:limit]
        )

    home_slider_cats = sorted(
        [c for c in active_cats if c.show_in_home_slider],
        key=lambda c: (c.home_slider_order, c.display_order, c.id),
    )

    category_sliders = []
    for cat in home_slider_cats:
        cat_ids = _cat_descendants_ids(cat.id)
        cat_prods = list(
            Product.objects.filter(category_id__in=cat_ids, is_active=True)
            .select_related('category', 'brand')
            .prefetch_related('images')
            .order_by('-is_featured', '-is_best_seller', '-created_at')[:8]
        )

        if cat_prods:
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

    perfume_products = []
    watch_products = []
    cosmetic_products = []

    if not category_sliders:
        perfume_products = get_category_products('perfumes', limit=8)
        watch_products = get_category_products('watches', limit=8)
        cosmetic_products = get_category_products(['cosmetics', 'care'], limit=8)
        default_types = [
            ('perfumes', perfume_products, 'قسم العطور الفاخرة', 'sparkles', 'عطور عالمية أصلية وماستر تستر بأعلى ثبات وفوحان', 'store:perfumes_catalog', 'perfumes-scroll'),
            ('watches', watch_products, 'قسم الساعات الفاخرة', 'watch', 'ساعات رجالية ونسائية بتصاميم عصرية وكلاسيكية راقية', 'store:watches_catalog', 'watches-scroll'),
            (['cosmetics', 'care'], cosmetic_products, 'مستحضرات التجميل والعناية', 'heart', 'منتجات عناية ومكياج أصلي من كبرى الماركات العالمية', 'store:cosmetics_catalog', 'cosmetics-scroll'),
        ]
        for type_keys, prods, title, icon, subtitle, url_name, s_id in default_types:
            if prods:
                t_first = type_keys if isinstance(type_keys, str) else type_keys[0]
                cat_obj = next((c for c in active_cats if c.category_type == t_first), None)
                category_sliders.append({
                    'category': cat_obj,
                    'title': title,
                    'subtitle': subtitle,
                    'icon': icon,
                    'catalog_url': reverse(url_name),
                    'slider_id': s_id,
                    'products': prods,
                })

    ready_gift_bundles = list(
        GiftBundle.objects.filter(is_active=True)
        .prefetch_related('items__product__images')
        .order_by('display_order', '-created_at')[:8]
    )
    gift_bundles = ready_gift_bundles if ready_gift_bundles else get_category_products('bundles', limit=8)

    featured_brands = Brand.objects.filter(is_active=True).annotate(
        products_count=Count('products', filter=Q(products__is_active=True))
    ).order_by('display_order', '-products_count', 'name_ar')[:8]

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
    banners = cache.get('bv_home_banners')
    if banners is None:
        banners = list(HeroBanner.objects.filter(is_active=True).order_by('display_order'))
        try:
            cache.set('bv_home_banners', banners, timeout=900)
        except Exception:
            pass

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

    products = Product.objects.filter(
        Q(brand=brand) | Q(brand_name__iexact=brand.name_en) | Q(brand_name__iexact=brand.name_ar),
        is_active=True,
    ).select_related('category', 'brand').prefetch_related('images')

    category_filter = request.GET.get('category', '').strip()
    grade_filter = request.GET.get('grade', '').strip()
    gender_filter = request.GET.get('gender', '').strip()
    sort_by = request.GET.get('sort', 'newest')
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

    if gender_filter == 'men':
        products = products.filter(
            Q(specifications__gender='men') |
            Q(name_ar__icontains='رجالي') |
            Q(name_ar__icontains='رجالية')
        )
    elif gender_filter == 'women':
        products = products.filter(
            Q(specifications__gender='women') |
            Q(name_ar__icontains='نسائي') |
            Q(name_ar__icontains='نسائية')
        )
    elif gender_filter == 'unisex':
        products = products.filter(
            Q(specifications__gender='unisex') |
            Q(name_ar__icontains='للجنسين') |
            Q(description__icontains='للجنسين')
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

    brand_side_meta = cache_get_or_set_safe(
        f"bv_brand_meta:{brand.slug}",
        lambda: {
            'available_categories': list(
                Category.objects.filter(
                    id__in=Product.objects.filter(
                        Q(brand=brand) | Q(brand_name__iexact=brand.name_en) | Q(brand_name__iexact=brand.name_ar),
                        is_active=True,
                    ).values_list('category_id', flat=True).distinct(),
                    is_active=True,
                ).order_by('display_order', 'name_ar')
            ),
            'other_brands': list(
                Brand.objects.filter(is_active=True).exclude(id=brand.id).order_by('display_order')[:6]
            ),
        },
        timeout=300,
    ) or {}
    available_categories = brand_side_meta.get('available_categories', [])
    other_brands = brand_side_meta.get('other_brands', [])

    paginator = Paginator(products, 24)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'brand': brand,
        'products': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'is_paginated': page_obj.has_other_pages(),
        'category_filter': category_filter,
        'grade_filter': grade_filter,
        'gender_filter': gender_filter,
        'sort_by': sort_by,
        'search_query': search_query,
        'available_categories': available_categories,
        'other_brands': other_brands,
        'total_count': paginator.count,
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

    if not main_category and all_main_categories and not search_query:
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
    elif not main_category:
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

    if gender_filter == 'men':
        products = products.filter(
            Q(specifications__gender='men') |
            Q(name_ar__icontains='رجالي') |
            Q(name_ar__icontains='رجالية')
        )
    elif gender_filter == 'women':
        products = products.filter(
            Q(specifications__gender='women') |
            Q(name_ar__icontains='نسائي') |
            Q(name_ar__icontains='نسائية')
        )
    elif gender_filter == 'unisex':
        products = products.filter(
            Q(specifications__gender='unisex') |
            Q(name_ar__icontains='للجنسين') |
            Q(description__icontains='للجنسين')
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

    if sort_by == 'price_low':
        products = products.order_by('price_yer')
    elif sort_by == 'price_high':
        products = products.order_by('-price_yer')
    elif sort_by == 'best_sellers':
        products = products.order_by('-is_best_seller', '-created_at')
    else:
        products = products.order_by('-created_at')

    if main_category:
        main_descendant_ids = _descendants_ids(main_category.id)
        available_brands = cache_get_or_set_safe(
            make_catalog_brands_key(main_category.id),
            lambda: list(
                Product.objects.filter(
                    category_id__in=main_descendant_ids,
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

    active_filters_count = 0
    if brand_filter:
        active_filters_count += 1
    if grade_filter:
        active_filters_count += 1
    if min_price or max_price:
        active_filters_count += 1
    if sort_by and sort_by != 'newest':
        active_filters_count += 1

    if main_category:
        catalog_reset_url = f"{reverse('store:product_list')}?category={main_category.slug}"
        if active_subcategory:
            catalog_reset_url += f"&subcategory={active_subcategory.slug}"
    else:
        catalog_reset_url = reverse('store:product_list')

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

    if _is_htmx_partial(request):
        return render(request, 'store/partials/product_grid.html', context)

    return render(request, 'store/product_list.html', context)


def product_quick_view(request, slug):
    """عرض نافذة منبثقة تفاعلية للمنتج (Quick View Modal) دون مغادرة الصفحة"""
    product = get_object_or_404(
        Product.objects.select_related('category', 'brand').prefetch_related('images'),
        slug=slug,
        is_active=True,
    )
    images = list(product.images.all())
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
        is_active=True,
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
