"""Batch supplier catalogue ingestion without per-product database queries."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select

from procurement_assistant.models import (
    CanonicalProduct,
    ProductMatch,
    ProductVariant,
    SupplierOffer,
    SupplierProduct,
)
from procurement_assistant.normalization import normalize_product_name, parse_pack


def catalog_offers(session, supplier, location, rows):
    products = {
        (product.external_product_id, product.external_variant_id): product
        for product in session.scalars(
            select(SupplierProduct).where(SupplierProduct.supplier_id == supplier.id)
        )
    }
    matches = {
        match.supplier_product_id: match
        for match in session.scalars(
            select(ProductMatch)
            .join(SupplierProduct)
            .where(SupplierProduct.supplier_id == supplier.id)
        )
    }
    offers = {
        offer.supplier_product_id: offer
        for offer in session.scalars(
            select(SupplierOffer).where(SupplierOffer.supplier_location_id == location.id)
        )
    }
    pending = ([], [], [], [], [])
    new_products, new_canonicals, new_variants, new_matches, new_offers = pending
    result = []

    for row in rows:
        identity = (str(row["external_id"]), str(row.get("external_variant_id") or ""))
        product = products.get(identity)
        if product is None:
            product = SupplierProduct(
                id=uuid.uuid4(),
                supplier_id=supplier.id,
                external_product_id=identity[0],
                external_variant_id=identity[1],
                source_name=row.get("name") or identity[0],
            )
            products[identity] = product
            new_products.append(product)
            canonical = CanonicalProduct(
                id=uuid.uuid4(),
                normalized_name=normalize_product_name(product.source_name, row.get("brand")),
                display_name=product.source_name,
                canonical_brand=row.get("brand"),
                category=row.get("category"),
                status="review",
                aliases=[],
            )
            new_canonicals.append(canonical)
            parsed = parse_pack(row.get("unit"), product.source_name)
            variant = None
            if parsed:
                variant = ProductVariant(
                    id=uuid.uuid4(),
                    canonical_product_id=canonical.id,
                    quantity=parsed.quantity,
                    base_unit=parsed.base_unit,
                    pack_count=parsed.pack_count,
                    total_quantity=parsed.total_quantity,
                    normalized_pack_text=parsed.normalized_text,
                    attributes={"created_by": "cloud_worker"},
                )
                new_variants.append(variant)
            match = ProductMatch(
                id=uuid.uuid4(),
                supplier_product_id=product.id,
                canonical_product_id=canonical.id,
                product_variant_id=variant.id if variant else None,
                match_method="new_source_product_v1",
                confidence=Decimal("0"),
                review_status="REVIEW",
            )
            matches[product.id] = match
            new_matches.append(match)

        product.source_name = row.get("name") or product.source_name
        product.source_brand = row.get("brand")
        product.source_category = row.get("category")
        product.source_pack_text = row.get("unit")
        product.product_url = row.get("product_url")
        product.image_url = row.get("image_url")
        product.product_metadata = {"location_note": row.get("location_note")}
        match = matches.get(product.id)
        offer = offers.get(product.id)
        if offer is None:
            offer = SupplierOffer(
                id=uuid.uuid4(),
                supplier_product_id=product.id,
                supplier_location_id=location.id,
                active=True,
                consecutive_misses=0,
            )
            offers[product.id] = offer
            new_offers.append(offer)
        offer.product_variant_id = match.product_variant_id if match else None
        result.append((row, offer))

    for group in (new_canonicals, new_products, new_variants, new_matches, new_offers):
        session.add_all(group)
        session.flush()
    return result
