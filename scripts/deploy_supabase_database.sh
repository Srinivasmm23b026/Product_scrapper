#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?Set DATABASE_URL to the Supabase direct or session-pooler connection string}"

if [[ -z "${PYTHON_BIN:-}" ]]; then
  if [[ -x .venv/bin/python ]]; then
    PYTHON_BIN=.venv/bin/python
  else
    PYTHON_BIN=python3
  fi
fi

"$PYTHON_BIN" -m alembic upgrade head

if [[ "${MIGRATE_LEGACY_DATA:-false}" == "true" ]]; then
  "$PYTHON_BIN" -m procurement_assistant.legacy_migration \
    --source "${LEGACY_SQLITE_PATH:-data/products.db}" \
    --target "$DATABASE_URL" \
    --report "${MIGRATION_REPORT_PATH:-/tmp/supabase-migration-report.json}"
fi

if [[ "${APPLY_SUPABASE_RLS:-false}" == "true" ]]; then
  command -v psql >/dev/null || { echo "psql is required to apply Supabase RLS" >&2; exit 1; }
  PSQL_DATABASE_URL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"
  psql "$PSQL_DATABASE_URL" --set ON_ERROR_STOP=1 --file infrastructure/supabase/rls.sql
fi
