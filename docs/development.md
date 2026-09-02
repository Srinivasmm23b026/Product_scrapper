# Local development

## Setup

Requirements are Python 3.11–3.14, SQLite for legacy data, and PostgreSQL 15+ for V1.

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
cp .env.example .env.local
docker compose up -d postgres
DATABASE_URL=postgresql+psycopg://procurement:procurement@localhost:5432/procurement \
  .venv/bin/alembic upgrade head
```

Pydantic deliberately does not auto-load `.env` files; export variables through your shell or a
secret-aware process manager. `.env.local` is ignored. The Supabase CLI configuration is available
under `supabase/config.toml`, but local Supabase is optional because the domain requires only normal
PostgreSQL.

Run the app and checks:

```bash
.venv/bin/uvicorn procurement_assistant.app:app --reload
.venv/bin/ruff check .
.venv/bin/python -m pytest -q
.venv/bin/cfn-lint infrastructure/aws/foundation.yaml infrastructure/aws/workload.yaml
node --check procurement_assistant/static/app.js
node --check procurement_assistant/static/auth.js
```

The offline suite uses frozen supplier fixtures. `python main.py` remains the legacy SQLite scraper
and performs live writes; do not use it as a smoke test. See the migration guide before importing.

## Main environment boundaries

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Any PostgreSQL provider; `postgres://` and `postgresql://` normalize to psycopg |
| `AUTH_PROVIDER` | `supabase` for beta or `cognito` for future AWS |
| `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` | Supabase Auth server configuration; legacy `SUPABASE_ANON_KEY` also works |
| `SUPABASE_SECRET_KEY` | Worker-only Storage credential; legacy `SUPABASE_SERVICE_ROLE_KEY` also works; never browser-exposed |
| `AUTH_REDIRECT_URL` | Allowed hosted login/recovery destination |
| `COOKIE_SECURE` | Must be true under hosted HTTPS |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | Small persistent-service SQLAlchemy pool |
| `DB_USE_NULL_POOL` | True for short GitHub jobs using transaction pooling |
| `OBJECT_STORAGE_PROVIDER` | `local`, `supabase`, or `s3` |
| `OBJECT_STORAGE_BUCKET`, `LOCAL_STORAGE_PATH` | Snapshot target settings |
| `METRICS_PROVIDER` | `logs` for beta or `cloudwatch` for AWS |
| `SUPPLIER`, `SUPPLIER_LOCATION_ID`, `EXPECTED_MIN` | Non-interactive worker contract |
| `HYPERPURE_OTP` | Explicit account OTP; unsuitable for unattended schedules |
| `COGNITO_*`, `AWS_REGION`, `RAW_SNAPSHOT_BUCKET`, `CLOUDWATCH_NAMESPACE` | Retained AWS target |

Never commit database passwords, provider keys, OTPs, JWTs, cookies, or `.env` files.
