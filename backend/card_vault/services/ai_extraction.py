from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import Any

import requests
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from card_vault.models import CardVaultCard, CardVaultImage, CardVaultIntakeSession
from card_vault.serializers import extracted_json_for_card


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-4.1-mini"
EXPECTED_CARD_COUNT = 10

CARD_JSON_FIELDS = (
    "slot_index",
    "player_name",
    "team",
    "league",
    "sport",
    "year",
    "brand",
    "product",
    "set_name",
    "card_number",
    "rookie_status",
    "insert_name",
    "parallel_name",
    "serial_number",
    "serial_total",
    "autograph_detected",
    "relic_detected",
    "patch_detected",
    "estimated_raw_value",
    "storage_recommendation",
    "confidence",
    "review_status",
)


class CardVaultExtractionError(Exception):
    pass


class MissingOpenAIKey(CardVaultExtractionError):
    pass


@dataclass
class ExtractionResult:
    session: CardVaultIntakeSession
    extracted_cards: list[dict[str, Any]]
    updated_count: int
    skipped_approved_count: int
    errors: list[str]
    crop_count: int = 0
    dry_run: bool = False


def extract_cards_from_group_images(
    front_group_image: CardVaultImage,
    back_group_image: CardVaultImage,
    *,
    api_key: str | None = None,
    model: str | None = None,
    timeout: int = 120,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    key = api_key or os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise MissingOpenAIKey("OPENAI_API_KEY is not set; Card Vault AI extraction cannot run.")

    prompt = _prompt()
    payload = {
        "model": model or os.environ.get("CARD_VAULT_OPENAI_MODEL", DEFAULT_MODEL),
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": _image_to_data_url(front_group_image)},
                    {"type": "input_image", "image_url": _image_to_data_url(back_group_image)},
                ],
            }
        ],
        "temperature": 0,
    }
    response = requests.post(
        OPENAI_RESPONSES_URL,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    raw_response = response.json()
    text = _response_text(raw_response)
    return parse_ai_card_array(text), raw_response


def run_extraction_for_session(
    session: CardVaultIntakeSession,
    *,
    force: bool = False,
    dry_run: bool = False,
    api_key: str | None = None,
    model: str | None = None,
) -> ExtractionResult:
    front_image = session.images.filter(role=CardVaultImage.ImageRole.FRONT_GROUP_ORIGINAL).first()
    back_image = session.images.filter(role=CardVaultImage.ImageRole.BACK_GROUP_ORIGINAL).first()
    if not front_image or not back_image:
        raise CardVaultExtractionError("Both front and back group images are required before extraction.")

    if not dry_run:
        session.extraction_status = "running"
        session.extraction_summary = {
            **(session.extraction_summary or {}),
            "started_at": timezone.now().isoformat(),
            "force": force,
            "dry_run": False,
            "progress_message": "Reading front/back group images with OpenAI Vision.",
            "error": "",
        }
        session.save(update_fields=["extraction_status", "extraction_summary", "updated_at"])

    try:
        extracted_cards, raw_response = extract_cards_from_group_images(
            front_image,
            back_image,
            api_key=api_key,
            model=model,
        )
    except MissingOpenAIKey as exc:
        if not dry_run:
            _mark_failed(session, str(exc), error_type="missing_openai_key")
        raise
    except Exception as exc:
        if not dry_run:
            _mark_failed(session, str(exc), error_type=type(exc).__name__)
        raise

    with transaction.atomic():
        if dry_run:
            updated_count = _count_updatable_cards(session, extracted_cards, force=force)
            skipped_approved_count = _count_skipped_approved_cards(session, extracted_cards, force=force)
            return ExtractionResult(
                session=session,
                extracted_cards=extracted_cards,
                updated_count=updated_count,
                skipped_approved_count=skipped_approved_count,
                errors=[],
                crop_count=0,
                dry_run=True,
            )

        session = CardVaultIntakeSession.objects.select_for_update().get(pk=session.pk)
        updated_count = 0
        skipped_approved_count = 0
        errors: list[str] = []
        cards_by_slot = {card.slot_index: card for card in session.cards.select_for_update()}
        crop_count = create_grid_crops_for_session(session, replace=force, errors=errors)
        cards_by_slot = {
            card.slot_index: card
            for card in session.cards.select_for_update()
        }

        for extracted in extracted_cards[:EXPECTED_CARD_COUNT]:
            slot_index = extracted.get("slot_index")
            if not isinstance(slot_index, int):
                errors.append(f"Skipping card without integer slot_index: {slot_index!r}")
                continue
            card = cards_by_slot.get(slot_index)
            if not card:
                errors.append(f"No draft card row exists for slot {slot_index}.")
                continue
            if card.review_status == CardVaultCard.ReviewStatus.APPROVED and not force:
                skipped_approved_count += 1
                continue
            if _card_has_existing_metadata(card) and not force:
                errors.append(f"Slot {slot_index} already has metadata; skipped to avoid overwriting review edits.")
                continue
            apply_extracted_card(card, extracted)
            updated_count += 1

        status = "completed" if len(extracted_cards) == EXPECTED_CARD_COUNT and not errors else "partial"
        session.ai_raw_response = raw_response
        session.extraction_status = status
        session.review_status = CardVaultIntakeSession.ReviewStatus.NEEDS_REVIEW
        session.extraction_summary = {
            **(session.extraction_summary or {}),
            "completed_at": timezone.now().isoformat(),
            "expected_card_count": EXPECTED_CARD_COUNT,
            "returned_card_count": len(extracted_cards),
            "updated_count": updated_count,
            "skipped_approved_count": skipped_approved_count,
            "crop_count": crop_count,
            "errors": errors,
            "progress_message": "AI extraction completed with warnings." if errors else "AI extraction completed.",
        }
        session.save(update_fields=["ai_raw_response", "extraction_status", "review_status", "extraction_summary", "updated_at"])
    return ExtractionResult(
        session=session,
        extracted_cards=extracted_cards,
        updated_count=updated_count,
        skipped_approved_count=skipped_approved_count,
        errors=errors,
        crop_count=crop_count,
    )


def apply_extracted_card(card: CardVaultCard, extracted: dict[str, Any]) -> None:
    card.player_name = _text(extracted.get("player_name"))
    card.team = _text(extracted.get("team"))
    card.league = _text(extracted.get("league"))
    card.sport = _text(extracted.get("sport")) or "basketball"
    card.year = _text(extracted.get("year"))
    card.brand = _text(extracted.get("brand"))
    card.product = _text(extracted.get("product"))
    card.set_name = _text(extracted.get("set_name"))
    card.card_number = _text(extracted.get("card_number"))
    card.rookie_status = bool(extracted.get("rookie_status"))
    card.insert_name = _text(extracted.get("insert_name"))
    card.parallel_name = _text(extracted.get("parallel_name"))
    card.serial_number = _text(extracted.get("serial_number"))
    card.serial_total = _text(extracted.get("serial_total"))
    card.autograph_detected = bool(extracted.get("autograph_detected"))
    card.relic_detected = bool(extracted.get("relic_detected"))
    card.patch_detected = bool(extracted.get("patch_detected"))
    card.estimated_raw_value = _decimal_or_none(extracted.get("estimated_raw_value"))
    card.storage_recommendation = _text(extracted.get("storage_recommendation"))
    card.confidence = _confidence(extracted.get("confidence"))
    card.review_status = CardVaultCard.ReviewStatus.NEEDS_REVIEW
    card.is_draft = True
    card.extracted_json = _normalized_card_json(card, extracted)
    card.save()


def _card_has_existing_metadata(card: CardVaultCard) -> bool:
    text_fields = (
        "player_name",
        "team",
        "league",
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
    if any((getattr(card, field) or "").strip() for field in text_fields):
        return True
    return bool(card.confidence or card.estimated_raw_value)


def parse_ai_card_array(text: str) -> list[dict[str, Any]]:
    raw = (text or "").strip()
    if not raw:
        raise CardVaultExtractionError("OpenAI returned an empty extraction response.")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", raw)
        if not match:
            raise CardVaultExtractionError("OpenAI response did not contain a JSON array.")
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise CardVaultExtractionError("OpenAI response contained malformed JSON.") from exc
    if not isinstance(parsed, list):
        raise CardVaultExtractionError("OpenAI response must be a JSON array of card objects.")
    normalized = []
    for item in parsed:
        if isinstance(item, dict):
            normalized.append(normalize_extracted_card(item))
    return normalized


def create_grid_crops_for_session(
    session: CardVaultIntakeSession,
    *,
    replace: bool = False,
    include_approved: bool = False,
    errors: list[str] | None = None,
) -> int:
    return create_best_crops_for_session(
        session,
        replace=replace,
        include_approved=include_approved,
        errors=errors,
    )


def create_best_crops_for_session(
    session: CardVaultIntakeSession,
    *,
    replace: bool = False,
    include_approved: bool = False,
    errors: list[str] | None = None,
) -> int:
    front_group = session.images.filter(role=CardVaultImage.ImageRole.FRONT_GROUP_ORIGINAL).first()
    back_group = session.images.filter(role=CardVaultImage.ImageRole.BACK_GROUP_ORIGINAL).first()
    if not front_group or not back_group:
        return 0
    cards_qs = session.cards.order_by("slot_index")
    if not include_approved:
        cards_qs = cards_qs.exclude(review_status=CardVaultCard.ReviewStatus.APPROVED)
    cards = list(cards_qs)
    created = 0
    created += _create_detected_crops_for_image(
        group_image=front_group,
        cards=cards,
        crop_role=CardVaultImage.ImageRole.FRONT_CROP,
        side="front",
        replace=replace,
        errors=errors,
    )
    created += _create_detected_crops_for_image(
        group_image=back_group,
        cards=cards,
        crop_role=CardVaultImage.ImageRole.BACK_CROP,
        side="back",
        replace=replace,
        errors=errors,
    )
    return created


def _create_detected_crops_for_image(
    *,
    group_image: CardVaultImage,
    cards: list[CardVaultCard],
    crop_role: str,
    side: str,
    replace: bool,
    errors: list[str] | None,
) -> int:
    expected_slots = {card.slot_index for card in cards[:EXPECTED_CARD_COUNT]}
    if not expected_slots:
        return 0
    try:
        group_image.image.open("rb")
        image = Image.open(group_image.image).convert("RGB")
        image.load()
    except (OSError, UnidentifiedImageError) as exc:
        if errors is not None:
            errors.append(f"{side} crop generation skipped: {exc}")
        return 0
    finally:
        try:
            group_image.image.close()
        except Exception:
            pass

    boxes, method, confidence = _detect_card_boxes_with_opencv(image, expected_count=len(expected_slots))
    if len(boxes) < len(expected_slots):
        openai_boxes, openai_method, openai_confidence = _detect_card_boxes_with_openai(
            group_image,
            image_size=image.size,
            expected_count=len(expected_slots),
            side=side,
            errors=errors,
        )
        if len(openai_boxes) >= len(expected_slots):
            boxes = openai_boxes
            method = openai_method
            confidence = openai_confidence

    if len(boxes) < len(expected_slots):
        if errors is not None:
            errors.append(
                f"{side} smart crop detection found {len(boxes)} of {len(expected_slots)} cards; using layout fallback."
            )
        layout_boxes = _layout_boxes_3_4_3(image.width, image.height, side=side)
        if len(layout_boxes) >= len(expected_slots):
            return _save_crop_images(
                image=image,
                group_image=group_image,
                cards=cards,
                crop_role=crop_role,
                side=side,
                replace=replace,
                boxes_by_slot=layout_boxes,
                detection_confidence=0.72,
                metadata_extra={"crop_method": "photo_layout_3_4_3"},
            )
        return _create_grid_crops_from_image(
            image=image,
            group_image=group_image,
            cards=cards,
            crop_role=crop_role,
            side=side,
            replace=replace,
            errors=errors,
        )

    boxes_by_slot = {slot: boxes[index] for index, slot in enumerate(sorted(expected_slots))}
    return _save_crop_images(
        image=image,
        group_image=group_image,
        cards=cards,
        crop_role=crop_role,
        side=side,
        replace=replace,
        boxes_by_slot=boxes_by_slot,
        detection_confidence=confidence,
        metadata_extra={"crop_method": method},
    )


def _create_grid_crops_for_image(
    *,
    group_image: CardVaultImage,
    cards: list[CardVaultCard],
    crop_role: str,
    side: str,
    replace: bool,
    errors: list[str] | None,
) -> int:
    if not cards:
        return 0
    try:
        group_image.image.open("rb")
        image = Image.open(group_image.image)
        image.load()
    except (OSError, UnidentifiedImageError) as exc:
        if errors is not None:
            errors.append(f"{side} crop generation skipped: {exc}")
        return 0
    finally:
        try:
            group_image.image.close()
        except Exception:
            pass
    return _create_grid_crops_from_image(
        image=image,
        group_image=group_image,
        cards=cards,
        crop_role=crop_role,
        side=side,
        replace=replace,
        errors=errors,
    )


def _create_grid_crops_from_image(
    *,
    image: Image.Image,
    group_image: CardVaultImage,
    cards: list[CardVaultCard],
    crop_role: str,
    side: str,
    replace: bool,
    errors: list[str] | None,
) -> int:
    width, height = image.size
    rows, cols = _grid_for_image(width, height)
    slot_boxes = _slot_boxes(width, height, rows, cols)
    return _save_crop_images(
        image=image,
        group_image=group_image,
        cards=cards,
        crop_role=crop_role,
        side=side,
        replace=replace,
        boxes_by_slot=slot_boxes,
        detection_confidence=0.5,
        metadata_extra={"crop_method": "simple_grid", "grid_rows": rows, "grid_cols": cols},
    )


def _save_crop_images(
    *,
    image: Image.Image,
    group_image: CardVaultImage,
    cards: list[CardVaultCard],
    crop_role: str,
    side: str,
    replace: bool,
    boxes_by_slot: dict[int, dict[str, int]],
    detection_confidence: float,
    metadata_extra: dict[str, Any],
) -> int:
    created = 0
    for card in cards[:EXPECTED_CARD_COUNT]:
        if card.slot_index not in boxes_by_slot:
            continue
        existing = CardVaultImage.objects.filter(
            session=group_image.session,
            card=card,
            role=crop_role,
            slot_index=card.slot_index,
        ).first()
        if existing and not replace:
            if side == "front" and not card.front_image_crop_id:
                card.front_image_crop = existing
                card.save(update_fields=["front_image_crop", "updated_at"])
            if side == "back" and not card.back_image_crop_id:
                card.back_image_crop = existing
                card.save(update_fields=["back_image_crop", "updated_at"])
            continue
        if existing and replace:
            existing.delete()

        box = boxes_by_slot[card.slot_index]
        crop = image.crop((box["x"], box["y"], box["x"] + box["width"], box["y"] + box["height"]))
        buffer = BytesIO()
        crop.save(buffer, format="JPEG", quality=90)
        base_name = Path(group_image.original_filename or group_image.image.name or f"{side}.jpg").stem
        crop_filename = f"{base_name}-slot-{card.slot_index}-{side}.jpg"
        output = ContentFile(buffer.getvalue(), name=crop_filename)
        crop_image = CardVaultImage.objects.create(
            session=group_image.session,
            card=card,
            role=crop_role,
            image=output,
            original_filename=crop_filename,
            slot_index=card.slot_index,
            crop_box=box,
            detection_confidence=detection_confidence,
            metadata={
                "source_image_id": group_image.id,
                **metadata_extra,
            },
        )
        if side == "front":
            card.front_image_crop = crop_image
            card.save(update_fields=["front_image_crop", "updated_at"])
        else:
            card.back_image_crop = crop_image
            card.save(update_fields=["back_image_crop", "updated_at"])
        created += 1
    return created


def _detect_card_boxes_with_opencv(image: Image.Image, *, expected_count: int) -> tuple[list[dict[str, int]], str, float]:
    try:
        import cv2
        import numpy as np
    except Exception:
        return [], "opencv_unavailable", 0.0

    rgb = np.array(image)
    height, width = rgb.shape[:2]
    scale = min(1.0, 1800.0 / max(width, height))
    small = cv2.resize(rgb, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else rgb
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)

    # Cards are materially lighter than the table, but this also tolerates colorful card art.
    threshold = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        71,
        -4,
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (11, 11))
    closed = cv2.morphologyEx(threshold, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    image_area = small.shape[0] * small.shape[1]
    candidates: list[dict[str, float]] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < image_area * 0.015 or area > image_area * 0.14:
            continue
        rect = cv2.minAreaRect(contour)
        (cx, cy), (rw, rh), _angle = rect
        if rw <= 0 or rh <= 0:
            continue
        short = min(rw, rh)
        long = max(rw, rh)
        aspect = long / short
        if aspect < 1.18 or aspect > 1.95:
            continue
        x, y, bw, bh = cv2.boundingRect(contour)
        fill_ratio = area / float(max(1, bw * bh))
        if fill_ratio < 0.35:
            continue
        pad_x = bw * 0.055
        pad_y = bh * 0.055
        candidates.append(
            {
                "x": max(0, x - pad_x),
                "y": max(0, y - pad_y),
                "width": min(small.shape[1], x + bw + pad_x) - max(0, x - pad_x),
                "height": min(small.shape[0], y + bh + pad_y) - max(0, y - pad_y),
                "cx": cx,
                "cy": cy,
                "area": area,
            }
        )

    candidates = _dedupe_detected_boxes(candidates)
    candidates = sorted(candidates, key=lambda item: item["area"], reverse=True)[:expected_count]
    if len(candidates) < expected_count:
        return [], "opencv_contour_detection_incomplete", 0.0

    ordered = _order_detected_boxes(candidates)
    boxes: list[dict[str, int]] = []
    inv_scale = 1.0 / scale
    for item in ordered[:expected_count]:
        x = int(round(item["x"] * inv_scale))
        y = int(round(item["y"] * inv_scale))
        bw = int(round(item["width"] * inv_scale))
        bh = int(round(item["height"] * inv_scale))
        x = max(0, min(width - 1, x))
        y = max(0, min(height - 1, y))
        bw = max(1, min(width - x, bw))
        bh = max(1, min(height - y, bh))
        boxes.append({"x": x, "y": y, "width": bw, "height": bh})
    return boxes, "opencv_contour_detection", 0.82


def _detect_card_boxes_with_openai(
    group_image: CardVaultImage,
    *,
    image_size: tuple[int, int],
    expected_count: int,
    side: str,
    errors: list[str] | None,
) -> tuple[list[dict[str, int]], str, float]:
    if os.environ.get("CARD_VAULT_USE_OPENAI_CROP_BOXES", "").strip().lower() not in {"1", "true", "yes"}:
        return [], "openai_crop_boxes_disabled", 0.0
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return [], "openai_crop_boxes_unavailable", 0.0
    prompt = f"""
Return strict JSON only. Analyze this {side} group photo of trading cards.
Find exactly {expected_count} visible card rectangles, ordered by visual slot position:
top-to-bottom, left-to-right within each row.

Return a JSON array of objects with:
slot_index: integer 1-{expected_count}
x: left coordinate as a number from 0 to 1
y: top coordinate as a number from 0 to 1
width: box width as a number from 0 to 1
height: box height as a number from 0 to 1
confidence: number from 0 to 1

Include the whole physical card, including borders, but exclude table background when possible.
Do not include shoes, hands, table glare, or partial non-card objects.
If unsure, still return the best rectangle for that slot with lower confidence.
""".strip()
    try:
        response = requests.post(
            OPENAI_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": os.environ.get("CARD_VAULT_CROP_OPENAI_MODEL")
                or os.environ.get("CARD_VAULT_OPENAI_MODEL", DEFAULT_MODEL),
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            {"type": "input_image", "image_url": _image_to_data_url(group_image)},
                        ],
                    }
                ],
                "temperature": 0,
            },
            timeout=120,
        )
        response.raise_for_status()
        raw_response = response.json()
        text = _response_text(raw_response)
    except Exception as exc:
        if errors is not None:
            errors.append(f"{side} OpenAI crop-box detection skipped: {type(exc).__name__}: {exc}")
        return [], "openai_crop_boxes_failed", 0.0

    try:
        parsed = _parse_crop_box_array(text)
    except CardVaultExtractionError as exc:
        if errors is not None:
            errors.append(f"{side} OpenAI crop-box response ignored: {exc}")
        return [], "openai_crop_boxes_malformed", 0.0

    width, height = image_size
    boxes: list[dict[str, int]] = []
    confidences: list[float] = []
    for item in parsed[:expected_count]:
        box = _relative_box_to_pixels(item, width=width, height=height)
        if box:
            boxes.append(box)
            confidences.append(_confidence(item.get("confidence")))
    if len(boxes) < expected_count:
        return [], "openai_crop_boxes_incomplete", 0.0
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.76
    return boxes, "openai_vision_crop_boxes", max(0.76, min(0.96, avg_confidence))


