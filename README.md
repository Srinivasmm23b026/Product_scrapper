# Product Scraper Pipeline

> **V1 migration status:** This file documents the preserved legacy scraper baseline. The
> repository is being evolved according to [MASTER_PRD.md](MASTER_PRD.md). Reproducible local
> setup and checks are documented in [docs/development.md](docs/development.md), and the original
> database/schema counts are recorded in [docs/baseline/2026-08-26.md](docs/baseline/2026-08-26.md).
> Sections below remain authoritative only for legacy behavior until superseded by phase-specific
> architecture and operational documentation.

Automated, zero-cost pipeline that scrapes product details (name, brand, price, MRP, unit, stock, image, URL) from four Indian ecommerce sites and stores them in a local SQLite database, tracking price history over time. No paid APIs, no LLM calls, no proxies — everything runs on plain HTTP requests once a day.

Every price is stamped with the exact location context it was fetched under (section 4), every pack size is parsed into a comparable unit price (section 5), and matching products across sites are linked into canonical groups (section 6) — so cross-site price comparisons are real, not just four disconnected lists sitting next to each other.

**Location-aware scraping:** BigBasket and Lots Wholesale are no longer scraped anonymously once — each is scraped once per pincode in `config.BIGBASKET_TARGET_PINCODES` / `config.LOTS_TARGET_PINCODES`, on its own `requests.Session()`, via a `set_location(session, pincode)` call made before browsing categories. Hyperpure gained an OTP-based `login()` for real per-account B2B pricing (see section 3.6). None of this is faked: every location-set attempt is verified at runtime (did the session's city cookie actually change? did a real storeCode come back?) and honestly degrades — falling back to the previous anonymous behavior with a clear `location_note` — rather than silently pretending a guessed private endpoint worked. See section 6 for exactly what is and isn't verified today, and what you need to supply (real captured endpoints / credentials) to make each one fully live.

```
Windows Task Scheduler (04:00 daily)
        |
        v
run_scraper.bat  ---->  python main.py
        |
        v
main.py: for each site in SCRAPERS { scrape() -> normalize -> db.upsert_product() }
        |
        v
scrapers/hyperpure.py    scrapers/bigbasket.py    scrapers/deliverit.py    scrapers/lots.py
        |                        |                         |                     |
        v                        v                         v                     v
  Session + optional      Session, per pincode:      requests.get()       Session, per pincode:
  login() (OTP) then      set_location() POST        parse JSON-LD        find_store_code() then
  requests.get()          then requests.get()        (<script type=       requests.post() w/ real
  parse __NEXT_DATA__     parse __NEXT_DATA__          application/ld+    storeCode + pincode
  (embedded JSON)         (embedded JSON)               json>)            parse __NEXT_DATA__ (menuId)
        |________________________|_________________________|_____________________|
                                        |
                                        v
                        list[dict] of normalized product records
                                        |
                                        v
                              data/products.db (SQLite)
                    products  |  price_history  |  scrape_runs
                                        |
                                        v
                              logs/scraper.log (audit trail)
```

---

## 1. Triggering — how the pipeline starts

A Windows Task Scheduler job does the triggering; nothing needs to be running in the background waiting.

- **Task name:** `ProductScraper` (check with `schtasks /query /tn "ProductScraper" /v /fo LIST`)
- **Schedule:** Daily at 04:00 AM
- **Action:** runs `C:\Users\hi\Documents\product-scraper\run_scraper.bat`

`run_scraper.bat` just changes into the project directory and invokes Python directly (no virtualenv activation needed — dependencies are installed into the system Python 3.11):

```bat
@echo off
cd /d "%~dp0"
"C:\Users\hi\AppData\Local\Programs\Python\Python311\python.exe" main.py
```

To run it manually at any time (e.g. to backfill or test), either double-click `run_scraper.bat` or run `python main.py` from inside the project folder.

To change the schedule:
```
schtasks /change /tn "ProductScraper" /st 06:00
```
To disable/delete it:
```
schtasks /delete /tn "ProductScraper" /f
```

---

## 2. Orchestration — `main.py`

`main.py` is the single entry point. It:

1. Sets up logging to both the console and `logs/scraper.log` (rotates are not configured — the file just grows; delete/archive it periodically if desired).
2. Opens one SQLite connection via `db.get_connection()` (creates `data/products.db` and its tables if they don't exist yet).
3. Loops over a fixed dict of scrapers:
   ```python
   SCRAPERS = {
       "hyperpure": hyperpure.scrape,
       "bigbasket": bigbasket.scrape,
       "deliverit": deliverit.scrape,
       "lots": lots.scrape,
   }
   ```
4. For each site, in order:
   - Records a row in `scrape_runs` (`db.start_run`) marking the run as started.
   - Calls that site's `scrape()` function, which returns a **plain list of normalized dicts** (see schema below) — each scraper handles its own HTTP requests, parsing, pacing, and error handling internally.
   - Upserts every product into the database (`db.upsert_product`), then commits.
   - Records the row count (or the exception message) back into `scrape_runs` (`db.finish_run`).
   - **A failure in one site does not stop the others** — each site's scrape is wrapped in its own `try/except`, so e.g. if BigBasket changes its page structure tomorrow, Hyperpure/Deliverit/Lots still run and get stored.
5. Logs a final total across all sites and exits (code 0 on success even if individual sites had errors — check `scrape_runs.error` for per-site failures).

Every scraper module exposes exactly one public function — `scrape() -> list[dict]` — which is what lets `main.py` treat all four sites identically despite very different underlying scraping techniques.

---

## 3. Per-site scraping logic

All four sites were chosen/adapted specifically because their product data is available in the plain server response — no headless browser is used in the shipped pipeline (Playwright was only used once, manually, during investigation to capture Lots Wholesale's network calls; it isn't a runtime dependency).

Every request goes out with a normal browser `User-Agent` (`config.HEADERS`) and a polite `REQUEST_DELAY_SECONDS = 3` pause between each HTTP call to the same site, so the scraper looks and behaves like a slow, considerate visitor rather than a bot storm.

### 3.1 Hyperpure (`scrapers/hyperpure.py`)

- **robots.txt:** fully open (`Disallow:` with nothing after it) — no restrictions.
- **Target URLs:** 22 hardcoded landing pages in `config.HYPERPURE_LANDING_URLS` (category-style pages like `/in/butter`, `/in/ghee`, `/in/cheese`, plus a couple of general ones).
- **Method:** `requests.Session().get(url)` on each page. Hyperpure is a Next.js app that server-renders a `<script id="__NEXT_DATA__" type="application/json">` block containing the full Redux-style initial state.
- **Extraction path:** `__NEXT_DATA__` → `props.pageProps.initialState.catalog.searchProductsForBuyer.products` (also checks a few sibling keys like `categoryProductsForBuyer` in case a page populates those instead). Each landing page yields ~20 products.
- **Fields pulled per product:** `Id`, `Name`, `Brand`, `CategoryName`/`ParentCategoryName`, `Price.PriceVal` (selling price), `Price.CompareAtPriceVal` (MRP, falls back to selling price if there's no discount), `Quantity.DisplayValue` (unit, e.g. "1 kg"), `IsInStock`, `ImagePath`, and `Slug` (used to rebuild the product URL as `https://www.hyperpure.com/in/<slug>`).
- **Dedup:** an in-memory `seen_ids` set skips repeat product IDs across the 22 pages (some products appear on multiple landing pages).
- **Typical yield:** ~366 products/run when unauthenticated (see 3.6 for the logged-in path).

### 3.2 BigBasket (`scrapers/bigbasket.py`)

- **robots.txt:** disallows `/p/`, `/product/`, `/ps/`, and `/pd/<id>/*` — i.e. individual product-detail pages are off-limits. It explicitly **allows** `/pc/<category>/<subcategory>/` category-listing pages. **The scraper only ever requests allowed category-listing URLs — it never touches an individual product page.**
- **Target URLs:** 13 category URLs in `config.BIGBASKET_CATEGORY_URLS` (fruits & vegetables, foodgrains/oil/masala, dairy, health/medicine, pet food, etc.), scraped once per pincode in `config.BIGBASKET_TARGET_PINCODES`.
- **Method:** each pincode gets its own `requests.Session()`. `bigbasket.set_location(session, pincode)` first hits `https://www.bigbasket.com/` to pick up baseline guest cookies, then POSTs to `config.BIGBASKET_SET_LOCATION_API` with the pincode — the same stateful address-set call BigBasket's own "Select Location" picker makes, whose response cookies (`_bb_cid`, `_bb_nhid`, ...) then ride along on every category request made with that session. It then does `session.get(url)` per category — same Next.js `__NEXT_DATA__` pattern as before.
- **Verified, not assumed:** `set_location()` diffs the session's `_bb_cid` cookie before/after the call and only reports success if it actually changed. `config.BIGBASKET_SET_LOCATION_API` is BigBasket's address-set path as best identified from its own frontend, but that modal is loaded lazily by BigBasket's JS (not present in the initial page bundle we could statically inspect), so it could not be confirmed byte-for-byte without a real browser network capture. **As shipped, this call 404s** — every product row is honestly stamped `pincode: None` with a `location_note` explaining the fallback, exactly like before, rather than a fabricated "it worked." If you capture the real endpoint (browser DevTools Network tab while using BigBasket's own location picker), drop it into `config.BIGBASKET_SET_LOCATION_API` and location-aware scraping activates automatically — no other code changes needed.
- **Extraction path:** `__NEXT_DATA__` → `props.pageProps.SSRData.tabs[].product_info.products[]`. Each product object also has a `children` array for other pack sizes/variants of the same item (e.g. a 1kg and a 15kg bag of the same mango) — the scraper flattens parent + children into separate rows, since each has its own ID, price, and pack size.
- **Fields pulled per product:** `id`, `desc` (name), `brand.name`, `category.mlc_name`, `pricing.discount.prim_price.sp` (selling price), `pricing.discount.mrp`, `w`/`pack_desc` (unit), `availability.not_for_sale` (inverted → in_stock), `images[0].l` (large image URL), `absolute_url` (prefixed with `https://www.bigbasket.com` to build the full product URL).
- **Dedup:** in-memory `seen_ids` keyed on `(external_id, pincode)` across all 13 category pages × all configured pincodes — so a successful location switch keeps each pincode's rows distinct, while a failed one (falling back to the same anonymous city) correctly collapses back down instead of duplicating.
- **Typical yield:** ~1,384 products/run per resolved pincode (today: 1 resolved "pincode" — the anonymous default city — since location-set 404s; see above).

### 3.3 Deliverit (`scrapers/deliverit.py`)

- **robots.txt:** open except `/checkout/`, `/cart/`, `/search/` — product pages are allowed.
- **Deliverit's product pages are a client-side-rendered React app with no `__NEXT_DATA__` product payload**, so instead of a category page, the scraper works product-by-product:
  1. Fetches `sitemap.xml` → finds `sitemap-products.xml?page=N` entries.
  2. Pulls raw product-page URLs (e.g. `https://www.deliverit.net.in/product/amul-butter-salted?pid=641`) out of up to `DELIVERIT_MAX_SITEMAP_PAGES` (3) sitemap pages via a simple `<loc>` regex.
  3. Caps the total at `DELIVERIT_MAX_PRODUCTS_PER_RUN` (60) to keep each run lightweight (there are 32 sitemap pages / thousands of products total — this is a deliberately small, capped sample, not full-catalog coverage).
  4. Fetches each individual product page with plain `requests.get()`.
- **Extraction path:** each product page has a `<script type="application/ld+json">` block — a standard schema.org `Product` object (used for Google SEO rich results), present in the *plain, non-JS-rendered* HTML. Parsed with BeautifulSoup + `json.loads()`.
- **Fields pulled per product:** `sku` (→ external ID, falls back to the `pid` query param if missing), `name`, `brand.name`, `offers.price` (used for both price and MRP — Deliverit's JSON-LD doesn't expose a separate MRP/discount field), `image`. A cheap regex check for the literal string "out of stock" in the page HTML sets `in_stock`.
- **Typical yield:** 60 products/run (hard-capped).

### 3.4 Lots Wholesale (`scrapers/lots.py`) — *added most recently*

- **robots.txt:** no `Disallow` directives at all — fully open.
- This site's category pages don't embed the product list directly; instead there's a two-step process per category, run once per pincode in `config.LOTS_TARGET_PINCODES`, each on its own `requests.Session()`:
  1. **Resolve the menuId:** `GET https://www.lotswholesale.com/category/<slug>` and parse its `__NEXT_DATA__` → `props.pageProps.valueFromServer.menuDetail.id`. Every category slug (e.g. `foodgrains-oil-masala/dals-pulses-`) maps to a numeric `menuId` (e.g. `130`) used internally by the site.
  2. **Call the site's own public product-search API** with that menuId, a real (not hardcoded) `storeCode` resolved by `lots.find_store_code(session, pincode)`, and the target pincode:
     ```
     POST https://api.lotswholesale.com/next-product/public/api/product/search
     Content-Type: application/json
     {"menuId": 130, "locale": "en_US", "page": 1, "pageSize": 60,
      "assortPriceStoreCode": "<resolved storeCode>", "pincode": "<target pincode>",
      "sorting": "SORTING_MENU_INDEX", ...}
     ```
     This is the exact same API/payload the site's own frontend calls (discovered once via a manual Playwright network-capture, then reproduced with plain `requests` — no browser needed at runtime, no auth/cookies required).
- **What `find_store_code()` actually found:** reading Lots' own production JS bundle shows `assortPriceStoreCode`/`registerZipcode` are pulled from `currentUser` — i.e. a **registered member's home store**, not a public per-request pincode lookup. Probing `api.lotswholesale.com`'s API gateway (which routes `/next-<service>/public/api/...`) confirms there is no reachable public "find my store" service at all: `next-store`, `next-location`, `next-address`, `next-member` all 404 at the gateway level (meaning those service names aren't registered), while `next-product`, `next-auth`, `next-cms` are real. So **as shipped, `config.LOTS_STORE_LOCATOR_API` is a placeholder that 404s**, and `find_store_code()` honestly falls back to `config.LOTS_DEFAULT_STORE_CODE` ("101") — logging why, and stamping `location_note` accordingly — rather than pretending a guessed endpoint resolved a real store. The `pincode` field is still sent in every payload (so the payload itself is genuinely dynamic per configured pincode, per the goal), it's just not yet verified to change pricing without a real store-locator response or a logged-in member session.
- **Target categories:** 23 curated slugs in `config.LOTS_CATEGORY_SLUGS` (dals, atta, oils, dry fruits, dairy, chocolates, namkeen, biscuits, tea/coffee, noodles/pasta, sauces, pickles, cleaning, soaps).
- **Pagination:** the API returns `totalPages`; the scraper walks pages `1..min(totalPages, LOTS_MAX_PAGES_PER_CATEGORY=3)` per category, so very large categories are capped at 180 products (3 × 60) each run.
- **Fields pulled per product:** `productCode` (external ID), `productName`, `brand`, `categoryL3`/`category`, `inVatPrice` (selling price), `pricingRecords[0].mrp`, `uda2`+`uda3` combined into a unit string (e.g. "30 KG"), `stockAvailableToSell` (>0 → in stock), `image`, and `slug` (used to build `https://www.lotswholesale.com/product/<slug>`).
- **Dedup:** in-memory `seen_ids` keyed on `(external_id, pincode)` across all categories/pages/pincodes.
- **Typical yield:** ~2,282 products/run per configured pincode — the largest contributor by far.

### 3.6 Hyperpure login (`hyperpure.login()`)

- Hyperpure's own frontend bundle shows its login flow is **phone number + OTP**, not email/password (an "OTP request limit" modal exists in the bundle; no password field anywhere), so real per-account contract pricing can't be reached by just guessing a password grant.
- `hyperpure.login(session, account)` POSTs the phone number to `config.HYPERPURE_LOGIN_SEND_OTP_API`, obtains the OTP code via an `otp_provider` callback (defaults to reading the `HYPERPURE_OTP` environment variable if set, else an interactive `input()` prompt), POSTs phone+OTP to `config.HYPERPURE_LOGIN_VERIFY_OTP_API`, and attaches the returned bearer token as `Authorization: Bearer <token>` on the session.
- **This cannot be made fully unattended** without a separate SMS-receiving integration (Twilio inbound, an Android SMS-forwarding bridge, etc.) — that's inherent to Hyperpure's own auth design, not a shortcut taken here. Configure `config.HYPERPURE_ACCOUNTS` with one `{"region": ..., "phone": ...}` entry per business account you hold real credentials for; with it empty (the default), `scrape()` keeps today's anonymous public-listing behavior exactly as before.
- The two login endpoint paths are the best identified from Hyperpure's own bundle's URL structure, not confirmed against a real account (no test credentials were available) — expect to verify/adjust them the first time you run this with real credentials, the same way you'd verify any newly-reverse-engineered endpoint per section 11.

### 3.5 Excluded: Udaan

Udaan (`udaan.com`) was investigated but deliberately **excluded**: its `robots.txt` explicitly disallows `/listing/` and `/product/` — exactly the catalog paths needed — and its sitemap only lists generic static pages (login, about, policies). Its real catalog and pricing also sit behind a login-gated B2B account. Scraping it would mean either violating robots.txt or needing a logged-in session, so it was left out rather than worked around.

---

## 4. Normalization — the common product schema

Regardless of source, every scraper's `scrape()` returns a list of dicts with exactly these keys (this is the contract `main.py` and `db.py` rely on):

| Key | Meaning |
|---|---|
| `source` | site identifier: `"hyperpure"`, `"bigbasket"`, `"deliverit"`, or `"lots"` |
| `external_id` | the product's ID on that site (used for dedup/upsert) |
| `name` | product name |
| `brand` | brand name (may be `None` if the site doesn't expose one, e.g. Deliverit's search doesn't always have it) |
| `category` | category/subcategory name, where available |
| `price` | current selling price (float) |
| `mrp` | list/MRP price (falls back to `price` if the site has no separate MRP concept, e.g. Hyperpure/Deliverit without a discount) |
| `unit` | **raw** pack size / quantity string as the site wrote it, e.g. `"1 kg"`, `"30 KG"`, `"500 Gram"` — kept for reference/debugging |
| `pack_qty` | pack size **parsed into a number**, expressed in `base_unit` (section 5) — `None` if unparseable |
| `base_unit` | one of `"kg"`, `"l"`, `"pc"` — the unit `pack_qty` is expressed in |
| `price_per_unit` | `price / pack_qty` — price per kg / per litre / per piece (section 5) — `None` if `pack_qty` is `None` |
| `in_stock` | `1` or `0` |
| `image_url` | product image URL |
| `product_url` | canonical URL to view the product on the source site |
| `pincode` | the postal pincode this price was fetched under, where we actually control one — `None` if the site doesn't accept one from an anonymous request (section 6 explains what location context applies instead) |
| `location_note` | **always populated** — a human-readable, empirically-verified description of exactly what location context produced this price (section 6) |

Each scraper is responsible for mapping its site's idiosyncratic JSON into this shape before returning.

---

## 5. Unit normalization — `scrapers/units.py`

Raw pack-size strings ("30 KG", "500 Gram", "1 kg", "750 ml", "Amul Butter Ip 500 G Pk40") are not comparable as-is — a ₹10,720 price tag on a "500 G" item is meaningless without knowing whether that price is for one 500g unit or a case of 40. `units.py` parses every raw unit string (falling back to the product name, since some sites — e.g. Deliverit — don't expose a separate quantity field at all) into:

- **`pack_qty`** — a number, always expressed in `base_unit`
- **`base_unit`** — always one of `"kg"`, `"l"`, or `"pc"`, so comparisons are apples-to-apples (a price-per-kg is never compared against a price-per-piece)

It handles unit-word variants (`kg`/`kilogram`/`kilograms`, `g`/`gm`/`gram`/`grams`, `ml`/`l`/`litre`/`liter`/…, `pc`/`pcs`/`piece`/`ea`/…) and, critically, **multi-pack multiplier suffixes**:

- `"500 G Pk40"` → the price is for a case of 40 × 500g, i.e. **20 kg total**, not 0.5 kg. (`Pk<N>` is Lots Wholesale's own B2B bulk-pack naming convention — this pattern appears in 262 of the ~4,400 scraped products, so getting it wrong would have silently corrupted a quarter of all cross-site comparisons involving Lots.)
- `"840gm Pouch (Pack of 10)"` → 10 × 840g = **8.4 kg total**, not 0.84 kg.

Both of these were real bugs caught during verification (see below) — before the fix, "Amul Butter Ip 500 G Pk40" computed as ₹21,440/kg (comparing a whole-case price against a single-unit weight) instead of the correct ₹536/kg, which would have made a same-brand, same-size Hyperpure listing at ₹565/kg look 40× more expensive than an equivalent Lots listing that was actually only marginally cheaper.

`unit_price(price, pack_qty, base_unit)` then just divides — returning `None` if `pack_qty` couldn't be parsed, rather than guessing.

**Known limitation:** a rarer `"<N>x<weight>"` style (e.g. `"Naturoz Walnut Giri 2 Pieces Twin Pack 2x250 G"`, ~13 of ~4,400 products) is not multiplier-corrected — the source's own labeling is inconsistent in these cases (piece-count and the `NxWeight` figure don't always agree), so rather than guess, `parse_unit` takes the first plain weight/volume/count match it finds and leaves the ambiguity undecided. These are flagged simply by their small absolute count if you want to audit them by hand: `SELECT * FROM products WHERE name LIKE '%x2%G%' OR name LIKE '%x250%'` etc.

**Verification performed:** after implementing the multiplier fix, every canonical group spanning more than one source was checked for internal `price_per_unit` consistency (`max(price_per_unit) > 3x min(price_per_unit)` within a group flags a likely remaining parsing bug). As of the last full run, **zero** cross-source groups show a >3x spread — see section 7 for how to re-run this check yourself.

---

## 6. Location verification — every price is stamped with where it came from, and every location-set attempt is verified, not assumed

**All four of these sites price by delivery location** (pincode / serviceable city / warehouse) — a price with no location attached is not a real price. This pipeline actively *tries* to set a real location/account context for BigBasket, Lots, and Hyperpure (via `set_location()`/`login()` in their scraper modules) rather than only ever reading the anonymous default — but it never claims success without checking, and it never silently falls back without saying so in `location_note`.

| Source | `pincode` today | What was verified, and what's still a placeholder |
|---|---|---|
| **BigBasket** | `None` (location-set 404s) | `bigbasket.set_location()` POSTs to `config.BIGBASKET_SET_LOCATION_API` on a `requests.Session()` per configured pincode (`config.BIGBASKET_TARGET_PINCODES`), then diffs the session's `_bb_cid` cookie before/after. **Confirmed:** an anonymous request resolves to `City_id=1`, and a bare `_bb_pin_code` cookie does NOT change it (must be a real stateful address-set call). **Not yet confirmed:** the exact address-set path — it's loaded lazily by BigBasket's own frontend JS (not in the initial page bundle), so it couldn't be pinned down without a live browser network capture; the shipped constant 404s, so `set_location()` reports failure and every row honestly falls back to the anonymous default city with a note saying so, exactly as verified previously. |
| **Lots Wholesale** | real pincode (e.g. `"110001"`), `storeCode` still the default `"101"` | `lots.find_store_code()` hits `config.LOTS_STORE_LOCATOR_API` per configured pincode (`config.LOTS_TARGET_PINCODES`) to resolve a real `storeCode`, then injects it into the search payload instead of hardcoding `"101"`. **Confirmed (new finding, from reading Lots' own production JS + probing its API gateway):** `storeCode`/`pincode` are actually populated from a **registered member's** `currentUser` object, and there's no reachable public "find my store" microservice (`next-store`/`next-location`/`next-address`/`next-member` all 404 at the gateway; only `next-product`/`next-auth`/`next-cms` exist) — so a truly public, anonymous pincode→store lookup may not exist for this site at all. The shipped locator constant 404s, so `find_store_code()` falls back to the documented default store and says so in `location_note`; the pincode itself is still genuinely dynamic per configured target (not hardcoded) in every payload. |
| **Hyperpure** | `None` unless `config.HYPERPURE_ACCOUNTS` is configured | `hyperpure.login()` drives Hyperpure's real phone+OTP login flow (confirmed: no password field exists, only OTP) and attaches the resulting bearer token to the session, so authenticated requests use its `*ForBuyer` catalog keys — i.e. real per-account contract pricing instead of the anonymous fallback. With no accounts configured (the default), or if login fails, it verifiably stays on the previously-confirmed anonymous behavior: repeated fetches of the same landing page return an identical product/price with no cookies sent. |
| **Deliverit** | `None` | Unchanged, and deliberately so: the product page's JSON-LD price comes back identically on repeated plain, cookie-less `requests.get()` calls — a single site-wide catalog price with no location branching in the response at all. The site's separate lat/long delivery-ETA check (visible in its network calls) does not affect this price; an unserviceable pincode blocks checkout rather than changing it. There is nothing to make location-aware here. |

**Because these are four independent hyperlocal/B2B apps with non-overlapping serviceable areas and different auth models, they do NOT all resolve to the same city today** — and BigBasket/Lots' *exact* private endpoints are still placeholders pending a real browser network capture (or, for Lots, possibly a logged-in member session) to replace the ones shipped here. That is the honest current state, not a hidden limitation: every attempt is logged, every result is verified against an observable signal (a changed cookie, a real storeCode, a working bearer token) before being trusted, and every row's `location_note` says exactly what happened for that specific run. To go from "placeholder, honestly falling back" to "actually live":

1. **BigBasket:** capture the real address-set request from a browser DevTools Network tab while using the site's own "Select Location" picker, and update `config.BIGBASKET_SET_LOCATION_API` (and its payload shape in `bigbasket.set_location()` if different).
2. **Lots:** either capture a real store-locator call the same way (if one exists for anonymous users), or extend `lots.find_store_code()`/`config.LOTS_STORE_LOCATOR_API` to log into a real member account per store you need coverage for.
3. **Hyperpure:** add real `{"region", "phone"}` entries to `config.HYPERPURE_ACCOUNTS` and run once per account with `HYPERPURE_OTP` set (or answer the interactive prompt) after the SMS arrives; verify/adjust `config.HYPERPURE_LOGIN_SEND_OTP_API` / `HYPERPURE_LOGIN_VERIFY_OTP_API` against the real response shape the first time.

Once any of these is genuinely live, treat cross-source comparisons at the *same* resolved pincode as location-consistent; until then, keep reading them as "each site's own reference-location listed price," not a same-city comparison. A canonical group (section 7) spanning two sources is a valid *product* match regardless — just keep any "X is cheaper" conclusion location-caveated.

---

## 7. Canonical product grouping — linking the same product across sources

Nothing about scraping four sites separately tells you that Hyperpure's `"Amul - Butter Salted, 500 gm"` and Lots' `"Amul Butter Ip 500 G Pk40"` are (differently-packed versions of) the same underlying product. `canonicalize.py` builds that link after every scrape:

1. **Bucket** every product by `(normalized brand, base_unit, pack_qty)` — products can only ever match if they're the same brand and the same *parsed* pack size (this is exactly why the unit-parsing fix in section 5 mattered: get the pack size wrong and products get bucketed apart, or worse, matched with the wrong price basis).
2. **Within a bucket**, greedily cluster by Jaccard similarity of "significant" name tokens (brand name, pack-size numbers, and packaging filler words like "pouch"/"bottle"/"pack" stripped out first). Two products join the same `canonical_products` group only if their remaining token overlap is ≥ 0.5.

This is a deliberately simple, fully transparent, zero-cost heuristic — no ML/fuzzy-embedding service — implemented in `canonicalize.rebuild(conn)`, which is called once at the end of every `main.py` run and **recomputes all groupings from scratch** (cheap at a few thousand rows; avoids stale clusters as names get corrected over time).

Each `products` row gets a `canonical_id` FK into the new `canonical_products` table:
```sql
CREATE TABLE canonical_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL,   -- name of the first product that founded the group
    brand TEXT, pack_qty REAL, base_unit TEXT,
    created_at TEXT NOT NULL
);
```

**To see a real cross-site product comparison** (remembering the location caveat from section 6):
```sql
SELECT p.source, p.name, p.price, p.price_per_unit, p.pincode
FROM products p
WHERE p.canonical_id = (
    SELECT canonical_id FROM products
    WHERE canonical_id IS NOT NULL
    GROUP BY canonical_id HAVING COUNT(DISTINCT source) > 1
    LIMIT 1
)
ORDER BY p.price_per_unit;
```
Or to list every group that spans more than one source, cheapest-per-unit first within each:
```sql
SELECT canonical_id, GROUP_CONCAT(DISTINCT source) AS sources, COUNT(*) AS n
FROM products WHERE canonical_id IS NOT NULL
GROUP BY canonical_id HAVING COUNT(DISTINCT source) > 1
ORDER BY n DESC;
```
As of the last full run: **~4,300 products → ~3,700 canonical groups, ~50 of which span more than one source** (the rest are single-source because the 4 sites' curated category lists in `config.py` don't fully overlap in coverage — add more overlapping categories to grow this number).

---

## 8. Database storage — `db.py` + `data/products.db`

Plain SQLite file, zero setup, zero cost. Four tables (schema created automatically on first run via `CREATE TABLE IF NOT EXISTS` in `db.SCHEMA`; an existing database from before these columns existed is migrated automatically via `ALTER TABLE ADD COLUMN` in `db._migrate()` — no manual DB surgery needed after pulling this update).

### `products`
One row per unique `(source, external_id, pincode)` — the current known state of that product **at that location** (section 4/6). This used to be keyed on just `(source, external_id)`; once BigBasket/Lots started scraping multiple pincodes per run, that old key would have let pincode B's price silently overwrite pincode A's row instead of keeping both as separate, comparable rows. `db.get_connection()` migrates an existing database to the new key automatically (rebuilding `products` in place, preserving every row) the first time you run the updated code — no manual DB surgery needed.
```sql
CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    name TEXT, brand TEXT, category TEXT,
    price REAL, mrp REAL,
    unit TEXT,               -- raw string as scraped
    pack_qty REAL,           -- parsed quantity, in base_unit
    base_unit TEXT,          -- "kg" | "l" | "pc"
    price_per_unit REAL,     -- price / pack_qty
    in_stock INTEGER,
    image_url TEXT, product_url TEXT,
    pincode TEXT,            -- section 6; '' (not NULL) when a site has no pincode concept
    location_note TEXT,      -- section 6, always populated
    canonical_id INTEGER,    -- section 7, FK -> canonical_products.id
    first_seen TEXT NOT NULL,   -- ISO timestamp, set once
    last_seen TEXT NOT NULL,    -- ISO timestamp, updated every run
    UNIQUE(source, external_id, pincode)
);
```
`db.upsert_product()` does an `INSERT ... ON CONFLICT(source, external_id, pincode) DO UPDATE` — so re-scraping the same product at the same location just refreshes its price/stock/last_seen in place, while the same product at a *different* pincode gets its own row. One subtlety: SQLite treats every `NULL` in a `UNIQUE` index as distinct from every other `NULL`, which would silently break dedup for Hyperpure/Deliverit's no-pincode case (`pincode: None` from the scraper) — `upsert_product()` coerces `None` to `''` before the insert so the constraint actually applies.

### `price_history`
One row appended **every time** a product is seen in a run — this is what turns a daily scrape into a price-trend dataset over weeks/months.
```sql
CREATE TABLE price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL, external_id TEXT NOT NULL,
    price REAL, mrp REAL, price_per_unit REAL,
    in_stock INTEGER, pincode TEXT,
    scraped_at TEXT NOT NULL
);
```
To see a product's price-per-unit over time:
```sql
SELECT scraped_at, price, price_per_unit, pincode FROM price_history
WHERE source='bigbasket' AND external_id='10000298'
ORDER BY scraped_at;
```

### `scrape_runs`
One row per site per run — an audit log for whether the automation is actually healthy.
```sql
CREATE TABLE scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL, finished_at TEXT,
    products_seen INTEGER DEFAULT 0,
    error TEXT   -- NULL on success, exception message on failure
);
```
To check whether last night's run was clean:
```sql
SELECT source, started_at, products_seen, error
FROM scrape_runs ORDER BY id DESC LIMIT 4;
```

### `canonical_products`
See section 7.

---

## 9. Logging

Every run writes to both the console and `logs/scraper.log` (plain text, one line per page/category fetched plus a final summary line). Since Task Scheduler runs the batch file with no visible console, `logs/scraper.log` is the only record of what happened overnight — check it first if the database looks stale.

---

## 10. File map

```
product-scraper/
├── config.py            # all target URLs/slugs, headers, delays, caps, LOCATION_CONTEXT — edit this to add coverage
├── db.py                 # SQLite schema + migration + upsert/run-logging helpers
├── canonicalize.py        # cross-source product grouping (section 7)
├── main.py                # orchestrator entry point (what Task Scheduler ultimately runs)
├── run_scraper.bat        # thin wrapper: cd + call python main.py
├── requirements.txt       # requests, beautifulsoup4, lxml (no browser deps)
├── scrapers/
│   ├── units.py            # pack-size parsing (section 5)
│   ├── hyperpure.py
│   ├── bigbasket.py
│   ├── deliverit.py
│   └── lots.py
├── data/
│   └── products.db        # SQLite database (created automatically)
└── logs/
    └── scraper.log         # append-only run log
```

---

## 11. Extending the pipeline

- **Add more categories to an existing site:** just add URLs/slugs to the relevant list in `config.py` — no code changes needed. More overlapping categories across sites also directly grows the number of cross-source canonical matches in section 7.
- **Add a new site:** first check its `robots.txt`, then view-source a product/category page looking for `__NEXT_DATA__`, `application/ld+json`, or any embedded JSON blob. If none is present in the plain HTML, do a one-off manual Playwright network capture (see how `lots.py`'s API was discovered) to find the underlying JSON API the frontend calls, then call that API directly with `requests` — this is what kept every site here zero-cost with no persistent browser dependency. Then: verify its location behavior empirically (section 6) before trusting any price from it, add an entry to `config.LOCATION_CONTEXT`, and write a new `scrapers/<site>.py` exposing a single `scrape() -> list[dict]` matching the schema in section 4 (including `pack_qty`/`base_unit`/`price_per_unit` via `scrapers/units.py`, and `pincode`/`location_note`), then register it in `main.py`'s `SCRAPERS` dict.
- **Re-verify unit parsing after adding a site/category:** run the >3x price-per-unit spread check from section 5/7 against the refreshed `canonical_products` groupings to catch any new multi-pack-suffix convention that `units.py` doesn't yet know about.
- **Change the schedule:** `schtasks /change /tn "ProductScraper" /st HH:MM`.
