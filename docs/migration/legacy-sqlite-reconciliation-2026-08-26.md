# Legacy SQLite → PostgreSQL reconciliation — 2026-08-26

## Validation environment

- Source: preserved local `data/products.db` from starting commit `727acbf`
- Source integrity: `ok`
- Target: temporary clean PostgreSQL 16 instance
- Alembic head: `2f18af8d6023`
- Migration command: `python -m procurement_assistant.legacy_migration`
- The full import was run twice; the second run inserted nothing and reconciled all source rows,
  proving idempotence against PostgreSQL.

## Source reconciliation

| Legacy entity | Source rows | Migrated observations/rows | Rejected | Reconciled |
|---|---:|---:|---:|---|
| `products` | 7,501 | 7,501 legacy product rows | 0 | Yes |
| `price_history` | 65,922 | 65,922 immutable observations | 0 | Yes |
| `scrape_runs` | 55 | 55 run records | 0 | Yes |
| `canonical_products` | 4,017 | 4,017 review-state canonical products | 0 | Yes |

## Target counts

| Entity | Rows |
|---|---:|
| Suppliers | 4 |
| Supplier locations | 10 |
| Supplier products | 4,663 |
| Supplier offers | 9,701 |
| Canonical products | 4,017 |
| Product variants | 3,836 |
| Product match decisions | 4,663 |
| Price observations | 65,922 |
| Scrape runs | 55 |

There are more offers than current legacy product rows because 2,200 inactive, history-only offers
were created to retain older observations whose blank location context no longer exists in the
current product snapshot. They are explicit historical containers, not current purchasable offers.

## Explicit transformations

- 600 legacy product rows contained an explicit multipack that was separated into each quantity,
  pack count, and total quantity.
- 431 current product rows had unknown/unparseable packs and therefore retain a supplier offer with
  no normalized variant.
- All 65,922 observations retain a null `scrape_run_id`; no run attribution was invented.
- Legacy pincode and location notes are stored in unverified/anonymous supplier-location metadata.
- Every legacy match is `REVIEW` with confidence zero and method `legacy_heuristic_unreviewed`.
- Deliverit is imported inactive because Phase 1 found its hostname unavailable.

## Legacy run status mapping

| New status | Rows | Rule |
|---|---:|---|
| `failed` | 1 | Legacy error was present |
| `interrupted` | 2 | No legacy finish timestamp |
| `suspicious_zero` | 6 | Finished with zero products and no recorded error |
| `partial` | 46 | Nonzero legacy result, but completeness was never proven |
| `complete` | 0 | Never inferred from legacy success alone |

## Limitations retained

- Historical observations cannot be linked to exact legacy runs.
- Pincodes do not prove store/warehouse identity.
- Legacy current availability may be stale.
- No fake availability changes, timestamps, run IDs, or verified location mappings were created.
- Prototype canonical groups are not treated as reviewed truth.

