from decimal import Decimal, InvalidOperation
from datetime import timedelta
from threading import Thread

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import close_old_connections, transaction
from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from rest_framework import status
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from card_vault.models import CardVaultCard, CardVaultImage, CardVaultIntakeSession, CardVaultPriceSnapshot, CardVaultValuationRun
from card_vault.serializers import (
    CardVaultBatchIntakeSerializer,
    CardVaultCardSerializer,
    CardVaultIntakeSessionSerializer,
    EDITABLE_CARD_FIELDS,
    draft_json_for_slot,
    extracted_json_for_card,
    rich_metadata_sections,
)
from card_vault.services.ai_extraction import (
    CardVaultExtractionError,
    MissingOpenAIKey,
    create_best_crops_for_session,
    run_extraction_for_session,
)
from card_vault.services.ai_enrichment import ENRICHMENT_MODE_CHOICES, ENRICHMENT_MODES, run_card_enrichment
from card_vault.services.valuation import (
    CardVaultValuationError,
    MissingBraveSearchKey,
    update_card_estimated_value,
)
from card_vault.services.pricing import provider_readiness, update_card_pricing

AI_EXTRACTION_STALE_AFTER = timedelta(minutes=3)


def _latest_price_snapshots():
    latest_snapshot_id = (
        CardVaultPriceSnapshot.objects
        .filter(card_id=OuterRef("card_id"))
        .order_by("-created_at", "-id")
        .values("id")[:1]
    )
    return CardVaultPriceSnapshot.objects.filter(id=Subquery(latest_snapshot_id))


class BatchCardIntakeView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        serializer = CardVaultBatchIntakeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        sport = (data.get("sport") or "basketball").strip() or "basketball"
        expected_count = data["expected_card_count"]

        session = CardVaultIntakeSession.objects.create(
            session_type=CardVaultIntakeSession.SessionType.BATCH_FRONT_BACK,
            title=data.get("title", ""),
            sport=sport,
            expected_card_count=expected_count,
            review_status=CardVaultIntakeSession.ReviewStatus.NEEDS_REVIEW,
            extraction_status="not_started",
            extraction_summary={
                "feature": "Batch Card Intake",
                "module": "Card Vault",
                "draft_card_count": expected_count,
                "crop_detection": "pending",
                "ai_extraction": "pending",
            },
            notes=data.get("notes", ""),
            created_by=request.user if request.user.is_authenticated else None,
        )
        CardVaultImage.objects.create(
            session=session,
            role=CardVaultImage.ImageRole.FRONT_GROUP_ORIGINAL,
            image=data["front_group_image"],
            original_filename=getattr(data["front_group_image"], "name", ""),
            metadata={"intake_role": "fronts", "expected_card_count": expected_count},
        )
        CardVaultImage.objects.create(
            session=session,
            role=CardVaultImage.ImageRole.BACK_GROUP_ORIGINAL,
            image=data["back_group_image"],
            original_filename=getattr(data["back_group_image"], "name", ""),
            metadata={"intake_role": "backs", "expected_card_count": expected_count},
        )

        cards = []
        for slot_index in range(1, expected_count + 1):
            draft = draft_json_for_slot(slot_index=slot_index, sport=sport)
            cards.append(
                CardVaultCard(
                    session=session,
                    slot_index=slot_index,
                    sport=sport,
                    extracted_json=draft,
                    confidence=0,
                    review_status=CardVaultCard.ReviewStatus.NEEDS_REVIEW,
                    is_draft=True,
                )
            )
        CardVaultCard.objects.bulk_create(cards)

        session = CardVaultIntakeSession.objects.prefetch_related("images", "cards").get(pk=session.pk)
        output = CardVaultIntakeSessionSerializer(session, context={"request": request})
        return Response(output.data, status=status.HTTP_201_CREATED)


