# Scraper and application operations

## Worker contract

Production invokes one supplier and one verified supplier-location UUID per task:

```bash
DATABASE_URL=... RAW_SNAPSHOT_DIR=/tmp/snapshots \
python -m procurement_assistant.cloud_worker \
  --supplier lots --supplier-location-id UUID --expected-min 3000
```

In AWS, the equivalent settings come from the task definition and Secrets Manager. The worker is
non-interactive. Configured Hyperpure accounts require `HYPERPURE_OTP`; because a human SMS OTP is
not schedulable, authenticated Hyperpure remains unavailable until a permitted unattended supplier
credential/session mechanism exists.

Each invocation:

1. starts a `running` scrape record;
2. invokes one supplier adapter;
3. writes the untouched normalized source result to S3/local snapshot storage;
4. upserts supplier catalog identities without auto-comparing new unreviewed products;
5. atomically writes observations and current-offer pointers;
6. ends as `complete`, `partial`, `failed`, `suspicious_zero`, or `interrupted`;
7. emits product count and run-state metrics.

A count below `expected-min` is partial. Zero is suspicious. Only complete runs advance missing-offer
counters. Three complete misses retire an offer; failed or partial runs never do.

## Alert paths

- `RunFailure >= 1`: failed, partial/count-drop, or suspicious-zero run.
- missing `ObservedProducts`: supplier data stale for more than one daily window.
- stopped ECS task with non-zero exit: startup, secret, database, or unhandled worker failure.
- unhealthy ALB target: application or database connectivity failure.
- AWS Budget forecast/actual thresholds: unexpected spend.

Alerts publish to the foundation SNS topic. The operator must confirm the email subscription and
test it before beta. The dashboard and `/api/scrape-runs` expose recent status, counts, timestamps,
warnings, errors, supplier, and location. Offers show their own last-check time and stale state.

## Triage

1. Locate the run by supplier/location and terminal status.
2. Inspect CloudWatch logs and the run `error_summary`/metadata.
3. Confirm raw snapshot existence before retrying or changing parsing.
4. Compare observed count with recent complete runs.
5. Check supplier reachability, robots/terms, location verification, and credentials.
6. Check database connectivity and capacity.
7. Retry only after the cause is understood. Never mark missing offers unavailable from a failed run.

Use `mark_interrupted()` for runs left `running` beyond the worker timeout. Do not edit historical
observations, purchases, or purchase items; corrections are additive records.
