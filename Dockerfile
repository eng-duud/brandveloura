# Brand Veloura Production Dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies for Pillow, PostgreSQL and Healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . /app/

# Ensure start script has executable permissions
RUN chmod +x /app/start.sh

# Collect static files into staticfiles directory
RUN python manage.py collectstatic --noinput

# Expose web port
EXPOSE 8000

# Docker Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health/ || exit 1

# Execute start script
CMD ["/bin/sh", "/app/start.sh"]
