from __future__ import annotations

import argparse
import json
import sqlite3
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from procurement_assistant.database import build_engine
from procurement_assistant.models import (
    CanonicalProduct,
    PriceObservation,
    ProductMatch,
    ProductVariant,
    ScrapeRun,
    Supplier,
    SupplierLocation,
    SupplierOffer,
    SupplierProduct,
)
from procurement_assistant.normalization import normalize_product_name, parse_pack

MIGRATION_NAMESPACE = uuid.UUID("5d37223d-5bb9-4ec0-a42b-18b8c00c56c0")
SUPPLIER_URLS = {
    "hyperpure": "https://www.hyperpure.com",
    "bigbasket": "https://www.bigbasket.com",
    "deliverit": "https://www.deliverit.net.in",
    "lots": "https://www.lotswholesale.com",
}


def stable_id(kind: str, *parts: object) -> uuid.UUID:
    value = ":".join(str(part) for part in parts)
    return uuid.uuid5(MIGRATION_NAMESPACE, f"{kind}:{value}")


def as_decimal(value: object) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def as_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def normalized_pincode(value: object) -> str:
    return str(value or "")


def migrate_legacy_sqlite(source_path: Path, target_engine: Engine) -> dict[str, Any]:
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    report: dict[str, Any] = {
        "source": str(source_path),
        "source_counts": {},
        "migrated": Counter(),
        "skipped_existing": Counter(),
        "rejected": Counter(),
        "transformed": Counter(),
        "limitations": [
            "Legacy price observations have no trustworthy scrape-run attribution.",
            "Legacy pincodes are preserved as unresolved location metadata, not verified stores.",
            "Legacy canonical matches are imported in REVIEW state with zero confidence.",
            "Legacy current availability may be stale and is not expanded into fabricated history.",
        ],
    }
    for table in ("products", "price_history", "scrape_runs", "canonical_products"):
        report["source_counts"][table] = source.execute(
            f"SELECT count(*) FROM {table}"
        ).fetchone()[0]

    products = source.execute("SELECT * FROM products ORDER BY id").fetchall()
    history = source.execute("SELECT * FROM price_history ORDER BY id").fetchall()
    runs = source.execute("SELECT * FROM scrape_runs ORDER BY id").fetchall()
    legacy_groups = {
        row["id"]: row
        for row in source.execute("SELECT * FROM canonical_products ORDER BY id").fetchall()
    }

    notes_by_location: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in products:
        location_key = (row["source"], normalized_pincode(row["pincode"]))
        notes_by_location[location_key]
        if row["location_note"]:
            notes_by_location[location_key].add(row["location_note"])
    for row in history:
        notes_by_location[(row["source"], normalized_pincode(row["pincode"]))]

    with Session(target_engine) as session:
        suppliers = _migrate_suppliers(session, {row["source"] for row in products}, report)
        locations = _migrate_locations(session, suppliers, notes_by_location, report)
        run_locations = _migrate_run_locations(session, suppliers, report)
        canonicals = _migrate_canonicals(session, legacy_groups, products, report)
        offers, current_rows = _migrate_products(
            session, products, suppliers, locations, canonicals, report
        )
        _ensure_history_offers(session, history, suppliers, locations, offers, report)
        _migrate_runs(session, runs, suppliers, run_locations, report)
        latest_observations = _migrate_history(session, history, offers, report)
        _link_current_observations(current_rows, offers, latest_observations)
        session.commit()

    source.close()
    report["migrated"] = dict(sorted(report["migrated"].items()))
    report["skipped_existing"] = dict(sorted(report["skipped_existing"].items()))
    report["rejected"] = dict(sorted(report["rejected"].items()))
    report["transformed"] = dict(sorted(report["transformed"].items()))
    report["reconciled"] = {
        "products": report["source_counts"]["products"]
        == report["migrated"].get("legacy_product_rows", 0)
        + report["skipped_existing"].get("legacy_product_rows", 0)
        + report["rejected"].get("products", 0),
        "price_history": report["source_counts"]["price_history"]
        == report["migrated"].get("price_observations", 0)
        + report["skipped_existing"].get("price_observations", 0)
        + report["rejected"].get("price_observations", 0),
        "scrape_runs": report["source_counts"]["scrape_runs"]
        == report["migrated"].get("scrape_runs", 0)
        + report["skipped_existing"].get("scrape_runs", 0)
        + report["rejected"].get("scrape_runs", 0),
    }
    if not all(report["reconciled"].values()):
        raise RuntimeError(f"legacy reconciliation failed: {report['reconciled']}")
    return report


