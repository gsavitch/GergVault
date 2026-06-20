from django.contrib.auth import get_user_model
from django.db.models import Q, QuerySet

from card_vault.models import GergVaultTenant, GergVaultTenantMembership


def default_tenant_for_user(user):
    if not getattr(user, "is_authenticated", False):
        return None
    membership = (
        GergVaultTenantMembership.objects
        .select_related("tenant")
        .filter(user=user)
        .order_by("created_at", "id")
        .first()
    )
    if membership:
        return membership.tenant
    base_slug = _slug(getattr(user, "username", "") or f"user-{user.pk}") or f"user-{user.pk}"
    slug = base_slug
    suffix = 2
    while GergVaultTenant.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{suffix}"
        suffix += 1
    tenant = GergVaultTenant.objects.create(
        name=f"{getattr(user, 'username', 'User')}'s Vault",
        slug=slug,
        created_by=user,
    )
    GergVaultTenantMembership.objects.create(
        tenant=tenant,
        user=user,
        role=GergVaultTenantMembership.Role.OWNER,
    )
    return tenant


def tenant_ids_for_user(user) -> list[int]:
    if not getattr(user, "is_authenticated", False):
        return []
    if getattr(user, "is_superuser", False):
        return list(GergVaultTenant.objects.values_list("id", flat=True))
    return list(
        GergVaultTenantMembership.objects
        .filter(user=user)
        .values_list("tenant_id", flat=True)
    )


def scope_queryset_to_user(queryset: QuerySet, user):
    if getattr(user, "is_superuser", False):
        return queryset
    tenant_ids = tenant_ids_for_user(user)
    model = queryset.model
    if model.__name__ == "CardVaultIntakeSession":
        return queryset.filter(Q(tenant_id__in=tenant_ids) | Q(tenant__isnull=True, created_by=user))
    if model.__name__ == "CardVaultCard":
        return queryset.filter(Q(tenant_id__in=tenant_ids) | Q(tenant__isnull=True, session__created_by=user))
    if model.__name__ == "CardVaultLocation":
        return queryset.filter(Q(tenant_id__in=tenant_ids) | Q(tenant__isnull=True))
    return queryset.filter(tenant_id__in=tenant_ids)


def _slug(value: str) -> str:
    slug = "-".join("".join(ch.lower() if ch.isalnum() else " " for ch in value).split())
    return slug[:240]
