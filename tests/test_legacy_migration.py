from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

import db as legacy_db
from procurement_assistant.database import Base
from procurement_assistant.legacy_migration import migrate_legacy_sqlite
from procurement_assistant.models import (
    PriceObservation,
    ProductMatch,
    ProductVariant,
    ScrapeRun,
    SupplierLocation,
    SupplierOffer,
    SupplierProduct,
)


def create_legacy_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(legacy_db.SCHEMA)
    connection.execute(
        "INSERT INTO canonical_products "
        "(id, canonical_name, brand, pack_qty, base_unit, created_at) "
        "VALUES (1, 'Test Rice', 'Test', 1, 'kg', '2026-01-01T00:00:00+00:00')"
    )
    products = [
        (
            1,
            "lots",
            "sku-1",
            "Test Rice 2 x 500 g",
            "Test",
            "Rice",
            100,
            110,
            "2 x 500 g",
            1,
            "kg",
            100,
            1,
            "https://images.test/rice.jpg",
            "https://example.test/rice",
            "110001",
            "fallback store; unverified",
            1,
            "2026-01-01T00:00:00+00:00",
            "2026-01-02T00:00:00+00:00",
        ),
        (
            2,
            "lots",
            "sku-2",
            "Mystery Assortment",
            "Test",
            "Other",
            50,
            50,
            None,
            None,
            None,
            None,
            1,
            None,
            None,
            "",
            None,
            1,
            "2026-01-01T00:00:00+00:00",
            "2026-01-02T00:00:00+00:00",
        ),
    ]
    connection.executemany(
        """
        INSERT INTO products
          (id, source, external_id, name, brand, category, price, mrp, unit, pack_qty,
           base_unit, price_per_unit, in_stock, image_url, product_url, pincode,
           location_note, canonical_id, first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        products,
    )
    connection.executemany(
        """
        INSERT INTO price_history
          (id, source, external_id, price, mrp, price_per_unit, in_stock, pincode, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "lots", "sku-1", 100, 110, 100, 1, "110001", "2026-01-02T00:00:00+00:00"),
            (2, "lots", "sku-2", 50, 50, None, 1, "", "2026-01-02T00:00:00+00:00"),
            (3, "lots", "sku-1", 105, 110, 105, 1, "", "2026-01-01T00:00:00+00:00"),
        ],
    )
    connection.executemany(
        """
        INSERT INTO scrape_runs
          (id, source, started_at, finished_at, products_seen, error)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "lots", "2026-01-02T00:00:00+00:00", "2026-01-02T00:05:00+00:00", 2, None),
            (2, "lots", "2026-01-03T00:00:00+00:00", "2026-01-03T00:01:00+00:00", 0, None),
        ],
    )
    connection.commit()
    connection.close()


def test_legacy_migration_is_reconciled_lossless_and_idempotent(tmp_path) -> None:
    source = tmp_path / "legacy.sqlite3"
    create_legacy_database(source)
    target = create_engine("sqlite://")
    Base.metadata.create_all(target)

    first = migrate_legacy_sqlite(source, target)
    assert first["reconciled"] == {
        "products": True,
        "price_history": True,
        "scrape_runs": True,
    }
    assert first["migrated"]["legacy_product_rows"] == 2
    assert first["migrated"]["price_observations"] == 3
    assert first["migrated"]["history_only_supplier_offers"] == 1
    assert first["transformed"]["observations_without_run_id"] == 3
    assert first["transformed"]["explicit_multipack_rows"] == 1
    assert first["transformed"]["unknown_pack_rows"] == 1

    with Session(target) as session:
        assert session.scalar(select(func.count()).select_from(SupplierProduct)) == 2
        assert session.scalar(select(func.count()).select_from(SupplierOffer)) == 3
        assert session.scalar(select(func.count()).select_from(PriceObservation)) == 3
        assert session.scalar(select(func.count()).select_from(ProductMatch)) == 2
        variants = session.scalars(select(ProductVariant)).all()
        assert len(variants) == 1
        assert variants[0].quantity == 0.5
        assert variants[0].pack_count == 2
        assert variants[0].total_quantity == 1
        unknown_offer = session.scalar(
            select(SupplierOffer)
            .join(SupplierProduct)
            .where(SupplierProduct.external_product_id == "sku-2")
        )
        assert unknown_offer.product_variant_id is None
        assert all(item.scrape_run_id is None for item in session.scalars(select(PriceObservation)))
        assert {run.status for run in session.scalars(select(ScrapeRun))} == {
            "partial",
            "suspicious_zero",
        }
        assert all(
            location.location_metadata["verified"] is False
            for location in session.scalars(select(SupplierLocation))
        )

    second = migrate_legacy_sqlite(source, target)
    assert second["reconciled"] == first["reconciled"]
    assert second["skipped_existing"]["legacy_product_rows"] == 2
    assert second["skipped_existing"]["price_observations"] == 3
    with Session(target) as session:
        assert session.scalar(select(func.count()).select_from(PriceObservation)) == 3
