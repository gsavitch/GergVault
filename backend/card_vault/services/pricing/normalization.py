from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote_plus

from card_vault.models import CardVaultCard


WAX_TERMS = (
    "box",
    "boxes",
    "hobby",
    "blaster",
    "mega",
    "retail",
    "pack",
    "packs",
    "case",
    "bundle",
    "sealed",
    "wax",
)
LOT_TERMS = (" lot ", "lots", "complete set", "team set", "pick your card", "you pick")
MEMORABILIA_TERMS = ("jersey only", "shirt", "photo", "poster", "autographed basketball")


@dataclass(frozen=True)
class NormalizedCard:
    key: str
    variants: list[str]
    player: str
    sport: str
    league: str
    year: str
    brand: str
    product: str
    set_name: str
    card_number: str
    parallel: str
    insert: str
    rookie: bool
    auto: bool
    relic: bool
    numbered: bool


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def normalized_card(card: CardVaultCard) -> NormalizedCard:
    numbered = bool(card.serial_number or card.serial_total)
    base_parts = [
        card.year,
        card.brand,
        card.product,
        card.set_name,
        card.player_name,
        f"#{card.card_number}" if card.card_number else "",
        card.team,
        card.parallel_name,
        card.insert_name,
        "rookie" if card.rookie_status else "",
        "autograph" if card.autograph_detected else "",
        "relic patch jersey" if card.relic_detected or card.patch_detected else "",
        "numbered" if numbered else "",
    ]
    key = " ".join(str(part).strip() for part in base_parts if str(part).strip())
    variants = _query_variants(card, key)
    return NormalizedCard(
        key=key,
        variants=variants,
        player=normalize_text(card.player_name),
        sport=normalize_text(card.sport),
        league=normalize_text(card.league),
        year=normalize_text(card.year),
        brand=normalize_text(card.brand),
        product=normalize_text(card.product),
        set_name=normalize_text(card.set_name),
        card_number=normalize_text(card.card_number).lstrip("#"),
        parallel=normalize_text(card.parallel_name),
        insert=normalize_text(card.insert_name),
        rookie=card.rookie_status,
        auto=card.autograph_detected,
        relic=card.relic_detected or card.patch_detected,
        numbered=numbered,
    )


def research_links(card: CardVaultCard) -> dict[str, str]:
    norm = normalized_card(card)
    encoded = quote_plus(norm.key)
    sold = quote_plus(norm.key + " sold")
    return {
        "ebay_active_search_url": f"https://www.ebay.com/sch/i.html?_nkw={encoded}",
        "ebay_sold_search_url": f"https://www.ebay.com/sch/i.html?_nkw={sold}&LH_Sold=1&LH_Complete=1",
        "130point_search_url": f"https://130point.com/sales/?search={sold}",
        "brave_search_url": f"https://search.brave.com/search?q={sold}",
        "google_search_url": f"https://www.google.com/search?q={sold}",
        "sportscardspro_search_url": f"https://www.sportscardspro.com/search-products?q={encoded}",
        "pricecharting_search_url": f"https://www.pricecharting.com/search-products?q={encoded}",
        "psa_pop_report_url": f"https://www.psacard.com/pop/tcg-cards?search={encoded}",
    }


