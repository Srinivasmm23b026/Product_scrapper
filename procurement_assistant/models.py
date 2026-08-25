from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from procurement_assistant.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    auth_provider_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)


class Restaurant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "restaurants"

    name: Mapped[str] = mapped_column(String(200), nullable=False)


class RestaurantMembership(Base):
    __tablename__ = "restaurant_memberships"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'manager', 'member')", name="valid_role"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurants.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RestaurantLocation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "restaurant_locations"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "label"),
        Index("ix_restaurant_locations_restaurant_beta", "restaurant_id", "is_beta_default"),
    )

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    address_line_1: Mapped[str | None] = mapped_column(String(255))
    address_line_2: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[str | None] = mapped_column(String(120))
    pincode: Mapped[str] = mapped_column(String(20), nullable=False)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    is_beta_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Supplier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "suppliers"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SupplierLocation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "supplier_locations"
    __table_args__ = (
        UniqueConstraint("supplier_id", "external_location_id"),
        CheckConstraint(
            "location_type IN ('store', 'warehouse', 'zone', 'city', 'fulfilment_center', "
            "'anonymous', 'unknown')",
            name="valid_location_type",
        ),
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_location_id: Mapped[str] = mapped_column(String(255), nullable=False)
    location_type: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    city: Mapped[str | None] = mapped_column(String(120))
    pincode: Mapped[str | None] = mapped_column(String(20))
    location_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SupplierLocationMapping(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "supplier_location_mappings"
    __table_args__ = (
        UniqueConstraint("restaurant_location_id", "supplier_id", "supplier_location_id"),
        CheckConstraint(
            "resolution_method IN ('verified_api', 'verified_session', 'manual', 'legacy', "
            "'fallback', 'unknown')",
            name="valid_resolution_method",
        ),
    )

    restaurant_location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurant_locations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    supplier_location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("supplier_locations.id", ondelete="CASCADE"), nullable=False
    )
    resolution_method: Mapped[str] = mapped_column(String(30), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CanonicalProduct(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "canonical_products"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'review', 'deprecated')", name="valid_status"
        ),
        Index("ix_canonical_products_name_brand", "normalized_name", "canonical_brand"),
    )

    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False)
    display_name: Mapped[str] = mapped_column(String(300), nullable=False)
    canonical_brand: Mapped[str | None] = mapped_column(String(160))
    category: Mapped[str | None] = mapped_column(String(160), index=True)
    subcategory: Mapped[str | None] = mapped_column(String(160))
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="review", nullable=False)


