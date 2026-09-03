from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from difflib import SequenceMatcher
from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from procurement_assistant.auth import TenantContext
from procurement_assistant.models import (
    CanonicalProduct,
    ExpenseEntry,
    InventoryItem,
    InventoryTransaction,
    PriceObservation,
    ProductMatch,
    ProductVariant,
    Purchase,
    PurchaseItem,
    ScrapeRun,
    Supplier,
    SupplierLocation,
    SupplierLocationMapping,
    SupplierOffer,
    SupplierProduct,
)
from procurement_assistant.normalization import normalize_product_name
from procurement_assistant.procurement import ComparableOffer, compare_offers
from procurement_assistant.schemas import (
    InventoryAdjustmentRequest,
    PurchaseRequest,
)


def mapped_supplier_locations(session: Session, tenant: TenantContext) -> list[uuid.UUID]:
    return list(
        session.scalars(
            select(SupplierLocationMapping.supplier_location_id).where(
                SupplierLocationMapping.restaurant_location_id == tenant.restaurant_location_id,
                SupplierLocationMapping.active.is_(True),
            )
        )
    )


def search_products(session: Session, query: str, *, limit: int = 25) -> list[dict]:
    query = query.strip()
    if not query:
        return []
    pattern = f"%{query}%"
    candidates = list(
        session.scalars(
            select(CanonicalProduct)
            .where(
                CanonicalProduct.status != "deprecated",
                or_(
                    CanonicalProduct.display_name.ilike(pattern),
                    CanonicalProduct.normalized_name.ilike(pattern),
                    CanonicalProduct.canonical_brand.ilike(pattern),
                    CanonicalProduct.category.ilike(pattern),
                ),
            )
            .limit(limit * 3)
        )
    )
    raw_matches = session.execute(
        select(CanonicalProduct)
        .join(ProductMatch, ProductMatch.canonical_product_id == CanonicalProduct.id)
        .join(SupplierProduct, SupplierProduct.id == ProductMatch.supplier_product_id)
        .where(SupplierProduct.source_name.ilike(pattern))
        .limit(limit * 2)
    ).scalars()
    fuzzy_pool = session.scalars(
        select(CanonicalProduct)
        .where(CanonicalProduct.status != "deprecated")
        .order_by(CanonicalProduct.id)
        .limit(5000)
    )
    by_id = {item.id: item for item in [*candidates, *raw_matches, *fuzzy_pool]}
    normalized_query = normalize_product_name(query)

    def score(product: CanonicalProduct):
        display = product.display_name.casefold()
        normalized = product.normalized_name.casefold()
        alternatives = [
            normalized,
            display,
            (product.canonical_brand or "").casefold(),
            (product.category or "").casefold(),
            *(alias.casefold() for alias in product.aliases),
        ]
        exact = normalized_query in alternatives or query.casefold() in alternatives
        prefix = normalized.startswith(normalized_query)
        fuzzy = max(SequenceMatcher(None, normalized_query, value).ratio() for value in alternatives)
        return exact, prefix, fuzzy

    ranked = [
        product
        for product in sorted(
            by_id.values(), key=lambda product: (*score(product), str(product.id)), reverse=True
        )
        if score(product)[0] or score(product)[1] or score(product)[2] >= 0.45
    ]
    return [
        {
            "id": product.id,
            "display_name": product.display_name,
            "brand": product.canonical_brand,
            "category": product.category,
            "status": product.status,
            "match_score": round(score(product)[2], 4),
        }
        for product in ranked[:limit]
    ]


def get_product(session: Session, product_id: uuid.UUID) -> CanonicalProduct:
    product = session.get(CanonicalProduct, product_id)
    if product is None or product.status == "deprecated":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return product