def comp_match_flags(card: CardVaultCard, title: str, snippet: str = "") -> dict:
    norm = normalized_card(card)
    haystack = normalize_text(f"{title} {snippet}")
    player_match = bool(norm.player and norm.player in haystack)
    year_match = bool(norm.year and norm.year in haystack)
    brand_match = bool(norm.brand and norm.brand in haystack)
    product_match = bool(norm.product and _token_match(norm.product, haystack))
    card_number_match = _card_number_match(norm.card_number, haystack)
    parallel_match = (not norm.parallel) or norm.parallel in haystack
    rookie_match = (not norm.rookie) or "rookie" in haystack or " rc " in f" {haystack} "
    auto_match = (not norm.auto) or "auto" in haystack or "autograph" in haystack
    relic_match = (not norm.relic) or any(term in haystack for term in ("relic", "patch", "jersey"))
    numbered_match = (not norm.numbered) or "/" in haystack or "numbered" in haystack
    score = (
        (0.25 if player_match else 0)
        + (0.15 if year_match else 0)
        + (0.20 if brand_match or product_match else 0)
        + (0.15 if card_number_match else 0)
        + (0.15 if parallel_match else 0)
        + (0.10 if rookie_match and auto_match and relic_match and numbered_match else 0)
    )
    return {
        "player_match": player_match,
        "year_match": year_match,
        "brand_match": brand_match,
        "product_match": product_match,
        "card_number_match": card_number_match,
        "parallel_match": parallel_match,
        "rookie_match": rookie_match,
        "auto_match": auto_match,
        "relic_match": relic_match,
        "numbered_match": numbered_match,
        "card_match_score": round(min(score, 1.0), 3),
        "exclusion_reason": exclusion_reason(card, title, snippet),
    }


def exclusion_reason(card: CardVaultCard, title: str, snippet: str = "") -> str:
    norm = normalized_card(card)
    haystack = f" {normalize_text(title + ' ' + snippet)} "
    if any(f" {term} " in haystack for term in WAX_TERMS):
        return "unopened_wax_or_sealed_product"
    if any(term in haystack for term in LOT_TERMS):
        return "lot_or_bundle_listing"
    if any(term in haystack for term in MEMORABILIA_TERMS):
        return "unrelated_memorabilia"
    if norm.player and norm.player not in haystack:
        return "wrong_or_missing_player"
    if norm.card_number and not _card_number_match(norm.card_number, haystack):
        return "wrong_or_missing_card_number"
    if norm.product and not _token_match(norm.product, haystack) and norm.set_name and not _token_match(norm.set_name, haystack):
        return "wrong_or_missing_product"
    return ""


def detect_grade(title: str, snippet: str = "") -> tuple[str, str]:
    haystack = normalize_text(f"{title} {snippet}")
    if "psa 10" in haystack:
        return "PSA 10", "graded"
    if "psa 9" in haystack:
        return "PSA 9", "graded"
    if "bgs 9.5" in haystack:
        return "BGS 9.5", "graded"
    if "sgc 10" in haystack:
        return "SGC 10", "graded"
    if "graded" in haystack:
        return "graded", "graded"
    if "raw" in haystack or "ungraded" in haystack:
        return "raw", "raw"
    return "", "raw"


def _query_variants(card: CardVaultCard, key: str) -> list[str]:
    without_team = " ".join(part for part in [card.year, card.brand, card.product, card.set_name, card.player_name, f"#{card.card_number}" if card.card_number else "", card.parallel_name] if part)
    without_insert = " ".join(part for part in [card.year, card.brand, card.product, card.player_name, f"#{card.card_number}" if card.card_number else "", card.parallel_name] if part)
    variants = [
        key,
        without_team,
        without_insert,
        f"{key} sold",
        f"{key} PSA 10",
        f"{key} raw",
        f"{key} eBay sold",
        f"{key} PriceCharting",
        f"{key} SportsCardsPro",
    ]
    seen = set()
    output = []
    for query in variants:
        query = re.sub(r"\s+", " ", query).strip()
        if query and query.lower() not in seen:
            seen.add(query.lower())
            output.append(query)
    return output


def _card_number_match(card_number: str, haystack: str) -> bool:
    if not card_number:
        return False
    escaped = re.escape(card_number)
    return bool(re.search(rf"(^|\s|#){escaped}($|\s|[.,;/)-])", haystack))


def _token_match(needle: str, haystack: str) -> bool:
    tokens = [token for token in re.split(r"[^a-z0-9]+", needle) if len(token) > 2]
    if not tokens:
        return False
    return all(token in haystack for token in tokens[:3])
