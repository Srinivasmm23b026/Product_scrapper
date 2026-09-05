from __future__ import annotations

import argparse
import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from procurement_assistant.database import build_engine, build_session_factory
from procurement_assistant.models import (
    CanonicalProduct,
    ProductMatch,
    ProductVariant,
    ScrapeRun,
    Supplier,
    SupplierLocation,
    SupplierOffer,
    SupplierProduct,
)
from procurement_assistant.normalization import normalize_product_name, parse_pack
from procurement_assistant.providers.observability import configure_metrics, log_event
from procurement_assistant.providers.storage import ObjectStorage, configure_storage
from procurement_assistant.scraping.service import ScrapeRunService
from procurement_assistant.scraping.types import OfferObservationInput, ScrapeResult
from procurement_assistant.settings import Settings
from scrapers import bigbasket, deliverit, hyperpure, lots

LOGGER = logging.getLogger("procurement-worker")
SCRAPERS = {
    "hyperpure": hyperpure.scrape,
    "bigbasket": bigbasket.scrape,
    "deliverit": deliverit.scrape,
    "lots": lots.scrape,
}


def _decimal(value) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _snapshot(
    settings: Settings, storage: ObjectStorage, source: str, products: list[dict]
) -> str:
    timestamp = datetime.now(UTC).strftime("%Y/%m/%d/%H%M%S")
    key = f"{settings.raw_snapshot_prefix.rstrip('/')}/{source}/{timestamp}-{uuid.uuid4()}.json"
    return storage.put_json(key, products)


def _verified_hyperpure_location(products: list[dict], location: SupplierLocation) -> dict | None:
    """Require authenticated outlet evidence to match the worker's DB location.

    The worker may not use a successful account session to overwrite an
    arbitrary supplier location.  Creation/update of the location itself is an
    explicit operator action after this evidence has been inspected.
    """
    identities = {
        json.dumps(row.get("authenticated_location"), sort_keys=True)
        for row in products
        if row.get("authenticated_location")
    }
    if not products:
        return None
    if not identities:
        raise ValueError("authenticated Hyperpure scrape returned no outlet identity evidence")
    if len(identities) != 1:
        raise ValueError("authenticated Hyperpure scrape returned multiple outlet identities")
    evidence = json.loads(identities.pop())
    if not evidence.get("verified") or evidence.get("verification_method") != "authenticated_hyperpure_outlet_api":
        raise ValueError("Hyperpure outlet evidence is not authenticated verification")
    if evidence.get("external_location_id") != location.external_location_id:
        raise ValueError("authenticated Hyperpure outlet does not match configured supplier location")
    if not location.location_metadata.get("verified"):
        raise ValueError("configured Hyperpure supplier location is not verified")
    return evidence


def _catalog_offer(session, supplier, location, row: dict) -> SupplierOffer:
    external_id = str(row.get("external_id") or "").strip()
    if not external_id:
        raise ValueError("scraper returned a product without external_id")
    product = session.scalar(
        select(SupplierProduct).where(
            SupplierProduct.supplier_id == supplier.id,
            SupplierProduct.external_product_id == external_id,
            SupplierProduct.external_variant_id == "",
        )
    )
    if product is None:
        product = SupplierProduct(
            supplier_id=supplier.id,
            external_product_id=external_id,
            external_variant_id="",
            source_name=row.get("name") or f"{supplier.name} product {external_id}",
            source_brand=row.get("brand"),
            source_category=row.get("category"),
            source_pack_text=row.get("unit"),
            product_url=row.get("product_url"),
            image_url=row.get("image_url"),
            product_metadata={"location_note": row.get("location_note")},
        )
        session.add(product)
        session.flush()
        canonical = CanonicalProduct(
            normalized_name=normalize_product_name(product.source_name, product.source_brand),
            display_name=product.source_name,
            canonical_brand=product.source_brand,
            category=product.source_category,
            status="review",
            aliases=[],
        )
        session.add(canonical)
        session.flush()
        parsed = parse_pack(product.source_pack_text, product.source_name)
        variant = None
        if parsed:
            variant = ProductVariant(
                canonical_product_id=canonical.id,
                quantity=parsed.quantity,
                base_unit=parsed.base_unit,
                pack_count=parsed.pack_count,
                total_quantity=parsed.total_quantity,
                normalized_pack_text=parsed.normalized_text,
                attributes={"created_by": "cloud_worker"},
            )
            session.add(variant)
            session.flush()
        session.add(
            ProductMatch(
                supplier_product_id=product.id,
                canonical_product_id=canonical.id,
                product_variant_id=variant.id if variant else None,
                match_method="new_source_product_v1",
                confidence=Decimal("0"),
                review_status="REVIEW",
            )
        )
    else:
        product.source_name = row.get("name") or product.source_name
        product.source_brand = row.get("brand")
        product.source_category = row.get("category")
        product.source_pack_text = row.get("unit")
        product.product_url = row.get("product_url")
        product.image_url = row.get("image_url")
    match = session.scalar(
        select(ProductMatch).where(ProductMatch.supplier_product_id == product.id)
    )
    offer = session.scalar(
        select(SupplierOffer).where(
            SupplierOffer.supplier_product_id == product.id,
            SupplierOffer.supplier_location_id == location.id,
        )
    )
    if offer is None:
        offer = SupplierOffer(
            supplier_product_id=product.id,
            product_variant_id=match.product_variant_id if match else None,
            supplier_location_id=location.id,
            active=True,
            consecutive_misses=0,
        )
        session.add(offer)
        session.flush()
    return offer