def get_offer_rows(
    session: Session, tenant: TenantContext, product_id: uuid.UUID
) -> list[tuple]:
    locations = mapped_supplier_locations(session, tenant)
    if not locations:
        return []
    return session.execute(
        select(SupplierOffer, ProductVariant, SupplierProduct, Supplier, SupplierLocation)
        .join(SupplierProduct, SupplierProduct.id == SupplierOffer.supplier_product_id)
        .join(ProductMatch, ProductMatch.supplier_product_id == SupplierProduct.id)
        .outerjoin(ProductVariant, ProductVariant.id == SupplierOffer.product_variant_id)
        .join(Supplier, Supplier.id == SupplierProduct.supplier_id)
        .join(SupplierLocation, SupplierLocation.id == SupplierOffer.supplier_location_id)
        .where(
            ProductMatch.canonical_product_id == product_id,
            SupplierOffer.supplier_location_id.in_(locations),
            SupplierOffer.active.is_(True),
        )
    ).all()


def serialize_offers(rows: list[tuple], *, stale_after_hours: int) -> list[dict]:
    stale_cutoff = datetime.now(UTC) - timedelta(hours=stale_after_hours)
    result = []
    for offer, variant, product, supplier, location in rows:
        last_seen = offer.last_seen_at
        if last_seen and last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=UTC)
        result.append(
            {
                "id": offer.id,
                "product_variant_id": variant.id if variant else None,
                "supplier_id": supplier.id,
                "supplier": supplier.name,
                "supplier_location": location.name,
                "product_name": product.source_name,
                "pack": product.source_pack_text
                or (variant.normalized_pack_text if variant else None),
                "pack_total_quantity": variant.total_quantity if variant else None,
                "base_unit": variant.base_unit if variant else None,
                "price": offer.current_price,
                "mrp": offer.current_mrp,
                "availability": offer.current_availability,
                "last_checked": offer.last_seen_at,
                "stale": not last_seen or last_seen < stale_cutoff,
                "product_url": product.product_url,
                "image_url": product.image_url,
            }
        )
    return result


def compare_product_offers(
    session: Session,
    tenant: TenantContext,
    *,
    product_id: uuid.UUID,
    required_quantity: Decimal,
    unit: str,
    stale_after_hours: int = 48,
) -> dict:
    get_product(session, product_id)
    rows = get_offer_rows(session, tenant, product_id)
    comparable = [
        ComparableOffer(
            offer_id=offer.id,
            supplier=supplier.name,
            product_name=product.source_name,
            pack_text=product.source_pack_text
            or (variant.normalized_pack_text if variant else None),
            pack_price=offer.current_price,
            pack_total_quantity=variant.total_quantity if variant else None,
            base_unit=variant.base_unit if variant else None,
            availability=offer.current_availability,
            product_url=product.product_url,
        )
        for offer, variant, product, supplier, _location in rows
    ]
    result = compare_offers(
        required_quantity=required_quantity, required_unit=unit, offers=comparable
    )
    serialized_rows = {
        row["id"]: row for row in serialize_offers(rows, stale_after_hours=stale_after_hours)
    }
    calculations = []
    for item in result.offers:
        calculations.append(
            {
                **serialized_rows[item.offer.offer_id],
                "packs_required": item.packs_required,
                "quantity_purchased": item.quantity_purchased,
                "excess_quantity": item.excess_quantity,
                "total_cost": item.total_cost,
                "normalized_unit_price": item.normalized_unit_price,
            }
        )
    return {
        "required_quantity": result.required_quantity,
        "base_unit": result.base_unit,
        "offers": calculations,
        "excluded": [
            {"offer_id": item.offer.offer_id, "reason": item.reason} for item in result.excluded
        ],
        "rankings": {
            "by_total_cost": result.by_total_cost,
            "by_unit_price": result.by_unit_price,
            "by_excess_quantity": result.by_excess_quantity,
        },
        "best_total_cost_offer_id": result.best_total_cost_offer_id,
        "best_unit_price_offer_id": result.best_unit_price_offer_id,
        "lowest_excess_offer_id": result.lowest_excess_offer_id,
    }


