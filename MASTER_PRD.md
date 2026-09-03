# Procurement Assistant V1 — Master PRD & Autonomous Codex Execution Plan

**Document type:** Product Requirements Document + Engineering Execution Specification  
**Target:** V1 restaurant procurement assistant  
**Primary implementation agent:** Codex  
**Execution mode:** Autonomous, phase-gated, stop only for genuine external blockers  
**Current repository state:** Implemented V1 application with PostgreSQL, provider adapters, and legacy compatibility
**V1 beta cloud target:** Supabase PostgreSQL/Auth/Storage + portable application hosting and scheduler
**Future cloud target:** AWS using student/promotional credits where permitted
**Status:** Supabase deployment preparation; hosted validation pending credentials

## 2026-09 Supabase-first amendment

This amendment supersedes AWS-first language elsewhere in this document only where it affects the
initial V1 beta dependency/order. It does not delete or invalidate the retained AWS architecture.

V1 beta uses Supabase as managed PostgreSQL, Auth, and optional private object storage. The combined
FastAPI/PWA may run on a suitable container host, and the Python scraper may run from GitHub Actions.
Core business behavior must use standard PostgreSQL and provider-neutral auth, storage, metrics, and
worker boundaries. It must not depend on Supabase Data APIs, RPC, generated clients, Edge Functions,
or RLS as its sole authorization mechanism.

Future AWS deployment replaces infrastructure/providers—Supabase PostgreSQL → RDS, Supabase Auth →
Cognito, Supabase Storage → S3, GitHub schedule → EventBridge/ECS, structured logs → CloudWatch—
without rewriting procurement, matching, comparison, purchase, inventory, expense, history, tenancy,
or scraper-run logic.

---

# 1. Product Vision

Build a procurement assistant for restaurants and local food businesses that helps them compare wholesale/e-commerce product prices for a specific location, estimate the real cost of buying required quantities, record purchases, track inventory, and analyze procurement spending.

The product should begin as a fixed-location beta and evolve later into a location-aware procurement platform that can support different suppliers, cities, pincodes, stores, warehouses, and serviceability zones.

The repository began as a data-acquisition prototype and now contains the restaurant application,
PostgreSQL domain model, migration, APIs/PWA, provider adapters, reliable worker, and deployment
assets. Remaining V1 work is hosted Supabase deployment/validation and real beta feedback; the
preserved SQLite path is legacy input rather than the application database.

---

# 2. V1 User Experience

A restaurant user should be able to:

1. Sign up and log in.
2. Operate from one configured beta location.
3. Search for a product such as rice, tomato, oil, milk, or onions.
4. Enter the required quantity, such as `25 kg`.
5. View comparable offers from supported suppliers.
6. See:
   - supplier,
   - pack size,
   - price,
   - normalized unit price,
   - number of packs needed,
   - quantity purchased,
   - excess quantity,
   - total procurement cost,
   - last observed time,
   - availability,
   - supplier product link.
7. Sort or compare by total cost, unit price, or excess quantity.
8. Open the original supplier product page.
9. Record the actual purchase.
10. Automatically update inventory.
11. Automatically create a procurement expense record.
12. View current inventory.
13. View spending analytics.
14. View product price history.

Canonical flow:

```text
Login
  ↓
Fixed Restaurant Location
  ↓
Search Product
  ↓
Select Required Quantity
  ↓
Compare Supplier Offers
  ↓
Open Supplier Listing / Record Purchase
  ↓
Purchase Ledger
  ├── Inventory Transaction
  └── Expense Entry
  ↓
Inventory + Spending + Price History
```

---

# 3. Target Users

## Primary

- Independent restaurants
- Small restaurant groups
- Local food vendors
- Cloud kitchens
- Cafes
- Small hospitality businesses purchasing ingredients in bulk

## V1 Beta

Target approximately:

- 1 fixed service location
- 3–4 supported suppliers
- 5–10 restaurant users

Do not optimize V1 for nationwide coverage.

---

# 4. Core Product Principles

1. **Data trust before feature breadth.**
2. **Price observations must always have timestamps.**
3. **A successful HTTP request is not automatically a successful scrape.**
4. **Supplier location semantics must be explicit.**
5. **Scraped price and actual purchase price are different concepts.**
6. **Canonical product, purchasable variant, supplier offer, and location must be separate entities.**
7. **Historical observations must never be rewritten when current data changes.**
8. **Missing products must not be marked unavailable because a scrape failed.**
9. **V1 should remain deterministic where possible.**
10. **LLMs must not be required for core product matching in V1.**
11. **Cloud architecture must be portable and cost-conscious.**
12. **Codex must prefer finishing V1 over speculative platform engineering.**

---

# 5. V1 Scope

## Included

- Existing supplier scraping
- Location-aware supplier data where technically available
- Reliable scrape-run semantics
- PostgreSQL persistence
- Historical price observations
- Product normalization
- Canonical product matching
- Quantity-based comparison
- User authentication
- Restaurant account
- Fixed beta location
- Product search
- Supplier comparison
- Supplier deep links
- Purchase recording
- Inventory tracking
- Procurement spending analytics
- Price-history UI
- Scheduled cloud scraping
- Monitoring
- Responsive restaurant-facing UI
- Beta hardening

## Explicitly Outside V1

Do not implement unless required for V1 correctness:

- AI chat procurement agent
- invoice OCR
- automated checkout
- cart automation
- supplier ordering APIs
- mixed-supplier basket optimization
- POS integrations
- accounting integrations
- recipe/BOM-based inventory depletion
- automatic kitchen consumption
- demand forecasting
- predictive purchasing
- nationwide dynamic location support
- multi-branch restaurant management
- native iOS/Android apps
- vendor negotiation
- notifications
- supplier bidding
- automatic savings claims not backed by time-aligned observations

---

# 6. Current Repository Baseline

Current project characteristics discovered during reconnaissance:

- Local Python batch scraper.
- Suppliers:
  - Hyperpure
  - BigBasket
  - Deliverit
  - Lots Wholesale
- SQLite database.
- Current and historical product observations.
- Heuristic canonical matching.
- Windows `.bat` launcher.
- External Windows Task Scheduler assumed by documentation.
- No frontend.
- No web API.
- No authentication.
- No automated tests.
- No CI.
- No container/deployment environment.
- Location behavior is inconsistent across suppliers.
- Existing data includes stale and partial observations.
- Current matching is prototype-grade.
- Generated data/log/bytecode artifacts are tracked.

Preserve existing useful behavior and data until migrations are verified.

---

# 7. Target Architecture

