from django.core.management.base import BaseCommand, CommandError

from card_vault.models import CardVaultCard, CardVaultIntakeSession
from django.utils import timezone

from card_vault.services.pricing import update_card_pricing


class Command(BaseCommand):
    help = "Update Card Vault estimated values from search-result comps."

    def add_arguments(self, parser):
        parser.add_argument("legacy_session_id", nargs="?", help="Legacy positional intake session id.")
        parser.add_argument("--session-id", default=None, help="Intake session id to update.")
        parser.add_argument("--card-id", type=int, default=None, help="Update one card instead of a whole session.")
        parser.add_argument("--all-approved", action="store_true", help="Update approved cards across the vault.")
        parser.add_argument("--missing-only", action="store_true", help="Only update cards missing estimated_raw_value.")
        parser.add_argument("--stale-days", type=int, default=None, help="Only update cards with no snapshot newer than this many days.")
        parser.add_argument("--provider", action="append", default=None, help="Provider to use. Repeatable.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Search and report valuation output without saving card or valuation rows.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite an existing estimated_raw_value. Default skips cards with an existing value.",
        )

    def handle(self, *args, **options):
        card_id = options["card_id"]
        session_id = options["session_id"] or options["legacy_session_id"]
        if not card_id and not session_id and not options["all_approved"]:
            raise CommandError("Provide --session-id, a legacy session_id, --card-id, or --all-approved.")

        cards = self._cards_for_options(
            session_id=session_id,
            card_id=card_id,
            all_approved=options["all_approved"],
            missing_only=options["missing_only"],
            stale_days=options["stale_days"],
        )
        updated = 0
        skipped = []
        errors = []
        for card in cards:
            try:
                result = update_card_pricing(
                    card.id,
                    force=options["force"],
                    dry_run=options["dry_run"],
                    providers=options["provider"],
                )
            except Exception as exc:
                errors.append(f"card {card.id}: {type(exc).__name__}: {exc}")
                continue
            if result.skipped:
                skipped.append(f"card {card.id}: {result.reason}")
                continue
            updated += 1
            pricing = result.pricing
            value = pricing.get("estimated_value_mid") or "unknown"
            confidence = pricing.get("confidence_label", "low")
            self.stdout.write(f"card {card.id}: midpoint ${value}, confidence {confidence}")

        suffix = " (dry-run)" if options["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(f"Card Vault value update finished: {updated} updated{suffix}."))
        if skipped:
            self.stdout.write(self.style.WARNING("Skipped: " + "; ".join(skipped)))
        if errors:
            self.stdout.write(self.style.ERROR("Errors: " + "; ".join(errors)))

    def _cards_for_options(self, *, session_id, card_id, all_approved, missing_only, stale_days):
        if card_id:
            try:
                cards = CardVaultCard.objects.filter(pk=card_id)
            except CardVaultCard.DoesNotExist as exc:
                raise CommandError(f"CardVaultCard not found: {card_id}") from exc
        elif all_approved:
            cards = CardVaultCard.objects.filter(review_status=CardVaultCard.ReviewStatus.APPROVED)
        else:
            try:
                session = CardVaultIntakeSession.objects.get(pk=session_id)
            except CardVaultIntakeSession.DoesNotExist as exc:
                raise CommandError(f"CardVaultIntakeSession not found: {session_id}") from exc
            cards = session.cards.exclude(review_status=CardVaultCard.ReviewStatus.IGNORED)
        if missing_only:
            cards = cards.filter(estimated_raw_value__isnull=True)
        if stale_days is not None:
            cutoff = timezone.now() - timezone.timedelta(days=stale_days)
            cards = cards.exclude(price_snapshots__created_at__gte=cutoff)
        return list(cards.order_by("slot_index", "id"))