def _parse_crop_box_array(text: str) -> list[dict[str, Any]]:
    raw = (text or "").strip()
    if not raw:
        raise CardVaultExtractionError("empty crop-box response")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", raw)
        if not match:
            raise CardVaultExtractionError("no JSON array in crop-box response")
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, list):
        raise CardVaultExtractionError("crop-box response must be a JSON array")
    return [item for item in parsed if isinstance(item, dict)]


def _relative_box_to_pixels(item: dict[str, Any], *, width: int, height: int) -> dict[str, int] | None:
    try:
        x = float(item["x"])
        y = float(item["y"])
        box_width = float(item["width"])
        box_height = float(item["height"])
    except (KeyError, TypeError, ValueError):
        return None
    if box_width <= 0 or box_height <= 0:
        return None
    x = max(0.0, min(0.98, x))
    y = max(0.0, min(0.98, y))
    box_width = max(0.01, min(1.0 - x, box_width))
    box_height = max(0.01, min(1.0 - y, box_height))
    px = int(round(x * width))
    py = int(round(y * height))
    pw = int(round(box_width * width))
    ph = int(round(box_height * height))
    px = max(0, min(width - 1, px))
    py = max(0, min(height - 1, py))
    pw = max(1, min(width - px, pw))
    ph = max(1, min(height - py, ph))
    aspect = max(pw, ph) / max(1, min(pw, ph))
    if aspect < 1.05 or aspect > 2.25:
        return None
    return {"x": px, "y": py, "width": pw, "height": ph}