```text
                         SUPPLIER SOURCES
          ┌───────────────┼────────────────┬───────────────┐
          │               │                │               │
      Hyperpure       BigBasket          Lots         Deliverit
          │               │                │               │
          └────────────── Scraper / Adapter Layer ──────────┘
                               │
                               ▼
                       Scrape Run Controller
                               │
                  ┌────────────┴────────────┐
                  │                         │
                  ▼                         ▼
          Raw Source Snapshot          Normalizer
        (provider storage)                 │
                                          ▼
                                  Product Identity Layer
                                          │
                       ┌──────────────────┼─────────────────┐
                       │                  │                 │
                       ▼                  ▼                 ▼
                 Canonical Product   Product Variant   Supplier Offer
                                                        │
                                                        ▼
                                               Price Observations
                                                        │
                                                        ▼
                                      Standard PostgreSQL (Supabase/RDS)
                                                        │
                                                        ▼
                                                Application Backend
                  ┌─────────────────────────────┬──────────────────────────────┐
                  │                             │                              │
                  ▼                             ▼                              ▼
               Search                    Procurement Engine                History
                                               │
                                               ▼
                                           Purchases
                                        ┌──────┴──────┐
                                        ▼             ▼
                                    Inventory      Expenses
                                        │             │
                                        └──────┬──────┘
                                               ▼
                                         Web App / PWA
                                               │
                                               ▼
                                         Restaurant User
```

---

# 8. Cloud Deployment Strategy

## V1 beta: Supabase-first, cloud-portable

- **Supabase PostgreSQL** — accessed through the existing ORM/Alembic database contract
- **Supabase Auth** — behind the authentication-provider interface
- **Supabase Storage or local storage** — behind the object-storage interface
- **GitHub Actions scheduled worker** — invokes the same non-interactive Python worker
- **Structured logs + persisted scrape runs** — provider-neutral beta visibility
- **Portable container host** — combined FastAPI/PWA; no Supabase Edge Function requirement

Backend tenant authorization remains mandatory. Supabase RLS may deny direct Data API access or add
defense in depth, but it is not the only authorization boundary. Service-role credentials are
server/worker-only and never exposed to browser code.

## Future option: AWS architecture

AWS must only be provisioned when the account type and permissions make it appropriate.

Preferred components:

- **Amazon RDS PostgreSQL** — application database
- **Amazon S3** — raw scrape snapshots, exports, backup artifacts
- **Amazon Cognito** — user authentication
- **Amazon EventBridge Scheduler** — scheduled scraper execution
- **Amazon CloudWatch** — logs, metrics, alarms
- **AWS Systems Manager Parameter Store or Secrets Manager** — secrets/configuration
- **Lambda** — optional for short/stateless scraper jobs
- **ECS/Fargate or another small worker runtime** — if scraping runtime exceeds practical Lambda constraints

Avoid unnecessary infrastructure. AWS is not a prerequisite for the V1 beta.

## Mandatory cost controls

When AWS deployment becomes available:

- create AWS Budget,
- enable billing alerts,
- prefer smallest practical database,
- use conservative log retention,
- use S3 lifecycle rules,
- avoid NAT Gateway unless clearly required,
- do not enable Multi-AZ solely for a beta,
- avoid idle compute,
- tag all resources,
- document estimated recurring cost.

## AWS student-account rule

Codex must determine whether access is:

1. a normal AWS account with educational/promotional credits, or
2. an AWS Academy/Learner Lab/training environment.

Do not deploy a real restaurant beta into a training/lab environment if its terms prohibit live/commercial workloads.

If account classification cannot be determined programmatically, this is a valid user blocker.

---

# 9. Target Domain Model

The V1 data model should conceptually support the following entities.

## Identity and tenancy

### User
- id
- auth_provider_id
- email
- created_at
- updated_at

### Restaurant
- id
- name
- created_at
- updated_at

### RestaurantMembership
- user_id
- restaurant_id
- role

### RestaurantLocation
- id
- restaurant_id
- label
- address fields as required
- city
- pincode
- latitude optional
- longitude optional
- is_beta_default

---

## Supplier model

### Supplier
- id
- code
- name
- base_url
- active

### SupplierLocation
Represents the supplier's actual operational location concept.

Examples:

- store
- warehouse
- serviceability zone
- city
- fulfilment center

Fields:

- id
- supplier_id
- external_location_id
- location_type
- name
- city
- pincode optional
- metadata
- active

### SupplierLocationMapping
Maps restaurant location to actual supplier location.

- restaurant_location_id
- supplier_id
- supplier_location_id
- resolution_method
- verified_at
- active

Do not assume `pincode` itself is supplier identity.

---

## Product model

### CanonicalProduct
Represents the conceptual item.

Example:

`Fortune Sunlite Sunflower Oil`

Possible fields:

- id
- normalized_name
- display_name
- canonical_brand
- category
- subcategory
- status
- created_at
- updated_at

### ProductVariant
Represents a purchasable normalized form.

Example:

`Fortune Sunlite Sunflower Oil — 1 L`

Fields:

- id
- canonical_product_id
- quantity
- base_unit
- pack_count
- total_quantity
- normalized_pack_text
- attributes
- created_at

### SupplierProduct
Represents supplier-side product identity.

Fields:

- id
- supplier_id
- external_product_id
- external_variant_id optional
- source_name
- source_brand
- source_pack_text
- product_url
- image_url
- metadata

### SupplierOffer
Represents the sale of a supplier product/variant at a supplier location.

Fields:

- id
- supplier_product_id
- product_variant_id
- supplier_location_id
- active
- current_price
- current_mrp
- current_availability
- last_seen_at
- consecutive_misses
- current_observation_id optional

The same supplier product may have different offers by location.

---

## Scraping and price history

### ScrapeRun
Fields:

- id
- supplier_id
- supplier_location_id
- started_at
- finished_at
- status
- expected_count
- observed_count
- failed_page_count
- warning_count
- error_summary
- metadata

Allowed V1 statuses:

- `running`
- `complete`
- `partial`
- `failed`
- `suspicious_zero`
- `interrupted`

### PriceObservation
Fields:

- id
- supplier_offer_id
- scrape_run_id
- price
- mrp
- availability
- observed_at
- raw_reference optional

Historical observations are immutable.

---

## Matching

Matching metadata should support:

- match_method
- match_confidence
- review_status
- matched_at

Recommended review states:

- `AUTO_MATCH`
- `REVIEW`
- `NO_MATCH`
- `MANUAL_MATCH`

---

## Purchasing

### Purchase
Fields:

- id
- restaurant_id
- restaurant_location_id
- supplier_id
- purchased_at
- total_amount
- notes
- created_by_user_id

### PurchaseItem
Fields:

- id
- purchase_id
- canonical_product_id
- product_variant_id
- supplier_offer_id optional
- supplier_product_url_snapshot
- packs
- quantity
- unit
- scraped_price_snapshot
- actual_unit_price
- actual_total_price

Never mutate historical purchases based on later scrape values.

---

## Inventory

### InventoryItem
Fields:

- id
- restaurant_id
- restaurant_location_id
- canonical_product_id
- base_unit
- current_quantity
- updated_at

