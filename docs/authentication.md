# Authentication and tenancy

## Provider boundary

The beta uses Supabase Auth. `AUTH_PROVIDER=supabase` selects `SupabaseAuthProvider` and its JWKS
verifier; `AUTH_PROVIDER=cognito` selects the retained AWS adapter. Both return the same internal
`AuthTokens` and `AuthPrincipal` types. Procurement services know only the authenticated subject,
never Supabase or Cognito token structures.

Required beta settings are `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` (the legacy
`SUPABASE_ANON_KEY` alias is accepted). The publishable key is low privilege, but this
server-rendered application keeps all auth calls on the server. The secret/service-role key is not
used for authentication and must never reach HTML, JavaScript, API responses, or Render settings.

Supabase access JWTs are verified locally against
`/auth/v1/.well-known/jwks.json`, including signature, issuer, `authenticated` audience, subject,
and expiry. Cognito continues to verify issuer, app client, token use, subject, expiry, and signature.
There is no insecure local fallback; incomplete provider configuration makes auth routes return 503.

## User flows

The API supports signup, email confirmation, password login, refresh, local-session logout, recovery,
and password reset through either adapter. For the existing code-entry UI, configure Supabase signup
and recovery email templates to display `{{ .Token }}` and add the deployed `/login` URL to Auth
redirect allowlists. If standard magic links are preferred later, add a dedicated callback flow rather
than parsing unverified fragments in the backend.

Browser sessions use HTTP-only, SameSite=Lax cookies. Hosted environments set `COOKIE_SECURE=true`.
API clients may use a bearer token. Responses add CSP, clickjacking, MIME-sniffing, referrer,
permissions-policy, no-store API caching, request IDs, and HSTS under secure-cookie deployments.

## Authorization remains server-side

After verification and login, `/onboarding` creates the application `users` row, restaurant
membership, and one fixed beta location using the verified provider subject. Every protected data
operation derives restaurant and location from that membership; client-provided tenant IDs cannot
override it. Supplier-location mappings remain manually verified administrative data.

Supabase RLS is defense in depth for its Data API, not the authorization authority. The beta backend
connects through a trusted PostgreSQL owner connection, which bypasses RLS, and therefore every API
query must continue enforcing the tenant boundary. `infrastructure/supabase/rls.sql` enables RLS and
revokes application-table access from `anon` and `authenticated`, so browser keys cannot bypass the
backend. Tenant isolation tests remain mandatory for both providers.

Real Supabase acceptance requires a project and test mailbox; local fake-provider tests prove the
provider contract but do not claim hosted email delivery or token issuance.
