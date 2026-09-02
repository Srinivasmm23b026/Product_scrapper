# Future AWS deployment

## Deployment status and account gate

The infrastructure is reproducible but has not been applied. Before creating resources, verify
whether the available account is a normal AWS account with educational/promotional credits or an
AWS Academy/Learner Lab. Do not put restaurant data or a live beta in a training environment whose
terms prohibit it.

`infrastructure/aws/foundation.yaml` creates the durable foundation.
`infrastructure/aws/workload.yaml` is deliberately
separate so the database, snapshots, and Cognito directory can survive workload replacement.

## Architecture

CloudFront provides the public HTTPS endpoint. A secret origin header prevents direct ALB access;
the ALB forwards to one small Fargate web task. Scheduled Fargate tasks use public IP egress (no NAT
Gateway), connect to a non-public encrypted RDS PostgreSQL instance, write encrypted raw snapshots
to S3, and publish CloudWatch metrics. Cognito handles identity. Secrets Manager owns the generated
database password.

This favors a small beta and supplier HTTP compatibility over high availability: one web task,
one `db.t4g.micro`, no Multi-AZ, no NAT Gateway. CloudFormation enables deletion protection and a
final RDS snapshot.

## Safe deployment sequence

1. Confirm account classification, allowed workload terms, region, credentials, and billing access.
2. Validate both templates with `cfn-lint`.
3. Deploy `foundation.yaml`, supplying a monitored email and monthly budget.
4. Confirm both the SNS and AWS Budget email subscriptions.
5. Build the Docker image, scan it, push an immutable tag to the output ECR repository.
6. Run `alembic upgrade head` as a one-off task against RDS.
7. Run the legacy migration and archive its reconciliation report.
8. Create and manually verify restaurant → supplier-location mappings. Never infer these from a
   pincode alone.
9. Deploy `workload.yaml` with the foundation outputs, immutable image URI, a random origin secret,
   and the four verified supplier-location UUIDs.
10. Exercise signup/confirmation/login and the core E2E flow through the CloudFront URL.
11. Trigger each worker once, inspect its run record/S3 snapshot/logs, then enable the schedules.

Deployment requires `CAPABILITY_IAM`. Keep parameter files outside Git if they contain the origin
secret or restaurant-specific location identifiers.

## Cost controls and estimate

The foundation creates an 80% forecast and 100% actual monthly budget alert, 14/30-day log
retention, a 180-day raw-snapshot expiry, ECR image retention, capped RDS autoscaling, and project
tags. A default-domain CloudFront distribution avoids a paid domain/certificate requirement.

Exact prices vary by region and date and must be checked in AWS Pricing Calculator before launch.
The persistent cost drivers are RDS, one Fargate web task, and the ALB; scheduled worker minutes,
S3, CloudFront, logs, and Cognito beta usage should be smaller. If the verified credit balance does
not comfortably cover the estimate, do not deploy. Multi-AZ and NAT Gateway are intentionally off.

## Ownership and secrets

- AWS account owner: billing, account terms, budget subscription, and destructive stack actions.
- Application operator: image releases, migrations, mappings, alarms, backups, and beta access.
- Secrets Manager: generated RDS credentials.
- Environment/task settings: Cognito IDs, database host, S3 bucket, and secure-cookie flag.
- Never place AWS credentials, database passwords, Cognito tokens, supplier OTPs, or the origin
  verification secret in Git.

## Backup and restore

RDS keeps seven days of automated backups and creates a final snapshot on stack deletion/replacement.
Before a release, create a manual snapshot. Restore into a new instance, point a one-off validation
task at it, run read-only count/reconciliation checks, and only then change workload parameters.
S3 versioning protects raw snapshots; lifecycle removes old versions after 30 days and objects after
180 days. A restore drill is required before real restaurant data is accepted.
