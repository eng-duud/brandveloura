import time
from django.conf import settings
from django.core.management.base import BaseCommand
from store.cache_backend import get_backend_metrics, inspect_redis_health
from store.cache_service import cache_delete, cache_get, cache_set, get_service_metrics


class Command(BaseCommand):
    help = 'Safely inspect Redis/Django cache health, session engine configuration, and hit/miss telemetry without exposing secrets.'

    def handle(self, *args, **options):
        self.stdout.write("=== Brand Veloura Cache & Session Architecture Check ===")
        self.stdout.write(f"SESSION_ENGINE: {settings.SESSION_ENGINE}")
        self.stdout.write(f"SESSION_CACHE_ALIAS: {settings.SESSION_CACHE_ALIAS}")

        for alias in ('default', 'sessions'):
            if alias not in settings.CACHES:
                continue
            info = inspect_redis_health(alias=alias)
            self.stdout.write(f"\n[Cache Alias: {alias}]")
            self.stdout.write(f"  Backend     : {info.get('backend')}")
            self.stdout.write(f"  Transport   : {info.get('transport')} (TLS={info.get('tls_enabled')})")
            self.stdout.write(f"  Key Prefix  : {info.get('key_prefix')} (v{info.get('version')})")
            self.stdout.write(f"  Timeout (s) : {info.get('timeout')}")
            self.stdout.write(f"  Reachable   : {info.get('reachable')} (ping={info.get('ping_ms')} ms)")
            if info.get('redis_version'):
                self.stdout.write(f"  Redis Ver   : {info.get('redis_version')}")
                self.stdout.write(f"  Memory Used : {info.get('used_memory_human')} / Max: {info.get('maxmemory_human')}")
                self.stdout.write(f"  Eviction    : {info.get('maxmemory_policy')}")
                self.stdout.write(f"  Clients     : {info.get('connected_clients')}")
                self.stdout.write(
                    f"  Keyspace    : hits={info.get('keyspace_hits')} misses={info.get('keyspace_misses')} "
                    f"(ratio={info.get('redis_hit_ratio')}%)"
                )

        t0 = time.perf_counter()
        smoke_key = 'bv_inspect_smoke_test'
        cache_set(smoke_key, {'status': 'ok'}, timeout=15)
        roundtrip_val = cache_get(smoke_key)
        cache_delete(smoke_key)
        rt_ms = round((time.perf_counter() - t0) * 1000, 3)

        self.stdout.write("\n[Round-Trip Smoke Test]")
        self.stdout.write(f"  Write/Read/Delete OK: {roundtrip_val == {'status': 'ok'}} ({rt_ms} ms)")

        self.stdout.write("\n[Process Metrics]")
        self.stdout.write(f"  Service Stats: {get_service_metrics()}")
        self.stdout.write(f"  Backend Stats: {get_backend_metrics()}")
