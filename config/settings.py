import os
import sys
from pathlib import Path
from urllib.parse import urlparse
# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file if available
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env')
except ImportError:
    pass

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'brand-veloura-luxury-secret-key-2026-prod-grade')

DEBUG = os.getenv('DJANGO_DEBUG', 'True') == 'True'

# Clean ALLOWED_HOSTS (strip schemes like https:// if mistakenly passed)
ALLOWED_HOSTS = []
raw_hosts = os.getenv('DJANGO_ALLOWED_HOSTS', '*').split(',')
for host in raw_hosts:
    cleaned = host.strip()
    if cleaned:
        cleaned = cleaned.replace('https://', '').replace('http://', '').rstrip('/')
        if cleaned and cleaned not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(cleaned)

railway_domain = os.getenv('RAILWAY_PUBLIC_DOMAIN', '').strip()
if railway_domain and railway_domain not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(railway_domain)
if '*' not in ALLOWED_HOSTS:
    for domain_pattern in ['.railway.app', '.up.railway.app', 'localhost', '127.0.0.1']:
        if domain_pattern not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(domain_pattern)

# CSRF Trusted Origins for Railway HTTPS & Custom Domains
CSRF_TRUSTED_ORIGINS = [
    origin.strip() for origin in os.getenv(
        'CSRF_TRUSTED_ORIGINS', 
        'https://*.railway.app,https://*.up.railway.app,http://localhost:8000,http://127.0.0.1:8000'
    ).split(',') if origin.strip()
]
if railway_domain:
    railway_origin = f"https://{railway_domain}"
    if railway_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(railway_origin)

# Automatically add any custom domain from ALLOWED_HOSTS to CSRF_TRUSTED_ORIGINS
for host in ALLOWED_HOSTS:
    if host not in ['*', 'localhost', '127.0.0.1'] and not host.startswith('.'):
        origin = f"https://{host}"
        if origin not in CSRF_TRUSTED_ORIGINS:
            CSRF_TRUSTED_ORIGINS.append(origin)

# Reverse Proxy & SSL Configuration (Essential for Railway SSL & Google OAuth Redirect URIs)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True

# Production Security Enhancements (Enabled when DEBUG=False and not running tests)
if not DEBUG and 'test' not in sys.argv:
    SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'True') == 'True'
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv('SECURE_HSTS_INCLUDE_SUBDOMAINS', 'True') == 'True'
    SECURE_HSTS_PRELOAD = os.getenv('SECURE_HSTS_PRELOAD', 'True') == 'True'

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'whitenoise.runserver_nostatic',
    'django.contrib.staticfiles',
    
    # Cloudinary storage
    'cloudinary_storage',
    'cloudinary',
    
    # Store application
    'store.apps.StoreConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'store.context_processors.store_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database Configuration (PostgreSQL / SQLite flexible fallback for Railway)
DATABASE_URL = os.getenv('DATABASE_URL')
if 'test' in sys.argv:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': ':memory:',
        }
    }
elif DATABASE_URL and 'username:password' not in DATABASE_URL:
    try:
        import dj_database_url
        DATABASES = {
            'default': dj_database_url.config(
                default=DATABASE_URL,
                conn_max_age=600,
                conn_health_checks=True,
            )
        }
    except ImportError:
        from urllib.parse import urlparse, unquote
        url = urlparse(DATABASE_URL)
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': unquote(url.path[1:]),
                'USER': unquote(url.username or ''),
                'PASSWORD': unquote(url.password or ''),
                'HOST': url.hostname,
                'PORT': url.port or 5432,
            }
        }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization & Localization
LANGUAGE_CODE = 'ar'
TIME_ZONE = 'Asia/Aden'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
WHITENOISE_MANIFEST_STRICT = False

# Media Files & Cloudinary Integration (Supports Railway Cloudinary URL or discrete keys)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

