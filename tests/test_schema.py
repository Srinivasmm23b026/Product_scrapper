from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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

EXPECTED_TABLES = {
    "canonical_products",
    "expense_entries",
    "inventory_items",
    "inventory_transactions",
    "price_observations",
    "product_matches",
    "product_variants",
    "purchase_items",
    "purchases",
    "restaurant_locations",
    "restaurant_memberships",
    "restaurants",
    "scrape_runs",
    "supplier_location_mappings",
    "supplier_locations",
    "supplier_offers",
    "supplier_products",
    "suppliers",
    "users",
}


def sqlite_engine():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


def make_offer_graph(session: Session):
    supplier = Supplier(code="test", name="Test Supplier", base_url="https://example.test")
    product = CanonicalProduct(
        normalized_name="sunflower oil",
        display_name="Sunflower Oil",
        canonical_brand="Fortune",
    )
    session.add_all([supplier, product])
    session.flush()
    location = SupplierLocation(
        supplier_id=supplier.id,
        external_location_id="store-1",
        location_type="store",
        name="Store 1",
    )
    variant = ProductVariant(
        canonical_product_id=product.id,
        quantity=Decimal("1"),
        base_unit="l",
        pack_count=1,
        total_quantity=Decimal("1"),
        normalized_pack_text="1 L",
    )
    supplier_product = SupplierProduct(
        supplier_id=supplier.id,
        external_product_id="sku-1",
        source_name="Fortune Sunflower Oil 1 L",
    )
    session.add_all([location, variant, supplier_product])
    session.flush()
    offer = SupplierOffer(
        supplier_product_id=supplier_product.id,
        product_variant_id=variant.id,
        supplier_location_id=location.id,
    )
    session.add(offer)
    session.flush()
    return supplier, location, offer


def test_metadata_creates_complete_domain_schema() -> None:
    engine = sqlite_engine()
    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES


def test_variant_rejects_incompatible_base_unit() -> None:
    engine = sqlite_engine()
    with Session(engine) as session:
        product = CanonicalProduct(normalized_name="rice", display_name="Rice")
        session.add(product)
        session.flush()
        session.add(
            ProductVariant(
                canonical_product_id=product.id,
                quantity=Decimal("1"),
                total_quantity=Decimal("1"),
                pack_count=1,
                base_unit="metre",
                normalized_pack_text="1 metre",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_observation_requires_offer_and_is_immutable() -> None:
    engine = sqlite_engine()
    with Session(engine) as session:
        supplier, location, offer = make_offer_graph(session)
        run = ScrapeRun(
            supplier_id=supplier.id,
            supplier_location_id=location.id,
            status="complete",
            finished_at=datetime.now(UTC),
            observed_count=1,
        )
        observation = PriceObservation(
            supplier_offer_id=offer.id,
            scrape_run_id=run.id,
            price=Decimal("125.50"),
            mrp=Decimal("130"),
            availability=True,
            observed_at=datetime.now(UTC),
        )
        session.add_all([run, observation])
        session.commit()

        stored = session.scalar(select(PriceObservation))
        assert stored is not None
        stored.price = Decimal("1")
        with pytest.raises(ValueError, match="immutable"):
            session.commit()


def test_initial_alembic_migration_round_trip(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "schema.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database_path}")
    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES | {"alembic_version"}

    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