def _dedupe_detected_boxes(candidates: list[dict[str, float]]) -> list[dict[str, float]]:
    kept: list[dict[str, float]] = []
    for item in sorted(candidates, key=lambda box: box["area"], reverse=True):
        duplicate = False
        for existing in kept:
            distance = ((item["cx"] - existing["cx"]) ** 2 + (item["cy"] - existing["cy"]) ** 2) ** 0.5
            if distance < min(item["width"], item["height"], existing["width"], existing["height"]) * 0.45:
                duplicate = True
                break
        if not duplicate:
            kept.append(item)
    return kept


def _order_detected_boxes(candidates: list[dict[str, float]]) -> list[dict[str, float]]:
    if not candidates:
        return []
    ordered_by_y = sorted(candidates, key=lambda item: item["cy"])
    median_h = sorted(item["height"] for item in ordered_by_y)[len(ordered_by_y) // 2]
    row_threshold = max(1.0, median_h * 0.55)
    rows: list[list[dict[str, float]]] = []
    for item in ordered_by_y:
        for row in rows:
            row_center = sum(entry["cy"] for entry in row) / len(row)
            if abs(item["cy"] - row_center) <= row_threshold:
                row.append(item)
                break
        else:
            rows.append([item])
    rows.sort(key=lambda row: sum(entry["cy"] for entry in row) / len(row))
    return [item for row in rows for item in sorted(row, key=lambda entry: entry["cx"])]


def _layout_boxes_3_4_3(width: int, height: int, *, side: str) -> dict[int, dict[str, int]]:
    if width <= height:
        if side == "front":
            ratios = {
                1: (0.068, 0.188, 0.281, 0.410),
                2: (0.278, 0.174, 0.491, 0.392),
                3: (0.531, 0.184, 0.740, 0.402),
                4: (0.045, 0.414, 0.264, 0.632),
                5: (0.288, 0.417, 0.503, 0.626),
                6: (0.535, 0.413, 0.752, 0.625),
                7: (0.790, 0.417, 0.998, 0.621),
                8: (0.069, 0.641, 0.299, 0.879),
                9: (0.333, 0.643, 0.550, 0.883),
                10: (0.649, 0.651, 0.870, 0.889),
            }
        else:
            ratios = {
                1: (0.064, 0.130, 0.302, 0.375),
                2: (0.312, 0.112, 0.531, 0.355),
                3: (0.547, 0.116, 0.783, 0.349),
                4: (0.064, 0.382, 0.307, 0.626),
                5: (0.312, 0.372, 0.543, 0.613),
                6: (0.561, 0.361, 0.780, 0.602),
                7: (0.795, 0.368, 0.998, 0.590),
                8: (0.064, 0.608, 0.295, 0.863),
                9: (0.332, 0.620, 0.562, 0.871),
                10: (0.622, 0.621, 0.851, 0.863),
            }
    else:
        return {}
    return {
        slot: {
            "x": int(round(left * width)),
            "y": int(round(top * height)),
            "width": max(1, int(round((right - left) * width))),
            "height": max(1, int(round((bottom - top) * height))),
        }
        for slot, (left, top, right, bottom) in ratios.items()
    }


def _grid_for_image(width: int, height: int) -> tuple[int, int]:
    return (2, 5) if width >= height else (5, 2)


def _slot_boxes(width: int, height: int, rows: int, cols: int) -> dict[int, dict[str, int]]:
    margin_x = int(width * 0.03)
    margin_y = int(height * 0.03)
    gap_x = int(width * 0.015)
    gap_y = int(height * 0.015)
    cell_w = max(1, int((width - (2 * margin_x) - ((cols - 1) * gap_x)) / cols))
    cell_h = max(1, int((height - (2 * margin_y) - ((rows - 1) * gap_y)) / rows))
    boxes: dict[int, dict[str, int]] = {}
    slot = 1
    for row in range(rows):
        for col in range(cols):
            if slot > EXPECTED_CARD_COUNT:
                break
            x = margin_x + col * (cell_w + gap_x)
            y = margin_y + row * (cell_h + gap_y)
            boxes[slot] = {"x": x, "y": y, "width": cell_w, "height": cell_h}
            slot += 1
    return boxes


def _count_updatable_cards(
    session: CardVaultIntakeSession,
    extracted_cards: list[dict[str, Any]],
    *,
    force: bool,
) -> int:
    slots = {card.get("slot_index") for card in extracted_cards if isinstance(card.get("slot_index"), int)}
    qs = session.cards.filter(slot_index__in=slots)
    if not force:
        qs = qs.exclude(review_status=CardVaultCard.ReviewStatus.APPROVED)
    return qs.count()


def _count_skipped_approved_cards(
    session: CardVaultIntakeSession,
    extracted_cards: list[dict[str, Any]],
    *,
    force: bool,
) -> int:
    if force:
        return 0
    slots = {card.get("slot_index") for card in extracted_cards if isinstance(card.get("slot_index"), int)}
    return session.cards.filter(
        slot_index__in=slots,
        review_status=CardVaultCard.ReviewStatus.APPROVED,
    ).count()


def normalize_extracted_card(item: dict[str, Any]) -> dict[str, Any]:
    normalized = {field: item.get(field) for field in CARD_JSON_FIELDS}
    try:
        normalized["slot_index"] = int(normalized["slot_index"])
    except (TypeError, ValueError):
        normalized["slot_index"] = None
    normalized["player_name"] = _text(normalized.get("player_name"))
    normalized["team"] = _text(normalized.get("team"))
    normalized["league"] = _text(normalized.get("league"))
    normalized["sport"] = _text(normalized.get("sport")) or "basketball"
    normalized["year"] = _text(normalized.get("year"))
    normalized["brand"] = _text(normalized.get("brand"))
    normalized["product"] = _text(normalized.get("product"))
    normalized["set_name"] = _text(normalized.get("set_name"))
    normalized["card_number"] = _text(normalized.get("card_number"))
    normalized["rookie_status"] = bool(normalized.get("rookie_status"))
    normalized["insert_name"] = _text(normalized.get("insert_name"))
    normalized["parallel_name"] = _text(normalized.get("parallel_name"))
    normalized["serial_number"] = _text(normalized.get("serial_number"))
    normalized["serial_total"] = _text(normalized.get("serial_total"))
    normalized["autograph_detected"] = bool(normalized.get("autograph_detected"))
    normalized["relic_detected"] = bool(normalized.get("relic_detected"))
    normalized["patch_detected"] = bool(normalized.get("patch_detected"))
    raw_value = _decimal_or_none(normalized.get("estimated_raw_value"))
    normalized["estimated_raw_value"] = str(raw_value) if raw_value is not None else None
    normalized["storage_recommendation"] = _text(normalized.get("storage_recommendation"))
    normalized["confidence"] = _confidence(normalized.get("confidence"))
    normalized["review_status"] = CardVaultCard.ReviewStatus.NEEDS_REVIEW
    return normalized


def _normalized_card_json(card: CardVaultCard, extracted: dict[str, Any]) -> dict[str, Any]:
    merged = extracted_json_for_card(card)
    merged["review_status"] = CardVaultCard.ReviewStatus.NEEDS_REVIEW
    for field in CARD_JSON_FIELDS:
        if field in extracted and field not in ("review_status", "estimated_raw_value"):
            merged[field] = normalize_extracted_card({**merged, **extracted}).get(field)
    if card.estimated_raw_value is not None:
        merged["estimated_raw_value"] = str(card.estimated_raw_value)
    return merged


def _mark_failed(session: CardVaultIntakeSession, message: str, *, error_type: str) -> None:
    session.extraction_status = "failed"
    session.review_status = CardVaultIntakeSession.ReviewStatus.NEEDS_REVIEW
    session.extraction_summary = {
        **(session.extraction_summary or {}),
        "failed_at": timezone.now().isoformat(),
        "error_type": error_type,
        "error": message,
        "progress_message": "AI extraction failed.",
    }
    session.save(update_fields=["extraction_status", "review_status", "extraction_summary", "updated_at"])


def _image_to_data_url(image: CardVaultImage) -> str:
    image.image.open("rb")
    try:
        raw = _compressed_image_bytes(image.image)
    finally:
        image.image.close()
    mime = "image/jpeg"
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _compressed_image_bytes(file_obj, *, max_dimension: int = 1800, quality: int = 86) -> bytes:
    try:
        source = Image.open(file_obj).convert("RGB")
        source.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        source.save(buffer, format="JPEG", quality=quality, optimize=True)
        return buffer.getvalue()
    except Exception:
        try:
            file_obj.seek(0)
        except Exception:
            pass
        return file_obj.read()


def _response_text(raw_response: dict[str, Any]) -> str:
    if isinstance(raw_response.get("output_text"), str):
        return raw_response["output_text"]
    chunks: list[str] = []
    for output in raw_response.get("output", []) or []:
        for content in output.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks).strip()


def _prompt() -> str:
    return """You are extracting trading-card metadata for Gerg Card Vault.

You will receive two group photos:
1. Fronts of the same 10 cards.
2. Backs of the same 10 cards.

Identify the cards by visual position/order. Match front and back by slot position:
left-to-right within each row, then top-to-bottom. Return exactly 10 objects when visible.

Return ONLY a strict JSON array. No markdown. No prose. Each object must have:
slot_index, player_name, team, league, sport, year, brand, product, set_name,
card_number, rookie_status, insert_name, parallel_name, serial_number,
serial_total, autograph_detected, relic_detected, patch_detected,
estimated_raw_value, storage_recommendation, confidence, review_status.

Use sport "basketball" unless the card clearly says otherwise.
Use review_status "needs_review" for every object.
Use empty strings for unknown text fields, false for unknown booleans,
null for unknown estimated_raw_value, and confidence from 0 to 1.
Do not invent serial numbers, rookie status, autographs, relics, or values.
"""


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(1, confidence))
