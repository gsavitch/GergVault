from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from card_vault.models import CardVaultIntakeSession
from card_vault.services.ai_extraction import create_best_crops_for_session


class Command(BaseCommand):
    help = "Regenerate Card Vault crop images for one intake session without running AI extraction."

    def add_arguments(self, parser):
        parser.add_argument("session_id")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Include approved cards. Without this, approved cards are skipped.",
        )
        parser.add_argument(
            "--keep-existing",
            action="store_true",
            help="Only attach/create missing crops instead of replacing existing crop images.",
        )

    def handle(self, *args, **options):
        session_id = options["session_id"]
        try:
            session = CardVaultIntakeSession.objects.get(pk=session_id)
        except CardVaultIntakeSession.DoesNotExist as exc:
            raise CommandError(f"CardVaultIntakeSession not found: {session_id}") from exc

        errors: list[str] = []
        crop_count = create_best_crops_for_session(
            session,
            replace=not options["keep_existing"],
            include_approved=options["force"],
            errors=errors,
        )
        session.extraction_summary = {
            **(session.extraction_summary or {}),
            "crop_count": crop_count,
            "crop_regenerated_at": timezone.now().isoformat(),
            "crop_regeneration_errors": errors,
        }
        session.save(update_fields=["extraction_summary", "updated_at"])

        self.stdout.write(self.style.SUCCESS(f"Card Vault crop regeneration finished: {crop_count} crop image(s)."))
        if errors:
            self.stdout.write(self.style.WARNING("Warnings: " + "; ".join(errors)))
