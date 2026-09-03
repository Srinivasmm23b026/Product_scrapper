from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from procurement_assistant.models import ProductMatch
from procurement_assistant.normalization import normalize_brand, normalize_product_name, parse_pack


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    canonical_product_id: uuid.UUID
    product_variant_id: uuid.UUID
    normalized_name: str
    canonical_brand: str | None
    base_unit: str
    total_quantity: Decimal
    category: str | None = None


@dataclass(frozen=True, slots=True)
class MatchDecision:
    canonical_product_id: uuid.UUID | None
    product_variant_id: uuid.UUID | None
    match_method: str
    confidence: Decimal
    review_status: str


def _tokens(value: str) -> frozenset[str]:
    return frozenset(value.split())


def _jaccard(left: str, right: str) -> Decimal:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return Decimal("0")
    return Decimal(len(a & b)) / Decimal(len(a | b))


def match_product(
    *,
    source_name: str,
    source_brand: str | None,
    source_pack_text: str | None,
    candidates: list[MatchCandidate],
) -> MatchDecision:
    pack = parse_pack(source_pack_text, source_name)
    if pack is None:
        return MatchDecision(None, None, "unparseable_pack", Decimal("0"), "REVIEW")

    name = normalize_product_name(source_name, source_brand)
    brand = normalize_brand(source_brand)
    ranked: list[tuple[Decimal, MatchCandidate]] = []
    for candidate in candidates:
        if candidate.base_unit != pack.base_unit:
            continue
        candidate_brand = normalize_brand(candidate.canonical_brand)
        if brand and candidate_brand and brand != candidate_brand:
            continue
        name_score = _jaccard(name, candidate.normalized_name)
        ranked.append((name_score, candidate))

    if not ranked:
        return MatchDecision(None, None, "no_compatible_candidate", Decimal("0"), "NO_MATCH")

    name_score, best = sorted(
        ranked,
        key=lambda item: (
            item[0],
            item[1].total_quantity == pack.total_quantity,
            str(item[1].product_variant_id),
        ),
        reverse=True,
    )[0]
    exact_variant = best.total_quantity == pack.total_quantity
    brand_verified = bool(brand and brand == normalize_brand(best.canonical_brand))

    if brand_verified and name_score >= Decimal("0.75") and exact_variant:
        confidence = min(Decimal("1"), Decimal("0.8") + name_score * Decimal("0.2"))
        return MatchDecision(
            best.canonical_product_id,
            best.product_variant_id,
            "brand_name_pack_v1",
            confidence.quantize(Decimal("0.0001")),
            "AUTO_MATCH",
        )

    if name_score >= Decimal("0.5"):
        confidence = name_score * (Decimal("0.75") if brand_verified else Decimal("0.55"))
        return MatchDecision(
            best.canonical_product_id,
            best.product_variant_id if exact_variant else None,
            "family_candidate_v1",
            confidence.quantize(Decimal("0.0001")),
            "REVIEW",
        )

    return MatchDecision(None, None, "below_threshold_v1", name_score, "NO_MATCH")


def persist_match_decision(
    session: Session, *, supplier_product_id: uuid.UUID, decision: MatchDecision
) -> ProductMatch:
    record = session.scalar(
        select(ProductMatch).where(ProductMatch.supplier_product_id == supplier_product_id)
    )
    if record is None:
        record = ProductMatch(supplier_product_id=supplier_product_id)
        session.add(record)
    record.canonical_product_id = decision.canonical_product_id
    record.product_variant_id = decision.product_variant_id
    record.match_method = decision.match_method
    record.confidence = decision.confidence
    record.review_status = decision.review_status
    return record