class CardVaultIntakeSessionDetailView(RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CardVaultIntakeSessionSerializer
    queryset = CardVaultIntakeSession.objects.prefetch_related("images", "cards")
    lookup_field = "pk"


class CardVaultCardUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, session_id, card_id):
        card = get_object_or_404(CardVaultCard, pk=card_id, session_id=session_id)
        serializer = CardVaultCardSerializer(card, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        card = serializer.save()
        card.extracted_json = extracted_json_for_card(card)
        card.save(update_fields=["extracted_json", "updated_at"])
        return Response(CardVaultCardSerializer(card, context={"request": request}).data)


class CardVaultCardApproveView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, session_id, card_id):
        card = get_object_or_404(CardVaultCard, pk=card_id, session_id=session_id)
        card.review_status = CardVaultCard.ReviewStatus.APPROVED
        card.is_draft = False
        card.approved_by = request.user
        card.approved_at = timezone.now()
        card.save(update_fields=["review_status", "is_draft", "approved_by", "approved_at", "updated_at"])
        if not card.session.cards.filter(review_status=CardVaultCard.ReviewStatus.NEEDS_REVIEW).exists():
            card.session.review_status = CardVaultIntakeSession.ReviewStatus.APPROVED
            card.session.save(update_fields=["review_status", "updated_at"])
        return Response(CardVaultCardSerializer(card, context={"request": request}).data)


class CardVaultCardValuationRunsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, card_id):
        card = get_object_or_404(CardVaultCard, pk=card_id)
        return Response([_valuation_run_payload(run) for run in card.valuation_runs.prefetch_related("comps").all()])

    def post(self, request, card_id):
        force = bool(request.data.get("force", True))
        providers = request.data.get("providers") or None
        result = update_card_pricing(card_id, force=force, providers=providers)
        if result.skipped:
            return Response({"skipped": True, "reason": result.reason}, status=status.HTTP_200_OK)
        return Response(_valuation_run_payload(result.run), status=status.HTTP_201_CREATED)


class CardVaultValuationRunDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, run_id):
        run = get_object_or_404(CardVaultValuationRun.objects.prefetch_related("comps"), pk=run_id)
        return Response(_valuation_run_payload(run))


@login_required
def dashboard(request):
    counts = CardVaultCard.objects.aggregate(
        total=Count("id"),
        needs_review=Count("id", filter=Q(review_status=CardVaultCard.ReviewStatus.NEEDS_REVIEW)),
        approved=Count("id", filter=Q(review_status=CardVaultCard.ReviewStatus.APPROVED)),
        ignored=Count("id", filter=Q(review_status=CardVaultCard.ReviewStatus.IGNORED)),
    )
    sessions = (
        CardVaultIntakeSession.objects.annotate(card_count=Count("cards"))
        .order_by("-created_at")[:12]
    )
    latest_snapshots = _latest_price_snapshots()
    collection = latest_snapshots.aggregate(
        low=Sum("estimated_value_low"),
        mid=Sum("estimated_value_mid"),
        high=Sum("estimated_value_high"),
    )
    missing_value = CardVaultCard.objects.filter(estimated_raw_value__isnull=True).exclude(
        review_status=CardVaultCard.ReviewStatus.IGNORED
    ).count()
    stale_cutoff = timezone.now() - timedelta(days=30)
    stale_value = CardVaultCard.objects.filter(price_snapshots__created_at__lt=stale_cutoff).distinct().count()
    top_cards = CardVaultCard.objects.filter(estimated_raw_value__isnull=False).order_by("-estimated_raw_value")[:10]
    grading_cards = CardVaultValuationRun.objects.filter(grading_recommendation__icontains="Grade review").select_related("card")[:10]
    low_confidence_runs = CardVaultValuationRun.objects.filter(confidence_label="low").select_related("card")[:10]
    return render(
        request,
        "card_vault/dashboard.html",
        {
            "counts": counts,
            "sessions": sessions,
            "collection": collection,
            "missing_value": missing_value,
            "stale_value": stale_value,
            "top_cards": top_cards,
            "grading_cards": grading_cards,
            "low_confidence_runs": low_confidence_runs,
        },
    )


