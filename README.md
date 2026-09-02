# Procurement Assistant V1

A location-aware restaurant procurement application that compares supplier packs by the
quantity a buyer actually needs, records actual purchases, updates inventory, tracks expenses,
and preserves trustworthy price history.

## What is implemented

- FastAPI application and responsive server-rendered PWA
- provider-neutral authentication with Supabase Auth for beta and Cognito retained for AWS
- server-derived restaurant tenancy and fixed beta location
- typo-tolerant product search and deterministic product matching
- quantity-aware offer comparison with separate total-cost, unit-price, and excess rankings
- supplier HTTPS deep links, timestamps, stale flags, and unknown-pack exclusion reasons
- immutable purchase ledger with scraped-price snapshots and actual paid amounts
- transactional purchase → inventory transaction + expense entry workflow
- inventory adjustments and auditable transaction history
- spending by time, supplier, category, and product
- trusted complete-run price history and data-quality-aware statistics
- PostgreSQL/Alembic schema and idempotent legacy SQLite migration
- non-interactive worker with local, Supabase Storage, and S3 snapshot adapters
- GitHub Actions beta scheduling plus retained EventBridge/ECS scheduling
- Supabase beta configuration and retained CloudFormation for the future AWS target

Supabase deployment and real restaurant feedback remain external release gates; no hosted resources
have been fabricated or claimed as deployed. Procurement logic uses standard PostgreSQL and does
not depend on Supabase Data APIs, RPC, Edge Functions, or generated clients.

## Local setup

Requirements: Python 3.11–3.14 and PostgreSQL 16+ (Docker Compose is optional).

```bash
python -m venv .venv
./.venv/bin/pip install -r requirements.lock
docker compose up -d postgres
DATABASE_URL=postgresql+psycopg://procurement:procurement@localhost:5432/procurement \
  ./.venv/bin/alembic upgrade head
```

Run the web application:

```bash
./.venv/bin/uvicorn procurement_assistant.app:app --reload
```

The UI is at `http://127.0.0.1:8000`; API documentation is at `/docs`. Authentication is
intentionally unavailable until Supabase settings are supplied or a test provider is injected.

Run quality gates:

```bash
./.venv/bin/ruff check .
./.venv/bin/pytest -q
./.venv/bin/cfn-lint infrastructure/aws/foundation.yaml infrastructure/aws/workload.yaml
docker build -t procurement-assistant:v1 .
```

## Documentation

- [Local development](docs/development.md)
- [API contract](docs/api.md)
- [Authentication and tenancy](docs/authentication.md)
- [Domain model](docs/architecture/domain-model.md)
- [Supabase beta deployment](docs/supabase-deployment.md)
- [Cloud portability and AWS migration](docs/cloud-portability.md)
- [AWS deployment and costs](docs/aws-deployment.md)
- [Scraper operations and alerts](docs/operations.md)
- [Legacy migration](docs/migration/sqlite-to-postgres.md)
- [Beta release checklist](docs/beta-release.md)

The legacy Windows `main.py` / `run_scraper.bat` path remains available for manual compatibility.
The beta scheduler invokes the same cloud worker from GitHub Actions; the AWS target invokes it from
EventBridge/ECS without changing scraper or persistence logic.
