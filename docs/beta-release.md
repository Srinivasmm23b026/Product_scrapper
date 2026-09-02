# Beta release checklist

## Automated gates

- Ruff and full Python suite
- API authorization/tenant tests
- procurement, matching, migration, fixture, and run-semantics tests
- Alembic upgrade from empty PostgreSQL and idempotent legacy reconciliation
- Supabase provider/storage/configuration tests
- frontend JavaScript syntax checks
- retained AWS CloudFormation lint
- container build and hosted health check
- secret and generated-artifact scans
- authenticated E2E: search → compare → purchase → inventory + expense + unchanged history

## Supabase/hosting gates

- Supabase project exists and its region/data terms are accepted
- direct/session/transaction connection strings are stored only as deployment secrets
- schema migration and legacy reconciliation pass against Supabase PostgreSQL
- Supabase RLS hardening is applied; anon/authenticated Data API access is denied
- private `raw-scrapes` bucket exists; secret/service-role key is worker-only
- asymmetric JWT signing is active; signup/recovery templates display OTP tokens; redirect allowlist is correct
- signup, confirmation, login, refresh, logout, recovery, and reset pass against the real project
- Render service is deployed with HTTPS/secure cookies and healthy database access
- GitHub scheduled workflow secrets are configured and both enabled suppliers complete manually
- workflow failure notification path is tested
- one fixed location and each supplier-location mapping are explicitly verified
- supplier links, availability, pack parsing, duplicates, freshness, and timestamps are sampled
- database-size query is reviewed; manual backup/export and restore drill pass
- 5–10 invited users understand beta limitations and data handling

Render's free service may cold-start and Supabase free projects may pause; these plans are suitable
only for an early test beta, not a service-level promise. Upgrade before operational dependency.

## Feedback

Do not manufacture results. Capture reviewer date/type, actual products, missing items/suppliers,
pack errors, comparison trust, purchase frequency, current workflow, inventory/history usefulness,
and next priority. Keep private business information out of Git.

V1 is beta-ready only after every hosted gate and the real E2E flow pass. Local readiness is not
evidence of deployment or restaurant validation.
