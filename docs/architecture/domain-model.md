# V1 domain model

## Design decisions

- PostgreSQL is the production database; SQLAlchemy keeps business code independent of a specific
  managed PostgreSQL vendor.
- UUID primary keys provide stable application identity and permit deterministic IDs for legacy
  migration. Supplier external IDs remain explicit alternate identities.
- Canonical product, purchasable variant, supplier product, location-specific offer, and immutable
  price observation are separate records.
- Restaurant pincode is never used as supplier-offer identity. A verified or explicitly unresolved
  `SupplierLocation` is mapped to a `RestaurantLocation` with resolution evidence.
- Current price fields on `SupplierOffer` are a query convenience. `PriceObservation` remains the
  historical authority.
- New observations require a scrape run. The nullable run reference exists only so legacy history
  can be migrated without inventing attribution.
- Purchases and purchase items are immutable snapshots. Actual paid values, not scraped prices,
  drive expenses.
- Inventory is a current balance backed by auditable transactions; V1 has no recipe consumption.

## Entity relationships

```text
User ──< RestaurantMembership >── Restaurant ──< RestaurantLocation
                                                │
                                                └──< SupplierLocationMapping
                                                          >── SupplierLocation >── Supplier

CanonicalProduct ──< ProductVariant ──< ProductMatch >── SupplierProduct >── Supplier
                           │                              │
                           └──────── SupplierOffer ───────┘
                                      │        │
                                      │        └── SupplierLocation
                                      └──< PriceObservation >── ScrapeRun

Restaurant ──< Purchase ──< PurchaseItem >── ProductVariant / SupplierOffer snapshot
                     │             │
                     │             └── InventoryTransaction >── InventoryItem
                     └── ExpenseEntry
```

## Invariants

- Base units are `kg`, `l`, or `piece` and variant quantities are positive.
- Supplier products are unique by supplier/external product/external variant.
- Offers are unique by supplier product/supplier location. The normalized variant may be null for
  legacy or newly observed products whose pack is not yet safely parseable.
- Observations cannot reference a nonexistent offer and are immutable through the application ORM.
- Run status is one of `running`, `complete`, `partial`, `failed`, `suspicious_zero`, or
  `interrupted`.
- Only one generated procurement expense may reference a purchase.
- Inventory balances are unique per restaurant/location/canonical product/base unit.
- Cross-tenant access is an application authorization responsibility and must always be derived
  from authenticated membership, never a trusted client restaurant ID.
- A supplier product has one current `ProductMatch` decision. `REVIEW` and `NO_MATCH` decisions may
  intentionally have no variant; family-level review may retain only a canonical product.

## Intentional legacy accommodation

Legacy SQLite observations have no reliable run or supplier-location identity. The new
`PriceObservation.scrape_run_id` is nullable solely for those migrated rows, and unresolved
locations use explicit `legacy`/`unknown` records and metadata. New ingestion code must always set
the run ID.

`SupplierOffer.current_observation_id` is retained as a denormalized pointer without a database
foreign key to avoid a circular table dependency. Ingestion sets it only after the referenced
observation has been flushed; integrity is covered by service tests.