@login_required
def intake_review(request, session_id):
    session = get_object_or_404(
        CardVaultIntakeSession.objects.prefetch_related("images", "cards"),
        pk=session_id,
    )
    front_group_image = session.images.filter(role=CardVaultImage.ImageRole.FRONT_GROUP_ORIGINAL).first()
    back_group_image = session.images.filter(role=CardVaultImage.ImageRole.BACK_GROUP_ORIGINAL).first()
    return render(
        request,
        "card_vault/intake_review.html",
        {
            "session": session,
            "front_group_image": front_group_image,
            "back_group_image": back_group_image,
            "cards": session.cards.all().order_by("slot_index"),
            "editable_fields": EDITABLE_CARD_FIELDS,
        },
    )


@login_required
def card_detail(request, card_id):
    card = get_object_or_404(
        CardVaultCard.objects.select_related(
            "session",
            "front_image_crop",
            "back_image_crop",
            "location",
        ),
        pk=card_id,
    )
    front_group_image = None
    back_group_image = None
    if card.session_id:
        front_group_image = card.session.images.filter(role=CardVaultImage.ImageRole.FRONT_GROUP_ORIGINAL).first()
        back_group_image = card.session.images.filter(role=CardVaultImage.ImageRole.BACK_GROUP_ORIGINAL).first()
    sections = rich_metadata_sections(card)
    external_link_labels = (
        ("Wikipedia", "wikipedia_url"),
        ("Player Wikipedia", "player_wikipedia_url"),
        ("Basketball Reference", "basketball_reference_url"),
        ("WNBA Profile", "wnba_profile_url"),
        ("NBA Profile", "nba_profile_url"),
        ("Sports Reference", "sports_reference_url"),
        ("League Player Profile", "league_player_profile_url"),
        ("Team Profile", "team_profile_url"),
        ("TCDB", "tcdb_url"),
        ("SportsCardsPro", "sportscardspro_url"),
        ("eBay Search", "ebay_search_url"),
        ("PSA Pop Report", "psa_pop_report_url"),
        ("Checklist", "checklist_url"),
    )
    external_links = [
        (label, sections.get("external_links", {}).get(field) or sections.get("player_profile", {}).get(field) or sections.get("product_checklist", {}).get(field))
        for label, field in external_link_labels
    ]
    external_links = [(label, url) for label, url in external_links if url]
    valuation = {
        "confidence": None,
        "valuation_date": None,
        "warning": "",
    }
    valuation.update(((card.extracted_json or {}).get("valuation") or {}))
    pricing = {
        "estimated_value_low": None,
        "estimated_value_mid": None,
        "estimated_value_high": None,
        "value_status": "no_reliable_estimate",
        "value_status_label": "No reliable estimate",
        "estimate_basis": "none",
        "rough_search_hint_count": 0,
        "rough_estimate_warning": "",
        "confidence_label": "",
        "confidence_score": None,
        "last_updated": None,
        "comp_count_total": 0,
        "sold_comp_count": 0,
        "active_listing_count": 0,
        "guide_source_count": 0,
        "search_hint_count": 0,
        "estimated_psa9_value_low": None,
        "estimated_psa9_value_mid": None,
        "estimated_psa9_value_high": None,
        "estimated_psa10_value_low": None,
        "estimated_psa10_value_mid": None,
        "estimated_psa10_value_high": None,
        "pricing_summary": "",
        "pricing_explanation": "",
        "confidence_explanation": "",
        "grading_recommendation": "",
        "valuation_sources": [],
        "provider_status": provider_readiness(),
    }
    pricing.update(((card.extracted_json or {}).get("pricing_intelligence") or {}))
    pricing.setdefault("provider_status", provider_readiness())
    return render(
        request,
        "card_vault/card_detail.html",
        {
            "card": card,
            "valuation": valuation,
            "pricing": pricing,
            "valuation_runs": card.valuation_runs.prefetch_related("comps").all()[:5],
            "metadata_sections": sections,
            "external_links": external_links,
            "enrichment_modes": ENRICHMENT_MODE_CHOICES,
            "enrichments": (card.extracted_json or {}).get("ai_enrichment_runs", [])[:6],
            "front_group_image": front_group_image,
            "back_group_image": back_group_image,
            "front_image": card.front_image_crop,
            "back_image": card.back_image_crop,
        },
    )


