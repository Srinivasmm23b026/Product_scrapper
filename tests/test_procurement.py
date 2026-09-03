from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from procurement_assistant.procurement import (
    ComparableOffer,
    compare_offers,
    normalize_required_quantity,
)


def offer(
    *,
    price: str | None,
    quantity: str | None,
    unit: str | None = "kg",
    available: bool | None = True,
    seed: int = 1,
) -> ComparableOffer:
    return ComparableOffer(
        offer_id=uuid.UUID(int=seed),
        supplier=f"Supplier {seed}",
        product_name="Test Product",
        pack_text=f"{quantity} {unit}" if quantity and unit else None,
        pack_price=Decimal(price) if price is not None else None,
        pack_total_quantity=Decimal(quantity) if quantity is not None else None,
        base_unit=unit,
        availability=available,
    )


def test_exact_fit() -> None:
    result = compare_offers(
        required_quantity="25", required_unit="kg", offers=[offer(price="500", quantity="5")]
    )
    value = result.offers[0]
    assert value.packs_required == 5
    assert value.quantity_purchased == Decimal("25")
    assert value.excess_quantity == 0
    assert value.total_cost == Decimal("2500.00")
    assert value.normalized_unit_price == Decimal("100.0000")


def test_required_quantity_over_pack_rounds_up() -> None:
    result = compare_offers(
        required_quantity="6", required_unit="kg", offers=[offer(price="500", quantity="5")]
    )
    value = result.offers[0]
    assert value.packs_required == 2
    assert value.quantity_purchased == Decimal("10")
    assert value.excess_quantity == Decimal("4")
    assert value.total_cost == Decimal("1000.00")


def test_mass_and_volume_inputs_are_normalized() -> None:
    assert normalize_required_quantity("2500", "g") == (Decimal("2.5"), "kg")
    assert normalize_required_quantity("1500", "ml") == (Decimal("1.5"), "l")
    assert normalize_required_quantity("12", "pcs") == (Decimal("12"), "piece")


def test_multipack_uses_total_pack_quantity() -> None:
    result = compare_offers(
        required_quantity="1.2",
        required_unit="kg",
        offers=[offer(price="200", quantity="0.5")],
    )
    assert result.offers[0].packs_required == 3
    assert result.offers[0].quantity_purchased == Decimal("1.5")


def test_unavailable_unknown_and_incompatible_offers_are_excluded() -> None:
    offers = [
        offer(price="100", quantity="1", available=False, seed=1),
        offer(price="100", quantity=None, seed=2),
        offer(price="100", quantity="1", unit="l", seed=3),
        offer(price=None, quantity="1", seed=4),
    ]
    result = compare_offers(required_quantity=1, required_unit="kg", offers=offers)
    assert not result.offers
    assert [item.reason for item in result.excluded] == [
        "unavailable",
        "pack_size_unknown",
        "incompatible_unit",
        "price_unknown",
    ]


def test_rankings_distinguish_total_unit_price_and_excess() -> None:
    bulk = offer(price="800", quantity="10", seed=1)
    exact = offer(price="100", quantity="1", seed=2)
    result = compare_offers(required_quantity=1, required_unit="kg", offers=[bulk, exact])
    assert result.best_total_cost_offer_id == exact.offer_id
    assert result.best_unit_price_offer_id == bulk.offer_id
    assert result.lowest_excess_offer_id == exact.offer_id
    assert result.by_total_cost != result.by_unit_price


@pytest.mark.parametrize(
    ("quantity", "unit"),
    [(0, "kg"), (-1, "kg"), ("not-a-number", "kg"), (1, "metre")],
)
def test_invalid_requirements_are_rejected(quantity, unit) -> None:
    with pytest.raises(ValueError):
        compare_offers(required_quantity=quantity, required_unit=unit, offers=[])

