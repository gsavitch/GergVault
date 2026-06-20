from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from card_vault.models import CardVaultCard, CardVaultComp, CardVaultPriceSnapshot, CardVaultValuationRun
from card_vault.serializers import extracted_json_for_card
from card_vault.services.pricing.confidence import confidence_explanation, robust_range
from card_vault.services.pricing.normalization import normalized_card, research_links
from card_vault.services.pricing.providers import brave, ebay_browse, manual, pricecharting, psa, sportscardspro


VALUE_DISCLAIMER = (
    "Estimated value only. Based on available comps and sources. Actual sale price depends on "
    "condition, timing, grading, demand, and buyer interest."
)
PROVIDERS = {
    "brave": brave.search,
    "ebay": ebay_browse.search,
    "ebay_browse": ebay_browse.search,
    "sportscardspro": sportscardspro.search,
    "pricecharting": pricecharting.search,
    "psa": psa.search,
    "manual": manual.search,
}
PROVIDER_ENV_VARS = {
    "brave": ("BRAVE_SEARCH_API_KEY",),
    "ebay": ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET"),
    "sportscardspro": ("SPORTSCARDSPRO_API_KEY",),
    "pricecharting": ("PRICECHARTING_API_KEY",),
    "psa": ("PSA_API_KEY",),
}


@dataclass
class PricingResult:
    run: CardVaultValuationRun | None
    skipped: bool
    reason: str
    pricing: dict[str, Any]


def provider_readiness() -> dict[str, dict[str, Any]]:
    labels = {
        "brave": "Brave Search",
        "ebay": "eBay Browse API",
        "sportscardspro": "SportsCardsPro",
        "pricecharting": "PriceCharting",
        "psa": "PSA",
    }
    help_text = {
        "brave": "Search-result discovery and rough fallback hints.",
        "ebay": "Improves active and sold listing coverage when Browse API credentials are configured.",
        "sportscardspro": "Future guide-price provider for card-specific values.",
        "pricecharting": "Future guide-price provider for raw and graded ranges.",
        "psa": "Future population-report and grading context provider.",
    }
    status = {}
    for provider, env_vars in PROVIDER_ENV_VARS.items():
        missing = [name for name in env_vars if not os.environ.get(name)]
        status[provider] = {
            "label": labels[provider],
            "configured": not missing,
            "missing_env_vars": missing,
            "env_vars": list(env_vars),
            "help_text": help_text[provider],
        }
    return status


