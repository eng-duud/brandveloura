from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from store import views as store_views

urlpatterns = [
    # لوحة الإدارة الفاخرة
    path('admin/', admin.site.urls),
    
    # مسارات المتجر
    path('', include('store.urls')),
    
    # مسارات PWA على المستوى الجذري
    path('manifest.json', store_views.pwa_manifest, name='root_manifest'),
    path('sw.js', store_views.service_worker, name='root_sw'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
