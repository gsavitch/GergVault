from __future__ import annotations

import os
import re
from decimal import Decimal, InvalidOperation
from typing import Any

import requests

from card_vault.models import CardVaultCard
from card_vault.services.pricing.normalization import comp_match_flags, detect_grade, normalized_card


BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
PRICE_RE = re.compile(
    r"(?:US\s*)?\$\s*(?P<dollars>\d{1,5}(?:,\d{3})*(?:\.\d{2})?)|"
    r"\bUSD\s*(?P<usd>\d{1,5}(?:,\d{3})*(?:\.\d{2})?)",
    re.I,
)


def search(card: CardVaultCard, *, provider_names: set[str] | None = None, limit: int = 8) -> dict[str, Any]:
    key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    if not key:
        return {"provider": "brave", "available": False, "warning": "BRAVE_SEARCH_API_KEY is not set.", "comps": []}
    norm = normalized_card(card)
    query = norm.variants[3] if len(norm.variants) > 3 else norm.key + " sold"
    try:
        response = requests.get(
            BRAVE_SEARCH_URL,
            headers={"Accept": "application/json", "X-Subscription-Token": key},
            params={"q": query, "count": limit, "country": "US", "search_lang": "en", "safesearch": "moderate"},
            timeout=25,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        return {"provider": "brave", "available": False, "warning": f"Brave Search failed: {exc}", "comps": []}
    results = ((payload or {}).get("web") or {}).get("results") or []
    comps = [_result_to_comp(card, result) for result in results if isinstance(result, dict)]
    return {"provider": "brave", "available": True, "query": query, "payload": payload, "comps": comps}


def _result_to_comp(card: CardVaultCard, result: dict[str, Any]) -> dict[str, Any]:
    title = _clean(result.get("title") or "")
    url = _clean(result.get("url") or "")
    snippet = _clean(result.get("description") or "")
    text = f"{title} {snippet}"
    flags = comp_match_flags(card, title, snippet)
    grade, raw_or_graded = detect_grade(title, snippet)
    price = _extract_price(text)
    source_type = _source_type(url, text)
    original_source_type = source_type
    if price is not None and source_type in {"active_listing", "sold_comp", "manual"}:
        source_type = "search_hint"
    exclusion_reason = flags["exclusion_reason"]
    if raw_or_graded == "graded" and source_type != "price_guide":
        exclusion_reason = exclusion_reason or "graded_comp_separate_from_raw"
    return {
        "provider": _provider_name(url, text),
        "source_type": source_type,
        "title": title,
        "url": url,
        "price": str(price) if price is not None else None,
        "currency": "USD",
        "sale_date": None,
        "listing_status": "sold_or_completed_hint" if "sold" in text.lower() or "completed" in text.lower() else "",
        "grade": grade,
        "raw_or_graded": raw_or_graded,
        "excluded": bool(exclusion_reason),
        "exclusion_reason": exclusion_reason,
        "raw_payload": {"snippet": snippet, "brave_result": result, "original_source_type": original_source_type},
        **flags,
    }


def _source_type(url: str, text: str) -> str:
    haystack = f"{url} {text}".lower()
    if "sportscardspro" in haystack or "pricecharting" in haystack:
        return "price_guide"
    if "psa" in haystack or "pop report" in haystack:
        return "pop_report"
    if "sold" in haystack or "completed" in haystack or "130point" in haystack:
        return "sold_comp"
    if "ebay" in haystack:
        return "active_listing"
    return "manual"


def _provider_name(url: str, text: str) -> str:
    haystack = f"{url} {text}".lower()
    if "ebay" in haystack:
        return "ebay"
    if "sportscardspro" in haystack:
        return "sportscardspro"
    if "pricecharting" in haystack:
        return "pricecharting"
    if "psa" in haystack:
        return "psa"
    if "130point" in haystack:
        return "130point"
    return "brave"


def _extract_price(text: str) -> Decimal | None:
    for match in PRICE_RE.finditer(text or ""):
        raw = match.group("dollars") or match.group("usd")
        if not raw:
            continue
        try:
            price = Decimal(raw.replace(",", "")).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            continue
        if Decimal("0.50") <= price <= Decimal("50000"):
            return price
    return None


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()
