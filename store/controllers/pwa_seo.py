import json
import os
from xml.sax.saxutils import escape as xml_escape

from django.conf import settings as django_settings
from django.core.cache import cache
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils.encoding import iri_to_uri
from django.views.decorators.http import require_POST

from ..models import Brand, Category, GiftBundle, Product, StoreSettings, WebPushSubscription
from ..cache_service import cache_get_or_set_safe
from ..push_notifications import bind_order_push_endpoint, get_or_create_vapid_keys
from .helpers import _bump_rate_limit, _get_client_ip, logger


def pwa_manifest(request):
    """ملف manifest.json لدعم تثبيت المتجر كتطبيق هاتف PWA متكامل — محسّن لـ ASO"""
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
    """
    ملف sw.js لإدارة الكاش، التصفح أوفلاين، وإظهار إشعارات الشريط العلوي لهواتف العملاء
    تماماً مثل التطبيقات الأصلية (صوت + اهتزاز + شارة عداد الأيقونة + بانر علوي داخل التطبيق المفتوح).
    """
    admin_prefix = "/" + (os.getenv('DJANGO_ADMIN_URL', 'admin').strip().strip('/') or 'admin')
    sw_code = """
    const CACHE_NAME = 'brand-veloura-pwa-v7';
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
                return Promise.allSettled(
                    PRECACHE_ASSETS.map((asset) => cache.add(asset))
                );
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
        '__ADMIN_PREFIX__',
        '/admin',
        '/api/',
        '/partials/',
        '/notifications/',
        '/cart',
        '/checkout',
        '/account',
        '/order',
        '/gift-slip/',
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
                fetch(event.request, { cache: 'no-store' }).catch(async () => {
                    return (await caches.match(OFFLINE_URL)) || Response.error();
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

    // استقبال إشعارات التطبيق المباشرة وعرضها في الشريط العلوي للنظام (Heads-Up OS Notification)
    self.addEventListener('push', (event) => {
        let payload = {
            title: 'Brand Veloura',
            body: 'إشعار جديد من المتجر',
            url: '/',
            icon: '/static/icons/icon-192.png',
            badge: '/static/icons/icon-192.png',
            tag: 'bv-' + Date.now(),
            renotify: true,
            timestamp: Date.now()
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
            silent: false,
            renotify: payload.renotify !== false,
            tag: payload.tag || ('bv-' + Date.now()),
            timestamp: payload.timestamp || Date.now(),
            dir: 'rtl',
            lang: 'ar',
            data: { url: payload.url || '/' },
            actions: [
                { action: 'open', title: 'عرض التفاصيل' },
                { action: 'dismiss', title: 'إغلاق' }
            ]
        };
        if (payload.image) {
            options.image = payload.image;
        }

        const tasks = [
            self.registration.showNotification(payload.title, options),
            clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
                windowClients.forEach((client) => {
                    client.postMessage({
                        type: 'BV_PUSH_RECEIVED',
                        payload: payload
                    });
                });
            })
        ];

        if (self.navigator && typeof self.navigator.setAppBadge === 'function') {
            tasks.push(self.navigator.setAppBadge().catch(() => {}));
        }

        event.waitUntil(Promise.allSettled(tasks));
    });

    // النقر على الإشعار من الشريط العلوي للهاتف وتوجيه العميل للصفحة المطلوبة مباشرة
    self.addEventListener('notificationclick', (event) => {
        event.notification.close();
        if (self.navigator && typeof self.navigator.clearAppBadge === 'function') {
            self.navigator.clearAppBadge().catch(() => {});
        }
        if (event.action === 'dismiss') {
            return;
        }
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
    sw_code = sw_code.replace('__ADMIN_PREFIX__', admin_prefix)
    response = HttpResponse(sw_code, content_type='application/javascript')
    response['Cache-Control'] = 'no-cache, max-age=0, must-revalidate'
    return response


def push_vapid_key(request):
    """إرجاع المفتاح العام VAPID لاشتراك أجهزة العملاء في إشعارات PWA"""
    pub_key, _, _ = get_or_create_vapid_keys()
    return JsonResponse({'publicKey': pub_key})


@require_POST
def push_subscribe(request):
    """تسجيل وتحديث اشتراك جهاز العميل في إشعارات الشريط العلوي وربطه بالحساب وطلبات الجلسة"""
    client_ip = _get_client_ip(request)
    push_throttle_key = f"bv_push_sub_rate_{client_ip}"
    if _bump_rate_limit(push_throttle_key, timeout=60) > 30:
        return JsonResponse({'error': 'Too many requests. Please try again later.'}, status=429)

    try:
        data = json.loads(request.body.decode('utf-8'))
        endpoint = str(data.get('endpoint', '')).strip()
        keys = data.get('keys', {})
        p256dh = str(keys.get('p256dh', '')).strip()
        auth = str(keys.get('auth', '')).strip()

        if not endpoint or not p256dh or not auth:
            return JsonResponse({'error': 'Invalid subscription payload'}, status=400)

        if not endpoint.startswith('https://') or len(endpoint) > 500:
            return JsonResponse({'error': 'Invalid endpoint protocol or length'}, status=400)

        if len(p256dh) > 255 or len(auth) > 255:
            return JsonResponse({'error': 'Invalid key parameters'}, status=400)

        user = request.user if request.user.is_authenticated else None
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:250]

        defaults = {
            'p256dh': p256dh,
            'auth': auth,
            'user_agent': user_agent,
        }
        if user is not None:
            defaults['user'] = user

        sub, created = WebPushSubscription.objects.update_or_create(
            endpoint=endpoint,
            defaults=defaults,
        )

        # حفظ الـ endpoint في الجلسة وربط أي طلبات حديثة للعميل (حتى لو كان زائراً وفعل الإشعارات بعد الطلب)
        request.session['push_endpoint'] = endpoint
        for ord_num in (request.session.get('recent_order_numbers') or []):
            bind_order_push_endpoint(ord_num, endpoint)
        if request.session.get('last_order_number'):
            bind_order_push_endpoint(request.session['last_order_number'], endpoint)
        request.session.modified = True

        return JsonResponse({'success': True, 'id': sub.id, 'created': created})
    except Exception as ex:
        logger.warning(f"Push subscription error from {client_ip}: {ex}")
        return JsonResponse({'error': 'Failed to process subscription'}, status=400)


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
    """توليد خريطة الموقع XML الديناميكية مع كاش Redis فائق السرعة واستعلامات خفيفة جداً"""
    raw_base = request.build_absolute_uri('/')[:-1]
    if not django_settings.DEBUG and raw_base.startswith('http://'):
        base_url = raw_base.replace('http://', 'https://', 1)
    else:
        base_url = raw_base

    def _build_sitemap_xml():
        urls = [
            {'loc': f"{base_url}/", 'priority': '1.0', 'changefreq': 'daily'},
            {'loc': f"{base_url}/products/", 'priority': '0.9', 'changefreq': 'daily'},
            {'loc': f"{base_url}/perfumes/", 'priority': '0.9', 'changefreq': 'daily'},
            {'loc': f"{base_url}/watches/", 'priority': '0.9', 'changefreq': 'daily'},
            {'loc': f"{base_url}/cosmetics/", 'priority': '0.9', 'changefreq': 'daily'},
            {'loc': f"{base_url}/brands/", 'priority': '0.9', 'changefreq': 'daily'},
            {'loc': f"{base_url}/gifting/", 'priority': '0.9', 'changefreq': 'daily'},
        ]

        for cat_slug in Category.objects.filter(is_active=True).values_list('slug', flat=True):
            urls.append({
                'loc': f"{base_url}/products/?category={cat_slug}",
                'priority': '0.8',
                'changefreq': 'weekly',
            })

        for b_slug in Brand.objects.filter(is_active=True).values_list('slug', flat=True):
            urls.append({
                'loc': f"{base_url}/brands/{b_slug}/",
                'priority': '0.85',
                'changefreq': 'weekly',
            })

        for b_slug in GiftBundle.objects.filter(is_active=True).values_list('slug', flat=True):
            urls.append({
                'loc': f"{base_url}/gifting/bundles/{b_slug}/",
                'priority': '0.8',
                'changefreq': 'weekly',
            })

        for prod_slug, updated_at in Product.objects.filter(is_active=True).order_by('-updated_at').values_list('slug', 'updated_at'):
            lastmod = updated_at.strftime('%Y-%m-%d') if updated_at else ''
            urls.append({
                'loc': f"{base_url}/products/{prod_slug}/",
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
        return '\n'.join(xml_lines)

    xml_body = cache_get_or_set_safe('bv_sitemap_xml', _build_sitemap_xml, timeout=3600)
    response = HttpResponse(xml_body, content_type="application/xml; charset=utf-8")
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