def _add_once(session: Session, model, key: uuid.UUID, report, counter: str, **values):
    existing = session.get(model, key)
    if existing is not None:
        report["skipped_existing"][counter] += 1
        return existing
    item = model(id=key, **values)
    session.add(item)
    report["migrated"][counter] += 1
    return item


def _migrate_suppliers(session, source_codes, report):
    result = {}
    for code in sorted(source_codes):
        supplier_id = stable_id("supplier", code)
        result[code] = _add_once(
            session,
            Supplier,
            supplier_id,
            report,
            "suppliers",
            code=code,
            name=code.replace("_", " ").title(),
            base_url=SUPPLIER_URLS.get(code, "https://invalid.example"),
            active=code not in {"deliverit"},
        )
    session.flush()
    return result


def _migrate_locations(session, suppliers, notes_by_location, report):
    result = {}
    for (source, pincode), notes in sorted(notes_by_location.items()):
        location_id = stable_id("supplier-location", source, pincode or "unresolved")
        result[(source, pincode)] = _add_once(
            session,
            SupplierLocation,
            location_id,
            report,
            "supplier_locations",
            supplier_id=suppliers[source].id,
            external_location_id=f"legacy:{pincode or 'unresolved'}",
            location_type="unknown" if pincode else "anonymous",
            name=f"Legacy {pincode or 'unresolved'} context",
            pincode=pincode or None,
            location_metadata={
                "legacy": True,
                "verified": False,
                "location_notes": sorted(notes),
            },
            active=True,
        )
    session.flush()
    return result


def _migrate_run_locations(session, suppliers, report):
    result = {}
    for source, supplier in suppliers.items():
        location_id = stable_id("supplier-location", source, "run-unattributed")
        result[source] = _add_once(
            session,
            SupplierLocation,
            location_id,
            report,
            "supplier_locations",
            supplier_id=supplier.id,
            external_location_id="legacy:run-unattributed",
            location_type="unknown",
            name="Legacy run with no location attribution",
            location_metadata={"legacy": True, "verified": False, "run_only": True},
            active=False,
        )
    session.flush()
    return result


def _migrate_canonicals(session, legacy_groups, products, report):
    result = {}
    for legacy_id, row in legacy_groups.items():
        key = stable_id("canonical", legacy_id)
        display_name = row["canonical_name"] or f"Legacy product group {legacy_id}"
        result[legacy_id] = _add_once(
            session,
            CanonicalProduct,
            key,
            report,
            "canonical_products",
            normalized_name=normalize_product_name(display_name, row["brand"]),
            display_name=display_name,
            canonical_brand=row["brand"],
            status="review",
            aliases=[],
        )
    for row in products:
        if row["canonical_id"] is not None:
            continue
        legacy_key = f"product:{row['source']}:{row['external_id']}"
        key = stable_id("canonical", legacy_key)
        result[legacy_key] = _add_once(
            session,
            CanonicalProduct,
            key,
            report,
            "canonical_products",
            normalized_name=normalize_product_name(row["name"] or legacy_key, row["brand"]),
            display_name=row["name"] or legacy_key,
            canonical_brand=row["brand"],
            category=row["category"],
            status="review",
            aliases=[],
        )
    session.flush()
    return result