def record_purchase(
    session: Session, tenant: TenantContext, payload: PurchaseRequest
) -> Purchase:
    location_ids = set(mapped_supplier_locations(session, tenant))
    supplier = session.get(Supplier, payload.supplier_id)
    if supplier is None or not supplier.active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid supplier")
    total = sum((item.actual_total_price for item in payload.items), Decimal("0"))
    purchase = Purchase(
        restaurant_id=tenant.restaurant_id,
        restaurant_location_id=tenant.restaurant_location_id,
        supplier_id=payload.supplier_id,
        purchased_at=payload.purchased_at,
        total_amount=total,
        notes=payload.notes,
        created_by_user_id=tenant.user_id,
    )
    session.add(purchase)
    session.flush()
    for item in payload.items:
        variant = session.get(ProductVariant, item.product_variant_id)
        if variant is None or variant.canonical_product_id != item.canonical_product_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid product variant")
        if item.unit != variant.base_unit:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Purchase unit is incompatible")
        offer = session.get(SupplierOffer, item.supplier_offer_id) if item.supplier_offer_id else None
        if item.supplier_offer_id and offer is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid supplier offer")
        if item.supplier_product_url_snapshot:
            parsed_url = urlparse(item.supplier_product_url_snapshot)
            if parsed_url.scheme != "https" or not parsed_url.netloc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Supplier URL must use HTTPS")
        if offer is not None:
            source_product = session.get(SupplierProduct, offer.supplier_product_id)
            match = session.scalar(
                select(ProductMatch).where(
                    ProductMatch.supplier_product_id == offer.supplier_product_id
                )
            )
            if (
                source_product is None
                or offer.supplier_location_id not in location_ids
                or source_product.supplier_id != payload.supplier_id
                or match is None
                or match.canonical_product_id != item.canonical_product_id
                or (
                    offer.product_variant_id is not None
                    and offer.product_variant_id != item.product_variant_id
                )
            ):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Supplier offer is outside tenant")
        purchase_item = PurchaseItem(
            purchase_id=purchase.id,
            canonical_product_id=item.canonical_product_id,
            product_variant_id=item.product_variant_id,
            supplier_offer_id=item.supplier_offer_id,
            supplier_product_url_snapshot=item.supplier_product_url_snapshot,
            packs=item.packs,
            quantity=item.quantity,
            unit=item.unit,
            scraped_price_snapshot=item.scraped_price_snapshot,
            actual_unit_price=item.actual_unit_price,
            actual_total_price=item.actual_total_price,
        )
        session.add(purchase_item)
        session.flush()
        inventory = session.scalar(
            select(InventoryItem).where(
                InventoryItem.restaurant_id == tenant.restaurant_id,
                InventoryItem.restaurant_location_id == tenant.restaurant_location_id,
                InventoryItem.canonical_product_id == item.canonical_product_id,
                InventoryItem.base_unit == item.unit,
            )
        )
        if inventory is None:
            inventory = InventoryItem(
                restaurant_id=tenant.restaurant_id,
                restaurant_location_id=tenant.restaurant_location_id,
                canonical_product_id=item.canonical_product_id,
                base_unit=item.unit,
                current_quantity=Decimal("0"),
            )
            session.add(inventory)
            session.flush()
        inventory.current_quantity += item.quantity
        inventory.updated_at = datetime.now(UTC)
        session.add(
            InventoryTransaction(
                inventory_item_id=inventory.id,
                transaction_type="purchase",
                quantity_delta=item.quantity,
                purchase_item_id=purchase_item.id,
                created_by_user_id=tenant.user_id,
                note=f"Purchase {purchase.id}",
            )
        )
    session.add(
        ExpenseEntry(
            restaurant_id=tenant.restaurant_id,
            restaurant_location_id=tenant.restaurant_location_id,
            purchase_id=purchase.id,
            category="procurement",
            amount=total,
            expense_date=payload.purchased_at.date(),
            supplier_id=payload.supplier_id,
        )
    )
    session.commit()
    session.refresh(purchase)
    return purchase


