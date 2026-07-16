"""Target pages to scrape, per site. Add more URLs here to expand coverage."""

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

REQUEST_DELAY_SECONDS = 3   # polite delay between requests to the same site
REQUEST_TIMEOUT = 20

DB_PATH = "data/products.db"

BIGBASKET_CATEGORY_URLS = [
    "https://www.bigbasket.com/pc/fruits-vegetables/fresh-fruits/",
    "https://www.bigbasket.com/pc/fruits-vegetables/fresh-vegetables/",
    "https://www.bigbasket.com/pc/fruits-vegetables/exotic-fruits-veggies/",
    "https://www.bigbasket.com/pc/fruits-vegetables/herbs-seasonings/",
    "https://www.bigbasket.com/pc/foodgrains-oil-masala/atta-flours-sooji/",
    "https://www.bigbasket.com/pc/foodgrains-oil-masala/dals-pulses/",
    "https://www.bigbasket.com/pc/foodgrains-oil-masala/dry-fruits/",
    "https://www.bigbasket.com/pc/foodgrains-oil-masala/edible-oils-ghee/",
    "https://www.bigbasket.com/pc/foodgrains-oil-masala/rice-rice-products/",
    "https://www.bigbasket.com/pc/foodgrains-oil-masala/salt-sugar-jaggery/",
    "https://www.bigbasket.com/pc/bakery-cakes-dairy/dairy/",
    "https://www.bigbasket.com/pc/beauty-hygiene/health-medicine/",
    "https://www.bigbasket.com/pc/kitchen-garden-pets/pet-food-accessories/",
]

# Hyperpure has no public paginated category API we could find without login;
# each landing page below embeds ~20 products server-side rendered.
HYPERPURE_LANDING_URLS = [
    "https://www.hyperpure.com/in/hyperpure",
    "https://www.hyperpure.com/in/packaging-material",
    "https://www.hyperpure.com/in/atta-maida-sooji",
    "https://www.hyperpure.com/in/butter",
    "https://www.hyperpure.com/in/cashews1",
    "https://www.hyperpure.com/in/cheese",
    "https://www.hyperpure.com/in/chicken-breast-boneless",
    "https://www.hyperpure.com/in/corn-flour-besan-others",
    "https://www.hyperpure.com/in/cream",
    "https://www.hyperpure.com/in/curd",
    "https://www.hyperpure.com/in/edible-oils",
    "https://www.hyperpure.com/in/eggs",
    "https://www.hyperpure.com/in/ghee",
    "https://www.hyperpure.com/in/ketchup-puree-pastes",
    "https://www.hyperpure.com/in/milk-milk-powder",
    "https://www.hyperpure.com/in/paneer",
    "https://www.hyperpure.com/in/pasta-noodles",
    "https://www.hyperpure.com/in/rice-rice-products",
    "https://www.hyperpure.com/in/salts-sugars",
    "https://www.hyperpure.com/in/tea-and-coffee",
    "https://www.hyperpure.com/in/tomato-onion-potato",
    "https://www.hyperpure.com/in/urad-rajma-other-dal",
]

# Deliverit embeds schema.org JSON-LD product data server-side on each
# product page. We discover product URLs from its sitemap (capped per run)
# and parse the JSON-LD directly with requests + BeautifulSoup.
DELIVERIT_SITEMAP_INDEX = "https://www.deliverit.net.in/sitemap.xml"
DELIVERIT_MAX_SITEMAP_PAGES = 3      # how many sitemap-products.xml pages to pull URLs from
DELIVERIT_MAX_PRODUCTS_PER_RUN = 60  # cap per automated run