cloudinary_url_env = os.getenv('CLOUDINARY_URL', '').strip()
if cloudinary_url_env:
    from urllib.parse import urlparse, unquote
    parsed_cld = urlparse(cloudinary_url_env)
    cld_cloud_name = parsed_cld.hostname or ''
    cld_api_key = unquote(parsed_cld.username or '')
    cld_api_secret = unquote(parsed_cld.password or '')
else:
    cld_cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME', '').strip()
    cld_api_key = os.getenv('CLOUDINARY_API_KEY', '').strip()
    cld_api_secret = os.getenv('CLOUDINARY_API_SECRET', '').strip()

if cld_cloud_name and cld_api_key and cld_api_secret:
    CLOUDINARY_STORAGE = {
        'CLOUD_NAME': cld_cloud_name,
        'API_KEY': cld_api_key,
        'API_SECRET': cld_api_secret,
    }
    DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'
    MEDIA_URL = f'https://res.cloudinary.com/{cld_cloud_name}/'
    media_storage_backend = 'cloudinary_storage.storage.MediaCloudinaryStorage'
else:
    media_storage_backend = 'django.core.files.storage.FileSystemStorage'

STORAGES = {
    "default": {
        "BACKEND": media_storage_backend,
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Production Logging Configuration for Railway Console
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
    },
    'loggers': {
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Authentication URLs
LOGIN_URL = 'store:login'
LOGIN_REDIRECT_URL = 'store:home'
LOGOUT_REDIRECT_URL = 'store:home'

# Google OAuth Configuration (Optional from .env or configured in StoreSettings)
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', '')

# Django Unfold Theme Customization (Luxury Pink, Rose & White)
from django.urls import reverse_lazy

UNFOLD = {
    "SITE_TITLE": "Brand Veloura | لوحة الإدارة",
    "SITE_HEADER": "Brand Veloura Boutique",
    "SITE_SUBHEADER": "المتجر الفاخر للعطور والساعات ومستحضرات التجميل",
    "COLORS": {
        "primary": {
            "50": "255 241 242",
            "100": "255 228 230",
            "200": "254 205 211",
            "300": "253 164 175",
            "400": "251 113 133",
            "500": "244 63 94",
            "600": "225 29 72",
            "700": "190 18 60",
            "800": "159 18 57",
            "900": "136 19 55",
            "950": "76 5 25",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "إدارة الطلبات والمالية",
                "separator": True,
                "items": [
                    {
                        "title": "الطلبات وفحص السندات",
                        "icon": "shopping_bag",
                        "link": reverse_lazy("admin:store_order_changelist"),
                    },
                    {
                        "title": "حسابات التحويل (الكريمي والمحافظ)",
                        "icon": "account_balance",
                        "link": reverse_lazy("admin:store_paymentaccount_changelist"),
                    },
                    {
                        "title": "مناطق الشحن وتكاليف التوصيل",
                        "icon": "local_shipping",
                        "link": reverse_lazy("admin:store_shippingzone_changelist"),
                    },
                ],
            },
            {
                "title": "الكتالوج والمنتجات الفاخرة",
                "separator": True,
                "items": [
                    {
                        "title": "المنتجات والمخزون",
                        "icon": "inventory_2",
                        "link": reverse_lazy("admin:store_product_changelist"),
                    },
                    {
                        "title": "الأقسام والفئات",
                        "icon": "category",
                        "link": reverse_lazy("admin:store_category_changelist"),
                    },
                ],
            },
            {
                "title": "واجهة المتجر وسعر الصرف",
                "separator": True,
                "items": [
                    {
                        "title": "إعدادات المتجر وسعر الصرف",
                        "icon": "tune",
                        "link": reverse_lazy("admin:store_storesettings_changelist"),
                    },
                    {
                        "title": "البانرات الترويجية والعروض",
                        "icon": "view_carousel",
                        "link": reverse_lazy("admin:store_herobanner_changelist"),
                    },
                ],
            },
        ],
    },
}