### InventoryTransaction
Fields:

- id
- inventory_item_id
- transaction_type
- quantity_delta
- purchase_item_id optional
- created_by_user_id
- created_at
- note

V1 transaction types:

- purchase
- manual_add
- manual_remove
- correction

---

## Financial tracking

### ExpenseEntry
Fields:

- id
- restaurant_id
- restaurant_location_id
- purchase_id optional
- category
- amount
- expense_date
- supplier_id optional
- metadata

For V1, procurement expenses generated from purchases are sufficient.

---

# 10. Quantity Procurement Engine

Given a required quantity and a supplier offer:

```text
packs_required = ceil(required_quantity / pack_total_quantity)
quantity_purchased = packs_required * pack_total_quantity
excess_quantity = quantity_purchased - required_quantity
total_cost = packs_required * pack_price
unit_price = pack_price / pack_total_quantity
```

Supported normalized base units for V1 should include at minimum:

- kg
- L
- piece

Conversions must support common source forms:

- g → kg
- ml → L
- piece / pcs / unit normalization
- multipacks

Examples:

```text
500 g                     → 0.5 kg
2 × 250 g                 → 0.5 kg
5 × 1 kg                  → 5 kg
12 pcs                    → 12 piece
Pack of 10                → 10 piece
1.5 L                     → 1.5 L
750 ml                    → 0.75 L
```

Never compare incompatible units.

V1 rankings:

- lowest total cost,
- lowest normalized unit price,
- lowest excess quantity.

These must be displayed separately because they may point to different offers.

Mixed-supplier optimization is not required for V1.

---

# 11. Supplier Deep-Link Behavior

Every supplier offer should retain the most useful stable supplier URL available.

The UI should allow users to open the original supplier listing.

Because supplier sites may require location/session/login state, the application must not guarantee that the price shown on the supplier page at click time equals the last scraped price.

Always show:

- last observed price,
- last checked timestamp,
- availability state,
- supplier.

Where appropriate, display a small disclaimer equivalent to:

> Supplier price may have changed since the last check.

---

# 12. Search Requirements

V1 search must support:

- canonical product name
- supplier product names
- brand
- category
- normalized aliases where available
- typo-tolerant/fuzzy matching

Results should prioritize:

1. exact or strong canonical name match,
2. brand + product match,
3. fuzzy match,
4. supplier raw-name fallback.

Do not require embeddings or a vector database for V1 unless measurable evaluation shows a concrete need.

---

# 13. Authentication and Authorization

Preferred V1 beta provider: Supabase Auth. Amazon Cognito remains the future AWS adapter.

V1 flows:

- signup
- email verification
- login
- logout
- forgot password
- password reset
- session refresh
- protected routes

Application tenancy must be enforced server-side.

Never trust a client-provided `restaurant_id` without verifying membership/ownership.

A user must not be able to access another restaurant's:

- purchases,
- inventory,
- expenses,
- settings.

---

# 14. API Expectations

Exact framework selection may be made by Codex based on repository compatibility.

Minimum logical API surface:

```text
GET  /products/search
GET  /products/{id}
GET  /products/{id}/offers
GET  /products/{id}/history

POST /compare

POST /purchases
GET  /purchases
GET  /purchases/{id}

GET  /inventory
POST /inventory/adjustments

GET  /analytics/spending

GET  /scrape-runs
GET  /scrape-runs/{id}
```

Admin/internal endpoints may be added where necessary.

All request/response contracts must be documented and tested.

---

# 15. UI Requirements

V1 should be a responsive web application or PWA.

## Primary navigation

- Dashboard
- Compare
- Inventory
- Purchases
- Spending

## Compare page

Primary inputs:

- product search
- required quantity
- unit selector when relevant

Offer result should show:

- supplier
- product name
- pack
- pack price
- normalized unit price
- packs required
- quantity purchased
- excess quantity
- total cost
- availability
- last checked timestamp
- supplier link

Highlight separately:

- best total cost
- best unit price

Do not visually imply that the cheapest unit price always means cheapest purchase.

## Dashboard

Minimum useful metrics:

- spending this month
- recent purchases
- inventory items running low if manual threshold exists
- recent price movements where reliable
- scraper freshness/last update indicator

## Inventory

Show:

- item
- quantity
- unit
- last purchase
- updated time

Allow manual positive and negative adjustments.

## Purchases

Show:

- supplier
- item
- quantity
- actual price
- date

## Spending

Show:

- current-month procurement spend
- spend over time
- spend by supplier
- spend by product/category

## Price history

Show:

- current price
- 7-day low where sufficient history exists
- 30-day low
- 30-day average
- chart
- last observed timestamp

Do not calculate misleading statistics when insufficient trustworthy history exists.

---

# 16. Testing Strategy

The project must gain automated tests before major downstream development depends on scraper output.

Testing layers:

## Unit tests

- unit parsing
- normalization
- procurement calculations
- matching helpers
- validation
- authorization helpers

## Scraper fixture tests

Freeze representative HTML/JSON/XML payloads for each source.

Do not rely exclusively on live network tests.

## Database tests

- migrations
- constraints
- run attribution
- history immutability
- transaction behavior
- stale-product logic

## Matching benchmark

Maintain reviewed examples containing:

- positive matches
- negative matches
- ambiguous cases
- cross-pack relationships

Report real metrics only from labeled fixtures.

Do not invent precision, recall, accuracy, or coverage numbers.

## API tests

- auth-required behavior
- tenant isolation
- search
- compare
- purchases
- inventory
- analytics

## UI tests

At minimum:

- key route smoke tests
- compare flow
- purchase recording
- inventory update
- auth-protected navigation

## End-to-end V1 flow

Must validate:

```text
login
→ search
→ compare
→ record purchase
→ inventory increases
→ expense appears
→ history remains unchanged
```

---

# 17. Scraper Reliability Rules

A scraper run is not binary success/failure.

Use:

- complete
- partial
- failed
- suspicious_zero
- interrupted

Objective completeness signals should be used where supplier data permits:

- API reported total count
- pagination total
- sitemap count
- category count
- expected page count
- previous-run count range

Examples of suspicious outcomes:

- previous normal count: ~2,000
- current count: 0
- HTTP requests succeeded

This is `suspicious_zero`, not `complete`.

Another example:

- expected: 2,000
- observed: 340
- several pages failed

This is `partial`.

A failed/partial scrape must not automatically mark missing products unavailable.

Only trustworthy complete runs may advance absence counters.

---

# 18. Historical Data Policy

The existing SQLite data is valuable but imperfect.

Migration must preserve legacy observations without inventing missing metadata.

Examples:

- If a historical row has no `run_id`, keep it as a legacy observation.
- If location mapping was ambiguous, preserve the original pincode/source metadata rather than pretending a supplier location was known.
- Do not create fake availability history.
- Do not fabricate missing timestamps.
- Do not silently deduplicate historical rows unless the deduplication rule is explicit and reversible.

