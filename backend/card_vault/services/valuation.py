from __future__ import annotations

import os
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Any

import requests
from django.db import transaction
from django.utils import timezone

from card_vault.models import CardVaultCard, CardVaultValuation
from card_vault.serializers import extracted_json_for_card


BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
PREFERRED_TERMS = (
    "ebay",
    "sold",
    "completed",
    "sportscardspro",
    "sports cards pro",
    "psa",
    "card ladder",
    "cardladder",
    "market movers",
)
SEALED_PRODUCT_TERMS = (
    "box",
    "boxes",
    "hobby",
    "blaster",
    "mega",
    "retail",
    "pack",
    "packs",
    "case ",
    "bundle",
    "costco",
    "format",
    "sealed",
)
PRICE_RE = re.compile(
    r"(?:US\s*)?\$\s*(?P<dollars>\d{1,5}(?:,\d{3})*(?:\.\d{2})?)|"
    r"\bUSD\s*(?P<usd>\d{1,5}(?:,\d{3})*(?:\.\d{2})?)",
    re.I,
)


class MissingBraveSearchKey(RuntimeError):
    pass


class CardVaultValuationError(RuntimeError):
    pass


@dataclass
class ValuationResult:
    card_id: int
    skipped: bool
    reason: str
    valuation: dict[str, Any]


def update_card_estimated_value(
    card_id: int,
    *,
    force: bool = False,
    dry_run: bool = False,
    api_key: str | None = None,
) -> ValuationResult:
    try:
        from card_vault.services.pricing import update_card_pricing

        pricing_result = update_card_pricing(card_id, force=force, dry_run=dry_run, providers=["brave", "manual"])
        pricing = pricing_result.pricing or {}
        return ValuationResult(
            card_id=card_id,
            skipped=pricing_result.skipped,
            reason=pricing_result.reason,
            valuation={
                "estimated_raw_value": pricing.get("estimated_value_mid"),
                "value_low": pricing.get("estimated_value_low"),
                "value_high": pricing.get("estimated_value_high"),
                "confidence": pricing.get("confidence_score", 0),
                "confidence_label": pricing.get("confidence_label", "low"),
                "comps": pricing.get("valuation_sources", []),
                "valuation_date": timezone.now().date().isoformat(),
                "warning": pricing.get("confidence_explanation", ""),
                "provider": "pricing_intelligence_v2",
            },
        )
    except Exception:
        # Fall back to the original v1 search-result path if the v2 engine cannot load.
        pass

    card = CardVaultCard.objects.select_related("session").get(pk=card_id)
    if card.review_status == CardVaultCard.ReviewStatus.IGNORED:
        return ValuationResult(card_id=card.id, skipped=True, reason="ignored", valuation={})
    if not card.player_name:
        return ValuationResult(card_id=card.id, skipped=True, reason="missing_player_name", valuation={})
    if card.estimated_raw_value is not None and not force:
        return ValuationResult(card_id=card.id, skipped=True, reason="existing_manual_value", valuation=_current_valuation(card))

    query = build_card_value_query(card)
    results = brave_search(query, api_key=api_key)
    valuation = build_valuation_from_results(card, query, results)

    if not dry_run:
        persist_valuation(card, valuation)

    return ValuationResult(card_id=card.id, skipped=False, reason="", valuation=valuation)


def build_card_value_query(card: CardVaultCard) -> str:
    parts = [
        card.player_name,
        card.year,
        card.brand,
        card.product,
        card.set_name,
        f"#{card.card_number}" if card.card_number else "",
        card.parallel_name,
        "rookie" if card.rookie_status else "",
        "auto autograph" if card.autograph_detected else "",
        "jersey patch relic" if card.relic_detected or card.patch_detected else "",
        "basketball card sold value",
    ]
    return " ".join(str(part).strip() for part in parts if str(part).strip())


