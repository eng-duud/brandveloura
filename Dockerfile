# Build production Tailwind CSS from the Django templates.
FROM node:22-alpine AS css-builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY tailwind.config.cjs ./
COPY static/css/tailwind.input.css ./static/css/tailwind.input.css
COPY templates ./templates
COPY store ./store
RUN npm run build:css

# Brand Veloura Production Docker image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies for Pillow, PostgreSQL and Healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies.
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source and the CSS generated in the Node build stage.
COPY . /app/
COPY --from=css-builder /app/static/css/tailwind.css /app/static/css/tailwind.css

# Ensure the start script has executable permissions.
RUN chmod +x /app/start.sh

# Collect static files into staticfiles directory.
RUN python manage.py collectstatic --noinput

EXPOSE 8000

# Docker Healthcheck.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health/ || exit 1

# Execute start script.
CMD ["/bin/sh", "/app/start.sh"]