A migration report must reconcile:

- source row counts
- migrated row counts
- rejected rows
- transformed rows
- legacy limitations

---

# 19. Git and Repository Rules

Codex must work in logical milestones.

Recommended practice:

- one coherent commit per completed phase or meaningful sub-phase,
- descriptive commit messages,
- keep the working tree understandable,
- do not bundle unrelated refactors.

Never commit:

- credentials
- OTPs
- tokens
- secrets
- `.env` files containing secrets
- private supplier session data
- runtime logs
- Python bytecode
- local virtual environments
- temporary browser profiles
- generated locks unrelated to dependency reproducibility

Repository should include a proper `.gitignore`.

Preserve existing user work.

Do not rewrite Git history unless explicitly required by the user.

---

# 20. Documentation Rules

Documentation must evolve with implementation.

Maintain at minimum:

- README
- architecture overview
- local development setup
- environment-variable reference
- database/domain model
- scraper behavior
- deployment guide
- cloud provider map, including retained AWS resources
- operational runbook
- testing instructions

Documentation must describe current implementation, not obsolete plans.

If an older design is retained for context, mark it explicitly as superseded.

---

# 21. Security Rules

- No secrets in source code.
- No supplier credentials in frontend bundles.
- Use environment variables or the selected cloud provider's secret/config services.
- Enforce tenant authorization server-side.
- Validate external input.
- Use parameterized database access/ORM protections.
- Use HTTPS in deployed environments.
- Avoid exposing internal scrape/admin endpoints publicly.
- Apply reasonable API rate limiting where useful.
- Validate redirect/deep-link handling.
- Never bypass CAPTCHA, MFA, supplier authentication, rate limits, or anti-bot mechanisms.
- Do not automate actions that violate supplier access controls.
- Do not store unnecessary personal data.

---

# 22. Observability

At minimum, track:

- scrape-run state
- supplier
- location
- duration
- observed product count
- expected product count where available
- failed pages
- parser errors
- database errors
- scheduler failures
- stale data age

Useful alerts:

- scraper failed
- suspicious zero
- abnormal count drop
- supplier data stale beyond threshold
- database connectivity failure
- application health failure

The application must not silently present old data as current.

---

# 23. Autonomous Execution Policy

Codex is the primary implementation agent.

It must not ask for approval after completing each phase.

It should proceed automatically when the next phase is technically possible.

## Codex must make normal engineering decisions independently

Examples:

- library selection
- schema naming
- test structure
- component organization
- refactoring approach
- indexing
- error handling
- dependency additions
- internal interfaces
- API shape details
- file organization
- minor UI behavior

Decision priority:

1. correctness
2. security
3. data integrity
4. maintainability
5. simplicity
6. cost-consciousness
7. testability
8. existing repository conventions
9. V1 scope

## These are NOT blockers

Codex must not stop because:

- a phase completed,
- it wants permission to continue,
- tests failed,
- lint failed,
- a refactor is needed,
- documentation is stale,
- a dependency needs to be added,
- the initial design needs adjustment,
- a schema migration is needed,
- implementation differs from the prototype,
- there are multiple reasonable libraries,
- a bug was discovered,
- the next phase is larger than the previous phase.

Codex should resolve these independently.

---

# 24. Valid Stop Conditions

Codex may stop only when progress genuinely depends on something unavailable from inside the repository/runtime.

Valid blockers include:

- Supabase project access, credentials, or project configuration
- Render/GitHub account access, secrets, or hosted-service configuration
- AWS account access or credentials
- AWS permissions
- inability to determine whether the provided AWS environment may host the beta
- supplier login credentials
- OTP
- CAPTCHA
- MFA
- authenticated browser action
- external secret
- domain/DNS ownership action
- billing/account action
- destructive action against user-owned external infrastructure
- required business data that cannot safely be inferred
- legal/terms constraint requiring user decision
- a supplier flow that requires manual consent/action

When only one subtask is blocked, Codex should continue any other independent work that does not depend on the blocker.

Stop only at the smallest unavoidable boundary.

---

# 25. Mandatory Blocker Format

When blocked, Codex must report exactly:

```text
BLOCKER:
<what is required>

WHY:
<why implementation cannot safely continue without it>

USER ACTION:
<precise action or information required from the user>

STATE:
<what has already been completed and verified>

RESUME FROM:
<exact next task to execute after the blocker is resolved>
```

Do not ask:

> How would you like to proceed?

Do not ask for approval of normal engineering decisions.

---

# 26. Phase Execution Rules

Every phase has:

- goal
- implementation scope
- acceptance criteria
- exit gate

Codex must:

1. inspect existing implementation before changing it,
2. make the smallest coherent design required for the phase,
3. implement,
4. add/update tests,
5. run relevant tests,
6. run lint/type checks if configured,
7. update documentation,
8. inspect Git diff,
9. fix issues,
10. commit logical work if repository permissions allow,
11. verify phase acceptance criteria,
12. proceed to next phase automatically.

Never claim a phase is complete if its acceptance criteria are not met.

---

# 27. The 20-Phase V1 Roadmap

---

## Phase 0 — Repository Baseline and Preservation

### Goal

Create a safe, reproducible baseline without changing product behavior.

### Implement

- Preserve existing SQLite database.
- Preserve current scraper behavior.
- Record baseline row counts and schema.
- Add proper `.gitignore`.
- Stop tracking future generated:
  - `__pycache__`
  - `.pyc`
  - runtime logs
  - session/lock metadata
  - local environments
- Decide how the tracked existing database/log artifacts are archived.
- Establish reproducible Python setup.
- Pin or constrain dependencies appropriately.
- Establish test directory/framework.
- Add smoke checks.
- Document current launch procedure and environment expectations.

### Do not

- redesign scrapers,
- rewrite matching,
- migrate storage yet,
- remove historical data.

### Acceptance criteria

- repository is clean after intended changes,
- historical data is preserved,
- source imports/compiles,
- local setup is documented,
- baseline data statistics are recorded,
- generated artifacts policy is explicit.

### Autonomous?

Yes.

---

## Phase 1 — Live Supplier Validation

### Goal

Determine the current real extraction and location mechanisms for:

- Hyperpure
- BigBasket
- Deliverit
- Lots Wholesale

### Investigate for each supplier

- discovery mechanism
- product ID
- variant ID
- name
- brand
- pack
- selling price
- MRP
- availability
- image
- product URL
- pagination
- catalogue completeness
- authentication
- location semantics

### Hyperpure

Verify:

- current landing pages,
- structured payloads,
- current location behavior,
- current known working location-price variation,
- product ID stability,
- pagination/lazy loading,
- authenticated vs anonymous differences.

Preserve working location behavior unless evidence supports a change.

### BigBasket

Determine:

