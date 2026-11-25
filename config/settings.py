import os
import sys
import hashlib
from pathlib import Path
from urllib.parse import urlparse
from django.core.management.utils import get_random_secret_key
# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file if available
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env')
except ImportError:
    pass

SECRET_KEY_ENV = os.getenv('DJANGO_SECRET_KEY', '').strip()
DEBUG = os.getenv('DJANGO_DEBUG', 'False').lower() in ('true', '1')

RUNNING_TESTS = len(sys.argv) > 1 and sys.argv[1] == 'test'
RUNNING_COLLECTSTATIC = len(sys.argv) > 1 and sys.argv[1] == 'collectstatic'

if SECRET_KEY_ENV:
    SECRET_KEY = SECRET_KEY_ENV
elif RUNNING_COLLECTSTATIC or RUNNING_TESTS:
    SECRET_KEY = get_random_secret_key()
elif DEBUG:
    SECRET_KEY = hashlib.sha256(f"bv-local-dev-{BASE_DIR}".encode()).hexdigest()
else:
    db_secret_seed = os.getenv('DATABASE_URL', '').strip()
    if db_secret_seed:
        SECRET_KEY = hashlib.pbkdf2_hmac(
            'sha256',
            db_secret_seed.encode('utf-8'),
            b'brandveloura-prod-key-derivation-v2',
            100_000,
        ).hex()
    else:
        SECRET_KEY = get_random_secret_key()

# Clean ALLOWED_HOSTS (strip schemes like https:// if mistakenly passed)
ALLOWED_HOSTS = []
DEFAULT_ALLOWED_HOSTS = 'brandveloura.com,www.brandveloura.com,.brandveloura.com,localhost,127.0.0.1'
raw_hosts = os.getenv('DJANGO_ALLOWED_HOSTS', DEFAULT_ALLOWED_HOSTS).split(',')
for host in raw_hosts:
    cleaned = host.strip()
    if cleaned:
        cleaned = cleaned.replace('https://', '').replace('http://', '').rstrip('/')
        # Ignore overly broad shared-hosting wildcards unless explicitly forced
        if cleaned in ('.railway.app', '.up.railway.app') and os.getenv('ALLOW_SHARED_RAILWAY_WILDCARDS', 'False').lower() not in ('true', '1'):
            continue
        if cleaned and cleaned not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(cleaned)

railway_domain = os.getenv('RAILWAY_PUBLIC_DOMAIN', '').strip()
if railway_domain and railway_domain not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(railway_domain)
if not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'brandveloura.com', 'www.brandveloura.com', '.brandveloura.com']
if RUNNING_TESTS and 'testserver' not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append('testserver')
if '*' not in ALLOWED_HOSTS:
    for domain_pattern in ['brandveloura.com', 'www.brandveloura.com', '.brandveloura.com', 'localhost', '127.0.0.1']:
        if domain_pattern not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(domain_pattern)

# CSRF Trusted Origins for Railway HTTPS & Custom Domains (strictly scoped to own domains)
CSRF_TRUSTED_ORIGINS = [
    origin.strip() for origin in os.getenv(
        'CSRF_TRUSTED_ORIGINS',
        'https://brandveloura.com,https://www.brandveloura.com,http://localhost:8000,http://127.0.0.1:8000'
    ).split(',')
    if origin.strip() and origin.strip() not in ('https://*.railway.app', 'https://*.up.railway.app')
]
if railway_domain:
    railway_origin = f"https://{railway_domain}"
    if railway_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(railway_origin)

# Automatically add any custom domain from ALLOWED_HOSTS to CSRF_TRUSTED_ORIGINS
for host in ALLOWED_HOSTS:
    if host not in ['*', 'localhost', '127.0.0.1', 'testserver'] and not host.startswith('.'):
        origin = f"https://{host}"
        if origin not in CSRF_TRUSTED_ORIGINS:
            CSRF_TRUSTED_ORIGINS.append(origin)

# Reverse Proxy & SSL Configuration (Essential for Railway SSL & Google OAuth Redirect URIs)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = os.getenv('USE_X_FORWARDED_HOST', 'False').lower() in ('true', '1')
USE_X_FORWARDED_PORT = True

# Cross-Origin Policies (allows Google Sign-In popups/redirects without blocking window communication)
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin-allow-popups'
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

