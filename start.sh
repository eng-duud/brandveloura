#!/bin/sh
set -e

echo "[STARTUP] Running database migrations..."
python manage.py migrate --noinput

echo "[STARTUP] Pruning expired database sessions..."
python manage.py clearsessions || true

if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    echo "[STARTUP] Ensuring admin superuser exists..."
    python manage.py setup_admin
fi

echo "[STARTUP] Starting Gunicorn on port ${PORT:-8000}..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers "${WEB_CONCURRENCY:-2}" \
    --threads "${GUNICORN_THREADS:-4}" \
    --timeout 90 \
    --keep-alive 5 \
    --max-requests 1500 \
    --max-requests-jitter 150 \
    --log-file - \
    --access-logfile -
