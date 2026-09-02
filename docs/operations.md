# Scraper and application operations

## Portable worker contract

Every runtime invokes the same Python entry point with one supplier and one verified location:

```bash
DATABASE_URL=... LOCAL_STORAGE_PATH=/tmp/snapshots \
python -m procurement_assistant.cloud_worker \
  --supplier lots --supplier-location-id UUID --expected-min 3000
```

For the beta, `.github/workflows/scheduled-scrape.yml` runs Hyperpure and Lots sequentially at a
non-peak cron minute. GitHub Actions supplies the Supabase transaction-pooler URL, location UUIDs,
Supabase Storage secret key, and bucket through encrypted secrets. Scheduled workflows may be
delayed, run only from the default branch, and can be disabled after repository inactivity; an
operator must check their enabled state. A non-complete run exits non-zero and makes its matrix job
red. BigBasket and Deliverit remain disabled because live validation found access/DNS failures;
silently scheduling known-broken adapters would create noise rather than freshness.

Configured Hyperpure accounts require an OTP. Because human SMS OTPs are not unattended, the beta
workflow uses only anonymous Hyperpure data unless a permitted unattended session mechanism exists.

Each invocation starts a run, invokes one adapter, stores an immutable normalized raw snapshot,
upserts source identities, atomically writes observations/current pointers, assigns a terminal status,
and emits a structured JSON event. Storage is selected by `OBJECT_STORAGE_PROVIDER`:

- `local` for development;
- `supabase` for the beta private `raw-scrapes` bucket;
- `s3` for the future AWS workload.

A count below `EXPECTED_MIN` is `partial`; zero is `suspicious_zero`. Only `complete` runs advance
missing-offer counters. Three complete misses retire an offer. Failed and partial runs never do.

## Visibility and alerts

Every web request and worker completion emits structured JSON to stdout. A scraper event includes
supplier, supplier location, run ID/status, start/end, duration, expected/observed count, failed
pages, warnings, and error summary. GitHub retains workflow logs and notifies according to repository
notification settings. `/api/scrape-runs` and the dashboard expose persisted operational state;
offers expose last-check time and staleness.

The minimum beta alert path is a failed GitHub Actions workflow plus daily operator review of stale
offers/run state. Configure repository notification or an external webhook before inviting users.
The retained AWS adapter publishes the same run to CloudWatch metrics; its alarms/SNS remain in
`infrastructure/aws`.

Triage in this order:

1. Find the persisted run by supplier/location and terminal status.
2. Inspect the GitHub/host structured event and run metadata.
3. Confirm the raw snapshot exists before changing parsing.
4. Compare counts with recent complete runs.
5. Check supplier access, verified location, and credential/OTP requirements.
6. Check Supabase connectivity, project pause/read-only state, and connection limits.
7. Retry only after understanding the cause; never infer unavailability from a failed run.

Use `mark_interrupted()` for abandoned `running` rows. Historical observations, purchases, and
purchase items are immutable; corrections are additive.
