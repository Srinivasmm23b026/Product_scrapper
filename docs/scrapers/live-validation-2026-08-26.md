# Live supplier validation — 2026-08-26

## Scope and method

This report validates the legacy adapters against live, unauthenticated supplier responses from
the audit environment. It records only response metadata and parsed field shapes; no credentials,
session data, or private responses are retained. No CAPTCHA, authentication, anti-bot control, or
access restriction was bypassed.

Validation used the repository's browser user agent, one representative category/landing request
per reachable source, and the existing parsers. The result is environment- and time-specific.

| Source | Current mechanism observed | Existing scraper valid? | Location valid? | Completeness signal | Status |
|---|---|---|---|---|---|
| Hyperpure | Public landing page contains Next.js `__NEXT_DATA__`; `searchProductsForBuyer.products` returned 20 products | Extraction works, but only for the first embedded page | No. Anonymous `/in/...` has no verified location identity; authenticated behavior was not tested | Payload says `hasMore=true`, `nextPage=2`; adapter does not paginate | **PARTIAL** |
| BigBasket | Category and configured location requests were denied with HTTP 403 from this environment | No live products could be extracted; the old parser cannot currently run here | No. Configured location request was denied and changed no city cookie | Unknown because access was denied before a catalogue response | **BROKEN** |
| Deliverit | DNS resolution failed for the host, robots file, sitemap index, and numbered product sitemap | No. Discovery cannot begin | Unknown/unavailable | None reachable | **BROKEN** |
| Lots Wholesale | Category `__NEXT_DATA__` resolved menu `130`; public product search returned 60 of 129 products and `totalPages=3` | Core category/search extraction works; configured page cap can truncate larger categories | No. Locator returned 404 and fell back to store `101` | API provides `totalElements`, `totalPages`, `numberOfElements`, `first`, and `last` | **PARTIAL** |

## Hyperpure evidence

- `GET https://www.hyperpure.com/robots.txt`: HTTP 200; empty `Disallow` directive and a sitemap
  declaration.
- `GET https://www.hyperpure.com/in/hyperpure`: HTTP 200, 986,687 response bytes.
- The existing extractor returned 20 product objects with stable-looking `Id`, `Name`, `Brand`,
  `Price`, `Quantity`, inventory, image, category, and slug fields.
- `searchProductsForBuyer` explicitly returned `hasMore: true` and `nextPage: 2`. The legacy
  scraper never follows this signal, so its catalogue completeness claim is unsupported.
- Public city routes such as `/ind/delhi` and `/ind/bengaluru` returned HTTP 200, but the legacy
  extraction path returned no products from either. Their location/pricing state cannot be mapped
  into the current adapter without further authorized protocol investigation.
- No Hyperpure account, OTP, or authenticated request was used. The configured send/verify OTP
  endpoints and contract-pricing behavior remain unknown rather than validated.

Conclusion: retain the first-page parser as useful code, but do not treat it as a complete or
location-resolved catalogue.

## BigBasket evidence

- The current robots policy retrieved through a normal web index allows general paths and selected
  category pagination, while disallowing product-detail and unrestricted query pagination paths.
- Direct category requests using the existing configured browser headers returned HTTP 403 and no
  cookies or product data.
- The baseline homepage request and configured location POST also returned HTTP 403; `_bb_cid`
  remained unset.
- The prior committed log showed the location URL returning 404 in July 2026. The current result is
  therefore not evidence that the old endpoint started working.

Conclusion: the current mechanism is broken in this runtime. Treat the access denial as an
external boundary; do not attempt evasion. Current data-source and location-selection protocols
remain unknown.

## Deliverit evidence

- DNS resolution failed for `www.deliverit.net.in` when requesting:
  - `/robots.txt`
  - `/sitemap.xml`
  - `/sitemap-products.xml?page=1`
- A current web search produced no indexed result for the supplier domain.
- This explains the committed run history's recent zero discoveries more strongly than a valid
  empty catalogue would. The old code's `suspicious_zero` semantics are inadequate because an
  empty first sitemap is still returned as a successful empty list.

Conclusion: classify the integration as broken, retain legacy observations, and do not manufacture
a replacement domain or infer a successor supplier.

## Lots Wholesale evidence

- `GET https://www.lotswholesale.com/robots.txt`: HTTP 200; sitemap access allowed and no observed
  disallow rule for the category/search flow.
- The configured category slug resolved to menu ID `130`.
- The public search API returned 60 rows on page 1, `totalElements=129`, and `totalPages=3`.
- Product rows exposed the fields used by the adapter: product code, name, brand, pricing records,
  VAT-inclusive price, pack attributes, stock, image, and slug.
- The configured store locator returned HTTP 404 and fallback store `101`.
- With the same store code, page-1 product IDs and prices were byte-for-byte equivalent for target
  pincodes `110001` and `560001`. This does not prove pincode never matters; it proves the current
  fallback cannot establish distinct supplier locations.
- The API's totals are suitable completeness signals. Categories whose `totalPages` exceed the
  configured cap of three are deliberately partial.

Conclusion: preserve the public catalogue adapter, but model its fallback as an unresolved supplier
location and classify capped or failed-page runs as partial.

## Phase implications

1. V1 must support inactive/broken suppliers without discarding their history.
2. Supplier location must be an entity with verification metadata; raw pincode is not offer identity.
3. Hyperpure and Lots expose objective pagination/completeness signals that the run controller must
   record.
4. BigBasket must not be presented as fresh until an allowed mechanism works without bypassing
   access controls.
5. Deliverit must produce `failed` or `suspicious_zero`, never a successful zero-result run.
6. No source currently qualifies as both complete and location-verified for the beta.

