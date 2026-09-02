# Supabase-first beta deployment

## Concrete V1 architecture

| Concern | Beta choice | Portability boundary |
|---|---|---|
| Web UI + API | One Render Docker web service | Standard OCI image/FastAPI |
| Database | Supabase PostgreSQL | SQLAlchemy + Alembic + ordinary PostgreSQL |
| Authentication | Supabase Auth | `AuthProvider` / `TokenVerifier` adapters |
| Raw snapshots | Private Supabase Storage bucket | `ObjectStorage` adapter; local/S3 also implemented |
| Scheduler/runtime | GitHub Actions + Python worker | Same CLI invoked by EventBridge/ECS later |
| Logs/alerts | Structured stdout, Actions failures, persisted runs | `MetricsSink`; CloudWatch adapter retained |

This is an early beta architecture, not a production SLA. Render free services cold-start after idle,
and Supabase free projects can pause. The API and workers use no Supabase Data API, RPC, generated
client, or Edge Function.

## Project preparation

1. Create a Supabase project in an acceptable region and record its URL, publishable key,
   server-only secret key, database password, direct connection, session pooler, and transaction
   pooler values in a password manager.
2. In Auth settings, enable email/password signup. Set Site URL to the deployed Render URL, allow the
   `/login` redirect, activate an asymmetric JWT signing key, and customize signup/recovery templates
   to show `{{ .Token }}` for the existing code-entry UI. Wait for the signing-key transition before
   testing; the backend deliberately verifies access tokens against the project's public JWKS.
3. Use a direct PostgreSQL connection for migrations if the machine has IPv6. From IPv4-only Render
   or GitHub, use Supavisor session mode on 5432 for migrations and the persistent web service.
4. Use transaction mode on 6543 for short scheduled workers with `DB_USE_NULL_POOL=true`; the engine
   disables psycopg prepared statements for this mode.

Connection strings belong only in environment/secret stores. Convert nothing manually: the database
layer accepts `postgres://`, `postgresql://`, or explicit `postgresql+psycopg://` and selects psycopg.

## Schema and trustworthy legacy data

From a trusted terminal with the migration/session URL exported:

```bash
export DATABASE_URL='postgresql://...'
MIGRATE_LEGACY_DATA=true \
MIGRATION_REPORT_PATH=/tmp/supabase-migration-report.json \
bash scripts/deploy_supabase_database.sh
```

The script applies Alembic then runs the idempotent SQLite migration. Review every reconciliation
boolean and source/migrated/rejected count before proceeding. Run it a second time and confirm rows
are skipped rather than duplicated. Do not put the report in Git if it contains operational data.

After schema/data migration, apply `infrastructure/supabase/rls.sql` through the SQL editor or set
`APPLY_SUPABASE_RLS=true` where `psql` is installed. It denies direct Data API access to application
tables; the trusted backend owner still bypasses RLS, so backend tenant checks remain essential.

## Private snapshot bucket

Run `infrastructure/supabase/storage.sql` in the SQL editor. Confirm `raw-scrapes` is private. The
worker uses the secret key because it is a trusted server process; that key bypasses Storage
RLS and therefore must exist only as a GitHub Actions secret. The web service does not need it.

## Web deployment

Connect this repository to a Render Blueprint using `render.yaml`. Its auto-deploy policy waits for
GitHub checks to pass. Supply these secret values in the dashboard:

- `DATABASE_URL`: Supavisor session-mode URL with `postgresql+psycopg://`;
- `SUPABASE_URL`;
- `SUPABASE_PUBLISHABLE_KEY`;
- `AUTH_REDIRECT_URL`: `https://<service>.onrender.com/login`.

Render builds the Dockerfile remotely, so a local Docker daemon is not a deployment prerequisite.
Verify `/api/health`, HTTPS/HSTS, secure cookies, signup through reset, and cold-start behavior.

## Scheduled workers

Configure repository Actions secrets:

- `SUPABASE_DATABASE_URL`: transaction-pooler URL;
- `SUPABASE_URL` and `SUPABASE_SECRET_KEY`;
- `HYPERPURE_SUPPLIER_LOCATION_ID` and `LOTS_SUPPLIER_LOCATION_ID` after manual verification.

Enable Actions, run `Scheduled supplier scrape` manually, and inspect each matrix job, structured log,
database run row, observation count, and Storage object. Only then rely on the daily schedule. Set
GitHub notifications or a webhook for workflow failures. BigBasket and Deliverit stay disabled until
their documented live access failures are resolved.

## Beta capacity and backups

The free database becomes read-only at its database-size quota and does not include automatic
backups. Before migration and weekly during beta, export with `pg_dump` using a direct/session URL,
encrypt the artifact, and keep it outside Git. Perform a restore drill into a disposable PostgreSQL
database.

Monitor:

```sql
select pg_size_pretty(pg_database_size(current_database())) as database_size;
select count(*) as observations,
       min(observed_at) as oldest,
       max(observed_at) as newest
from price_observations;
```

Price observations intentionally retain unchanged prices because each timestamp proves freshness.
Do not delete history based on a guessed quota. If growth approaches the verified plan limit, first
measure table/index size, then archive older immutable observations to object storage with a tested
restore path or upgrade the plan.

Official operational references: [database connection modes](https://supabase.com/docs/guides/database/connecting-to-postgres),
[SQLAlchemy pooling guidance](https://supabase.com/docs/guides/troubleshooting/using-sqlalchemy-with-supabase-FUqebT),
[JWT signing keys](https://supabase.com/docs/guides/auth/signing-keys), and
[API key security](https://supabase.com/docs/guides/getting-started/api-keys), and
[Storage access control](https://supabase.com/docs/guides/storage/security/access-control).
