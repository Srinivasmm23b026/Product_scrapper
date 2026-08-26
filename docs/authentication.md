# Authentication and tenancy

Amazon Cognito is the production identity provider. The application requires
`COGNITO_USER_POOL_ID`, `COGNITO_APP_CLIENT_ID`, and `AWS_REGION` to configure it. Without those
values auth routes return a service-unavailable response rather than accepting an insecure fallback.

Access/ID JWTs are verified against the user pool's JWKS, expected issuer, application client, token
use, signature, and expiry. Browser sessions use HTTP-only, SameSite cookies; deployed environments
must set `COOKIE_SECURE=true` under HTTPS. API clients may use a bearer token.

After email verification and login, `/onboarding` uses `/api/restaurants/bootstrap` to create the
V1 restaurant, membership, and one beta location. `/api/auth/session` reports whether that step is
complete. Every protected data operation derives restaurant and location
from that authenticated membership. There is no API parameter that can override this tenant.

Supplier-location mappings are administrative data. They must be configured only after a supplier
store/warehouse/zone mapping is verified; onboarding does not guess a mapping from restaurant
pincode.

The Cognito integration and every auth contract are testable through provider/verifier interfaces.
Real Cognito acceptance remains blocked until an allowed AWS account is supplied and classified.

Production responses add CSP, clickjacking, MIME-sniffing, referrer, permissions-policy, no-store
API caching, and HSTS headers. The CloudFormation workload sets secure cookies and forces public
traffic through HTTPS CloudFront; the ALB only forwards requests carrying its secret origin header.
