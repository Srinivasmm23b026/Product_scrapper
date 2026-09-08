# Hyperpure authentication discovery — in progress

This is an evidence log, not a completed implementation or authenticated
validation report. No OTP has been requested and no account session has been
captured. Account access is the next required input. Existing supplier data has
not been changed.

## Public application evidence

Retrieved the live homepage and its referenced application bundle on 2026-09-06:

- Homepage: https://www.hyperpure.com
- Bundle: https://www.hyperpure.com/_next/static/chunks/pages/_app-cf7823805bc45eb4.js
- Bundle SHA-256: `15c5684aa11e983bbcd389bbbda8bdc0e2619a475acbb00f437218458bb6304c`

Observed in the downloaded application code:

- The sign-in action posts to `api/registration/signin`, reads the response
  `authorization` header, and stores it through the cookie helper as `token`
  (`posToken` exists for the POS integration).
- The request factory reads the cookie and supplies `Authorization`. Its normal
  web path preserves the supplied token format; it does not universally prepend
  `Bearer`.
- The account action calls `consumer/signInUser/v2?fetchThroughV2=...` and stores
  a replacement authorization header when one is present. If no outlet cookie
  exists, it saves the returned outlet ID and repeats the account request.
- Requests include `X-OutletId`, `routing_context`, `DeviceId`, `DeviceName`,
  `X-Client`, `HeaderRoute`, `APIVersion`, `AppType`, and platform/app-mode
  metadata. Which fields are necessary must be determined by authenticated
  request replay, not assumed from their presence.
- Catalogue requests use `consumer/v2/search`, including outlet ID, pagination,
  query/filter fields, and a `getGlobalCatalog` flag. Authenticating then reading
  public landing-page HTML does not establish outlet-specific catalogue prices.
- The application has a session-expired path that clears token/outlet/app-mode
  cookies and navigates to sign-in. The inspected bundle contains no literal
  `refreshToken` or `refresh_token` and no literal `refresh`. This is limited
  evidence, not proof that no renewal mechanism exists elsewhere.
- `Access_Token`, `Payload_Token`, and `accessTokenExpiration` local-storage
  names appear with chatbot support endpoints. They must not be mistaken for
  the main account authentication flow without runtime evidence.
- Cookie helpers support persistent expiry. Cookie expiry does not establish
  server-side token lifetime.

## Existing repository findings

- `authenticate_location()` asks its OTP provider for a code *before* sending
  the OTP request. The replacement bootstrap must send, confirm success, then
  collect and use the OTP once.
- Login retains authorization only in an in-memory requests session.
- The prior cloud worker required `HYPERPURE_OTP` for configured accounts.
- The prior authenticated scraper read public landing pages and attached
  outlet metadata. That is insufficient evidence of authenticated pricing.
- Scheduled Hyperpure scraping currently skips when its supplier-location
  secret is absent. This must not be replaced with an invented verified outlet.

## Strategy evaluation and provisional selection

| Candidate | Current evidence and decision gate |
| --- | --- |
| Native refresh token | No dedicated refresh flow identified in this bundle; inspect live responses and expiry behavior before ruling it out. |
| Reusable HTTP session | Leading candidate: web requests explicitly use authorization and outlet context; replay must prove acceptance outside the browser. Small runtime footprint and low Actions maintenance if supported. |
| Browser storage state | Can preserve cookie/local-storage/IndexedDB state if required; larger sensitive artifact and browser dependency. Verify whether any of that is needed beyond the HTTP session. |
| Automatic browser renewal | Use only if runtime evidence shows browser execution renews state that direct HTTP cannot. Adds deployment and site-change maintenance. |
| Secure export/import | Appropriate bootstrap companion to either HTTP or browser reuse. Capture state immediately after login; never put credentials in fixtures or repository files. |
| Manual reauthentication | Necessary fallback only when the real session can no longer be renewed. Never request OTP in unattended workers. |
| Account-response token replacement | Observed application behavior; test whether replacement occurs, invalidates prior state, or extends lifetime before calling it automatic renewal. |

The reusable HTTP session is selected provisionally because it directly matches
the public application's behavior and avoids a browser dependency. Mutable
authorization/cookie state is encrypted into private Supabase Storage with a
separately managed Fernet key. Static GitHub secrets alone cannot persist
rotations. See `hyperpure-authentication.md` for the implemented architecture.

## Required next evidence

1. Obtain the authorized account phone number and prepare secure runtime capture
   before sending an OTP. Ask for the OTP only after confirmed delivery request.
2. Capture before/after cookie and browser-storage structure, relevant network
   responses, and authenticated outlet/catalogue metadata without logging secrets.
3. Replay the minimum session through direct HTTP, test a browser restart, and
   inspect token changes/expiry metadata. Record actual elapsed-time observations;
   do not infer hours or days of validity from one successful request.
4. Resolve outlet/service-zone identity and distinguish a Guest Outlet from a
   verifiable service location. Keep location unverified absent evidence.
5. Validate the implemented session provider, secure persistence, bootstrap,
   authenticated catalogue path, and worker states against the real account.
6. Validate real scrape/snapshots/comparison and conditional hosted offer E2E,
   then commit logical validated changes, push, and inspect CI/Render.

Authenticated replay, session lifetime, outlet verification, real scrape,
hosted E2E, commits, CI, and deployment verification remain pending. Offline
implementation and focused tests are present but require full-suite and live
validation before completion.
