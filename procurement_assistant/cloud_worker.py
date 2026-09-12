from __future__ import annotations

import argparse
import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from procurement_assistant.catalog_ingestion import catalog_offers
from procurement_assistant.database import build_engine, build_session_factory
from procurement_assistant.models import (
    ScrapeRun,
    Supplier,
    SupplierLocation,
)
from procurement_assistant.providers.observability import configure_metrics, log_event
from procurement_assistant.providers.storage import ObjectStorage, configure_storage
from procurement_assistant.scraping.service import ScrapeRunService
from procurement_assistant.scraping.types import OfferObservationInput, ScrapeResult
from procurement_assistant.settings import Settings
from scrapers import bigbasket, deliverit, hyperpure, lots

LOGGER = logging.getLogger("procurement-worker")
SCRAPERS = {
    "hyperpure": hyperpure.scrape_authenticated,
    "bigbasket": bigbasket.scrape,
    "deliverit": deliverit.scrape,
    "lots": lots.scrape,
}


def _write_workflow_authentication_status(status: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as output:
            output.write(f"authentication_status={status}\n")


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
    if (
        not evidence.get("verified")
        or evidence.get("verification_method")
        != "authenticated_hyperpure_outlet_catalogue_api"
    ):
        raise ValueError("Hyperpure outlet evidence is not authenticated verification")
    if evidence.get("external_location_id") != location.external_location_id:
        raise ValueError("authenticated Hyperpure outlet does not match configured supplier location")
    if not location.location_metadata.get("verified"):
        raise ValueError("configured Hyperpure supplier location is not verified")
    return evidence


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
        products = SCRAPERS[source]()
        authenticated_location = (
            _verified_hyperpure_location(products, location) if source == "hyperpure" else None
        )
        raw_reference = _snapshot(settings, storage, source, products)
        observed_at = datetime.now(UTC)
        observations = []
        warnings = []
        with factory.begin() as session:
            db_supplier = session.get(Supplier, supplier.id)
            db_location = session.get(SupplierLocation, location.id)
            valid_rows = []
            identities = set()
            for row in products:
                identity = (
                    str(row.get("external_id") or ""),
                    str(row.get("external_variant_id") or ""),
                )
                if not identity[0]:
                    warnings.append("product without external ID excluded")
                    continue
                if identity in identities:
                    warnings.append(
                        f"{row.get('external_id', 'unknown')}: duplicate supplier offer skipped"
                    )
                    continue
                try:
                    for key in ("price", "mrp"):
                        value = _decimal(row.get(key))
                        if value is not None and (not value.is_finite() or value < 0):
                            raise ValueError("invalid price")
                except (ValueError, ArithmeticError):
                    warnings.append(f"{row.get('external_id', 'unknown')}: invalid price")
                    continue
                identities.add(identity)
                valid_rows.append(row)
            for row, offer in catalog_offers(
                session, db_supplier, db_location, valid_rows
            ):
                try:
                    observations.append(
                        OfferObservationInput(
                            supplier_offer_id=offer.id,
                            price=_decimal(row.get("price")),
                            mrp=_decimal(row.get("mrp")),
                            availability=(
                                None
                                if row.get("in_stock") is None
                                else bool(row.get("in_stock"))
                            ),
                            observed_at=observed_at,
                            raw_reference=raw_reference,
                        )
                    )
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
                    {"authentication_status": products[0].get("authentication_status")}
                    if source == "hyperpure" and products
                    else {}
                ),
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
        if source == "hyperpure":
            authentication_status = (
                scrape_run.run_metadata.get("authentication_status")
                or ("reauthentication-required" if scrape_run.status == "reauthentication_required" else "failed")
            )
            _write_workflow_authentication_status(str(authentication_status))
        if scrape_run.status == "reauthentication_required":
            log_event(
                "hyperpure_authentication_status",
                supplier=source,
                status="reauthentication-required",
                action="run python -m procurement_assistant.hyperpure_auth_bootstrap",
            )
            return 0
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
        if args.supplier == "hyperpure":
            _write_workflow_authentication_status("failed")
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