def _variant_for_row(session, row, canonical, report):
    if row["pack_qty"] is None or row["base_unit"] is None:
        report["transformed"]["unknown_pack_rows"] += 1
        return None
    base_unit = "piece" if row["base_unit"] == "pc" else row["base_unit"].lower()
    total = as_decimal(row["pack_qty"]).normalize()
    parsed = parse_pack(row["unit"], row["name"])
    if parsed and parsed.base_unit == base_unit and abs(parsed.total_quantity - total) <= Decimal(
        "0.000001"
    ):
        quantity, pack_count = parsed.quantity, parsed.pack_count
        normalized_text = parsed.normalized_text
        if pack_count > 1:
            report["transformed"]["explicit_multipack_rows"] += 1
    else:
        quantity, pack_count = total, 1
        normalized_text = f"{total.normalize()} {base_unit}"
    quantity = quantity.normalize()
    variant_id = stable_id(
        "variant", canonical.id, quantity, base_unit, pack_count, total, normalized_text
    )
    return _add_once(
        session,
        ProductVariant,
        variant_id,
        report,
        "product_variants",
        canonical_product_id=canonical.id,
        quantity=quantity,
        base_unit=base_unit,
        pack_count=pack_count,
        total_quantity=total,
        normalized_pack_text=normalized_text,
        attributes={"legacy": True},
    )


def _migrate_products(session, products, suppliers, locations, canonicals, report):
    offers = {}
    current_rows = {}
    for row in products:
        source, external_id = row["source"], row["external_id"]
        if not source or not external_id:
            report["rejected"]["products"] += 1
            continue
        pincode = normalized_pincode(row["pincode"])
        location = locations.get((source, pincode))
        if location is None:
            report["rejected"]["products"] += 1
            continue
        canonical_key = row["canonical_id"] if row["canonical_id"] is not None else (
            f"product:{source}:{external_id}"
        )
        canonical = canonicals[canonical_key]
        variant = _variant_for_row(session, row, canonical, report)
        product_id = stable_id("supplier-product", source, external_id)
        product = _add_once(
            session,
            SupplierProduct,
            product_id,
            report,
            "supplier_products",
            supplier_id=suppliers[source].id,
            external_product_id=str(external_id),
            external_variant_id="",
            source_name=row["name"] or f"Legacy product {external_id}",
            source_brand=row["brand"],
            source_category=row["category"],
            source_pack_text=row["unit"],
            product_url=row["product_url"],
            image_url=row["image_url"],
            product_metadata={"legacy": True},
        )
        session.flush()
        offer_id = stable_id("supplier-offer", source, external_id, location.id)
        offer_existed = session.get(SupplierOffer, offer_id) is not None
        offer = _add_once(
            session,
            SupplierOffer,
            offer_id,
            report,
            "supplier_offers",
            supplier_product_id=product.id,
            product_variant_id=variant.id if variant else None,
            supplier_location_id=location.id,
            active=True,
            current_price=as_decimal(row["price"]),
            current_mrp=as_decimal(row["mrp"]),
            current_availability=bool(row["in_stock"]) if row["in_stock"] is not None else None,
            last_seen_at=as_datetime(row["last_seen"]),
            consecutive_misses=0,
        )
        match_id = stable_id("product-match", product.id)
        _add_once(
            session,
            ProductMatch,
            match_id,
            report,
            "product_matches",
            supplier_product_id=product.id,
            canonical_product_id=canonical.id,
            product_variant_id=variant.id if variant else None,
            match_method="legacy_heuristic_unreviewed",
            confidence=Decimal("0"),
            review_status="REVIEW",
            matched_at=as_datetime(row["last_seen"]) or datetime.fromtimestamp(0, UTC),
        )
        offers[(source, str(external_id), pincode)] = offer
        current_rows[offer.id] = row
        report["skipped_existing" if offer_existed else "migrated"]["legacy_product_rows"] += 1
    session.flush()
    return offers, current_rows


def _migrate_runs(session, runs, suppliers, run_locations, report):
    for row in runs:
        source = row["source"]
        if source not in suppliers:
            report["rejected"]["scrape_runs"] += 1
            continue
        run_id = stable_id("scrape-run", row["id"])
        if row["finished_at"] is None:
            status = "interrupted"
        elif row["error"]:
            status = "failed"
        elif row["products_seen"] == 0:
            status = "suspicious_zero"
        else:
            status = "partial"
        _add_once(
            session,
            ScrapeRun,
            run_id,
            report,
            "scrape_runs",
            supplier_id=suppliers[source].id,
            supplier_location_id=run_locations[source].id,
            started_at=as_datetime(row["started_at"]),
            finished_at=as_datetime(row["finished_at"]),
            status=status,
            observed_count=row["products_seen"] or 0,
            failed_page_count=0,
            warning_count=0,
            error_summary=row["error"],
            run_metadata={"legacy_id": row["id"], "original_status_unverifiable": True},
        )
    session.flush()