# lotswholesale.com: each /category/<slug> page embeds a numeric menuId
# (__NEXT_DATA__ -> valueFromServer.menuDetail.id) which is then POSTed to
# the site's own public JSON API (api.lotswholesale.com/next-product/public
# /api/product/search) to get paginated product results. No login/cookies
# required. robots.txt has no Disallow directives for this site.
LOTS_CATEGORY_SLUGS = [
    "foodgrains-oil-masala/dals-pulses-",
    "foodgrains-oil-masala/atta-maida-sooji",
    "foodgrains-oil-masala/cooking-oil-ghee",
    "foodgrains-oil-masala/dry-fruits",
    "foodgrains-oil-masala/rice-poha",
    "foodgrains-oil-masala/salt-sugar",
    "foodgrains-oil-masala/spices-masale-",
    "dairy-fresh-frozen/milk-dahi",
    "dairy-fresh-frozen/butter-Chesse",
    "dairy-fresh-frozen/fruits-vegetables/fruits",
    "dairy-fresh-frozen/fruits-vegetables/vegetables",
    "biscuits-snacks-chocolates/chocolates",
    "biscuits-snacks-chocolates/namkeen",
    "biscuits-snacks-chocolates/biscuits-cookies",
    "tea-coffee-cold-drinks/tea",
    "tea-coffee-cold-drinks/coffee-instant-premix",
    "instant-packaged-food/noodles",
    "instant-packaged-food/pasta",
    "sauces-spreads-cooking-essentials/sauces-vinegar",
    "sauces-spreads-cooking-essentials/pickles",
    "cleaning-laundry/dishwash",
    "cleaning-laundry/fabric-care",
    "hair-body-care/soaps-body-wash",
]
LOTS_PAGE_SIZE = 60
LOTS_MAX_PAGES_PER_CATEGORY = 3  # cap per category per run

# ---------------------------------------------------------------------------
# Location context. Every price on every one of these sites is location-
# dependent (delivery pincode / serviceable city / warehouse), so a price is
# meaningless without recording what location it was fetched for.
#
# BigBasket and Lots are now scraped once per pincode below via a real
# stateful session (requests.Session() + a set_location() call before
# browsing categories) instead of a single fixed fallback city -- see
# scrapers/bigbasket.py and scrapers/lots.py. Hyperpure and Deliverit's
# behavior was verified empirically (see README.md "Location verification")
# to NOT vary by anonymous pincode/cookie at all, so they keep a single
# static LOCATION_CONTEXT entry; Hyperpure's *real* per-account pricing
# requires the login flow in scrapers/hyperpure.py instead.
# ---------------------------------------------------------------------------

# Every pincode below triggers its own full category-scrape pass, so keep
# this list short -- it directly multiplies run time and request volume.
BIGBASKET_TARGET_PINCODES = ["110001", "560001", "400001"]
LOTS_TARGET_PINCODES = ["110001", "560001"]

# BigBasket's web app calls an address/location endpoint from its "Select
# Location" picker modal to switch the delivery city for the current guest
# session; the response's Set-Cookie headers (_bb_cid, _bb_nhid, _bb_dsid,
# _bb_pin_code, ...) are what actually drive which city's prices later
# category requests return, carried automatically by requests.Session().
# NOTE: this modal's request is loaded lazily by BigBasket's frontend (not
# present in the initial page bundle), so the exact path could not be
# confirmed by static JS inspection alone -- bigbasket.set_location()
# verifies at runtime (by diffing the session's _bb_cid cookie before/after)
# whether the call actually worked, and degrades honestly (falls back to
# the anonymous default city, logs a warning, stamps location_note
# accordingly) rather than silently assuming success. If BigBasket changes
# or 404s this path, recapture the real one from a browser DevTools Network
# tab while using the site's own location picker (same technique originally
# used to find Lots' search API -- see README section 11) and update this
# constant.
BIGBASKET_SET_LOCATION_API = "https://www.bigbasket.com/mapi/v3.4/user/address/"

# Lots Wholesale's own frontend bundle shows storeCode/pincode come from
# `currentUser.assortPriceStoreCode` / `currentUser.registerZipcode` -- i.e.
# a *registered member's* home store, not a public per-request pincode
# lookup. Probing api.lotswholesale.com's API gateway confirms there is no
# reachable public "find my store" service (next-store, next-location,
# next-address, next-member all 404 at the gateway itself -- those service
# names aren't registered at all; only next-product, next-auth, next-cms
# are real). This constant is the integration point for a real store
# locator call *if* one is captured later (e.g. from a logged-in member
# session's network traffic); lots.set_location() calls it, verifies at
# runtime whether a real storeCode came back, and falls back to
# LOTS_DEFAULT_STORE_CODE with an honest location_note when it can't --
# never silently pretends the default store is pincode-specific.
LOTS_STORE_LOCATOR_API = "https://api.lotswholesale.com/next-product/public/api/store/by-pincode"
LOTS_DEFAULT_STORE_CODE = "101"

