# Stage 1: Build production Tailwind CSS from the Django templates & JS.
FROM node:22-alpine AS css-builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY tailwind.config.cjs ./
COPY static/css/tailwind.input.css ./static/css/tailwind.input.css
COPY static/js ./static/js
COPY templates ./templates
COPY store ./store
RUN npm run build:css

# Stage 2: Build Python wheels so build toolchains (gcc/headers) stay out of runtime.
FROM python:3.12-slim AS py-builder
ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip wheel --wheel-dir /wheels -r requirements.txt

# Stage 3: Slim Brand Veloura Production runtime image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install minimal runtime libraries only (no gcc or -dev headers).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install pre-built Python wheels cleanly via requirements.txt.
COPY --from=py-builder /wheels /wheels
COPY requirements.txt /app/requirements.txt
RUN pip install --no-index --find-links=/wheels -r /app/requirements.txt && rm -rf /wheels

# Copy application source and the CSS generated in the Node build stage.
COPY . /app/
COPY --from=css-builder /app/static/css/tailwind.css /app/static/css/tailwind.css

# Normalize line endings (Windows CRLF -> LF) and ensure executable permissions.
RUN sed -i 's/\r$//' /app/start.sh && chmod +x /app/start.sh

# Collect compressed manifest static files and drop root privileges.
RUN mkdir -p /app/staticfiles /app/media && \
    DJANGO_DEBUG=False python manage.py collectstatic --noinput && \
    addgroup --system appuser && \
    adduser --system --ingroup appuser appuser && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Docker Healthcheck.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health/ || exit 1

# Execute start script.
CMD ["/bin/sh", "/app/start.sh"]
