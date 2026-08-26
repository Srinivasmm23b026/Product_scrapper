# Beta release checklist

## Automated release gates

- `ruff check .`
- full `pytest` suite
- Alembic upgrade from an empty PostgreSQL database
- idempotent legacy migration with reconciled counts
- CloudFormation syntax/schema lint
- container build and vulnerability scan
- secret scan and tracked-artifact review
- core authenticated E2E: search → compare → record purchase → inventory + expense + unchanged price history

## Operator gates

- AWS account type and workload terms confirmed
- current AWS price estimate fits credits; budget emails confirmed
- foundation/workload deployed without drift
- RDS restore drill completed
- Cognito email verification, reset, refresh, and logout exercised against the real pool
- one fixed restaurant location explicitly configured
- each supplier-location mapping manually verified and timestamped
- supplier deep links, availability, pack parsing, duplicates, and timestamps sampled
- every worker triggered once; snapshot, run status, metrics, logs, and alarm delivery verified
- HTTPS CloudFront endpoint used; direct ALB requests return 403
- 5–10 invited restaurant users consent to the beta data handling expectations

## Feedback record

Do not manufacture results. For each reviewer, capture date, restaurant type, products actually
purchased, missing items/suppliers, pack-size errors, comparison trust, purchase frequency, current
workflow, inventory usefulness, history usefulness, and the next feature they would prioritize.
Redact private business information from Git.

V1 is release-complete only after the external deployment/operator gates pass and actual reviewers
can execute the canonical flow. Current automated implementation readiness is not evidence of those
external outcomes.
