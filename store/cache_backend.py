import logging
import threading
import time
from urllib.parse import urlparse

from django.conf import settings as django_settings
from django.core.cache import caches
from django.core.cache.backends.redis import RedisCache

try:
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - fallback when redis-py is absent
    class RedisError(Exception):
        pass


logger = logging.getLogger('store.cache')

_METRICS_LOCK = threading.Lock()
_METRICS = {}
_LAST_ERROR_LOG_TS = {}
_ERROR_LOG_COOLDOWN_SEC = 60.0
_HANDLED_ERRORS = (RedisError, OSError, TimeoutError, ConnectionError)


def _record_metric(bucket, key, amount=1):
    with _METRICS_LOCK:
        entry = _METRICS.setdefault(
            bucket,
            {'hits': 0, 'misses': 0, 'sets': 0, 'deletes': 0, 'errors': 0},
        )
        entry[key] = entry.get(key, 0) + amount


def _log_degraded_once(bucket, operation, exc):
    now = time.monotonic()
    should_log = False
    with _METRICS_LOCK:
        last = _LAST_ERROR_LOG_TS.get(bucket, 0.0)
        if now - last >= _ERROR_LOG_COOLDOWN_SEC:
            _LAST_ERROR_LOG_TS[bucket] = now
            should_log = True
    if should_log:
        # Never log raw exception details that might leak connection URLs or passwords.
        logger.warning(
            "[REDIS_FALLBACK] cache_bucket=%s operation=%s exc_type=%s — degrading gracefully to database fallback.",
            bucket,
            operation,
            type(exc).__name__,
        )


def get_backend_metrics():
    """Return a thread-safe snapshot of in-process cache backend counters."""
    with _METRICS_LOCK:
        return {k: dict(v) for k, v in _METRICS.items()}


def reset_backend_metrics():
    """Reset in-process counters (intended for isolated benchmarks and tests)."""
    with _METRICS_LOCK:
        _METRICS.clear()


class ResilientRedisCache(RedisCache):
    """Django built-in RedisCache hardened with graceful failover, metrics, and scoped clear()."""

    def _bucket(self):
        return self.key_prefix or 'default'

    def _fail(self, operation, exc, fallback=None):
        bucket = self._bucket()
        _record_metric(bucket, 'errors')
        _log_degraded_once(bucket, operation, exc)
        return fallback

    def add(self, key, value, timeout=None, version=None):
        bucket = self._bucket()
        try:
            kwargs = {'version': version}
            if timeout is not None:
                kwargs['timeout'] = timeout
            added = super().add(key, value, **kwargs)
            if added:
                _record_metric(bucket, 'sets')
            return added
        except _HANDLED_ERRORS as exc:
            return self._fail('add', exc, fallback=False)

    def get(self, key, default=None, version=None):
        bucket = self._bucket()
        sentinel = object()
        try:
            val = super().get(key, default=sentinel, version=version)
            if val is sentinel:
                _record_metric(bucket, 'misses')
                return default
            _record_metric(bucket, 'hits')
            return val
        except _HANDLED_ERRORS as exc:
            return self._fail('get', exc, fallback=default)

    def set(self, key, value, timeout=None, version=None):
        bucket = self._bucket()
        try:
            kwargs = {'version': version}
            if timeout is not None:
                kwargs['timeout'] = timeout
            super().set(key, value, **kwargs)
            _record_metric(bucket, 'sets')
        except _HANDLED_ERRORS as exc:
            self._fail('set', exc)

    def touch(self, key, timeout=None, version=None):
        try:
            kwargs = {'version': version}
            if timeout is not None:
                kwargs['timeout'] = timeout
            return super().touch(key, **kwargs)
        except _HANDLED_ERRORS as exc:
            return self._fail('touch', exc, fallback=False)

    def delete(self, key, version=None):
        bucket = self._bucket()
        try:
            deleted = super().delete(key, version=version)
            _record_metric(bucket, 'deletes')
            return deleted
        except _HANDLED_ERRORS as exc:
            return self._fail('delete', exc, fallback=False)

    def get_many(self, keys, version=None):
        bucket = self._bucket()
        key_list = list(keys)
        if not key_list:
            return {}
        try:
            res = super().get_many(key_list, version=version)
            hits = len(res)
            misses = max(0, len(key_list) - hits)
            if hits:
                _record_metric(bucket, 'hits', hits)
            if misses:
                _record_metric(bucket, 'misses', misses)
            return res
        except _HANDLED_ERRORS as exc:
            return self._fail('get_many', exc, fallback={})

    def has_key(self, key, version=None):
        try:
            return super().has_key(key, version=version)
        except _HANDLED_ERRORS as exc:
            return self._fail('has_key', exc, fallback=False)

    def incr(self, key, delta=1, version=None):
        try:
            return super().incr(key, delta=delta, version=version)
        except _HANDLED_ERRORS as exc:
            return self._fail('incr', exc, fallback=None)

    def set_many(self, data, timeout=None, version=None):
        bucket = self._bucket()
        try:
            kwargs = {'version': version}
            if timeout is not None:
                kwargs['timeout'] = timeout
            failed = super().set_many(data, **kwargs)
            _record_metric(bucket, 'sets', len(data))
            return failed
        except _HANDLED_ERRORS as exc:
            self._fail('set_many', exc)
            return list(data.keys())

    def delete_many(self, keys, version=None):
        bucket = self._bucket()
        key_list = list(keys)
        if not key_list:
            return
        try:
            super().delete_many(key_list, version=version)
            _record_metric(bucket, 'deletes', len(key_list))
        except _HANDLED_ERRORS as exc:
            self._fail('delete_many', exc)

    def clear(self):
        """Scope clear() to this alias's key_prefix via non-blocking SCAN so sessions are never wiped."""
        bucket = self._bucket()
        try:
            if not self.key_prefix:
                return super().clear()
            client = self._cache.get_client(None, write=True)
            pattern = f"{self.key_prefix}:*"
            batch = []
            for k in client.scan_iter(match=pattern, count=200):
                batch.append(k)
                if len(batch) >= 200:
                    try:
                        client.unlink(*batch)
                    except Exception:
                        client.delete(*batch)
                    batch.clear()
            if batch:
                try:
                    client.unlink(*batch)
                except Exception:
                    client.delete(*batch)
            _record_metric(bucket, 'deletes')
            return True
        except _HANDLED_ERRORS as exc:
            return self._fail('clear', exc, fallback=False)