- why old location endpoint returns 404,
- current location-selection mechanism,
- relevant cookies/session/location identifiers,
- current category/product data source,
- completeness/pagination behavior.

### Deliverit

Determine:

- current sitemap/index behavior,
- robots-discovered sitemaps,
- category/search/API alternatives,
- cause of recent zero discovery,
- JSON-LD reliability,
- catalogue size/completeness signals.

### Lots

Determine:

- current pincode-to-store mapping,
- whether authentication is needed,
- role of `storeCode`,
- whether pincode independently affects price/catalogue,
- whether both beta pincodes should map to the same store,
- pagination completeness.

### Output

Produce and save a validation report:

| Source | Current mechanism | Existing scraper valid? | Location valid? | Completeness signal | Status |
|---|---|---|---|---|---|

Allowed status:

- WORKING
- PARTIAL
- BROKEN
- BLOCKED_BY_AUTH

### Acceptance criteria

- each source classified,
- assumptions validated with evidence,
- broken assumptions documented,
- no repository implementation changed merely to hide unresolved live-source uncertainty.

### Autonomous?

Yes, unless supplier authentication/manual action is required.

---

## Phase 2 — V1 Domain Model and PostgreSQL Schema Design

### Goal

Define the application data model before downstream implementation.

### Implement

Model:

- users
- restaurants
- memberships
- restaurant_locations
- suppliers
- supplier_locations
- supplier_location_mappings
- canonical_products
- product_variants
- supplier_products
- supplier_offers
- scrape_runs
- price_observations
- purchases
- purchase_items
- inventory_items
- inventory_transactions
- expense_entries

### Requirements

- stable keys
- timestamps
- uniqueness constraints
- foreign-key decisions
- indexes
- explicit location semantics
- immutable price history
- supplier offer separation from product identity
- current-state convenience fields where justified

### Deliverables

- schema/ER documentation
- migration framework
- initial schema migrations
- schema tests

### Acceptance criteria

- schema supports V1 flows,
- schema supports multiple future locations without requiring redesign,
- pincode is not overloaded as supplier offer identity,
- product family/variant/offer concepts are separate,
- tests verify key constraints.

### Autonomous?

Yes.

---

## Phase 3 — Scrape Run Reliability Layer

### Goal

Make data collection attributable and trustworthy.

### Implement

Scrape statuses:

- running
- complete
- partial
- failed
- suspicious_zero
- interrupted

Capture:

- supplier
- supplier location
- start/end time
- expected count
- observed count
- failed pages
- warnings
- error details

Every new price observation must reference its scrape run.

### Product disappearance rules

Add:

- `last_seen_at`
- `consecutive_misses`
- availability/status handling

Only trustworthy complete runs can contribute to absence/unavailability decisions.

### Transaction rules

- partial DB writes must not masquerade as successful full runs,
- run completion state must reflect actual data persistence state.

### Acceptance criteria

- zero results are never automatically successful,
- partial runs are represented,
- observations are attributable,
- failed runs cannot retire products,
- transactional failure cases have tests.

### Autonomous?

Yes.

---

## Phase 4 — Test and Fixture Foundation

### Goal

Create regression protection for all critical parsing and data behavior.

### Implement

Frozen fixtures for:

- Hyperpure
- BigBasket
- Deliverit
- Lots

Unit tests for unit parsing including:

- `500 g`
- `2 x 250 g`
- `2 × 250 g`
- `5 x 1 kg`
- `12 pcs`
- `Pack of 10`
- `1.5 L`
- `750 ml`
- `25 KG`

Fix the known `2x250 G` issue.

Add tests for:

- scraper extraction
- pagination
- location metadata
- failure behavior
- database migrations
- run semantics
- current/stale state
- transaction boundaries

### Acceptance criteria

- deterministic test suite,
- known parser bug fixed,
- fixture-based scraper tests exist for all supported sources,
- important failure paths covered,
- no reliance solely on live network tests.

### Autonomous?

Yes.

---

## Phase 5 — Product Normalization and Matching V1

### Goal

Create reliable canonical product and variant matching.

### Inputs

Use normalized:

- brand
- product name
- category
- base commodity
- quantity
- base unit
- pack count
- variant attributes

### Matching behavior

Maintain:

- match confidence
- match method
- review state

States:

- AUTO_MATCH
- REVIEW
- NO_MATCH
- MANUAL_MATCH

### Rules

- deterministic matching first,
- no LLM dependency for core V1 matching,
- separate product-family identity from pack variant,
- never match incompatible base units,
- avoid empty-brand over-grouping.

### Benchmark

Create reviewed positive/negative/ambiguous fixtures.

Report actual measured benchmark metrics only.

### Acceptance criteria

- deterministic matcher,
- tests for positive and negative cases,
- family vs variant distinction works,
- confidence/review metadata stored,
- benchmark reproducible.

### Autonomous?

Yes.

---

## Phase 6 — Quantity Comparison / Procurement Engine

### Goal

Calculate real procurement cost for restaurant-required quantities.

### Implement

For each offer:

```text
packs_required
quantity_purchased
excess_quantity
total_cost
normalized_unit_price
```

Support:

- kg/g
- L/ml
- pieces/counts
- multipacks

Reject incompatible comparisons.

### Ranking

Expose separately:

- lowest total cost
- lowest unit price
- lowest excess

### Acceptance criteria

Tests cover:

- exact fit,
- required over-pack purchase,
- multipacks,
- unavailable offers,
- unknown pack sizes,
- incompatible units,
- edge quantities.

### Autonomous?

Yes.

---

## Phase 7 — SQLite to PostgreSQL Migration

### Goal

Move persistence from prototype SQLite to production-suitable PostgreSQL.

### Implement

- local PostgreSQL environment,
- application database abstraction,
- `DATABASE_URL`,
- migration utility from existing SQLite,
- reconciliation report.

Preserve historical data while explicitly marking legacy limitations.

### Do not

Invent:

- run IDs
- location mappings
- availability values
- missing timestamps

### Acceptance criteria

- repeatable migration,
- source/migrated counts reconciled,
- no silent loss,
- integrity tests pass,
- local application uses PostgreSQL.

### Autonomous?

Yes.

---

## Phase 8 — Supabase Foundation and Cloud-Portability Boundary

### Goal

Prepare and provision the minimal Supabase foundation suitable for the beta without coupling domain
logic to Supabase.

### Preferred resources

- Supabase PostgreSQL through `DATABASE_URL`
- Supabase Auth behind `AuthProvider`
- optional private Supabase Storage behind `ObjectStorage`
- portable container hosting for the FastAPI/PWA
- GitHub Actions or another beta-appropriate Python scheduler
- structured logs and persisted scrape-run diagnostics

### Add

- Supabase configuration and secret inventory
- standard Alembic deployment workflow
- provider adapters and selection settings
- defense-in-depth Data API/RLS controls where useful
- free-tier storage/connection monitoring notes
- explicit future AWS migration contract

