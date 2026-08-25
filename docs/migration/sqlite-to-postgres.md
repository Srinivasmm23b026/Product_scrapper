# Running the legacy migration

## Start local PostgreSQL

```bash
docker compose up -d postgres
export DATABASE_URL=postgresql+psycopg://procurement:procurement@localhost:5432/procurement
.venv/bin/alembic upgrade head
```

The Compose password is local-development-only. Deployed credentials must come from a secret
manager and must not be committed.

## Import

```bash
.venv/bin/python -m procurement_assistant.legacy_migration \
  --source data/products.db \
  --target "$DATABASE_URL" \
  --report data/legacy-migration-report.json
```

The report path under `data/` is ignored runtime output. Review its source/migrated/rejected totals
before treating an import as successful.

The import is deterministic and idempotent. It never changes the source SQLite file, and it refuses
to claim reconciliation if product, observation, or run totals do not balance. Existing target IDs
are skipped on rerun.

