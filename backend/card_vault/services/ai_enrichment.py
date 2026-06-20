from __future__ import annotations

import json
import os
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote_plus

import requests
from django.utils import timezone

from card_vault.models import CardVaultCard
from card_vault.serializers import extracted_json_for_card
from card_vault.services.ai_extraction import (
    DEFAULT_MODEL,
    OPENAI_RESPONSES_URL,
    MissingOpenAIKey,
    _image_to_data_url,
    _response_text,
)


ENRICHMENT_MODE_CHOICES = (
    ("visual_metadata", "Visual metadata"),
    ("market_research", "Market research"),
    ("image_match", "Internet image match"),
    ("full", "Full enrichment"),
)
ENRICHMENT_MODES = {value for value, _label in ENRICHMENT_MODE_CHOICES}

ENRICHMENT_FIELDS = (
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
    "player_full_name",
    "player_slug",
    "player_wikipedia_url",
    "player_official_profile_url",
    "league_player_profile_url",
    "team_profile_url",
    "player_position",
    "player_status",
    "hall_of_fame_status",
    "career_summary_short",
    "career_stats_summary",
    "career_stats",
    "latest_season_stats",
    "player_awards_summary",
    "card_type",
    "card_type_explanation",
    "rarity_tier",
    "rarity_explanation",
    "collector_interest_score",
    "investment_score",
    "grading_candidate_score",
    "manufacturer",
    "product_line",
    "release_year",
    "checklist_url",
    "checklist_name",
    "checklist_card_title",
    "known_parallel_family",
    "possible_parallel_matches",
    "estimated_raw_value_low",
    "estimated_raw_value_mid",
    "estimated_raw_value_high",
    "value_confidence",
    "value_last_updated",
    "valuation_sources",
    "recent_comp_summary",
    "protection_level",
    "protection_reason",
    "recommended_supply",
    "physical_location_label",
    "wikipedia_url",
    "basketball_reference_url",
    "wnba_profile_url",
    "nba_profile_url",
    "sports_reference_url",
    "tcdb_url",
    "sportscardspro_url",
    "ebay_search_url",
    "psa_pop_report_url",
)