### Infrastructure as code

Prefer reproducible configuration/scripts compatible with Supabase, the chosen host, and GitHub.

Do not create unnecessary services.

### Acceptance criteria

- environment documented,
- database reachable securely,
- secrets not committed,
- service-role secrets remain server-only,
- ordinary PostgreSQL remains the database contract,
- resource ownership clear,
- infrastructure reproducible where feasible.

### Autonomous?

Yes for all offline preparation; hosted acceptance requires project credentials.

### Possible blocker

Supabase project URL, keys, database password, and hosting/GitHub configuration.

---

## Phase 9 — Authentication and Restaurant Tenancy

### Goal

Implement secure user authentication and tenant isolation.

### Preferred

Supabase Auth for V1 beta behind a provider interface; retain Cognito as the AWS adapter.

### Implement

- signup
- email verification
- login
- logout
- password reset
- session refresh
- protected routes
- user-to-restaurant membership

### Security

Tenant identity must be derived server-side from authenticated user context.

### Acceptance criteria

- auth flows work,
- protected routes reject anonymous users,
- restaurant data cannot be accessed cross-tenant,
- authorization tests exist.

### Autonomous?

Yes after Supabase Auth resources exist.

### Possible blocker

Supabase project credentials or email-template/redirect configuration.

---

## Phase 10 — Application Backend API

### Goal

Expose reliable business logic to the UI.

### Implement

Minimum APIs:

```text
GET  /products/search
GET  /products/{id}
GET  /products/{id}/offers
GET  /products/{id}/history

POST /compare

POST /purchases
GET  /purchases
GET  /purchases/{id}

GET  /inventory
POST /inventory/adjustments

GET  /analytics/spending

GET  /scrape-runs
GET  /scrape-runs/{id}
```

### Requirements

- validation
- structured errors
- authorization
- typed schemas
- pagination where relevant
- tests
- API documentation

### Acceptance criteria

- API supports all V1 UI flows,
- tenant isolation tested,
- comparison engine integrated,
- response contracts documented.

### Autonomous?

Yes.

---

## Phase 11 — Restaurant-Facing UI

### Goal

Build the primary user experience.

### Recommended shape

Responsive web app / PWA.

### Navigation

- Dashboard
- Compare
- Inventory
- Purchases
- Spending

### Compare

Must show:

- search
- required quantity
- unit
- supplier
- product
- pack
- price
- normalized unit price
- packs required
- quantity purchased
- excess
- total
- availability
- last checked
- supplier deep link

Highlight separately:

- BEST TOTAL COST
- BEST UNIT PRICE

### UX states

Implement:

- loading
- error
- no results
- unavailable offer
- stale data
- unknown pack size

### Acceptance criteria

- responsive,
- usable on phone and desktop,
- compare flow functional,
- auth integrated,
- primary pages complete,
- UI smoke tests pass.

### Autonomous?

Yes.

---

## Phase 12 — Purchase Tracking

### Goal

Record real restaurant purchases.

### Implement

Purchase entry including:

- supplier
- product/variant
- quantity
- packs
- scraped price snapshot
- actual paid price
- total
- timestamp
- supplier link snapshot

### Key rule

`scraped_price != actual_purchase_price`

The actual paid amount is authoritative for finances.

### Acceptance criteria

- purchase stored immutably,
- price snapshot preserved,
- historical scrape changes do not mutate purchases,
- tests pass.

### Autonomous?

Yes.

---

## Phase 13 — Inventory Tracking

### Goal

Tie procurement actions to usable inventory state.

### Implement

A recorded purchase creates a positive inventory transaction.

Allow:

- manual add
- manual remove
- correction

Expose current inventory per canonical item.

### Do not implement

- recipe depletion
- POS integration
- automatic kitchen usage

### Acceptance criteria

- purchase updates inventory,
- adjustments work,
- inventory history auditable,
- negative/invalid edge cases handled,
- tests pass.

### Autonomous?

Yes.

---

## Phase 14 — Financial and Spending Analytics

### Goal

Track procurement expenditure.

### Implement

Purchase → expense entry.

Expose:

- current month spend
- spend over time
- spend by supplier
- spend by category/product
- recent purchases

### Savings claims

Only calculate savings when a valid comparable offer existed at the relevant time.

Do not compare historical purchase price against today's unrelated price and call it savings.

### Acceptance criteria

- expenses match purchases,
- dashboards use actual paid price,
- grouping totals reconcile,
- tests cover analytics.

### Autonomous?

Yes.

---

## Phase 15 — Price History UI and Analytics

### Goal

Turn historical scraping into user value.

### Show where data quality supports it

- current price
- last checked
- 7-day low
- 30-day low
- 30-day average
- history chart

### Rules

- exclude clearly invalid/failed-run observations,
- do not fabricate statistics from insufficient data,
- supplier/location context must be explicit.

### Acceptance criteria

- history APIs and UI work,
- timestamps visible,
- invalid observations excluded correctly,
- charts render,
- tests pass.

### Autonomous?

Yes.

---

## Phase 16 — Provider-Neutral Scheduled Scraping

### Goal

Replace Windows Task Scheduler as the production scheduling mechanism.

### Architecture

```text
Beta scheduler (GitHub Actions)
        ↓
Portable Python worker
        ↓
Standard PostgreSQL (Supabase)
        ↓
ObjectStorage adapter (Supabase/local)
        ↓
Structured logs + persisted run state
```

### Runtime selection

Use GitHub Actions for the initial beta because the existing scraper is Python and can exceed an Edge
Function's practical fit. Keep the CLI/runtime contract unchanged so AWS later selects Lambda or
ECS/Fargate based on measured duration without changing scraper business logic.

### Windows compatibility

The old `.bat` flow may remain for local legacy/manual usage, but it must no longer be the only production scheduler.

### Acceptance criteria

- scheduled cloud execution works,
- no interactive prompts,
- logs available,
- secrets externalized,
- failures visible,
- scraper output persists correctly.

### Autonomous?

Yes after GitHub/Supabase secrets are configured.

### Possible blockers

Supplier authentication, Supabase credentials, or GitHub repository secret configuration.

---

## Phase 17 — Monitoring and Operational Visibility

### Goal

Prevent silent bad/stale data.

### Track

- supplier
- location
- run status
- start/end
- duration
- product count
- expected count
- failed pages
- warnings
- freshness

### Alerts

At minimum:

- failed run
- suspicious zero
- abnormal count drop
- supplier data stale
- database connectivity failure

### Optional internal/admin screen

Show status similar to:

```text
Hyperpure   COMPLETE          2,351 products   07:02
BigBasket   PARTIAL           1,421/2,035      07:18
Lots        FAILED            store error
Deliverit   SUSPICIOUS_ZERO   0 products
```

### Acceptance criteria

- failures are observable,
- stale data identified,
- alert paths documented,
- application can indicate data freshness.