def adjust_inventory(
    session: Session, tenant: TenantContext, payload: InventoryAdjustmentRequest
) -> InventoryItem:
    if payload.transaction_type not in {"manual_add", "manual_remove", "correction"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid adjustment type")
    if payload.quantity_delta == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Adjustment cannot be zero")
    if payload.transaction_type == "manual_add" and payload.quantity_delta < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Manual add must be positive")
    if payload.transaction_type == "manual_remove" and payload.quantity_delta > 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Manual remove must be negative")
    inventory = session.scalar(
        select(InventoryItem).where(
            InventoryItem.restaurant_id == tenant.restaurant_id,
            InventoryItem.restaurant_location_id == tenant.restaurant_location_id,
            InventoryItem.canonical_product_id == payload.canonical_product_id,
            InventoryItem.base_unit == payload.base_unit,
        )
    )
    if inventory is None:
        inventory = InventoryItem(
            restaurant_id=tenant.restaurant_id,
            restaurant_location_id=tenant.restaurant_location_id,
            canonical_product_id=payload.canonical_product_id,
            base_unit=payload.base_unit,
            current_quantity=Decimal("0"),
        )
        session.add(inventory)
        session.flush()
    new_quantity = inventory.current_quantity + payload.quantity_delta
    if new_quantity < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Inventory cannot become negative")
    inventory.current_quantity = new_quantity
    inventory.updated_at = datetime.now(UTC)
    session.add(
        InventoryTransaction(
            inventory_item_id=inventory.id,
            transaction_type=payload.transaction_type,
            quantity_delta=payload.quantity_delta,
            created_by_user_id=tenant.user_id,
            note=payload.note,
        )
    )
    session.commit()
    session.refresh(inventory)
    return inventory


def spending_analytics(session: Session, tenant: TenantContext) -> dict:
    today = date.today()
    month_start = date(today.year, today.month, 1)
    base = [
        ExpenseEntry.restaurant_id == tenant.restaurant_id,
        ExpenseEntry.restaurant_location_id == tenant.restaurant_location_id,
    ]
    month_total = session.scalar(
        select(func.coalesce(func.sum(ExpenseEntry.amount), 0)).where(
            *base, ExpenseEntry.expense_date >= month_start
        )
    )
    by_supplier = session.execute(
        select(Supplier.id, Supplier.name, func.sum(ExpenseEntry.amount))
        .join(ExpenseEntry, ExpenseEntry.supplier_id == Supplier.id)
        .where(*base)
        .group_by(Supplier.id, Supplier.name)
        .order_by(func.sum(ExpenseEntry.amount).desc())
    ).all()
    over_time = session.execute(
        select(ExpenseEntry.expense_date, func.sum(ExpenseEntry.amount))
        .where(*base)
        .group_by(ExpenseEntry.expense_date)
        .order_by(ExpenseEntry.expense_date)
    ).all()
    by_product = session.execute(
        select(
            CanonicalProduct.id,
            CanonicalProduct.display_name,
            CanonicalProduct.category,
            func.sum(PurchaseItem.actual_total_price),
        )
        .join(PurchaseItem, PurchaseItem.canonical_product_id == CanonicalProduct.id)
        .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .where(
            Purchase.restaurant_id == tenant.restaurant_id,
            Purchase.restaurant_location_id == tenant.restaurant_location_id,
        )
        .group_by(
            CanonicalProduct.id, CanonicalProduct.display_name, CanonicalProduct.category
        )
        .order_by(func.sum(PurchaseItem.actual_total_price).desc())
    ).all()
    category_totals: dict[str, Decimal] = defaultdict(Decimal)
    for _product_id, _name, category, amount in by_product:
        category_totals[category or "Uncategorized"] += amount
    recent = session.execute(
        select(Purchase, Supplier)
        .join(Supplier, Supplier.id == Purchase.supplier_id)
        .where(
            Purchase.restaurant_id == tenant.restaurant_id,
            Purchase.restaurant_location_id == tenant.restaurant_location_id,
        )
        .order_by(Purchase.purchased_at.desc())
        .limit(10)
    ).all()
    return {
        "current_month_spend": month_total,
        "by_supplier": [
            {"supplier_id": supplier_id, "supplier": name, "amount": amount}
            for supplier_id, name, amount in by_supplier
        ],
        "over_time": [{"date": day, "amount": amount} for day, amount in over_time],
        "by_product": [
            {
                "product_id": product_id,
                "product": name,
                "category": category,
                "amount": amount,
            }
            for product_id, name, category, amount in by_product
        ],
        "by_category": [
            {"category": category, "amount": amount}
            for category, amount in sorted(
                category_totals.items(), key=lambda item: item[1], reverse=True
            )
        ],
        "recent_purchases": [
            {
                "purchase_id": purchase.id,
                "supplier": supplier.name,
                "purchased_at": purchase.purchased_at,
                "amount": purchase.total_amount,
            }
            for purchase, supplier in recent
        ],
    }


def price_history(
    session: Session, tenant: TenantContext, product_id: uuid.UUID
) -> dict:
    locations = mapped_supplier_locations(session, tenant)
    rows = session.execute(
        select(PriceObservation, SupplierOffer.id, Supplier, SupplierLocation, ScrapeRun)
        .join(SupplierOffer, SupplierOffer.id == PriceObservation.supplier_offer_id)
        .join(SupplierProduct, SupplierProduct.id == SupplierOffer.supplier_product_id)
        .join(ProductMatch, ProductMatch.supplier_product_id == SupplierProduct.id)
        .join(Supplier, Supplier.id == SupplierProduct.supplier_id)
        .join(SupplierLocation, SupplierLocation.id == SupplierOffer.supplier_location_id)
        .outerjoin(ScrapeRun, ScrapeRun.id == PriceObservation.scrape_run_id)
        .where(
            ProductMatch.canonical_product_id == product_id,
            SupplierOffer.supplier_location_id.in_(locations),
        )
        .order_by(PriceObservation.observed_at)
    ).all()
    observations = []
    trusted_prices: list[tuple[datetime, Decimal]] = []
    for observation, offer_id, supplier, location, run in rows:
        trusted = run is not None and run.status == "complete"
        observed_at = observation.observed_at
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)
        observations.append(
            {
                "id": observation.id,
                "offer_id": offer_id,
                "supplier": supplier.name,
                "supplier_location": location.name,
                "price": observation.price,
                "mrp": observation.mrp,
                "availability": observation.availability,
                "observed_at": observed_at,
                "trusted_for_statistics": trusted,
                "data_quality": "complete_run" if trusted else "legacy_or_incomplete",
            }
        )
        if trusted and observation.price is not None:
            trusted_prices.append((observed_at, observation.price))
    now = datetime.now(UTC)

    def stats(days: int):
        values = [price for timestamp, price in trusted_prices if timestamp >= now - timedelta(days=days)]
        if len(values) < 2:
            return {"low": None, "average": None, "sample_count": len(values)}
        return {
            "low": min(values),
            "average": (sum(values) / len(values)).quantize(Decimal("0.01")),
            "sample_count": len(values),
        }

    latest = observations[-1] if observations else None
    return {
        "current_price": latest["price"] if latest else None,
        "last_observed_at": latest["observed_at"] if latest else None,
        "latest_supplier": latest["supplier"] if latest else None,
        "latest_supplier_location": latest["supplier_location"] if latest else None,
        "observations": observations,
        "seven_day": stats(7),
        "thirty_day": stats(30),
    }
