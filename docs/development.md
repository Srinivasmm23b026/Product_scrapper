# Local development

## Requirements

- Python 3.11–3.14
- SQLite 3 for the legacy data pipeline
- PostgreSQL 15+ for the V1 application schema
- Internet access only when intentionally running live supplier validation or scraping

## Setup

Create an isolated environment with a supported Python and install the locked dependencies:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.lock
```

On Windows, use `.venv\\Scripts\\python.exe` instead of `.venv/bin/python`.

## Checks

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/cfn-lint infra/foundation.yaml infra/workload.yaml
```

The default suite is deterministic and offline. Supplier parser tests use sanitized frozen payloads
under `tests/fixtures/`; live supplier validation is a separate, intentional operation and is never
required for the normal test run.

Apply the V1 schema to the database selected by `DATABASE_URL`:

```bash
export DATABASE_URL=postgresql+psycopg://procurement:procurement@localhost:5432/procurement
.venv/bin/alembic upgrade head
```

For the standard local PostgreSQL container and legacy import procedure, see
[`docs/migration/sqlite-to-postgres.md`](migration/sqlite-to-postgres.md).

## Legacy scraper launch

The original behavior remains available during the migration period:

```bash
.venv/bin/python main.py
```

This command performs live HTTP requests and mutates `data/products.db` and
`logs/scraper.log`. Do not use it as a smoke test. `run_scraper.bat` remains for the
documented legacy Windows workflow, but cloud scheduling will replace it for production.

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `HYPERPURE_OTP` | No | One-time OTP for an explicitly configured Hyperpure account |
| `DATABASE_URL` | For V1 | SQLAlchemy PostgreSQL connection URL; defaults to the documented local database |
| `AWS_REGION` | For Cognito/AWS | AWS region, default `ap-south-1` |
| `COGNITO_USER_POOL_ID` | For auth | Cognito user-pool identifier |
| `COGNITO_APP_CLIENT_ID` | For auth | Cognito application client without a client secret |
| `COOKIE_SECURE` | Deployment | Must be `true` when served over HTTPS |
| `OFFER_STALE_AFTER_HOURS` | No | UI freshness threshold, default 48 hours |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | AWS tasks | Split database settings injected from Secrets Manager |
| `RAW_SNAPSHOT_BUCKET` | Cloud worker | S3 bucket for raw scrape snapshots; local runs use `RAW_SNAPSHOT_DIR` |
| `CLOUDWATCH_NAMESPACE` | Cloud worker | Enables terminal run/count metrics |
| `SUPPLIER`, `SUPPLIER_LOCATION_ID`, `EXPECTED_MIN` | Cloud worker | Non-interactive scheduled invocation contract |

Never commit `.env` files, credentials, OTPs, tokens, cookies, or supplier session data.
