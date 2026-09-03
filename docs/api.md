# Application API

The FastAPI application exposes OpenAPI at `/docs` and `/openapi.json`. All domain endpoints require
a verified Supabase/Cognito bearer token or the equivalent secure HTTP-only access-token cookie.

## Authentication

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/signup` | Create provider user and send verification code |
| POST | `/api/auth/confirm` | Confirm email verification code |
| POST | `/api/auth/login` | Authenticate and issue token response/cookies |
| POST | `/api/auth/forgot-password` | Start password recovery |
| POST | `/api/auth/reset-password` | Confirm recovery code and new password |
| POST | `/api/auth/refresh` | Refresh access session |
| POST | `/api/auth/logout` | Revoke current session and clear cookies |
| GET | `/api/auth/session` | Return identity and fixed-location onboarding state |
| POST | `/api/restaurants/bootstrap` | Create the authenticated user's one V1 restaurant/location |

## Procurement

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/products/search?q=` | Canonical, brand, category, alias, raw-name, and fuzzy search |
| GET | `/api/products/{id}` | Canonical product detail |
| GET | `/api/products/{id}/offers` | Tenant-location-filtered current offers and freshness |
| GET | `/api/products/{id}/history` | Observations and trustworthy 7/30-day statistics |
| POST | `/api/compare` | Quantity-aware rankings and explicit excluded offers |
| POST | `/api/purchases` | Atomically create purchase, inventory additions, and expense |
| GET | `/api/purchases` | Tenant purchase ledger |
| GET | `/api/purchases/{id}` | Immutable purchase detail and snapshots |
| GET | `/api/inventory` | Current tenant/location balances |
| POST | `/api/inventory/adjustments` | Manual add/remove/correction transaction |
| GET | `/api/inventory/{id}/transactions` | Auditable inventory history |
| GET | `/api/analytics/spending` | Actual-paid spend by time, supplier, product, and category |
| GET | `/api/scrape-runs` | Recent freshness/run state |
| GET | `/api/scrape-runs/{id}` | Run diagnostics |

`POST /api/compare` example:

```json
{"product_id":"<uuid>","required_quantity":"25","unit":"kg"}
```

The response keeps `by_total_cost`, `by_unit_price`, and `by_excess_quantity` separate. Offers with
unknown pack, price, availability, or incompatible units are returned in `excluded` with a reason.

## Tenancy and errors

Restaurant identity is always resolved server-side from the authenticated provider subject and
membership. Client-provided restaurant IDs are not accepted by domain endpoints. Purchase,
inventory, expense, and location queries include that resolved tenant boundary.

Validation failures use HTTP 422. Authentication uses 401, onboarding/tenant violations use 403,
missing tenant-owned records use 404, duplicate onboarding uses 409, and invalid business state uses
400. External identity-provider codes are reduced to a safe error class; tokens and credentials are
never logged or returned in error details.
