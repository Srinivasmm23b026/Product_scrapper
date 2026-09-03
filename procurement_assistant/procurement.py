from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, InvalidOperation

UNIT_FACTORS = {
    "kg": (Decimal("1"), "kg"),
    "g": (Decimal("0.001"), "kg"),
    "gram": (Decimal("0.001"), "kg"),
    "grams": (Decimal("0.001"), "kg"),
    "l": (Decimal("1"), "l"),
    "litre": (Decimal("1"), "l"),
    "liter": (Decimal("1"), "l"),
    "ml": (Decimal("0.001"), "l"),
    "piece": (Decimal("1"), "piece"),
    "pieces": (Decimal("1"), "piece"),
    "pc": (Decimal("1"), "piece"),
    "pcs": (Decimal("1"), "piece"),
    "unit": (Decimal("1"), "piece"),
    "units": (Decimal("1"), "piece"),
}


@dataclass(frozen=True, slots=True)
class ComparableOffer:
    offer_id: uuid.UUID
    supplier: str
    product_name: str
    pack_text: str | None
    pack_price: Decimal | None
    pack_total_quantity: Decimal | None
    base_unit: str | None
    availability: bool | None
    product_url: str | None = None


@dataclass(frozen=True, slots=True)
class ProcurementCalculation:
    offer: ComparableOffer
    packs_required: int
    quantity_purchased: Decimal
    excess_quantity: Decimal
    total_cost: Decimal
    normalized_unit_price: Decimal


@dataclass(frozen=True, slots=True)
class ExcludedOffer:
    offer: ComparableOffer
    reason: str


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    required_quantity: Decimal
    base_unit: str
    offers: tuple[ProcurementCalculation, ...]
    excluded: tuple[ExcludedOffer, ...]
    by_total_cost: tuple[uuid.UUID, ...]
    by_unit_price: tuple[uuid.UUID, ...]
    by_excess_quantity: tuple[uuid.UUID, ...]
    best_total_cost_offer_id: uuid.UUID | None
    best_unit_price_offer_id: uuid.UUID | None
    lowest_excess_offer_id: uuid.UUID | None


def normalize_required_quantity(quantity: Decimal | str | int, unit: str) -> tuple[Decimal, str]:
    try:
        value = Decimal(str(quantity))
    except InvalidOperation as exc:
        raise ValueError("quantity must be numeric") from exc
    if value <= 0:
        raise ValueError("quantity must be greater than zero")
    normalized_unit = unit.strip().casefold()
    if normalized_unit not in UNIT_FACTORS:
        raise ValueError(f"unsupported unit: {unit}")
    factor, base_unit = UNIT_FACTORS[normalized_unit]
    return (value * factor).normalize(), base_unit


def compare_offers(
    *,
    required_quantity: Decimal | str | int,
    required_unit: str,
    offers: list[ComparableOffer],
) -> ComparisonResult:
    required, base_unit = normalize_required_quantity(required_quantity, required_unit)
    calculated: list[ProcurementCalculation] = []
    excluded: list[ExcludedOffer] = []

    for offer in offers:
        reason = _exclusion_reason(offer, base_unit)
        if reason:
            excluded.append(ExcludedOffer(offer, reason))
            continue
        pack_quantity = offer.pack_total_quantity
        pack_price = offer.pack_price
        packs = int((required / pack_quantity).to_integral_value(rounding=ROUND_CEILING))
        purchased = pack_quantity * packs
        calculated.append(
            ProcurementCalculation(
                offer=offer,
                packs_required=packs,
                quantity_purchased=purchased.normalize(),
                excess_quantity=(purchased - required).normalize(),
                total_cost=(pack_price * packs).quantize(Decimal("0.01")),
                normalized_unit_price=(pack_price / pack_quantity).quantize(
                    Decimal("0.0001")
                ),
            )
        )

    by_total = sorted(calculated, key=lambda item: (item.total_cost, str(item.offer.offer_id)))
    by_unit = sorted(
        calculated, key=lambda item: (item.normalized_unit_price, str(item.offer.offer_id))
    )
    by_excess = sorted(
        calculated,
        key=lambda item: (item.excess_quantity, item.total_cost, str(item.offer.offer_id)),
    )
    return ComparisonResult(
        required_quantity=required,
        base_unit=base_unit,
        offers=tuple(calculated),
        excluded=tuple(excluded),
        by_total_cost=tuple(item.offer.offer_id for item in by_total),
        by_unit_price=tuple(item.offer.offer_id for item in by_unit),
        by_excess_quantity=tuple(item.offer.offer_id for item in by_excess),
        best_total_cost_offer_id=by_total[0].offer.offer_id if by_total else None,
        best_unit_price_offer_id=by_unit[0].offer.offer_id if by_unit else None,
        lowest_excess_offer_id=by_excess[0].offer.offer_id if by_excess else None,
    )


def _exclusion_reason(offer: ComparableOffer, base_unit: str) -> str | None:
    if offer.availability is not True:
        return "unavailable" if offer.availability is False else "availability_unknown"
    if offer.pack_price is None or offer.pack_price < 0:
        return "price_unknown"
    if offer.pack_total_quantity is None or offer.pack_total_quantity <= 0:
        return "pack_size_unknown"
    if offer.base_unit != base_unit:
        return "incompatible_unit"
    return None