@login_required
def run_card_ai_enrichment(request, card_id):
    if request.method != "POST":
        return redirect("card_vault:card-detail", card_id=card_id)
    card = get_object_or_404(
        CardVaultCard.objects.select_related("front_image_crop", "back_image_crop"),
        pk=card_id,
    )
    mode = request.POST.get("mode") or "full"
    if mode not in ENRICHMENT_MODES:
        mode = "full"
    model = (request.POST.get("model") or "").strip() or None
    force = request.POST.get("force") == "on"
    enrichment = run_card_enrichment(card, mode=mode, model=model, force=force)
    if enrichment["status"] == "failed":
        messages.error(request, "Card AI enrichment failed: " + "; ".join(enrichment["errors"]))
    else:
        messages.success(request, f"Card AI enrichment finished: {enrichment['mode_label']} ({enrichment['status']}).")
        if enrichment["errors"]:
            messages.warning(request, "Enrichment warnings: " + "; ".join(enrichment["errors"]))
    return redirect("card_vault:card-detail", card_id=card_id)


@login_required
def update_card_value(request, card_id):
    if request.method != "POST":
        return redirect("card_vault:card-detail", card_id=card_id)
    card = get_object_or_404(CardVaultCard, pk=card_id)
    try:
        result = update_card_pricing(card.id, force=True)
    except CardVaultValuationError as exc:
        messages.error(request, f"Card Vault value update failed: {exc}")
    except Exception as exc:
        messages.error(request, f"Card Vault value update failed unexpectedly: {type(exc).__name__}: {exc}")
    else:
        if result.skipped:
            messages.warning(request, f"Value update skipped: {result.reason}.")
        else:
            pricing = result.pricing
            value = pricing.get("estimated_value_mid") or "unknown"
            confidence = pricing.get("confidence_label", "low")
            messages.success(request, f"Pricing Intelligence v2 updated midpoint ${value} with {confidence} confidence.")
            if pricing.get("provider_warnings"):
                messages.warning(request, "Provider warnings: " + "; ".join(pricing["provider_warnings"][:5]))
    return redirect("card_vault:card-detail", card_id=card_id)


@login_required
def update_session_values(request, session_id):
    if request.method != "POST":
        return redirect("card_vault:intake-review", session_id=session_id)
    session = get_object_or_404(CardVaultIntakeSession, pk=session_id)
    cards = session.cards.exclude(review_status=CardVaultCard.ReviewStatus.IGNORED).order_by("slot_index")
    updated = 0
    skipped: list[str] = []
    errors: list[str] = []
    for card in cards:
        if not card.player_name:
            skipped.append(f"slot {card.slot_index}: missing player")
            continue
        try:
            result = update_card_pricing(card.id, force=True)
        except Exception as exc:
            errors.append(f"slot {card.slot_index}: {type(exc).__name__}: {exc}")
            continue
        if result.skipped:
            skipped.append(f"slot {card.slot_index}: {result.reason}")
        else:
            updated += 1

    summary = {
        **(session.extraction_summary or {}),
        "valuation_updated_count": updated,
        "valuation_skipped": skipped,
        "valuation_errors": errors,
        "valuation_updated_at": timezone.now().isoformat(),
    }
    session.extraction_summary = summary
    session.save(update_fields=["extraction_summary", "updated_at"])
    messages.success(request, f"Estimated value update finished: {updated} card(s) updated.")
    if skipped:
        messages.warning(request, "Skipped: " + "; ".join(skipped[:8]))
    if errors:
        messages.error(request, "Value update errors: " + "; ".join(errors[:5]))
    return redirect("card_vault:intake-review", session_id=session_id)