# Hyperpure is B2B/contract-priced: real per-buyer pricing requires being
# logged into a specific business account. Its login flow is phone+OTP, not
# email/password (confirmed via its own frontend bundle -- an "OTP request
# limit" modal exists, no password field does), so it cannot be fully
# non-interactively scripted without an SMS-receiving integration.
# hyperpure.login() sends the OTP then obtains the code via HYPERPURE_OTP
# (an env var you set right before running, once you've received the SMS)
# or an interactive input() prompt as a fallback.
HYPERPURE_LOGIN_SEND_OTP_API = "https://www.hyperpure.com/api/v1/auth/login/send-otp"
HYPERPURE_LOGIN_VERIFY_OTP_API = "https://www.hyperpure.com/api/v1/auth/login/verify-otp"

# One entry per business account/region you hold real credentials for.
# Left empty by default: with no accounts configured, hyperpure.scrape()
# falls back to today's existing anonymous public-listing behavior instead
# of failing the whole run.
HYPERPURE_ACCOUNTS = [
    # {"region": "delhi-ncr", "phone": "9100000000"},
]

LOCATION_CONTEXT = {
    "hyperpure": {
        "pincode": None,
        "location_note": (
            "No location cookie sent (anonymous, unauthenticated request). "
            "Verified deterministic: identical product/price returned across "
            "repeated fetches with no cookies. Hyperpure is a B2B platform "
            "where real pricing is per-buyer-contract after login; this is "
            "the public anonymous listing price only, not a specific pincode. "
            "Configure HYPERPURE_ACCOUNTS above to scrape real per-account "
            "pricing via login instead."
        ),
    },
    "deliverit": {
        "pincode": None,
        "location_note": (
            "Product page JSON-LD price is returned by a plain, cookie-less "
            "HTTP GET with no location/session state at all -- verified "
            "identical price across repeated fetches. This is a single "
            "site-wide catalog price, not tied to a delivery pincode; the "
            "site's separate delivery-ETA/serviceability check (lat/long "
            "based) does not affect it. Nothing to make location-aware here: "
            "if a pincode isn't serviced, checkout blocks delivery rather "
            "than changing this base price."
        ),
    },
}


def bigbasket_location_note(pincode, resolved, detail=""):
    """resolved=True means set_location() verified the session's city
    cookie actually changed after the address-set call."""
    if resolved:
        return (
            f"Location explicitly set via BigBasket's address-set API to "
            f"pincode {pincode} before scraping; verified the session's "
            f"city cookie actually changed before trusting any price from "
            f"this run. {detail}"
        ).strip()
    return (
        f"Attempted to set location to pincode {pincode} via BigBasket's "
        f"address-set API, but the session's city cookie did not verifiably "
        f"change afterwards -- falling back to the anonymous default city "
        f"(City_id=1) for this run rather than mislabeling it. {detail}"
    ).strip()


def lots_location_note(pincode, store_code, resolved):
    if resolved:
        return (
            f"storeCode {store_code} was resolved for pincode {pincode} via "
            f"Lots' store-locator call and injected into the search payload "
            f"in place of the hardcoded default."
        )
    return (
        f"Could not resolve a pincode-specific storeCode for {pincode} -- no "
        f"public store-locator endpoint was reachable (Lots ties storeCode "
        f"to a registered member account's home store, not an anonymous "
        f"pincode lookup; see LOTS_STORE_LOCATOR_API comment in config.py). "
        f"Falling back to default store {store_code}. pincode is still sent "
        f"in the payload for transparency but is not verified to affect "
        f"pricing."
    )


def hyperpure_location_note(account, logged_in):
    if logged_in:
        return (
            f"Authenticated as business account '{account['region']}' via "
            f"Hyperpure's phone+OTP login flow; the Authorization bearer "
            f"token captured at login is attached to every request, so "
            f"these prices reflect that account's real contract pricing, "
            f"not the anonymous public listing."
        )
    return (
        LOCATION_CONTEXT["hyperpure"]["location_note"]
        + f" (login attempt for account '{account['region']}' failed -- see log.)"
    )
