from django.core.management.base import BaseCommand

from card_vault.services.pricing import provider_readiness


class Command(BaseCommand):
    help = "Show Card Vault pricing provider readiness without exposing secret values."

    def handle(self, *args, **options):
        for key, provider in provider_readiness().items():
            status = "configured" if provider["configured"] else "missing"
            missing = ", ".join(provider["missing_env_vars"]) if provider["missing_env_vars"] else "none"
            self.stdout.write(f"{key}: {status} (missing: {missing})")