### Autonomous?

Yes.

---

## Phase 18 — Beta Hardening

### Goal

Prepare the product for restaurant testing.

### Security

Verify:

- no committed secrets,
- auth isolation,
- HTTPS,
- secure session/token handling,
- database protection,
- safe redirects/deep links,
- non-public internal endpoints.

### Data

Verify:

- beta location explicit,
- supplier location mappings correct,
- timestamps displayed,
- stale offers marked,
- duplicate offers reviewed,
- deep links work where technically possible.

### UX

Verify:

- mobile responsiveness,
- loading/error/empty states,
- typo-tolerant search,
- quantity validation,
- unavailable items,
- unknown pack handling.

### Reliability

Verify:

- clean deployment,
- migration from scratch,
- database backup/restore process,
- scraper health,
- application smoke tests,
- E2E core flow.

### Acceptance criteria

- all critical/high release blockers resolved,
- deployment reproducible,
- E2E flow passes,
- no known data-integrity defect that could materially mislead restaurant users.

### Autonomous?

Yes.

---

## Phase 19 — Restaurant Beta Release and Feedback

### Goal

Release the first usable beta to real restaurant reviewers.

### Target

Approximately:

- 1 fixed location
- 3–4 supported suppliers
- 5–10 restaurant users

### Validate with users

Collect feedback on:

- actual products purchased,
- trust in comparisons,
- missing products,
- missing suppliers,
- pack-size correctness,
- purchase frequency,
- inventory usefulness,
- price-history usefulness,
- current procurement workflow,
- features worth prioritizing next.

### V1 completion criteria

V1 is complete when:

- beta application is deployed in an allowed environment,
- users can authenticate,
- fixed location works,
- search works,
- quantity comparison works,
- supplier links work where possible,
- purchases can be recorded,
- inventory updates,
- expenses update,
- price history renders,
- scraping is scheduled,
- data freshness is visible,
- monitoring exists,
- core E2E tests pass.

### Codex behavior

Do not invent user feedback.

If actual restaurant testing or user credentials are required, stop using the blocker format.

### Autonomous?

No once genuine external beta feedback is required.

---

# 28. Cross-Phase Quality Gates

Before proceeding from any implementation phase, Codex must verify the relevant subset of:

- tests pass,
- migrations pass,
- lint passes if configured,
- formatting passes if configured,
- type checks pass if configured,
- no secrets detected,
- documentation updated,
- Git diff reviewed,
- no accidental generated files,
- no unexplained data loss,
- acceptance criteria met.

If a check fails, fix it instead of asking permission.

---

# 29. Completion Definition

The V1 implementation is considered complete when all technically executable phases through Phase 18 are complete and Phase 19 is ready for real restaurant beta feedback.

A fully completed V1 must provide:

```text
Authentication
Fixed beta location
Search
Product matching
Supplier comparison
Quantity calculation
Supplier deep links
Price timestamps
Price history
Purchase tracking
Inventory
Spending analytics
Scheduled scraping
Run reliability
Monitoring
Supabase-hosted V1 beta application/data layer where permitted
Portable future AWS application/data layer
```

---

# 30. Master Codex Execution Prompt

Copy the following prompt into Codex from the repository root.

---

## MASTER EXECUTION PROMPT

You are the primary implementation agent for this repository.

Your objective is to independently transform the existing local Python product-scraping prototype into the **Procurement Assistant V1** defined in the repository's Master PRD.

Read the entire Master PRD before making changes.

The project is a procurement comparison application for restaurants and local food businesses. It should collect supplier product/price information, normalize and match equivalent products, compare the real purchase cost for requested bulk quantities, provide supplier deep links, record purchases, update inventory, track procurement spending, expose price history, authenticate restaurant users, and operate from a fixed beta location.

The current repository already contains scraper implementations and historical SQLite data. Treat them as valuable existing work, not disposable scaffolding.

### Execution mode

Operate autonomously.

Do **not** ask the user for approval between phases.

Do **not** stop after finishing a milestone merely to ask whether to continue.

Continue through the PRD phases in order as long as progress is technically possible and safe.

### Decision authority

You are expected to make normal engineering decisions independently.

When several reasonable solutions exist, choose one based on:

1. correctness
2. security
3. data integrity
4. maintainability
5. simplicity
6. cost-conscious, cloud-portable design
7. testability
8. existing repository conventions
9. V1 scope

Briefly document material architectural decisions and continue.

Do not ask the user to select between ordinary implementation alternatives unless the choice fundamentally changes product behavior and cannot reasonably be inferred from the PRD.

### Phase behavior

For every phase:

1. inspect the current code related to that phase,
2. confirm relevant assumptions,
3. design the smallest coherent change,
4. implement it,
5. add or update tests,
6. run relevant tests,
7. run configured lint/type/format checks,
8. update documentation,
9. inspect the Git diff,
10. fix regressions,
11. verify acceptance criteria,
12. create a logical commit when repository permissions allow,
13. proceed automatically to the next phase.

Do not claim completion if acceptance criteria are not satisfied.

### Preserve existing work

Do not casually delete or rewrite:

- existing scrapers,
- historical SQLite data,
- useful current functionality,
- user-authored files,
- uncommitted changes.

Migrate carefully and verify before deprecating old paths.

### No fabricated evidence

Never fabricate:

- test results,
- scrape success,
- external endpoint behavior,
- product counts,
- matching accuracy,
- performance results,
- AWS resources,
- Supabase resources,
- deployments,
- price observations,
- user feedback.

If something cannot be verified, label it as unknown.

### Supplier access rules

Treat supplier websites as external, unstable, and untrusted.

Do not bypass:

- authentication,
- CAPTCHA,
- MFA,
- anti-bot controls,
- access restrictions,
- supplier rate limits.

Do not automate restricted actions.

If a source requires authorized login or user interaction, this may become a legitimate blocker.

### Data-quality rules

A successful request does not mean a successful scrape.

Represent runs using:

- running
- complete
- partial
- failed
- suspicious_zero
- interrupted

Never mark a zero-product run complete merely because requests returned successfully.

A failed or partial scrape must not automatically mark missing products unavailable.

Historical price observations must be immutable.

Do not invent missing run IDs, location mappings, availability history, or timestamps during migration.

### Product-model rules

Do not treat source, external ID, and pincode as the entire domain identity.

Keep separate concepts for:

- canonical product,
- product variant,
- supplier product,
- supplier location,
- supplier offer,
- price observation.

Location should conceptually map:

restaurant location
→ supplier location/store/warehouse/zone
→ catalogue/pricing

### Matching rules

V1 matching should be deterministic and testable.

Do not make an LLM mandatory for core canonical matching.

Track:

- method,
- confidence,
- review state.

Use reviewed positive and negative fixtures.

Never invent benchmark accuracy.

### Quantity-comparison rules

For each offer compute:

