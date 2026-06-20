from __future__ import annotations

from decimal import Decimal
from statistics import median
from typing import Iterable


def confidence_label(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def confidence_explanation(*, sold_count: int, active_count: int, guide_count: int, spread_ratio: float, exact_count: int) -> tuple[float, str, str]:
    score = 0.15
    reasons = []
    if sold_count >= 5:
        score += 0.45
        reasons.append("5+ sold comps")
    elif sold_count >= 2:
        score += 0.30
        reasons.append("2-4 sold comps")
    elif sold_count == 1:
        score += 0.18
        reasons.append("1 sold comp")
    else:
        reasons.append("no sold comps")

    if exact_count >= 5:
        score += 0.20
        reasons.append("strong exact-card matching")
    elif exact_count >= 2:
        score += 0.12
        reasons.append("some exact-card matches")
    else:
        reasons.append("weak exact-card match coverage")

    if guide_count:
        score += min(0.12, guide_count * 0.06)
        reasons.append(f"{guide_count} guide source(s)")
    if active_count and not sold_count:
        score += 0.08
        reasons.append("active listings only; discounted")
    elif active_count:
        score += 0.05
        reasons.append(f"{active_count} active listing(s)")

    if spread_ratio > 1.2:
        score -= 0.18
        reasons.append("very wide price spread")
    elif spread_ratio > 0.65:
        score -= 0.08
        reasons.append("moderate price spread")
    else:
        score += 0.08
        reasons.append("narrow price range")

    score = max(0.0, min(0.95, round(score, 2)))
    label = confidence_label(score)
    return score, label, "; ".join(reasons)


def robust_range(values: Iterable[Decimal]) -> tuple[Decimal | None, Decimal | None, Decimal | None, float]:
    ordered = sorted(value for value in values if value is not None)
    if not ordered:
        return None, None, None, 0.0
    if len(ordered) >= 5:
        trimmed = ordered[1:-1]
    else:
        trimmed = ordered
    low = trimmed[0]
    high = trimmed[-1]
    mid = Decimal(str(median(trimmed))).quantize(Decimal("0.01"))
    spread_ratio = float((high - low) / mid) if mid else 0.0
    return low.quantize(Decimal("0.01")), mid, high.quantize(Decimal("0.01")), spread_ratio