def _ensure_history_offers(session, history, suppliers, locations, offers, report):
    for row in history:
        source = row["source"]
        external_id = str(row["external_id"])
        pincode = normalized_pincode(row["pincode"])
        key = (source, external_id, pincode)
        if key in offers:
            continue
        location = locations[(source, pincode)]
        product_id = stable_id("supplier-product", source, external_id)
        product = session.get(SupplierProduct, product_id)
        if product is None:
            product = _add_once(
                session,
                SupplierProduct,
                product_id,
                report,
                "supplier_products",
                supplier_id=suppliers[source].id,
                external_product_id=external_id,
                external_variant_id="",
                source_name=f"Legacy product {external_id}",
                product_metadata={"legacy": True, "history_only": True},
            )
            session.flush()
            match = _add_once(
                session,
                ProductMatch,
                stable_id("product-match", product.id),
                report,
                "product_matches",
                supplier_product_id=product.id,
                canonical_product_id=None,
                product_variant_id=None,
                match_method="legacy_history_only",
                confidence=Decimal("0"),
                review_status="NO_MATCH",
                matched_at=as_datetime(row["scraped_at"]),
            )
        else:
            match = session.get(ProductMatch, stable_id("product-match", product.id))
        variant_id = match.product_variant_id if match is not None else None
        offer_id = stable_id("supplier-offer", source, external_id, location.id)
        offer = _add_once(
            session,
            SupplierOffer,
            offer_id,
            report,
            "history_only_supplier_offers",
            supplier_product_id=product.id,
            product_variant_id=variant_id,
            supplier_location_id=location.id,
            active=False,
            current_price=None,
            current_mrp=None,
            current_availability=None,
            last_seen_at=None,
            consecutive_misses=0,
        )
        offers[key] = offer
    session.flush()


def _migrate_history(session, history, offers, report):
    latest = {}
    for row in history:
        pincode = normalized_pincode(row["pincode"])
        key = (row["source"], str(row["external_id"]), pincode)
        offer = offers.get(key)
        if offer is None:
            report["rejected"]["price_observations"] += 1
            continue
        observation_id = stable_id("price-observation", row["id"])
        existing = session.get(PriceObservation, observation_id)
        if existing is not None:
            report["skipped_existing"]["price_observations"] += 1
            observation = existing
        else:
            observation = PriceObservation(
                id=observation_id,
                supplier_offer_id=offer.id,
                scrape_run_id=None,
                price=as_decimal(row["price"]),
                mrp=as_decimal(row["mrp"]),
                availability=bool(row["in_stock"]) if row["in_stock"] is not None else None,
                observed_at=as_datetime(row["scraped_at"]),
                legacy_metadata={
                    "legacy_price_history_id": row["id"],
                    "source": row["source"],
                    "pincode": pincode or None,
                    "run_attribution": "unknown",
                },
            )
            session.add(observation)
            report["migrated"]["price_observations"] += 1
            report["transformed"]["observations_without_run_id"] += 1
        prior = latest.get(offer.id)
        if prior is None or observation.observed_at > prior.observed_at:
            latest[offer.id] = observation
    session.flush()
    return latest


def _link_current_observations(current_rows, offers, latest):
    for offer_id, row in current_rows.items():
        observation = latest.get(offer_id)
        if observation is None:
            continue
        if (
            observation.observed_at == as_datetime(row["last_seen"])
            and observation.price == as_decimal(row["price"])
        ):
            offers[(row["source"], str(row["external_id"]), normalized_pincode(row["pincode"]))].current_observation_id = observation.id


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate the legacy scraper SQLite database")
    parser.add_argument("--source", type=Path, default=Path("data/products.db"))
    parser.add_argument("--target", required=True, help="SQLAlchemy target database URL")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = migrate_legacy_sqlite(args.source, build_engine(args.target))
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