- packs required,
- quantity purchased,
- excess,
- normalized unit price,
- total purchase cost.

Support common:

- mass,
- volume,
- piece,
- multipack

formats.

Never compare incompatible units.

Display separately:

- best total cost,
- best unit price,
- lowest excess.

### Purchase rules

Scraped price and actual paid price are separate.

Recorded purchases must preserve:

- supplier,
- product,
- variant,
- quantity,
- pack count,
- scraped-price snapshot,
- actual price,
- timestamp,
- supplier URL snapshot.

Future scraper changes must not rewrite old purchases.

### Inventory rules

A recorded purchase should create an inventory addition.

V1 must also support manual:

- add,
- remove,
- correction.

Do not implement recipe/POS depletion unless required for core correctness.

### Expense rules

Purchases should create procurement expense entries.

Spending analytics must use actual paid values.

Do not make unsupported savings claims.

### Supabase V1 beta rules

Supabase is the initial beta provider for managed PostgreSQL and Auth, with optional private Storage.
Use `DATABASE_URL`, standard SQLAlchemy/Alembic migrations, provider adapters, backend tenant checks,
and structured logs. Keep service-role credentials outside the browser and Git. Do not require
Supabase Data APIs, RPC, Edge Functions, generated clients, or provider-specific domain behavior.

GitHub Actions is the beta scheduler for the existing Python worker. Preserve the worker contract so
EventBridge plus Lambda/ECS can replace scheduling/runtime later without a business-logic rewrite.

### Future AWS rules

AWS remains a future cloud target, using student/promotional credits where legally and technically appropriate.

Before production-like deployment, determine whether access is:

- a normal AWS account with credits, or
- an AWS Academy/Learner Lab/training environment.

Do not deploy a live restaurant beta into an environment whose terms prohibit this use.

Preferred AWS services where appropriate:

- RDS PostgreSQL
- S3
- Cognito
- EventBridge Scheduler
- CloudWatch
- Parameter Store or Secrets Manager
- Lambda or ECS/Fargate depending on measured runtime

Keep infrastructure minimal.

Mandatory cost-conscious behavior:

- AWS Budget
- billing alerts
- smallest practical resources
- conservative log retention
- S3 lifecycle policies
- no unnecessary NAT Gateway
- no unnecessary Multi-AZ
- no idle compute
- resource tagging
- cost documentation

Do not hardcode AWS service assumptions into domain/business logic.

Application database access should remain environment-driven, such as through `DATABASE_URL`.

### Git rules

Use logical commits when allowed.

Do not commit:

- passwords,
- API keys,
- AWS credentials,
- supplier credentials,
- OTPs,
- tokens,
- session cookies,
- private account data,
- `.env` secrets,
- runtime logs,
- Python bytecode,
- local virtual environments,
- temporary browser/session directories.

Maintain a proper `.gitignore`.

Do not rewrite Git history unless explicitly necessary and safe.

### Stop conditions

Do not stop because:

- a phase completed,
- you want approval,
- tests failed,
- a bug exists,
- lint failed,
- documentation is stale,
- refactoring is required,
- a dependency must be added,
- the architecture needs adjustment,
- a migration is required,
- there are several reasonable libraries,
- implementation differs from the old prototype.

Solve these and continue.

Stop only when further progress genuinely requires something unavailable to you, such as:

- Supabase project URL/keys/database access,
- hosting or GitHub repository secret configuration,
- AWS credentials/access for the future AWS target,
- missing AWS permissions,
- inability to determine permitted AWS account type,
- supplier credentials,
- OTP,
- CAPTCHA,
- MFA,
- authenticated manual browser action,
- external secret,
- DNS/domain ownership,
- billing/account action,
- destructive action involving user-owned external infrastructure,
- product/business information that cannot reasonably be inferred,
- legal/terms constraint requiring user choice,
- actual restaurant beta feedback.

When one task is blocked, continue all independent work that does not depend on that blocker.

Stop only at the smallest unavoidable boundary.

### Mandatory blocker report

When you must stop, use exactly:

BLOCKER:
<what is required>

WHY:
<why implementation cannot safely continue without it>

USER ACTION:
<precise action or information required from the user>

STATE:
<what has already been completed and verified>

RESUME FROM:
<exact next task to execute after the blocker is resolved>

Do not ask vague questions such as:

"How would you like to proceed?"

### Required phase order

Execute:

0. Repository Baseline and Preservation  
1. Live Supplier Validation  
2. V1 Domain Model and PostgreSQL Schema Design  
3. Scrape Run Reliability Layer  
4. Test and Fixture Foundation  
5. Product Normalization and Matching V1  
6. Quantity Comparison / Procurement Engine  
7. SQLite to PostgreSQL Migration  
8. Supabase Foundation and Cloud-Portability Boundary
9. Supabase Authentication and Restaurant Tenancy
10. Application Backend API  
11. Restaurant-Facing UI  
12. Purchase Tracking  
13. Inventory Tracking  
14. Financial and Spending Analytics  
15. Price History UI and Analytics  
16. Provider-Neutral Scheduled Scraping
17. Monitoring and Operational Visibility  
18. Beta Hardening  
19. Restaurant Beta Release and Feedback

Read and use the detailed requirements and acceptance criteria for each phase from the Master PRD.

### Current objective

Resume from the implemented core without redoing completed work. Adapt Phase 8/9/16–18 for a
Supabase-first beta, preserve AWS as a statically validated future target, and continue until hosted
Supabase credentials/configuration or real restaurant feedback is genuinely required.

---

# 31. End-of-Phase Progress Report Format

After each phase, Codex may print a concise status report while continuing:

```text
PHASE <N> COMPLETE — <name>

Implemented:
- ...

Validation:
- tests: ...
- lint/type checks: ...
- migrations/data checks: ...

Key decisions:
- ...

Remaining risks:
- ...

Proceeding to Phase <N+1>.
```

This is informational only.

Do not wait for user approval.

---

# 32. Final Completion Report Format

When all technically executable phases are complete, report:

```text
V1 IMPLEMENTATION STATUS

Completed phases:
...

Blocked/deferred phases:
...

Application:
...

Data:
...

Scrapers:
...

AWS:
...

Supabase:
...

Tests:
...

Deployment:
...

Known limitations:
...

Beta readiness:
...

USER ACTION REQUIRED:
...
```

Do not claim real-world restaurant validation until actual restaurant users have tested the beta.

---

# 33. Final Product Standard

The final V1 should be demonstrably more than a scraper.

It should function as a coherent procurement workflow:

```text
Supplier Data
    ↓
Reliable Observation
    ↓
Normalized Product
    ↓
Comparable Offer
    ↓
Restaurant Quantity Requirement
    ↓
Procurement Cost Comparison
    ↓
Purchase
    ↓
Inventory + Expense
    ↓
Historical Insight
```

Every implementation decision should support this flow, data trust, and restaurant usability.
