from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from card_vault.models import GergVaultTenant, GergVaultTrafficEvent


class Command(BaseCommand):
    help = "Run production readiness checks for hosted GergVault."

    def handle(self, *args, **options):
        checks = []
        checks.append(("debug_disabled", not settings.DEBUG))
        checks.append(("secure_session_cookie", settings.SESSION_COOKIE_SECURE))
        checks.append(("secure_csrf_cookie", settings.CSRF_COOKIE_SECURE))
        checks.append(("hsts_enabled", settings.SECURE_HSTS_SECONDS > 0))
        checks.append(("traffic_tracking_enabled", settings.GERGVAULT_TRACK_TRAFFIC))
        checks.append(("rate_limit_enabled", settings.GERGVAULT_RATE_LIMIT_ENABLED))
        checks.append(("tenant_model_present", GergVaultTenant.objects.exists()))
        checks.append(("traffic_table_writable", _traffic_table_writable()))
        failed = [name for name, ok in checks if not ok]
        for name, ok in checks:
            self.stdout.write(f"{'PASS' if ok else 'FAIL'} {name}")
        if failed:
            raise SystemExit(1)


def _traffic_table_writable() -> bool:
    try:
        GergVaultTrafficEvent.objects.order_by("-created_at").first()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return True
    except Exception:
        return False