def update_card_pricing(
    card_id: int,
    *,
    providers: list[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> PricingResult:
    card = CardVaultCard.objects.select_related("session").get(pk=card_id)
    if card.review_status == CardVaultCard.ReviewStatus.IGNORED:
        return PricingResult(None, True, "ignored", {})
    if not card.player_name:
        return PricingResult(None, True, "missing_player_name", {})
    if card.estimated_raw_value is not None and not force:
        return PricingResult(None, True, "existing_manual_value", (card.extracted_json or {}).get("pricing_intelligence", {}))

    provider_names = providers or ["brave", "sportscardspro", "pricecharting", "ebay", "psa", "manual"]
    norm = normalized_card(card)
    started_at = timezone.now()
    run = None
    if not dry_run:
        run = CardVaultValuationRun.objects.create(
            card=card,
            status=CardVaultValuationRun.Status.RUNNING,
            started_at=started_at,
            query_used=norm.variants[0],
            normalized_card_key=norm.key,
        )

    provider_payloads = []
    comps = []
    warnings = []
    try:
        for provider_name in provider_names:
            adapter = PROVIDERS.get(provider_name)
            if not adapter:
                warnings.append(f"{provider_name}: unknown provider")
                continue
            payload = adapter(card)
            provider_payloads.append(payload)
            if payload.get("warning"):
                warnings.append(f"{payload.get('provider', provider_name)}: {payload['warning']}")
            comps.extend(payload.get("comps") or [])
        pricing = calculate_pricing(card, comps, provider_payloads, warnings)
        if not dry_run and run:
            persist_pricing(card, run, pricing, provider_payloads)
    except Exception as exc:
        if run:
            run.status = CardVaultValuationRun.Status.FAILED
            run.completed_at = timezone.now()
            run.error_message = f"{type(exc).__name__}: {exc}"
            run.save(update_fields=["status", "completed_at", "error_message"])
        raise
    return PricingResult(run, False, "", pricing)


def calculate_pricing(
    card: CardVaultCard,
    comps: list[dict[str, Any]],
    provider_payloads: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    included_raw = [
        comp for comp in comps
        if not comp.get("excluded") and comp.get("price") and comp.get("raw_or_graded", "raw") == "raw"
    ]
    sold = [comp for comp in included_raw if comp.get("source_type") == CardVaultComp.SourceType.SOLD_COMP]
    active = [comp for comp in included_raw if comp.get("source_type") == CardVaultComp.SourceType.ACTIVE_LISTING]
    guides = [comp for comp in included_raw if comp.get("source_type") == CardVaultComp.SourceType.PRICE_GUIDE]
    search_hints = [comp for comp in included_raw if comp.get("source_type") == CardVaultComp.SourceType.SEARCH_HINT]
    scarcity = [comp for comp in comps if comp.get("source_type") == CardVaultComp.SourceType.POP_REPORT]

    weighted_values = []
    if sold:
        weighted_values += _weighted_prices(sold, Decimal("0.65"))
        weighted_values += _weighted_prices(guides, Decimal("0.20"))
        weighted_values += _weighted_prices(active, Decimal("0.10"), active_discount=Decimal("0.70"))
    elif guides or active:
        weighted_values += _weighted_prices(guides, Decimal("0.50"))
        weighted_values += _weighted_prices(active, Decimal("0.40"), active_discount=Decimal("0.70"))
    elif active:
        weighted_values += _weighted_prices(active, Decimal("1.00"), active_discount=Decimal("0.70"))

    low, mid, high, spread_ratio = robust_range(weighted_values)
    value_status = "verified_estimate" if mid is not None else "no_reliable_estimate"
    estimate_basis = "verified sold/listing/guide comps" if mid is not None else "none"
    rough_hint_count = 0
    if mid is None:
        rough_values, rough_hint_count = _rough_search_hint_values(search_hints)
        if len(rough_values) >= 2:
            low, mid, high, spread_ratio = robust_range(rough_values)
            value_status = "rough_search_estimate"
            estimate_basis = "rough search-based estimate"
    exact_count = len([comp for comp in included_raw if float(comp.get("card_match_score") or 0) >= 0.75])
    confidence_score, label, why = confidence_explanation(
        sold_count=len(sold),
        active_count=len(active),
        guide_count=len(guides),
        spread_ratio=spread_ratio,
        exact_count=exact_count,
    )
    if value_status == "rough_search_estimate":
        label = "low"
        confidence_score = min(confidence_score, 0.25)
        why = (
            "rough search-based estimate; no verified sold comps or price-guide data available; "
            f"{rough_hint_count} weak price hint(s)"
        )
    elif len(included_raw) < 3:
        label = "low"
        confidence_score = min(confidence_score, 0.44)
        why = f"fewer than 3 included comps; {why}"
    if not sold:
        label = "low" if not guides else label

    graded = _graded_estimates(comps)
    summary = _summary(low, mid, high, value_status=value_status)
    explanation = _explanation(len(sold), len(active), len(guides), len(scarcity), why, value_status=value_status)
    return {
        "estimated_value_low": _str_money(low),
        "estimated_value_mid": _str_money(mid),
        "estimated_value_high": _str_money(high),
        "value_status": value_status,
        "value_status_label": _value_status_label(value_status),
        "estimate_basis": estimate_basis,
        "rough_search_hint_count": rough_hint_count,
        "rough_estimate_warning": (
            "Rough search-based estimate. No verified sold comps or price-guide data available."
            if value_status == "rough_search_estimate"
            else ("Needs stronger pricing source." if value_status == "no_reliable_estimate" else "")
        ),
        "confidence_label": label,
        "confidence_score": confidence_score,
        "comp_count_total": len(comps),
        "included_comp_count": len(included_raw),
        "sold_comp_count": len(sold),
        "active_listing_count": len(active),
        "guide_source_count": len(guides),
        "search_hint_count": len(search_hints),
        "scarcity_source_count": len(scarcity),
        "pricing_summary": summary,
        "pricing_explanation": explanation,
        "confidence_explanation": why,
        "research_links": research_links(card),
        "provider_warnings": warnings,
        "provider_status": provider_readiness(),
        "disclaimer": VALUE_DISCLAIMER,
        "comps": comps,
        "valuation_sources": _source_summary(comps, provider_payloads),
        "last_updated": timezone.now().isoformat(),
        "estimated_psa9_value_low": graded.get("PSA 9", {}).get("low"),
        "estimated_psa9_value_mid": graded.get("PSA 9", {}).get("mid"),
        "estimated_psa9_value_high": graded.get("PSA 9", {}).get("high"),
        "estimated_psa10_value_low": graded.get("PSA 10", {}).get("low"),
        "estimated_psa10_value_mid": graded.get("PSA 10", {}).get("mid"),
        "estimated_psa10_value_high": graded.get("PSA 10", {}).get("high"),
        "grading_upside_score": _grading_upside_score(mid, graded),
        "grading_recommendation": _grading_recommendation(mid, graded, card),
    }


@transaction.atomic
def persist_pricing(
    card: CardVaultCard,
    run: CardVaultValuationRun,
    pricing: dict[str, Any],
    provider_payloads: list[dict[str, Any]],
) -> None:
    for comp in pricing["comps"]:
        CardVaultComp.objects.create(
            valuation_run=run,
            provider=comp.get("provider") or "unknown",
            source_type=comp.get("source_type") or CardVaultComp.SourceType.MANUAL,
            title=comp.get("title") or "",
            url=comp.get("url") or "",
            price=_decimal_or_none(comp.get("price")),
            currency=comp.get("currency") or "USD",
            sale_date=comp.get("sale_date") or None,
            listing_status=comp.get("listing_status") or "",
            grade=comp.get("grade") or "",
            raw_or_graded=comp.get("raw_or_graded") or "raw",
            card_match_score=float(comp.get("card_match_score") or 0),
            player_match=bool(comp.get("player_match")),
            year_match=bool(comp.get("year_match")),
            brand_match=bool(comp.get("brand_match")),
            product_match=bool(comp.get("product_match")),
            card_number_match=bool(comp.get("card_number_match")),
            parallel_match=bool(comp.get("parallel_match")),
            rookie_match=bool(comp.get("rookie_match")),
            auto_match=bool(comp.get("auto_match")),
            relic_match=bool(comp.get("relic_match")),
            numbered_match=bool(comp.get("numbered_match")),
            excluded=bool(comp.get("excluded")),
            exclusion_reason=comp.get("exclusion_reason") or "",
            raw_payload=comp.get("raw_payload") or comp,
        )

    run.status = CardVaultValuationRun.Status.COMPLETED if pricing["included_comp_count"] else CardVaultValuationRun.Status.PARTIAL
    run.completed_at = timezone.now()
    run.estimated_value_low = _decimal_or_none(pricing.get("estimated_value_low"))
    run.estimated_value_mid = _decimal_or_none(pricing.get("estimated_value_mid"))
    run.estimated_value_high = _decimal_or_none(pricing.get("estimated_value_high"))
    run.estimated_psa9_value_low = _decimal_or_none(pricing.get("estimated_psa9_value_low"))
    run.estimated_psa9_value_mid = _decimal_or_none(pricing.get("estimated_psa9_value_mid"))
    run.estimated_psa9_value_high = _decimal_or_none(pricing.get("estimated_psa9_value_high"))
    run.estimated_psa10_value_low = _decimal_or_none(pricing.get("estimated_psa10_value_low"))
    run.estimated_psa10_value_mid = _decimal_or_none(pricing.get("estimated_psa10_value_mid"))
    run.estimated_psa10_value_high = _decimal_or_none(pricing.get("estimated_psa10_value_high"))
    run.value_confidence = float(pricing.get("confidence_score") or 0)
    run.confidence_label = pricing.get("confidence_label") or "low"
    run.comp_count_total = int(pricing.get("comp_count_total") or 0)
    run.sold_comp_count = int(pricing.get("sold_comp_count") or 0)
    run.active_listing_count = int(pricing.get("active_listing_count") or 0)
    run.guide_source_count = int(pricing.get("guide_source_count") or 0)
    run.scarcity_source_count = int(pricing.get("scarcity_source_count") or 0)
    run.grading_upside_score = float(pricing.get("grading_upside_score") or 0)
    run.grading_recommendation = pricing.get("grading_recommendation") or ""
    run.pricing_summary = pricing.get("pricing_summary") or ""
    run.pricing_explanation = pricing.get("pricing_explanation") or ""
    run.raw_provider_payload = {"providers": provider_payloads, "pricing": pricing}
    run.save()

    CardVaultPriceSnapshot.objects.create(
        card=card,
        valuation_run=run,
        estimated_value_low=run.estimated_value_low,
        estimated_value_mid=run.estimated_value_mid,
        estimated_value_high=run.estimated_value_high,
        confidence_label=run.confidence_label,
        comp_count=run.comp_count_total,
        source_summary=pricing.get("valuation_sources") or {},
    )

    card.estimated_raw_value = run.estimated_value_mid
    data = extracted_json_for_card(card)
    data["pricing_intelligence"] = _json_safe(pricing)
    data["valuation"] = _legacy_valuation(pricing)
    data["estimated_raw_value"] = _str_money(run.estimated_value_mid)
    data["estimated_raw_value_low"] = pricing.get("estimated_value_low")
    data["estimated_raw_value_mid"] = pricing.get("estimated_value_mid")
    data["estimated_raw_value_high"] = pricing.get("estimated_value_high")
    data["value_confidence"] = pricing.get("confidence_score")
    data["value_last_updated"] = pricing.get("last_updated")
    data["valuation_sources"] = pricing.get("valuation_sources")
    data["recent_comp_summary"] = pricing.get("pricing_explanation")
    for key, url in pricing.get("research_links", {}).items():
        data[key] = url
    card.extracted_json = data
    card.review_status = CardVaultCard.ReviewStatus.NEEDS_REVIEW
    card.is_draft = True
    card.save(update_fields=["estimated_raw_value", "extracted_json", "review_status", "is_draft", "updated_at"])


def _weighted_prices(comps: list[dict[str, Any]], weight: Decimal, *, active_discount: Decimal = Decimal("1.00")) -> list[Decimal]:
    if not comps:
        return []
    repeat = max(1, int(weight * 100))
    values = []
    for comp in comps:
        price = _decimal_or_none(comp.get("price"))
        if price is not None:
            values.extend([price * active_discount] * repeat)
    return values


def _rough_search_hint_values(comps: list[dict[str, Any]]) -> tuple[list[Decimal], int]:
    values = []
    for comp in comps:
        price = _decimal_or_none(comp.get("price"))
        if price is None:
            continue
        if price < Decimal("0.50") or price > Decimal("500"):
            continue
        if float(comp.get("card_match_score") or 0) < 0.75:
            continue
        values.append(price)
    return values, len(values)


def _graded_estimates(comps: list[dict[str, Any]]) -> dict[str, dict[str, str | None]]:
    output = {}
    for grade in ("PSA 9", "PSA 10"):
        prices = [_decimal_or_none(comp.get("price")) for comp in comps if comp.get("grade") == grade and not comp.get("excluded")]
        low, mid, high, _spread = robust_range([price for price in prices if price is not None])
        output[grade] = {"low": _str_money(low), "mid": _str_money(mid), "high": _str_money(high)}
    return output


def _grading_upside_score(raw_mid: Decimal | None, graded: dict[str, dict[str, str | None]]) -> float:
    psa10 = _decimal_or_none(graded.get("PSA 10", {}).get("mid"))
    if not raw_mid or not psa10:
        return 0
    return float(min(100, max(0, ((psa10 - raw_mid - Decimal("35")) / raw_mid) * 50)))


def _grading_recommendation(raw_mid: Decimal | None, graded: dict[str, dict[str, str | None]], card: CardVaultCard) -> str:
    if raw_mid is None:
        return "Inspect condition first; no reliable raw estimate yet."
    if raw_mid < Decimal("20") and not (card.rookie_status or card.autograph_detected or card.serial_total):
        return "Usually do not grade below $20 raw unless condition is exceptional or personal value matters."
    psa10 = _decimal_or_none(graded.get("PSA 10", {}).get("mid"))
    if psa10 and psa10 - raw_mid - Decimal("35") > raw_mid * 2:
        return "Grade review: PSA 10 upside may justify grading cost if condition looks gem-mint."
    if card.rookie_status or card.autograph_detected or card.serial_total:
        return "Grade review recommended because rookie/auto/numbered attributes can improve upside; inspect condition first."
    return "Inspect condition first before grading."


def _summary(low, mid, high, *, value_status: str) -> str:
    if mid is None:
        return "No reliable raw estimate yet."
    if value_status == "rough_search_estimate":
        return f"Rough search-based estimate ${low}-${high}, midpoint ${mid}."
    return f"Estimated raw value ${low}-${high}, midpoint ${mid}."


def _explanation(sold_count: int, active_count: int, guide_count: int, scarcity_count: int, why: str, *, value_status: str) -> str:
    prefix = ""
    if value_status == "rough_search_estimate":
        prefix = "No verified sold comps or price-guide data available. "
    elif value_status == "no_reliable_estimate":
        prefix = "Needs stronger pricing source. "
    return (
        prefix
        + f"Based on {sold_count} sold comp(s), {active_count} active listing(s), "
        f"{guide_count} guide source(s), and {scarcity_count} scarcity source(s). {why}."
    )


def _value_status_label(value_status: str) -> str:
    return {
        "verified_estimate": "Verified estimate",
        "rough_search_estimate": "Rough search estimate",
        "no_reliable_estimate": "No reliable estimate",
    }.get(value_status, "No reliable estimate")


def _source_summary(comps: list[dict[str, Any]], provider_payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [
        {
            "provider": comp.get("provider"),
            "source_type": comp.get("source_type"),
            "title": comp.get("title"),
            "url": comp.get("url"),
            "price": comp.get("price"),
            "excluded": comp.get("excluded"),
            "exclusion_reason": comp.get("exclusion_reason"),
        }
        for comp in comps[:20]
    ]
    for payload in provider_payloads:
        for name, url in (payload.get("research_links") or {}).items():
            rows.append({"provider": payload.get("provider"), "source_type": "research_link", "title": name, "url": url})
    return rows


def _legacy_valuation(pricing: dict[str, Any]) -> dict[str, Any]:
    return {
        "estimated_raw_value": pricing.get("estimated_value_mid"),
        "value_low": pricing.get("estimated_value_low"),
        "value_high": pricing.get("estimated_value_high"),
        "confidence": pricing.get("confidence_score"),
        "confidence_label": pricing.get("confidence_label"),
        "comps": pricing.get("valuation_sources", []),
        "valuation_date": timezone.now().date().isoformat(),
        "warning": "" if pricing.get("confidence_label") != "low" else pricing.get("confidence_explanation", ""),
        "disclaimer": VALUE_DISCLAIMER,
        "provider": "pricing_intelligence_v2",
        "value_status": pricing.get("value_status"),
        "value_status_label": pricing.get("value_status_label"),
        "rough_estimate_warning": pricing.get("rough_estimate_warning"),
    }


def _decimal_or_none(value) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _str_money(value) -> str | None:
    if value is None:
        return None
    return str(Decimal(str(value)).quantize(Decimal("0.01")))


def _json_safe(value):
    if isinstance(value, Decimal):
        return str(value.quantize(Decimal("0.01")))
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
