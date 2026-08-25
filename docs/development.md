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
```

Apply the V1 schema to the database selected by `DATABASE_URL`:

```bash
export DATABASE_URL=postgresql+psycopg://procurement:procurement@localhost:5432/procurement
.venv/bin/alembic upgrade head
```

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

Never commit `.env` files, credentials, OTPs, tokens, cookies, or supplier session data.
