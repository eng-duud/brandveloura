import os
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import Http404
from store import views as store_views

# مسار لوحة الإدارة السري القابل للتخصيص عبر متغيرات البيئة (Security Hardened Admin URL)
raw_admin_url = os.getenv('DJANGO_ADMIN_URL', 'admin').strip().strip('/')
admin_url = raw_admin_url if raw_admin_url else 'admin'


def fake_admin_honeypot(request):
    """إرجاع 404 لأي متطفل أو روبوت فحص يحاول استكشاف مسار admin/ التقليدي إذا تم تغييره"""
    raise Http404("الصفحة غير موجودة")


urlpatterns = [
    # لوحة الإدارة الفاخرة (على المسار السري المحدد)
    path(f'{admin_url}/', admin.site.urls),
    
    # مسارات المتجر
    path('', include('store.urls')),
    
    # مسارات PWA على المستوى الجذري
    path('manifest.json', store_views.pwa_manifest, name='root_manifest'),
    path('sw.js', store_views.service_worker, name='root_sw'),
    
    # مسارات محركات البحث والذكاء الاصطناعي (SEO / GEO / AI Overviews)
    path('robots.txt', store_views.robots_txt, name='robots_txt'),
    path('sitemap.xml', store_views.sitemap_xml, name='sitemap_xml'),
    path('llms.txt', store_views.llms_txt, name='llms_txt'),
    
    # فحص سلامة النظام السحابي (Railway Healthcheck)
    path('health/', store_views.health_check, name='health_check'),
    path('healthz/', store_views.health_check, name='healthz_check'),
]

# إذا تم تخصيص مسار إداري سري مختلف عن 'admin'، نحمي مسار 'admin/' القديم بإرجاع 404 وهمي
if admin_url != 'admin':
    urlpatterns.append(path('admin/', fake_admin_honeypot))

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
