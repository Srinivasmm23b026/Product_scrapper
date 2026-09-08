# Hyperpure persistent authentication

## Selected architecture

Scheduled Hyperpure scraping uses a reusable HTTP session. Hyperpure's current
web client sends the login response's authorization value to
`https://api.hyperpure.com` and accepts a replacement authorization header from
the authenticated account endpoint. The worker mirrors that behavior through
`HyperpureSessionProvider`; it does not need a browser unless live discovery
later proves an unobserved browser-bound dependency.

The session state contains the opaque authorization value, Hyperpure cookies,
the generated device ID, selected outlet ID, routing context when returned, and
capture/validation timestamps. It is encrypted with Fernet before storage. The
encrypted payload is a mutable object in the existing private Supabase Storage
bucket. `HYPERPURE_SESSION_ENCRYPTION_KEY` is configured separately in the
operator environment and GitHub Actions secrets. Neither the key nor plaintext
session is stored in PostgreSQL, source control, workflow artifacts, or logs.

Static GitHub secrets are a poor home for the payload itself because a scheduled
job cannot update a rotated secret with the workflow's read-only repository
token. Supabase Storage already provides server-only mutable storage in this
beta stack. The workflow remains serialized, which prevents normal scheduled
runs from racing while updating the session object.

## Strategy comparison

| Strategy | Reliability / renewal | Security and leakage | Actions / local operation | Maintenance and decision |
| --- | --- | --- | --- | --- |
| Native refresh token | Best if supplied, but none appears in the inspected web bundle. Runtime discovery remains required. | Small secret surface. | Simple. | Use if authenticated evidence reveals one. |
| Reusable HTTP session | Matches observed web behavior, including replacement authorization headers. | Encrypted payload and separate key; no browser profile. | Small dependency/runtime footprint in both environments. | Selected. |
| Browser storage state | Broadly captures cookies and web storage. | Larger sensitive artifact. | Browser install increases job time and failure surface. | Reserve for evidence that direct HTTP cannot reproduce login state. |
| Automated browser renewal | Could execute client-only behavior. | Broadest state and automation surface. | Fragile selectors/browser lifecycle. | Reserve for a proven client-execution requirement. |
| Secure export/import | Useful as the one-time bootstrap around the selected HTTP session. | Safe when encrypted before persistence. | The included CLI performs this role. | Selected companion. |
| OTP each run | Reliable only with human presence and wastes operational effort. | Repeated OTP handling. | Incompatible with unattended Actions. | Fallback only after server rejection. |
| Account-response token replacement | Observed in the web application; lifetime extension is not yet measured. | Same encrypted payload. | Persisted transparently after responses. | Implemented as the available renewal path. |

The selected path has fewer dependencies and less site-specific automation than
a stored browser profile. Its main susceptibility is an API or response-schema
change. Validation therefore requires a real authenticated account response,
complete outlet identity, and outlet-aware catalogue schema before publishing
observations.

## Initial bootstrap and reauthentication

Configure the private Supabase bucket and existing server credentials described
in `docs/supabase-deployment.md`. Generate an encryption key locally:

```bash
.venv/bin/python -m procurement_assistant.hyperpure_auth_bootstrap \
  --generate-encryption-key
```

Store that output directly in the secret manager as
`HYPERPURE_SESSION_ENCRYPTION_KEY`. Do not add it to an env file or shell
history. Export these values from a secret-aware local process:

```text
HYPERPURE_SESSION_STORAGE_PROVIDER=supabase
HYPERPURE_SESSION_BUCKET=raw-scrapes
HYPERPURE_SESSION_ENCRYPTION_KEY=<secret-manager value>
SUPABASE_URL=<project URL>
SUPABASE_SECRET_KEY=<server secret>
```

Run the bootstrap without command-line account data so the phone is prompted:

```bash
.venv/bin/python -m procurement_assistant.hyperpure_auth_bootstrap
```

The tool prepares encrypted persistence first, verifies the account, asks
Hyperpure to send an OTP, and prints confirmation only after the request
succeeds. It then reads the OTP without terminal echo, signs in once, saves the
session immediately, validates the authenticated account, persists replacement
authorization if returned, resolves the outlet, and reads the complete
authenticated outlet catalogue. It reports a verified location only after that
catalogue is nonempty and has the required product price/availability fields.
Use `--outlet-id` only when the account has multiple outlets and the desired
authenticated outlet ID is known.

If the result says `location_verified: false`, authentication was preserved but
the returned outlet lacked a stable ID, address, pincode, or another required
identity field. A visible `Guest Outlet` name is insufficient. Do not create a
verified supplier location or schedule Hyperpure until a service outlet can be
proven.

Configure the same encryption key as the GitHub repository or environment
secret `HYPERPURE_SESSION_ENCRYPTION_KEY`. The scheduled workflow already has
the Supabase URL/server key and reads the encrypted object from
`private-auth/hyperpure/session.enc.json` in the private bucket. Never download
or upload that object as a workflow artifact.

When a run reports `reauthentication-required`, repeat the bootstrap. This
overwrites only the encrypted session object. It does not rewrite supplier
locations, offers, observations, or history.

## Worker states

| State | Behavior |
| --- | --- |
| `authenticated` | Stored state passed the account check; scrape the selected outlet catalogue. |
| `refreshed` | Hyperpure returned replacement authorization or outlet/routing state; persist it before scraping. |
| `reauthentication-required` | State is missing, corrupt, or rejected with 401/403; record the run state, preserve offer freshness, exit gracefully, and request local bootstrap. |
| `failed` | Storage, network, response-schema, or persistence failure; record failure and fail the job. |

GitHub Actions writes the authentication state to the job summary. It never
prompts for an OTP. Auth failures do not invoke the public adapter. Only the
authenticated `consumer/v2/search` response with `outletId` and
`getGlobalCatalog=false` can become scheduled Hyperpure observations.

## Location and live validation gate

Before setting `HYPERPURE_SUPPLIER_LOCATION_ID`, retain evidence from the
bootstrap output and authenticated responses for outlet ID, name, address,
pincode, city, account ID, service zone, and warehouse city when present. The
database location must use `external_location_id=outlet:<Hyperpure ID>` and
`location_metadata.verified=true` only when those fields establish a stable,
reproducible service location. Create the restaurant-to-supplier mapping only
for that verified location.

Then dispatch the workflow and verify all of the following from authoritative
state: nonzero authenticated products; one matching outlet identity on every
row; location-specific prices; raw snapshot object; price observations; a
complete run; and a procurement comparison response for the mapped restaurant.
Run the hosted supplier-offer purchase/inventory/analytics/history path only
after those checks. Do not interpret a successful anonymous/public response as
this validation.

## Current evidence limits

The public bundle inspection is recorded in
`hyperpure-auth-discovery-2026-09-06.md`. No account OTP has yet been requested.
Consequently, actual server-side session lifetime, browser-restart survival,
device binding, replacement-token behavior, authenticated search schema,
outlet identity, scrape results, and hosted E2E remain unverified. Session
lifetime must be reported from elapsed observations after bootstrap rather than
inferred from cookie expiry.