@login_required
def card_valuations(request, card_id):
    card = get_object_or_404(CardVaultCard, pk=card_id)
    runs = card.valuation_runs.prefetch_related("comps").all()
    return render(request, "card_vault/card_valuations.html", {"card": card, "runs": runs})


@login_required
def pricing_dashboard(request):
    snapshots = _latest_price_snapshots()
    collection = snapshots.aggregate(
        low=Sum("estimated_value_low"),
        mid=Sum("estimated_value_mid"),
        high=Sum("estimated_value_high"),
    )
    missing_value = CardVaultCard.objects.filter(estimated_raw_value__isnull=True).exclude(
        review_status=CardVaultCard.ReviewStatus.IGNORED
    ).count()
    stale_cutoff = timezone.now() - timedelta(days=30)
    stale_value = CardVaultCard.objects.filter(price_snapshots__created_at__lt=stale_cutoff).distinct().count()
    top_cards = CardVaultCard.objects.filter(estimated_raw_value__isnull=False).order_by("-estimated_raw_value")[:10]
    grading_cards = CardVaultValuationRun.objects.filter(grading_recommendation__icontains="Grade review").select_related("card")[:25]
    low_confidence_runs = CardVaultValuationRun.objects.filter(confidence_label="low").select_related("card")[:25]
    return render(
        request,
        "card_vault/pricing_dashboard.html",
        {
            "collection": collection,
            "missing_value": missing_value,
            "stale_value": stale_value,
            "top_cards": top_cards,
            "grading_cards": grading_cards,
            "low_confidence_runs": low_confidence_runs,
            "provider_status": provider_readiness(),
        },
    )


@login_required
def run_ai_extraction_from_review(request, session_id):
    if request.method != "POST":
        return redirect("card_vault:intake-review", session_id=session_id)
    session = get_object_or_404(CardVaultIntakeSession, pk=session_id)
    if _wants_json(request):
        if session.extraction_status in {"queued", "running"} and not _is_extraction_stale(session):
            return JsonResponse(_session_status_payload(session))
        session.extraction_status = "queued"
        session.extraction_summary = {
            **(session.extraction_summary or {}),
            "queued_at": timezone.now().isoformat(),
            "progress_message": "Queued AI extraction.",
            "error": "",
        }
        session.save(update_fields=["extraction_status", "extraction_summary", "updated_at"])
        Thread(
            target=_run_ai_extraction_background,
            args=(str(session.pk),),
            daemon=True,
        ).start()
        return JsonResponse(_session_status_payload(session), status=202)

    try:
        result = run_extraction_for_session(session, force=False)
    except MissingOpenAIKey as exc:
        messages.error(request, str(exc))
    except CardVaultExtractionError as exc:
        messages.error(request, f"Card Vault AI extraction failed: {exc}")
    except Exception as exc:
        messages.error(request, f"Card Vault AI extraction failed unexpectedly: {type(exc).__name__}: {exc}")
    else:
        messages.success(
            request,
            (
                "AI extraction finished: "
                f"{result.updated_count} card(s) updated, "
                f"{result.skipped_approved_count} approved card(s) skipped."
            ),
        )
        if result.errors:
            messages.warning(request, "Extraction warnings: " + "; ".join(result.errors))
    return redirect("card_vault:intake-review", session_id=session_id)


@login_required
def ai_extraction_status(request, session_id):
    session = get_object_or_404(CardVaultIntakeSession, pk=session_id)
    return JsonResponse(_session_status_payload(session))


