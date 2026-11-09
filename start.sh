#!/bin/sh
set -e

echo "[STARTUP] Running database migrations..."
python manage.py migrate --noinput

if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    echo "[STARTUP] Configuring admin superuser..."
    python manage.py setup_admin --username="$DJANGO_SUPERUSER_USERNAME" --password="$DJANGO_SUPERUSER_PASSWORD" --email="${DJANGO_SUPERUSER_EMAIL:-admin@brandveloura.com}"
fi

echo "[STARTUP] Starting Gunicorn on port ${PORT:-8000}..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers 2 \
    --threads 4 \
    --timeout 120 \
    --log-file - \
    --access-logfile -