def run_card_enrichment(
    card: CardVaultCard,
    *,
    mode: str = "full",
    model: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    model_name = model or os.environ.get("CARD_VAULT_OPENAI_MODEL", DEFAULT_MODEL)
    if mode not in ENRICHMENT_MODES:
        mode = "full"

    run = {
        "id": timezone.now().strftime("%Y%m%d%H%M%S%f"),
        "mode": mode,
        "mode_label": dict(ENRICHMENT_MODE_CHOICES).get(mode, mode),
        "model_name": model_name,
        "status": "running",
        "started_at": timezone.now().isoformat(),
        "completed_at": "",
        "changed_fields": [],
        "proposed_json": {},
        "raw_response": {},
        "external_image_candidates": [],
        "errors": [],
        "needs_human_confirmation": True,
    }

    try:
        if mode in {"visual_metadata", "full"}:
            proposed, raw_response = enrich_card_with_openai(card, mode=mode, model=model_name)
            run["proposed_json"] = proposed
            run["raw_response"] = raw_response
        if mode in {"image_match", "market_research", "full"}:
            candidates = find_external_image_candidates(card)
            run["external_image_candidates"] = candidates
            if mode == "market_research":
                run["proposed_json"].setdefault("research_notes", _research_notes(candidates))

        changed_fields = _merge_enrichment_into_card(card, run, force=force)
        run["changed_fields"] = changed_fields
        run["status"] = "completed" if not run["errors"] else "partial"
    except MissingOpenAIKey as exc:
        run["errors"].append(str(exc))
        run["status"] = "failed"
    except Exception as exc:
        run["errors"].append(f"{type(exc).__name__}: {exc}")
        run["status"] = "failed"

    run["completed_at"] = timezone.now().isoformat()
    _store_enrichment_run(card, run)
    return run


def enrich_card_with_openai(
    card: CardVaultCard,
    *,
    mode: str,
    model: str,
    timeout: int = 90,
) -> tuple[dict[str, Any], dict[str, Any]]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise MissingOpenAIKey("OPENAI_API_KEY is not set; per-card enrichment cannot run.")

    content: list[dict[str, str]] = [{"type": "input_text", "text": _enrichment_prompt(card, mode)}]
    if card.front_image_crop_id:
        content.append({"type": "input_image", "image_url": _image_to_data_url(card.front_image_crop)})
    if card.back_image_crop_id:
        content.append({"type": "input_image", "image_url": _image_to_data_url(card.back_image_crop)})

    response = requests.post(
        OPENAI_RESPONSES_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "input": [{"role": "user", "content": content}],
            "temperature": 0,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    raw = response.json()
    return _parse_object(_response_text(raw)), raw


def find_external_image_candidates(card: CardVaultCard, *, limit: int = 8) -> list[dict[str, Any]]:
    query = _card_search_query(card)
    candidates: list[dict[str, Any]] = []
    endpoint = os.environ.get("CARD_VAULT_IMAGE_SEARCH_ENDPOINT", "").strip()
    if endpoint:
        candidates.extend(_search_custom_endpoint(endpoint, query, limit=limit))
    if len(candidates) < limit:
        candidates.extend(_search_duckduckgo_links(query, limit=limit - len(candidates)))

    seen: set[str] = set()
    unique = []
    for candidate in candidates:
        url = candidate.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(candidate)
    return unique[:limit]


def _merge_enrichment_into_card(card: CardVaultCard, run: dict[str, Any], *, force: bool) -> list[str]:
    proposed = run.get("proposed_json") or {}
    changed_fields: list[str] = []
    for field in ENRICHMENT_FIELDS:
        if field not in proposed:
            continue
        value = proposed.get(field)
        if value in (None, "") and field not in {"rookie_status", "autograph_detected", "relic_detected", "patch_detected"}:
            continue
        value = _coerce_field_value(field, value)
        if value is None and field != "estimated_raw_value":
            continue
        if hasattr(card, field):
            current = getattr(card, field)
            if force or current in (None, "", 0):
                setattr(card, field, value)
                changed_fields.append(field)
        else:
            draft = card.extracted_json or {}
            current = draft.get(field)
            if force or current in (None, "", [], {}, 0):
                draft[field] = _json_safe(value)
                card.extracted_json = draft
                changed_fields.append(field)

    draft = extracted_json_for_card(card)
    for field in ENRICHMENT_FIELDS:
        if field in proposed and not hasattr(card, field):
            value = _coerce_field_value(field, proposed.get(field))
            if value is not None:
                draft[field] = _json_safe(value)
    draft["review_status"] = CardVaultCard.ReviewStatus.NEEDS_REVIEW
    draft["ai_enrichment"] = {
        "latest_run_id": run["id"],
        "latest_mode": run["mode"],
        "latest_status": run["status"],
        "changed_fields": changed_fields,
        "proposed_json": proposed,
        "external_image_candidates": run.get("external_image_candidates", []),
        "needs_human_confirmation": True,
    }
    card.extracted_json = draft
    card.review_status = CardVaultCard.ReviewStatus.NEEDS_REVIEW
    card.is_draft = True
    card.save()
    return changed_fields


def _store_enrichment_run(card: CardVaultCard, run: dict[str, Any]) -> None:
    data = card.extracted_json or extracted_json_for_card(card)
    runs = list(data.get("ai_enrichment_runs") or [])
    runs.insert(0, _json_safe(run))
    data["ai_enrichment_runs"] = runs[:12]
    data.setdefault("ai_enrichment", {})
    data["ai_enrichment"] = {
        **data["ai_enrichment"],
        "latest_run_id": run["id"],
        "latest_mode": run["mode"],
        "latest_status": run["status"],
        "changed_fields": run.get("changed_fields", []),
        "proposed_json": run.get("proposed_json", {}),
        "external_image_candidates": run.get("external_image_candidates", []),
        "needs_human_confirmation": True,
    }
    card.extracted_json = data
    card.save(update_fields=["extracted_json", "review_status", "is_draft", "updated_at"])


def _search_custom_endpoint(endpoint: str, query: str, *, limit: int) -> list[dict[str, Any]]:
    try:
        response = requests.get(endpoint, params={"q": query, "limit": limit}, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    return [
        {
            "source": item.get("source") or "custom",
            "title": item.get("title") or "",
            "url": item.get("url") or item.get("link") or "",
            "image_url": item.get("image_url") or item.get("thumbnail") or "",
            "match_type": "external_candidate",
            "confidence": float(item.get("confidence") or 0.5),
        }
        for item in items
        if isinstance(item, dict)
    ]


def _search_duckduckgo_links(query: str, *, limit: int) -> list[dict[str, Any]]:
    if not query:
        return []
    search_url = f"https://duckduckgo.com/html/?q={quote_plus(query + ' trading card front back')}"
    try:
        response = requests.get(search_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        response.raise_for_status()
    except Exception:
        return []
    links = re.findall(r'class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', response.text, flags=re.I | re.S)
    candidates = []
    for url, title in links[:limit]:
        clean_title = re.sub(r"<[^>]+>", "", title)
        candidates.append(
            {
                "source": "duckduckgo",
                "title": clean_title,
                "url": url.replace("&amp;", "&"),
                "image_url": "",
                "match_type": "search_result_candidate",
                "confidence": 0.35,
            }
        )
    return candidates


def _coerce_field_value(field: str, value: Any) -> Any:
    if field in {"estimated_raw_value", "estimated_raw_value_low", "estimated_raw_value_mid", "estimated_raw_value_high"}:
        return _decimal_or_none(value)
    if field in {"collector_interest_score", "investment_score", "grading_candidate_score"}:
        try:
            return max(0, min(100, int(float(value))))
        except (TypeError, ValueError):
            return None
    if field in {"value_confidence", "confidence"}:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return None
    if field in {"possible_parallel_matches", "valuation_sources"}:
        return value if isinstance(value, list) else []
    if field in {"rookie_status", "autograph_detected", "relic_detected", "patch_detected"}:
        return bool(value)
    return str(value).strip()


def _parse_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        parsed = json.loads(match.group(0)) if match else {}
    return parsed if isinstance(parsed, dict) else {}


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _card_search_query(card: CardVaultCard) -> str:
    parts = [
        card.year,
        card.brand,
        card.product,
        card.set_name,
        card.player_name,
        card.team,
        f"#{card.card_number}" if card.card_number else "",
        card.parallel_name,
        card.insert_name,
    ]
    return " ".join(part for part in parts if part).strip()


def _research_notes(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "No external image or checklist candidates found automatically."
    return f"Found {len(candidates)} external candidate(s). Confirm exact front/back match before using as canonical images."


def _enrichment_prompt(card: CardVaultCard, mode: str) -> str:
    return f"""
Return strict JSON only. Enrich this single trading card using the provided front/back crop images and existing metadata.
Mode: {mode}

Existing metadata:
player_name={card.player_name}
team={card.team}
league={card.league}
sport={card.sport}
year={card.year}
brand={card.brand}
product={card.product}
set_name={card.set_name}
card_number={card.card_number}
rookie_status={card.rookie_status}
insert_name={card.insert_name}
parallel_name={card.parallel_name}
serial_number={card.serial_number}
serial_total={card.serial_total}

Return JSON with any of these fields when supported by the images or reliable card knowledge:
player_name, team, league, sport, year, brand, product, set_name, card_number,
rookie_status, insert_name, parallel_name, serial_number, serial_total,
autograph_detected, relic_detected, patch_detected, estimated_raw_value,
storage_recommendation, confidence,
player_full_name, player_slug, player_wikipedia_url, player_official_profile_url,
league_player_profile_url, team_profile_url, player_position, player_status,
hall_of_fame_status, career_summary_short, career_stats_summary,
career_stats, latest_season_stats, player_awards_summary,
card_type, card_type_explanation, rarity_tier, rarity_explanation,
collector_interest_score, investment_score, grading_candidate_score,
manufacturer, product_line, release_year, checklist_url, checklist_name,
checklist_card_title, known_parallel_family, possible_parallel_matches,
estimated_raw_value_low, estimated_raw_value_mid, estimated_raw_value_high,
value_confidence, value_last_updated, valuation_sources, recent_comp_summary,
protection_level, protection_reason, recommended_supply, physical_location_label,
wikipedia_url, basketball_reference_url, wnba_profile_url, nba_profile_url,
sports_reference_url, tcdb_url, sportscardspro_url, ebay_search_url,
psa_pop_report_url, notes.

Rules:
- Do not guess aggressively.
- Use null or empty string when unsure.
- Use card_type values only from: base, rookie, insert, parallel, autograph, relic, patch, numbered, case_hit, short_print, unknown.
- Use rarity_tier values only from: common, uncommon, rare, scarce, ultra_rare, unknown.
- Confidence must be 0 to 1.
- Keep output draft-quality; a human will review it.
""".strip()
