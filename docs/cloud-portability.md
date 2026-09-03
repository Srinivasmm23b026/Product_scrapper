# Cloud portability and AWS migration contract

## Boundary

Procurement models/services, matching, normalization, quantity comparison, purchases, inventory,
expenses, history, tenant rules, and scraper run semantics import no Supabase or AWS SDK. Provider
selection happens in application composition (`configure_auth`) or worker composition
(`configure_storage`, `configure_metrics`). The database contract is PostgreSQL through SQLAlchemy.

## Provider-coupling inventory

| Category | Current files | Classification and boundary |
|---|---|---|
| Infrastructure only | `infrastructure/aws/*.yaml` | RDS, Cognito, S3, ECS/EventBridge, CloudWatch, CloudFront, budgets; retained and linted but not required by the beta |
| Configuration only | `settings.py`, `.env.example`, `render.yaml`, task/workflow environment | Chooses providers and supplies identifiers; no procurement behavior changes |
| Authentication provider | `providers/auth/cognito.py`, `providers/auth/supabase.py` | SDK/REST/JWT details normalize to `AuthProvider`, `AuthTokens`, and `AuthPrincipal` |
| Worker storage | `providers/storage.py` | Local, Supabase Storage, and S3 normalize to `ObjectStorage.put_json` |
| Worker monitoring | `providers/observability.py` | Structured logs are always emitted; CloudWatch is an optional metrics sink |
| AWS runtime compatibility | `app.py` (`Mangum` handler), `cloud_worker.py` composition | Hosting entry points only; FastAPI routes, scraper behavior, and persistence services remain unchanged |
| Direct core-domain coupling | none | Automated tests reject `boto3` or Supabase references in models, matching, normalization, procurement, services, and scrape-run logic |

AWS packages remain runtime dependencies because the same image supports the retained target. They
are imported only when an AWS adapter is selected (apart from the optional Mangum entry point), so
Supabase beta behavior does not require AWS credentials or API calls.

## Supabase → AWS mapping

| Migration | Configuration change | Data migration | Adapter change | Code unchanged | Main risks |
|---|---|---|---|---|---|
| PostgreSQL → RDS | Point `DATABASE_URL`/split DB settings at RDS | `pg_dump`/`pg_restore`, sequences, Alembic revision and counts | None | All ORM/domain/API logic | downtime, timezone/extension/version mismatch, missed writes |
| Supabase Auth → Cognito | `AUTH_PROVIDER=cognito`, pool/client/region IDs | Create/invite users; map old provider subject to new subject before cutover | Supabase → Cognito auth/verifier | sessions, membership authorization, domain logic | password hashes generally non-portable, subject remapping, forced reset |
| Supabase Storage → S3 | `OBJECT_STORAGE_PROVIDER=s3`, bucket/region | Copy objects and verify key/checksum inventory | Supabase → S3 storage | worker/scraper/run persistence | missing objects, service-key leakage, URI references to old scheme |
| GitHub schedule → EventBridge/ECS | Deploy AWS task/schedule parameters and secret injection | None | Runtime composition only | Python worker and adapters | timeouts, egress, task launch permissions, OTP suppliers |
| Structured host logs → CloudWatch | `METRICS_PROVIDER=cloudwatch`, namespace | Optional log export only | Log → CloudWatch metrics sink | run classification and API behavior | alarm parity, retention/cost, missing dimensions |
| Render → ECS/CloudFront | Deploy retained CloudFormation image/workload | None beyond DB/auth cutover | Hosting configuration | Docker image, FastAPI/PWA | proxy headers, cookies, origin security, cutover DNS |

## Authentication subject migration

`users.auth_provider_id` stores the provider subject. Before switching providers, create an encrypted
mapping of Supabase user UUID → Cognito subject based on verified email/ownership, update those rows
transactionally during a maintenance window, and reconcile membership counts. Never match solely on
an unverified email supplied by a client. Existing restaurant IDs and all procurement records remain
unchanged. Expect users to confirm invitations or reset passwords because credentials are not assumed
portable.

## Database migration proof

Freeze writes, capture source counts/checksums and Alembic revision, dump with PostgreSQL tools,
restore into encrypted RDS, run migrations, and compare every domain-table count plus key financial
totals and min/max observation timestamps. Run the full hosted E2E against a staging endpoint before
cutover. Preserve the Supabase project read-only until rollback is no longer required.

## Retained AWS artifacts

`infrastructure/aws` continues to define RDS, Cognito, S3, ECR, ECS/Fargate, EventBridge Scheduler,
CloudFront, CloudWatch/SNS, budgets, and lifecycle controls. Its task environment explicitly selects
the Cognito, S3, and CloudWatch adapters. Static validation remains part of every release gate even
while AWS is deferred.

`.github/workflows/ci.yml` continuously checks both targets: the suite and Alembic run against a
normal PostgreSQL 16 service, AWS templates are linted, tracked files are audited, and the same
Dockerfile used by Render is built. Render waits for repository checks before auto-deploying.