def build_adapter(
    settings,
    factory,
    source,
    supplier,
    location,
    expected_min,
    storage: ObjectStorage | None = None,
):
    storage = storage or configure_storage(settings)

    def adapter() -> ScrapeResult:
        if source == "hyperpure" and getattr(__import__("config"), "HYPERPURE_ACCOUNTS", []):
            if not os.environ.get("HYPERPURE_OTP"):
                raise RuntimeError("non-interactive Hyperpure run requires HYPERPURE_OTP")
        products = SCRAPERS[source]()
        authenticated_location = (
            _verified_hyperpure_location(products, location) if source == "hyperpure" else None
        )
        raw_reference = _snapshot(settings, storage, source, products)
        observed_at = datetime.now(UTC)
        observations = []
        observed_offer_ids = set()
        warnings = []
        with factory.begin() as session:
            db_supplier = session.get(Supplier, supplier.id)
            db_location = session.get(SupplierLocation, location.id)
            for row in products:
                try:
                    offer = _catalog_offer(session, db_supplier, db_location, row)
                    if offer.id in observed_offer_ids:
                        warnings.append(
                            f"{row.get('external_id', 'unknown')}: duplicate supplier offer skipped"
                        )
                        continue
                    observations.append(
                        OfferObservationInput(
                            supplier_offer_id=offer.id,
                            price=_decimal(row.get("price")),
                            mrp=_decimal(row.get("mrp")),
                            availability=bool(row.get("in_stock")),
                            observed_at=observed_at,
                            raw_reference=raw_reference,
                        )
                    )
                    observed_offer_ids.add(offer.id)
                except (TypeError, ValueError) as exc:
                    warnings.append(f"{row.get('external_id', 'unknown')}: {exc}")
        expected = expected_min if len(observations) < expected_min else len(observations)
        return ScrapeResult(
            observations=tuple(observations),
            expected_count=expected,
            warnings=tuple(warnings),
            complete_signal=True,
            metadata={
                "raw_snapshot": raw_reference,
                "source_rows": len(products),
                **(
                    {"authenticated_location": authenticated_location}
                    if authenticated_location
                    else {}
                ),
            },
        )

    return adapter


def run(source: str, supplier_location_id: uuid.UUID, expected_min: int) -> int:
    started = time.monotonic()
    settings = Settings()
    factory = build_session_factory(
        build_engine(
            settings.resolved_database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            use_null_pool=settings.db_use_null_pool,
        )
    )
    with factory() as session:
        location = session.get(SupplierLocation, supplier_location_id)
        if location is None:
            raise ValueError(f"unknown supplier location {supplier_location_id}")
        supplier = session.get(Supplier, location.supplier_id)
        if supplier is None or supplier.code != source:
            raise ValueError("supplier location does not belong to requested supplier")
        supplier_id, location_id = supplier.id, location.id
    service = ScrapeRunService(factory)
    adapter = build_adapter(
        settings,
        factory,
        source,
        supplier,
        location,
        expected_min,
        configure_storage(settings),
    )
    run_id = service.execute(
        supplier_id=supplier_id, supplier_location_id=location_id, adapter=adapter
    )
    with factory() as session:
        scrape_run = session.get(ScrapeRun, run_id)
        configure_metrics(settings).record_scrape_run(
            source, scrape_run, time.monotonic() - started
        )
        return 0 if scrape_run.status == "complete" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one non-interactive V1 supplier scrape")
    parser.add_argument(
        "--supplier", default=os.environ.get("SUPPLIER"), choices=sorted(SCRAPERS)
    )
    parser.add_argument(
        "--supplier-location-id",
        default=os.environ.get("SUPPLIER_LOCATION_ID"),
        type=uuid.UUID,
    )
    parser.add_argument(
        "--expected-min", default=os.environ.get("EXPECTED_MIN"), type=int
    )
    args = parser.parse_args()
    if not args.supplier or not args.supplier_location_id or args.expected_min is None:
        parser.error("supplier, supplier-location-id, and expected-min are required")
    if args.expected_min < 1:
        parser.error("--expected-min must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        return run(args.supplier, args.supplier_location_id, args.expected_min)
    except Exception as exc:
        log_event(
            "scrape_worker_crashed",
            supplier=args.supplier,
            supplier_location=str(args.supplier_location_id),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        LOGGER.exception("worker failed before a terminal scrape result")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