class ProductVariant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_variants"
    __table_args__ = (
        CheckConstraint("base_unit IN ('kg', 'l', 'piece')", name="valid_base_unit"),
        CheckConstraint("quantity > 0", name="positive_quantity"),
        CheckConstraint("pack_count > 0", name="positive_pack_count"),
        CheckConstraint("total_quantity > 0", name="positive_total_quantity"),
        UniqueConstraint(
            "canonical_product_id", "quantity", "base_unit", "pack_count", "normalized_pack_text"
        ),
    )

    canonical_product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("canonical_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    base_unit: Mapped[str] = mapped_column(String(10), nullable=False)
    pack_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    total_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    normalized_pack_text: Mapped[str] = mapped_column(String(160), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class SupplierProduct(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "supplier_products"
    __table_args__ = (
        UniqueConstraint("supplier_id", "external_product_id", "external_variant_id"),
        Index("ix_supplier_products_source_name", "source_name"),
        Index("ix_supplier_products_source_brand", "source_brand"),
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_product_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_variant_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    source_name: Mapped[str] = mapped_column(String(500), nullable=False)
    source_brand: Mapped[str | None] = mapped_column(String(200))
    source_category: Mapped[str | None] = mapped_column(String(200))
    source_pack_text: Mapped[str | None] = mapped_column(String(200))
    product_url: Mapped[str | None] = mapped_column(String(2048))
    image_url: Mapped[str | None] = mapped_column(String(2048))
    product_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class ProductMatch(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "product_matches"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="valid_confidence"),
        CheckConstraint(
            "review_status IN ('AUTO_MATCH', 'REVIEW', 'NO_MATCH', 'MANUAL_MATCH')",
            name="valid_review_status",
        ),
        UniqueConstraint("supplier_product_id"),
    )

    supplier_product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("supplier_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    canonical_product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("canonical_products.id", ondelete="CASCADE"), nullable=True, index=True
    )
    product_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    match_method: Mapped[str] = mapped_column(String(80), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SupplierOffer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "supplier_offers"
    __table_args__ = (
        UniqueConstraint("supplier_product_id", "product_variant_id", "supplier_location_id"),
        CheckConstraint("consecutive_misses >= 0", name="nonnegative_misses"),
        Index("ix_supplier_offers_variant_active", "product_variant_id", "active"),
        Index("ix_supplier_offers_location_seen", "supplier_location_id", "last_seen_at"),
    )

    supplier_product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("supplier_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    supplier_location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("supplier_locations.id", ondelete="RESTRICT"), nullable=False
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    current_mrp: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    current_availability: Mapped[bool | None] = mapped_column(Boolean)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_misses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_observation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


class ScrapeRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "scrape_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'complete', 'partial', 'failed', 'suspicious_zero', "
            "'interrupted')",
            name="valid_status",
        ),
        CheckConstraint("observed_count >= 0", name="nonnegative_observed_count"),
        CheckConstraint("failed_page_count >= 0", name="nonnegative_failed_pages"),
        CheckConstraint("warning_count >= 0", name="nonnegative_warnings"),
        Index("ix_scrape_runs_supplier_location_started", "supplier_id", "supplier_location_id", "started_at"),
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    supplier_location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("supplier_locations.id", ondelete="RESTRICT"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="running", nullable=False, index=True)
    expected_count: Mapped[int | None] = mapped_column(Integer)
    observed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text)
    run_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class PriceObservation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "price_observations"
    __table_args__ = (
        CheckConstraint("price IS NULL OR price >= 0", name="nonnegative_price"),
        CheckConstraint("mrp IS NULL OR mrp >= 0", name="nonnegative_mrp"),
        Index("ix_price_observations_offer_observed", "supplier_offer_id", "observed_at"),
        Index("ix_price_observations_run", "scrape_run_id"),
    )

    supplier_offer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("supplier_offers.id", ondelete="RESTRICT"), nullable=False
    )
    scrape_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("scrape_runs.id", ondelete="RESTRICT"), nullable=True
    )
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    mrp: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    availability: Mapped[bool | None] = mapped_column(Boolean)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_reference: Mapped[str | None] = mapped_column(String(2048))
    legacy_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Purchase(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "purchases"
    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="nonnegative_total"),
        Index("ix_purchases_restaurant_purchased", "restaurant_id", "purchased_at"),
    )

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurants.id", ondelete="RESTRICT"), nullable=False
    )
    restaurant_location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurant_locations.id", ondelete="RESTRICT"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PurchaseItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "purchase_items"
    __table_args__ = (
        CheckConstraint("packs > 0", name="positive_packs"),
        CheckConstraint("quantity > 0", name="positive_quantity"),
        CheckConstraint("actual_unit_price >= 0", name="nonnegative_actual_unit_price"),
        CheckConstraint("actual_total_price >= 0", name="nonnegative_actual_total_price"),
    )

    purchase_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("purchases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    canonical_product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("canonical_products.id", ondelete="RESTRICT"), nullable=False
    )
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    supplier_offer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("supplier_offers.id", ondelete="SET NULL")
    )
    supplier_product_url_snapshot: Mapped[str | None] = mapped_column(String(2048))
    packs: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    unit: Mapped[str] = mapped_column(String(10), nullable=False)
    scraped_price_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    actual_unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    actual_total_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)


class InventoryItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "inventory_items"
    __table_args__ = (
        CheckConstraint("base_unit IN ('kg', 'l', 'piece')", name="valid_base_unit"),
        UniqueConstraint(
            "restaurant_id", "restaurant_location_id", "canonical_product_id", "base_unit"
        ),
    )

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False
    )
    restaurant_location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurant_locations.id", ondelete="CASCADE"), nullable=False
    )
    canonical_product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("canonical_products.id", ondelete="RESTRICT"), nullable=False
    )
    base_unit: Mapped[str] = mapped_column(String(10), nullable=False)
    current_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 6), default=0, nullable=False)
    low_stock_threshold: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class InventoryTransaction(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "inventory_transactions"
    __table_args__ = (
        CheckConstraint(
            "transaction_type IN ('purchase', 'manual_add', 'manual_remove', 'correction')",
            name="valid_transaction_type",
        ),
        CheckConstraint("quantity_delta <> 0", name="nonzero_delta"),
        Index("ix_inventory_transactions_item_created", "inventory_item_id", "created_at"),
    )

    inventory_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False
    )
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    purchase_item_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("purchase_items.id", ondelete="RESTRICT")
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    note: Mapped[str | None] = mapped_column(Text)


class ExpenseEntry(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "expense_entries"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="nonnegative_amount"),
        Index("ix_expense_entries_restaurant_date", "restaurant_id", "expense_date"),
    )

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False
    )
    restaurant_location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("restaurant_locations.id", ondelete="CASCADE"), nullable=False
    )
    purchase_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("purchases.id", ondelete="RESTRICT"), unique=True
    )
    category: Mapped[str] = mapped_column(String(80), default="procurement", nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("suppliers.id", ondelete="RESTRICT")
    )
    expense_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


def _prevent_immutable_update(_mapper: object, _connection: object, target: object) -> None:
    raise ValueError(f"{type(target).__name__} records are immutable")


event.listen(PriceObservation, "before_update", _prevent_immutable_update)
event.listen(Purchase, "before_update", _prevent_immutable_update)
event.listen(PurchaseItem, "before_update", _prevent_immutable_update)
