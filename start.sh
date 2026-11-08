#!/bin/sh
set -e

echo "[STARTUP] Running database migrations..."
python manage.py migrate --noinput

echo "[STARTUP] Starting Gunicorn on port ${PORT:-8000}..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers 2 \
    --threads 4 \
    --timeout 120 \
    --log-file - \
    --access-logfile -