def inspect_redis_health(alias='default'):
    """Safely check configured cache backend and Redis telemetry without exposing URLs or secrets."""
    cfg = django_settings.CACHES.get(alias, {})
    location = str(cfg.get('LOCATION', '') or '')
    parsed_scheme = urlparse(location).scheme if '://' in location else 'local'
    tls_enabled = parsed_scheme == 'rediss'

    result = {
        'alias': alias,
        'backend': cfg.get('BACKEND', 'unknown'),
        'key_prefix': cfg.get('KEY_PREFIX', ''),
        'version': cfg.get('VERSION', 1),
        'timeout': cfg.get('TIMEOUT', 300),
        'transport': parsed_scheme,
        'tls_enabled': tls_enabled,
        'reachable': False,
        'ping_ms': None,
        'redis_version': None,
        'used_memory_human': None,
        'maxmemory_human': None,
        'maxmemory_policy': None,
        'connected_clients': None,
        'keyspace_hits': None,
        'keyspace_misses': None,
        'redis_hit_ratio': None,
        'in_process_metrics': get_backend_metrics().get(cfg.get('KEY_PREFIX') or alias, {}),
    }

    backend_obj = caches[alias]
    if not hasattr(backend_obj, '_cache') or not hasattr(backend_obj._cache, 'get_client'):
        # LocMemCache or non-Redis backend
        t0 = time.perf_counter()
        smoke_key = 'bv_health_smoke'
        backend_obj.set(smoke_key, 'ok', timeout=5)
        ok = backend_obj.get(smoke_key) == 'ok'
        backend_obj.delete(smoke_key)
        result['reachable'] = ok
        result['ping_ms'] = round((time.perf_counter() - t0) * 1000, 3)
        return result

    try:
        client = backend_obj._cache.get_client(None, write=False)
        t0 = time.perf_counter()
        pong = bool(client.ping())
        result['ping_ms'] = round((time.perf_counter() - t0) * 1000, 3)
        result['reachable'] = pong
        if pong:
            info = client.info()
            hits = int(info.get('keyspace_hits', 0) or 0)
            misses = int(info.get('keyspace_misses', 0) or 0)
            total_ops = hits + misses
            result.update({
                'redis_version': info.get('redis_version'),
                'used_memory_human': info.get('used_memory_human'),
                'maxmemory_human': info.get('maxmemory_human'),
                'maxmemory_policy': info.get('maxmemory_policy'),
                'connected_clients': info.get('connected_clients'),
                'keyspace_hits': hits,
                'keyspace_misses': misses,
                'redis_hit_ratio': round((hits / total_ops) * 100, 2) if total_ops else None,
            })
    except _HANDLED_ERRORS as exc:
        result['error_type'] = type(exc).__name__
    return result
