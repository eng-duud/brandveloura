import logging
import os
import time

from django.conf import settings
from django.db import connection

logger = logging.getLogger('store.performance')


class PerformanceAndObservabilityMiddleware:
    """Lightweight latency & slow-query logger with zero secret/PII exposure."""

    def __init__(self, get_response):
        self.get_response = get_response
        try:
            self.slow_ms = int(os.getenv('SLOW_REQUEST_THRESHOLD_MS', '500'))
        except (ValueError, TypeError):
            self.slow_ms = 500

    def __call__(self, request):
        path = request.path or '/'
        if path.startswith('/static/') or path in ('/health/', '/healthz/', '/sw.js'):
            return self.get_response(request)

        start = time.perf_counter()
        q_before = len(connection.queries) if settings.DEBUG else 0

        response = self.get_response(request)

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        if duration_ms >= self.slow_ms and not getattr(settings, 'RUNNING_TESTS', False):
            q_count = (len(connection.queries) - q_before) if settings.DEBUG else None
            logger.warning(
                "[SLOW_REQUEST] method=%s path=%s status=%s duration_ms=%.2f db_queries=%s htmx=%s",
                request.method,
                path[:120],
                getattr(response, 'status_code', '-'),
                duration_ms,
                q_count if q_count is not None else 'n/a',
                bool(request.headers.get('HX-Request')),
            )
        return response
