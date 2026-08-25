from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from procurement_assistant.database import Base
from procurement_assistant.models import (
    CanonicalProduct,
    PriceObservation,
    ProductVariant,
    ScrapeRun,
    Supplier,
    SupplierLocation,
    SupplierOffer,
    SupplierProduct,
)
from procurement_assistant.scraping.service import ScrapePersistenceError, ScrapeRunService
from procurement_assistant.scraping.types import OfferObservationInput, ScrapeResult


@pytest.fixture
def scrape_context():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        supplier = Supplier(code="supplier", name="Supplier", base_url="https://example.test")
        product = CanonicalProduct(normalized_name="rice", display_name="Rice")
        session.add_all([supplier, product])
        session.flush()
        location = SupplierLocation(
            supplier_id=supplier.id,
            external_location_id="store",
            location_type="store",
            name="Store",
        )
        variant = ProductVariant(
            canonical_product_id=product.id,
            quantity=Decimal("1"),
            base_unit="kg",
            pack_count=1,
            total_quantity=Decimal("1"),
            normalized_pack_text="1 kg",
        )
        source_product = SupplierProduct(
            supplier_id=supplier.id,
            external_product_id="rice-1",
            source_name="Rice 1 kg",
        )
        session.add_all([location, variant, source_product])
        session.flush()
        first_offer = SupplierOffer(
            supplier_product_id=source_product.id,
            product_variant_id=variant.id,
            supplier_location_id=location.id,
        )
        session.add(first_offer)
        session.flush()
        context = factory, supplier.id, location.id, first_offer.id
    return context


def observed(offer_id, price: str = "100") -> OfferObservationInput:
    return OfferObservationInput(
        supplier_offer_id=offer_id,
        price=Decimal(price),
        mrp=Decimal(price),
        availability=True,
        observed_at=datetime.now(UTC),
    )


def test_zero_is_suspicious_and_does_not_retire_offer(scrape_context) -> None:
    factory, supplier_id, location_id, offer_id = scrape_context
    service = ScrapeRunService(factory, retire_after_misses=1)

    run_id = service.execute(
        supplier_id=supplier_id,
        supplier_location_id=location_id,
        adapter=lambda: ScrapeResult(expected_count=10, complete_signal=True),
    )

    with factory() as session:
        run = session.get(ScrapeRun, run_id)
        offer = session.get(SupplierOffer, offer_id)
        assert run.status == "suspicious_zero"
        assert offer.active is True
        assert offer.consecutive_misses == 0


def test_partial_run_persists_seen_data_but_does_not_advance_misses(scrape_context) -> None:
    factory, supplier_id, location_id, offer_id = scrape_context
    service = ScrapeRunService(factory, retire_after_misses=1)

    run_id = service.execute(
        supplier_id=supplier_id,
        supplier_location_id=location_id,
        adapter=lambda: ScrapeResult(
            observations=(observed(offer_id),),
            expected_count=2,
            failed_pages=("page 2 timeout",),
            complete_signal=False,
        ),
    )

    with factory() as session:
        run = session.get(ScrapeRun, run_id)
        assert run.status == "partial"
        assert run.failed_page_count == 1
        assert session.scalar(select(PriceObservation).where(PriceObservation.scrape_run_id == run_id))


def test_only_complete_run_advances_absence_counter(scrape_context) -> None:
    factory, supplier_id, location_id, offer_id = scrape_context
    service = ScrapeRunService(factory, retire_after_misses=1)
    with factory.begin() as session:
        first_offer = session.get(SupplierOffer, offer_id)
        source_product = SupplierProduct(
            supplier_id=supplier_id,
            external_product_id="rice-2",
            source_name="Other Rice 1 kg",
        )
        session.add(source_product)
        session.flush()
        missing_offer = SupplierOffer(
            supplier_product_id=source_product.id,
            product_variant_id=first_offer.product_variant_id,
            supplier_location_id=location_id,
        )
        session.add(missing_offer)
        session.flush()
        missing_offer_id = missing_offer.id

    run_id = service.execute(
        supplier_id=supplier_id,
        supplier_location_id=location_id,
        adapter=lambda: ScrapeResult(
            observations=(
                OfferObservationInput(
                    supplier_offer_id=offer_id,
                    price=Decimal("100"),
                    mrp=Decimal("100"),
                    availability=True,
                    observed_at=datetime.now(UTC),
                ),
            ),
            expected_count=1,
            complete_signal=True,
        ),
    )
    with factory() as session:
        assert session.get(ScrapeRun, run_id).status == "complete"
        assert session.get(SupplierOffer, offer_id).consecutive_misses == 0
        retired = session.get(SupplierOffer, missing_offer_id)
        assert retired.consecutive_misses == 1
        assert retired.active is False
        assert retired.current_availability is False


def test_adapter_failure_records_failed_run_without_observations(scrape_context) -> None:
    factory, supplier_id, location_id, _offer_id = scrape_context
    service = ScrapeRunService(factory)

    def fail():
        raise RuntimeError("network unavailable")

    run_id = service.execute(
        supplier_id=supplier_id, supplier_location_id=location_id, adapter=fail
    )
    with factory() as session:
        run = session.get(ScrapeRun, run_id)
        assert run.status == "failed"
        assert "network unavailable" in run.error_summary
        assert session.scalar(select(PriceObservation)) is None


def test_persistence_failure_rolls_back_every_observation(scrape_context) -> None:
    factory, supplier_id, location_id, offer_id = scrape_context
    service = ScrapeRunService(factory)
    duplicate = observed(offer_id)

    with pytest.raises(ScrapePersistenceError):
        service.execute(
            supplier_id=supplier_id,
            supplier_location_id=location_id,
            adapter=lambda: ScrapeResult(
                observations=(duplicate, duplicate), expected_count=2, complete_signal=True
            ),
        )

    with factory() as session:
        run = session.scalar(select(ScrapeRun))
        assert run.status == "failed"
        assert "duplicate offer" in run.error_summary
        assert session.scalar(select(PriceObservation)) is None


def test_stale_running_runs_become_interrupted(scrape_context) -> None:
    factory, supplier_id, location_id, _offer_id = scrape_context
    with factory.begin() as session:
        stale = ScrapeRun(
            supplier_id=supplier_id,
            supplier_location_id=location_id,
            status="running",
            started_at=datetime.now(UTC) - timedelta(hours=2),
        )
        session.add(stale)

    service = ScrapeRunService(factory)
    assert service.mark_interrupted(older_than=timedelta(hours=1)) == 1
    with factory() as session:
        assert session.get(ScrapeRun, stale.id).status == "interrupted"
