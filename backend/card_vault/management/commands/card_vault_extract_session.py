from django.core.management.base import BaseCommand, CommandError

from card_vault.models import CardVaultIntakeSession
from card_vault.services.ai_extraction import (
    CardVaultExtractionError,
    MissingOpenAIKey,
    run_extraction_for_session,
)


class Command(BaseCommand):
    help = "Run Card Vault AI extraction for one intake session."

    def add_arguments(self, parser):
        parser.add_argument("session_id")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite approved cards too. Without this, approved cards are skipped.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Call extraction and report what would update without saving cards, crops, or session response.",
        )
        parser.add_argument(
            "--model",
            default=None,
            help="Optional OpenAI vision model override.",
        )

    def handle(self, *args, **options):
        session_id = options["session_id"]
        try:
            session = CardVaultIntakeSession.objects.get(pk=session_id)
        except CardVaultIntakeSession.DoesNotExist as exc:
            raise CommandError(f"CardVaultIntakeSession not found: {session_id}") from exc

        try:
            result = run_extraction_for_session(
                session,
                force=options["force"],
                dry_run=options["dry_run"],
                model=options["model"],
            )
        except MissingOpenAIKey as exc:
            raise CommandError(str(exc)) from exc
        except CardVaultExtractionError as exc:
            raise CommandError(f"Card Vault AI extraction failed: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                "Card Vault extraction finished: "
                f"{result.updated_count} updated, "
                f"{result.skipped_approved_count} approved skipped, "
                f"{len(result.extracted_cards)} returned"
                + (" (dry-run)." if result.dry_run else ".")
            )
        )
        if result.errors:
            self.stdout.write(self.style.WARNING("Warnings: " + "; ".join(result.errors)))