# Global Session & Long-Lived Cookie Configuration (365-Day Persistent Session, Write-On-Modify Only)
SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db'
SESSION_CACHE_ALIAS = 'sessions'
SESSION_COOKIE_AGE = 86400 * 365  # 1 full year persistent shopping & auth session
SESSION_SAVE_EVERY_REQUEST = False  # Avoid synchronous DB/Redis writes on every read-only GET request
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# Production Security Enhancements (Enabled when DEBUG=False and not running tests)
if not DEBUG and not RUNNING_TESTS:
    SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'True') == 'True'
    SECURE_REDIRECT_EXEMPT = [r'^health/?$', r'^healthz/?$']
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    CSRF_COOKIE_HTTPONLY = True
    CSRF_COOKIE_SAMESITE = 'Lax'
    X_FRAME_OPTIONS = 'DENY'
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv('SECURE_HSTS_INCLUDE_SUBDOMAINS', 'True') == 'True'
    SECURE_HSTS_PRELOAD = os.getenv('SECURE_HSTS_PRELOAD', 'True') == 'True'

# Upload Limits (Maximum 10MB for receipt uploads)
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# Caching Configuration (LocMemCache default, Redis if REDIS_URL provided)
REDIS_URL = os.getenv('REDIS_URL') or os.getenv('REDIS_TLS_URL')
_REDIS_SOCKET_TIMEOUT = float(os.getenv('REDIS_SOCKET_TIMEOUT', '2.0'))
_REDIS_CONNECT_TIMEOUT = float(os.getenv('REDIS_CONNECT_TIMEOUT', '2.0'))
if REDIS_URL and 'test' not in sys.argv:
    _redis_options = {
        'socket_connect_timeout': _REDIS_CONNECT_TIMEOUT,
        'socket_timeout': _REDIS_SOCKET_TIMEOUT,
        'retry_on_timeout': True,
        'health_check_interval': 30,
    }
    if REDIS_URL.startswith('rediss://') and os.getenv('REDIS_SSL_CERT_REQS', '').lower() == 'none':
        _redis_options['ssl_cert_reqs'] = None
    CACHES = {
        'default': {
            'BACKEND': 'store.cache_backend.ResilientRedisCache',
            'LOCATION': REDIS_URL,
            'KEY_PREFIX': 'veloura_cat',
            'VERSION': 1,
            'TIMEOUT': 300,
            'OPTIONS': dict(_redis_options),
        },
        'sessions': {
            'BACKEND': 'store.cache_backend.ResilientRedisCache',
            'LOCATION': REDIS_URL,
            'KEY_PREFIX': 'veloura_sess',
            'VERSION': 1,
            'TIMEOUT': 86400 * 30,
            'OPTIONS': dict(_redis_options),
        },
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'veloura-default-cache',
            'KEY_PREFIX': 'veloura_cat',
            'VERSION': 1,
            'TIMEOUT': 300,
            'OPTIONS': {
                'MAX_ENTRIES': 3000,
            },
        },
        'sessions': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'veloura-sessions-cache',
            'KEY_PREFIX': 'veloura_sess',
            'VERSION': 1,
            'TIMEOUT': 86400 * 30,
            'OPTIONS': {
                'MAX_ENTRIES': 2000,
            },
        },
    }


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
    'store.middleware.PerformanceAndObservabilityMiddleware',
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
                conn_max_age=int(os.getenv('DB_CONN_MAX_AGE', '600')),
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
                'CONN_MAX_AGE': int(os.getenv('DB_CONN_MAX_AGE', '600')),
                'CONN_HEALTH_CHECKS': True,
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
WHITENOISE_MANIFEST_STRICT = False
WHITENOISE_USE_FINDERS = DEBUG or ('test' in sys.argv)
staticfiles_storage_backend = (
    'django.contrib.staticfiles.storage.StaticFilesStorage'
    if (DEBUG or 'test' in sys.argv)
    else 'whitenoise.storage.CompressedManifestStaticFilesStorage'
)
STATICFILES_STORAGE = staticfiles_storage_backend

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
        'PREFIX': '',
    }
    DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'
    MEDIA_URL = '/media/'
    media_storage_backend = 'cloudinary_storage.storage.MediaCloudinaryStorage'
else:
    media_storage_backend = 'django.core.files.storage.FileSystemStorage'

STORAGES = {
    "default": {
        "BACKEND": media_storage_backend,
    },
    "staticfiles": {
        "BACKEND": staticfiles_storage_backend,
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
        'store': {
            'handlers': ['console'],
            'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
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