def brave_search(query: str, *, api_key: str | None = None, count: int = 10) -> list[dict[str, Any]]:
    key = (api_key if api_key is not None else os.environ.get("BRAVE_SEARCH_API_KEY", "")).strip()
    if not key:
        raise MissingBraveSearchKey("BRAVE_SEARCH_API_KEY is not set; Card Vault valuation cannot run.")
    try:
        response = requests.get(
            BRAVE_SEARCH_URL,
            headers={"Accept": "application/json", "X-Subscription-Token": key},
            params={
                "q": query,
                "count": count,
                "country": "US",
                "search_lang": "en",
                "safesearch": "moderate",
            },
            timeout=25,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise CardVaultValuationError(f"Brave Search request failed: {exc}") from exc

    payload = response.json()
    web = payload.get("web") if isinstance(payload, dict) else {}
    results = web.get("results") if isinstance(web, dict) else []
    return results if isinstance(results, list) else []


def build_valuation_from_results(
    card: CardVaultCard,
    query: str,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    comps = [_result_to_comp(card, result) for result in results if isinstance(result, dict)]
    comps = [comp for comp in comps if comp["url"]]
    comps.sort(key=_comp_rank, reverse=True)
    priced = [comp for comp in comps if comp["price"] is not None]
    prices = [Decimal(str(comp["price"])) for comp in priced]

    estimated = None
    value_low = None
    value_high = None
    if prices:
        estimated = _money(median(prices))
        value_low = _money(min(prices))
        value_high = _money(max(prices))

    confidence = _confidence_for_comps(comps, priced)
    now = timezone.now()
    return {
        "estimated_raw_value": str(estimated) if estimated is not None else None,
        "value_low": str(value_low) if value_low is not None else None,
        "value_high": str(value_high) if value_high is not None else None,
        "confidence": confidence,
        "comps": comps[:8],
        "valuation_date": now.date().isoformat(),
        "updated_at": now.isoformat(),
        "query": query,
        "provider": "brave_search",
        "warning": _valuation_warning(confidence, priced),
        "disclaimer": "Estimated raw value from search-result snippets only; verify exact comps before pricing.",
        "future_providers": ["ebay_sold", "sportscardspro", "cardladder", "psa", "market_movers"],
    }


@transaction.atomic
def persist_valuation(card: CardVaultCard, valuation: dict[str, Any]) -> None:
    estimated = _decimal_or_none(valuation.get("estimated_raw_value"))
    card.estimated_raw_value = estimated

    data = extracted_json_for_card(card)
    data["valuation"] = valuation
    data["estimated_raw_value"] = str(estimated) if estimated is not None else None
    data["estimated_raw_value_low"] = valuation.get("value_low")
    data["estimated_raw_value_mid"] = valuation.get("estimated_raw_value")
    data["estimated_raw_value_high"] = valuation.get("value_high")
    data["value_confidence"] = valuation.get("confidence", 0)
    data["value_last_updated"] = valuation.get("valuation_date")
    data["valuation_sources"] = [
        {"source": comp.get("source"), "url": comp.get("url"), "price": comp.get("price")}
        for comp in valuation.get("comps", [])[:8]
    ]
    data["recent_comp_summary"] = _recent_comp_summary(valuation)
    card.extracted_json = data
    card.review_status = CardVaultCard.ReviewStatus.NEEDS_REVIEW
    card.is_draft = True
    card.save(update_fields=["estimated_raw_value", "extracted_json", "review_status", "is_draft", "updated_at"])

    valuation_date = timezone.datetime.fromisoformat(valuation["valuation_date"]).date()
    for comp in valuation.get("comps", []):
        amount = _decimal_or_none(comp.get("price"))
        if amount is None:
            continue
        CardVaultValuation.objects.create(
            card=card,
            source=comp.get("source") or "search_result",
            amount=amount,
            confidence=float(valuation.get("confidence") or 0),
            valuation_date=valuation_date,
            raw_data=comp,
            notes=valuation.get("disclaimer", ""),
        )


def _result_to_comp(card: CardVaultCard, result: dict[str, Any]) -> dict[str, Any]:
    title = _clean(result.get("title") or "")
    url = _clean(result.get("url") or result.get("profile", {}).get("url") or "")
    snippet = _clean(result.get("description") or "")
    if not snippet and result.get("extra_snippets"):
        snippet = _clean(" ".join(str(item) for item in result.get("extra_snippets") or []))
    text = f"{title} {snippet}"
    rejected_reason = _rejected_comp_reason(card, title, url, snippet)
    price = None if rejected_reason else _extract_price(text)
    return {
        "title": title,
        "url": url,
        "source": _source_for(url, text),
        "price": str(price) if price is not None else None,
        "snippet": snippet,
        "preferred": _is_preferred(url, text),
        "rejected_reason": rejected_reason,
    }


def _extract_price(text: str) -> Decimal | None:
    values = []
    for match in PRICE_RE.finditer(text or ""):
        raw = match.group("dollars") or match.group("usd")
        if not raw:
            continue
        price = _decimal_or_none(raw.replace(",", ""))
        if price is not None and Decimal("0.50") <= price <= Decimal("50000"):
            values.append(price)
    if not values:
        return None
    return _money(values[0])


def _source_for(url: str, text: str) -> str:
    haystack = f"{url} {text}".lower()
    if "ebay" in haystack:
        return "ebay"
    if "sportscardspro" in haystack or "sports cards pro" in haystack:
        return "sportscardspro"
    if "cardladder" in haystack or "card ladder" in haystack:
        return "card_ladder"
    if "psa" in haystack:
        return "psa"
    if "market movers" in haystack or "marketmovers" in haystack:
        return "market_movers"
    return "search_result"


def _is_preferred(url: str, text: str) -> bool:
    haystack = f"{url} {text}".lower()
    return any(term in haystack for term in PREFERRED_TERMS)


def _rejected_comp_reason(card: CardVaultCard, title: str, url: str, snippet: str) -> str:
    haystack = f"{title} {url} {snippet}".lower()
    player = (card.player_name or "").lower()
    card_number = (card.card_number or "").strip().lower()
    if any(term in haystack for term in SEALED_PRODUCT_TERMS):
        if not player or player not in haystack:
            return "sealed_or_box_product"
        if "checklist" in haystack and "$" in haystack:
            return "checklist_or_box_price"
    if "checklist" in haystack and player and player not in haystack:
        return "checklist_not_card_comp"
    if player and player not in haystack and card_number and f"#{card_number}" not in haystack:
        return "missing_player_match"
    return ""


def _comp_rank(comp: dict[str, Any]) -> tuple[int, int, int]:
    return (
        1 if comp.get("preferred") else 0,
        1 if comp.get("price") is not None else 0,
        len(comp.get("snippet") or ""),
    )


def _confidence_for_comps(comps: list[dict[str, Any]], priced: list[dict[str, Any]]) -> float:
    preferred_priced = [comp for comp in priced if comp.get("preferred")]
    if not priced:
        return 0.15 if comps else 0.0
    confidence = Decimal("0.28") + (Decimal("0.09") * min(len(priced), 5))
    confidence += Decimal("0.06") * min(len(preferred_priced), 4)
    if len(priced) == 1:
        confidence = min(confidence, Decimal("0.42"))
    return float(min(confidence, Decimal("0.85")).quantize(Decimal("0.01")))


def _valuation_warning(confidence: float, priced: list[dict[str, Any]]) -> str:
    if not priced:
        return "No priced comps were found in search snippets."
    if confidence < 0.5:
        return "Low-confidence estimate; confirm exact sold comps manually."
    return ""


def _current_valuation(card: CardVaultCard) -> dict[str, Any]:
    return (card.extracted_json or {}).get("valuation", {})


def _recent_comp_summary(valuation: dict[str, Any]) -> str:
    comps = valuation.get("comps") or []
    priced = [comp for comp in comps if comp.get("price")]
    if not priced:
        return "No priced comps were found in search-result snippets."
    value = valuation.get("estimated_raw_value")
    low = valuation.get("value_low")
    high = valuation.get("value_high")
    return f"{len(priced)} priced search-result comp(s); estimated raw range ${low} to ${high}, midpoint ${value}."


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _money(value: Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()