@login_required
def regenerate_crops_from_review(request, session_id):
    if request.method != "POST":
        return redirect("card_vault:intake-review", session_id=session_id)
    session = get_object_or_404(CardVaultIntakeSession, pk=session_id)
    errors: list[str] = []
    crop_count = create_best_crops_for_session(
        session,
        replace=True,
        include_approved=False,
        errors=errors,
    )
    summary = {
        **(session.extraction_summary or {}),
        "crop_count": crop_count,
        "crop_regenerated_at": timezone.now().isoformat(),
        "crop_regeneration_errors": errors,
    }
    session.extraction_summary = summary
    session.save(update_fields=["extraction_summary", "updated_at"])
    messages.success(request, f"Crop regeneration finished: {crop_count} crop image(s) replaced.")
    if errors:
        messages.warning(request, "Crop warnings: " + "; ".join(errors))
    return redirect("card_vault:intake-review", session_id=session_id)


@login_required
@transaction.atomic
def update_card_from_review(request, session_id, card_id):
    if request.method != "POST":
        return redirect("card_vault:intake-review", session_id=session_id)
    card = get_object_or_404(CardVaultCard, pk=card_id, session_id=session_id)
    action = request.POST.get("action", "save")
    _apply_card_form(card, request.POST)

    if action == "approve":
        card.review_status = CardVaultCard.ReviewStatus.APPROVED
        card.is_draft = False
        card.approved_by = request.user
        card.approved_at = timezone.now()
    elif action == "needs_review":
        card.review_status = CardVaultCard.ReviewStatus.NEEDS_REVIEW
        card.is_draft = True
        card.approved_by = None
        card.approved_at = None
    elif action == "ignored":
        card.review_status = CardVaultCard.ReviewStatus.IGNORED
        card.is_draft = False
        card.approved_by = None
        card.approved_at = None

    card.extracted_json = extracted_json_for_card(card)
    card.save()
    next_url = request.POST.get("next") or ""
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("card_vault:intake-review", session_id=session_id)


def _apply_card_form(card: CardVaultCard, post_data) -> None:
    text_fields = (
        "player_name",
        "team",
        "league",
        "sport",
        "year",
        "brand",
        "product",
        "set_name",
        "card_number",
        "insert_name",
        "parallel_name",
        "serial_number",
        "serial_total",
        "storage_recommendation",
    )
    bool_fields = ("rookie_status", "autograph_detected", "relic_detected", "patch_detected")
    for field in text_fields:
        setattr(card, field, (post_data.get(field) or "").strip())
    for field in bool_fields:
        setattr(card, field, post_data.get(field) == "on")

    raw_value = (post_data.get("estimated_raw_value") or "").strip()
    if raw_value:
        try:
            card.estimated_raw_value = Decimal(raw_value)
        except InvalidOperation:
            card.estimated_raw_value = None
    else:
        card.estimated_raw_value = None

    raw_confidence = (post_data.get("confidence") or "").strip()
    try:
        confidence = float(raw_confidence) if raw_confidence else 0
    except ValueError:
        confidence = 0
    card.confidence = max(0, min(1, confidence))


def _wants_json(request) -> bool:
    accept = request.headers.get("Accept", "")
    requested_with = request.headers.get("X-Requested-With", "")
    return "application/json" in accept or requested_with == "XMLHttpRequest"


def _run_ai_extraction_background(session_id: str) -> None:
    close_old_connections()
    try:
        session = CardVaultIntakeSession.objects.get(pk=session_id)
        run_extraction_for_session(session, force=False)
    except Exception as exc:
        try:
            session = CardVaultIntakeSession.objects.get(pk=session_id)
            session.extraction_status = "failed"
            session.extraction_summary = {
                **(session.extraction_summary or {}),
                "failed_at": timezone.now().isoformat(),
                "error": f"{type(exc).__name__}: {exc}",
                "progress_message": "AI extraction failed.",
            }
            session.save(update_fields=["extraction_status", "extraction_summary", "updated_at"])
        finally:
            close_old_connections()
    else:
        close_old_connections()


