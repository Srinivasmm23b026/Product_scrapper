from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from procurement_assistant import cloud_worker
from procurement_assistant.cloud_worker import build_adapter
from procurement_assistant.database import Base
from procurement_assistant.models import (
    PriceObservation,
    ProductMatch,
    ScrapeRun,
    Supplier,
    SupplierLocation,
    SupplierOffer,
    SupplierProduct,
)
from procurement_assistant.scraping.service import ScrapeRunService
from procurement_assistant.settings import Settings


def test_authenticated_hyperpure_evidence_must_match_a_verified_supplier_location() -> None:
    location = SupplierLocation(
        supplier_id="00000000-0000-0000-0000-000000000001",
        external_location_id="outlet:42",
        location_type="store",
        name="Verified outlet",
        location_metadata={"verified": True},
    )
    product = {
        "authenticated_location": {
            "external_location_id": "outlet:42",
            "verified": True,
            "verification_method": "authenticated_hyperpure_outlet_api",
        }
    }

    assert cloud_worker._verified_hyperpure_location([product], location) == product[
        "authenticated_location"
    ]

    location.location_metadata = {"verified": False}
    with pytest.raises(ValueError, match="not verified"):
        cloud_worker._verified_hyperpure_location([product], location)

    location.location_metadata = {"verified": True}
    product["authenticated_location"]["external_location_id"] = "outlet:other"
    with pytest.raises(ValueError, match="does not match"):
        cloud_worker._verified_hyperpure_location([product], location)


def test_cloud_adapter_persists_catalog_snapshot_and_partial_signal(tmp_path, monkeypatch):
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        supplier = Supplier(code="lots", name="Lots", base_url="https://lots.example")
        session.add(supplier)
        session.flush()
        location = SupplierLocation(
            supplier_id=supplier.id,
            external_location_id="store-101",
            location_type="store",
            name="Store 101",
        )
        session.add(location)
        session.flush()
        supplier_id, location_id = supplier.id, location.id

    products = [
        {
            "source": "lots",
            "external_id": "rice-1",
            "name": "Test Basmati Rice",
            "brand": "Test",
            "category": "Rice",
            "price": 100,
            "mrp": 110,
            "unit": "1 kg",
            "in_stock": 1,
            "product_url": "https://lots.example/rice",
            "location_note": "verified fixture",
        },
        {
            "source": "lots",
            "external_id": "rice-1",
            "name": "Test Basmati Rice",
            "brand": "Test",
            "category": "Rice",
            "price": 100,
            "mrp": 110,
            "unit": "1 kg",
            "in_stock": 1,
            "product_url": "https://lots.example/rice",
            "location_note": "duplicate fallback fixture",
        },
    ]
    monkeypatch.setitem(cloud_worker.SCRAPERS, "lots", lambda: products)
    settings = Settings(database_url="sqlite://", local_storage_path=tmp_path)
    with factory() as session:
        supplier = session.get(Supplier, supplier_id)
        location = session.get(SupplierLocation, location_id)
    adapter = build_adapter(settings, factory, "lots", supplier, location, expected_min=2)
    run_id = ScrapeRunService(factory).execute(
        supplier_id=supplier_id, supplier_location_id=location_id, adapter=adapter
    )

    with factory() as session:
        run = session.get(ScrapeRun, run_id)
        assert run.status == "partial"
        assert run.observed_count == 1
        assert run.run_metadata["source_rows"] == 2
        assert run.warning_count == 1
        product = session.scalar(select(SupplierProduct))
        match = session.scalar(select(ProductMatch))
        offer = session.scalar(select(SupplierOffer))
        observation = session.scalar(select(PriceObservation))
        assert product.source_name == "Test Basmati Rice"
        assert match.review_status == "REVIEW"
        assert offer.current_price == Decimal("100.00")
        assert observation.observed_at is not None
        assert observation.raw_reference
        assert list(tmp_path.rglob("*.json"))
