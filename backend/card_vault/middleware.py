from time import monotonic

from django.conf import settings

from card_vault.models import GergVaultTrafficEvent


class GergVaultTrafficMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = monotonic()
        response = self.get_response(request)
        duration_ms = int((monotonic() - started) * 1000)
        self._record_event(request, response, duration_ms)
        return response

    def _record_event(self, request, response, duration_ms: int) -> None:
        if not getattr(settings, "GERGVAULT_TRACK_TRAFFIC", True):
            return
        path = request.path or "/"
        if _is_excluded_path(path):
            return

        user = request.user if getattr(request, "user", None) and request.user.is_authenticated else None
        resolver_match = getattr(request, "resolver_match", None)
        route_name = ""
        if resolver_match:
            route_name = ":".join(part for part in [resolver_match.namespace, resolver_match.url_name] if part)

        try:
            GergVaultTrafficEvent.objects.create(
                user=user,
                session_key=getattr(getattr(request, "session", None), "session_key", "") or "",
                event_type=_event_type_for(path),
                path=path[:512],
                route_name=route_name[:255],
                method=(request.method or "GET")[:12],
                status_code=getattr(response, "status_code", 0) or 0,
                duration_ms=max(0, duration_ms),
                ip_address=_client_ip(request),
                forwarded_for=(request.META.get("HTTP_X_FORWARDED_FOR") or "")[:512],
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                referrer=request.META.get("HTTP_REFERER", ""),
                host=(request.get_host() or "")[:255],
                query_string_present=bool(request.META.get("QUERY_STRING")),
            )
        except Exception:
            # Analytics must never break the product path.
            return


def _is_excluded_path(path: str) -> bool:
    default_excludes = ("/static/", "/media/", "/favicon.ico")
    configured = tuple(getattr(settings, "GERGVAULT_TRAFFIC_EXCLUDED_PREFIXES", default_excludes))
    return any(path.startswith(prefix) for prefix in configured)


def _event_type_for(path: str) -> str:
    if path.startswith("/api/"):
        return GergVaultTrafficEvent.EventType.API_REQUEST
    if path.startswith("/accounts/"):
        return GergVaultTrafficEvent.EventType.AUTH
    if path.startswith("/admin/"):
        return GergVaultTrafficEvent.EventType.ADMIN
    if path.startswith("/card-vault/") or path == "/":
        return GergVaultTrafficEvent.EventType.PAGE_VIEW
    return GergVaultTrafficEvent.EventType.OTHER


def _client_ip(request):
    raw = request.META.get("HTTP_CF_CONNECTING_IP") or request.META.get("REMOTE_ADDR") or ""
    if not raw:
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR") or ""
        raw = forwarded_for.split(",", 1)[0].strip()
    return raw or None