def _session_status_payload(session: CardVaultIntakeSession) -> dict:
    summary = session.extraction_summary or {}
    return {
        "session_id": str(session.pk),
        "review_status": session.review_status,
        "extraction_status": session.extraction_status,
        "progress_message": summary.get("progress_message") or _progress_message(session.extraction_status),
        "updated_count": summary.get("updated_count", 0),
        "skipped_approved_count": summary.get("skipped_approved_count", 0),
        "returned_card_count": summary.get("returned_card_count"),
        "crop_count": summary.get("crop_count"),
        "errors": summary.get("errors") or summary.get("crop_regeneration_errors") or [],
        "error": summary.get("error", ""),
        "started_at": summary.get("started_at"),
        "queued_at": summary.get("queued_at"),
        "completed_at": summary.get("completed_at"),
        "failed_at": summary.get("failed_at"),
        "is_stale": _is_extraction_stale(session),
        "needs_reload": session.extraction_status in {"completed", "partial", "failed"},
    }


def _progress_message(status: str) -> str:
    return {
        "not_started": "AI extraction has not started.",
        "queued": "Queued AI extraction.",
        "running": "Reading front/back images with OpenAI Vision.",
        "completed": "AI extraction completed.",
        "partial": "AI extraction completed with warnings.",
        "failed": "AI extraction failed.",
    }.get(status, status)


def _is_extraction_stale(session: CardVaultIntakeSession) -> bool:
    if session.extraction_status not in {"queued", "running"}:
        return False
    summary = session.extraction_summary or {}
    raw_started = summary.get("started_at") or summary.get("queued_at")
    if not raw_started:
        return session.updated_at < timezone.now() - AI_EXTRACTION_STALE_AFTER
    try:
        started = timezone.datetime.fromisoformat(str(raw_started))
    except ValueError:
        return session.updated_at < timezone.now() - AI_EXTRACTION_STALE_AFTER
    if timezone.is_naive(started):
        started = timezone.make_aware(started, timezone.get_current_timezone())
    return started < timezone.now() - AI_EXTRACTION_STALE_AFTER


def _valuation_run_payload(run: CardVaultValuationRun | None) -> dict:
    if run is None:
        return {}
    return {
        "id": run.id,
        "card_id": run.card_id,
        "status": run.status,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "query_used": run.query_used,
        "normalized_card_key": run.normalized_card_key,
        "estimated_value_low": str(run.estimated_value_low) if run.estimated_value_low is not None else None,
        "estimated_value_mid": str(run.estimated_value_mid) if run.estimated_value_mid is not None else None,
        "estimated_value_high": str(run.estimated_value_high) if run.estimated_value_high is not None else None,
        "value_confidence": run.value_confidence,
        "confidence_label": run.confidence_label,
        "comp_count_total": run.comp_count_total,
        "sold_comp_count": run.sold_comp_count,
        "active_listing_count": run.active_listing_count,
        "guide_source_count": run.guide_source_count,
        "scarcity_source_count": run.scarcity_source_count,
        "pricing_summary": run.pricing_summary,
        "pricing_explanation": run.pricing_explanation,
        "grading_recommendation": run.grading_recommendation,
        "error_message": run.error_message,
        "comps": [
            {
                "id": comp.id,
                "provider": comp.provider,
                "source_type": comp.source_type,
                "title": comp.title,
                "url": comp.url,
                "price": str(comp.price) if comp.price is not None else None,
                "currency": comp.currency,
                "sale_date": comp.sale_date,
                "listing_status": comp.listing_status,
                "grade": comp.grade,
                "raw_or_graded": comp.raw_or_graded,
                "card_match_score": comp.card_match_score,
                "excluded": comp.excluded,
                "exclusion_reason": comp.exclusion_reason,
            }
            for comp in run.comps.all()
        ],
    }
