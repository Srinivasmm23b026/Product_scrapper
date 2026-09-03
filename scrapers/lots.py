"""Scraper for lotswholesale.com, now location-aware.

Each /category/<slug> page embeds a numeric menuId in its Next.js
__NEXT_DATA__ script (valueFromServer.menuDetail.id). That menuId is then
POSTed to the site's own public JSON API to get paginated product data
(name, brand, price, mrp, stock, image) -- no login, cookies, or headless
browser required. robots.txt for this site has no Disallow directives.

Previously this scraper hardcoded assortPriceStoreCode/nonAssortPriceStoreCode
to Lots' default store '101' regardless of the `pincode` sent alongside it.
find_store_code() below is the two-step system requested: resolve a
pincode's real storeCode via Lots' store-locator call first, then inject
that storeCode into the search payload instead of the hardcoded default.

IMPORTANT, verified by reading Lots' own production frontend bundle: its
storeCode actually comes from `currentUser.assortPriceStoreCode` --  a
*registered member's* home store -- and there is no reachable public
"find my store by pincode" service behind its API gateway (next-store,
next-location, next-address, next-member all 404 at the gateway itself;
only next-product, next-auth, next-cms are real registered services). So
find_store_code() calls the configured locator endpoint, but honestly
verifies the response actually contains a different, real storeCode before
trusting it, and falls back to the documented default otherwise -- see
config.LOTS_STORE_LOCATOR_API for how to point this at a real endpoint if
you capture one (e.g. from a logged-in member session's network traffic).
"""
import json
import logging
import re
import time

import requests

import config
from scrapers.units import parse_unit, unit_price

logger = logging.getLogger(__name__)

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)
SEARCH_API = "https://api.lotswholesale.com/next-product/public/api/product/search"

API_HEADERS = {
    **config.HEADERS,
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=UTF-8",
    "Referer": "https://www.lotswholesale.com/",
}


def find_store_code(session: requests.Session, pincode: str):
    """Looks up which storeCode services `pincode` via Lots' store-locator
    API. Returns (store_code, resolved) -- resolved=False means the locator
    call didn't produce a usable, pincode-specific storeCode, and the
    caller should fall back to config.LOTS_DEFAULT_STORE_CODE rather than
    treat the default as if it were pincode-verified.
    """
    try:
        resp = session.get(
            config.LOTS_STORE_LOCATOR_API,
            params={"pincode": pincode},
            headers=API_HEADERS,
            timeout=config.REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning("lots: store locator request failed for %s: %s", pincode, exc)
        return config.LOTS_DEFAULT_STORE_CODE, False

    if not resp.ok:
        logger.warning(
            "lots: store locator returned %s for pincode %s -- no public "
            "pincode->store lookup is confirmed to exist for this site "
            "(see scrapers/lots.py docstring); falling back to default store %s",
            resp.status_code, pincode, config.LOTS_DEFAULT_STORE_CODE,
        )
        return config.LOTS_DEFAULT_STORE_CODE, False

    try:
        data = resp.json()
    except ValueError:
        return config.LOTS_DEFAULT_STORE_CODE, False

    store_code = data.get("storeCode") or data.get("store_code")
    if not store_code:
        return config.LOTS_DEFAULT_STORE_CODE, False
    return str(store_code), True


def _get_menu_id(session: requests.Session, slug: str):
    url = f"https://www.lotswholesale.com/category/{slug}"
    resp = session.get(url, headers=config.HEADERS, timeout=config.REQUEST_TIMEOUT)
    resp.raise_for_status()
    return _extract_menu_id(resp.text)


def _extract_menu_id(html: str):
    m = NEXT_DATA_RE.search(html)
    if not m:
        return None
    data = json.loads(m.group(1))
    menu_detail = data.get("props", {}).get("pageProps", {}).get("valueFromServer", {}).get("menuDetail")
    return menu_detail.get("id") if menu_detail else None


def _search_page(session: requests.Session, menu_id: int, page: int, pincode: str, store_code: str):
    payload = {
        "menuId": menu_id,
        "locale": "en_US",
        "assortPriceStoreCode": store_code,
        "assortOrderStoreCode": store_code,
        "nonAssortPriceStoreCode": store_code,
        "nonAssortOrderStoreCode": store_code,
        "pincode": pincode,
        "makroNo": None,
        "reloadPrice": True,
        "loadHierarchy": True,
        "countryOfOrigin": None,
        "page": page,
        "pageSize": config.LOTS_PAGE_SIZE,
        "sorting": "SORTING_MENU_INDEX",
    }
    resp = session.post(
        SEARCH_API, headers=API_HEADERS, data=json.dumps(payload), timeout=config.REQUEST_TIMEOUT
    )
    resp.raise_for_status()
    return resp.json()


def _normalize(p: dict, pincode: str, location_note: str) -> dict:
    pricing = (p.get("pricingRecords") or [{}])[0]
    mrp = pricing.get("mrp")
    price = p.get("inVatPrice") if p.get("inVatPrice") is not None else pricing.get("sellingPrice")
    unit = None
    if p.get("uda2") and p.get("uda3"):
        unit = f"{p['uda2']} {p['uda3']}"
    name = p.get("productName")
    pack_qty, base_unit = parse_unit(unit, name)
    stock = p.get("stockAvailableToSell")
    slug = p.get("slug")
    return {
        "source": "lots",
        "external_id": str(p.get("productCode")),
        "name": name,
        "brand": p.get("brand"),
        "category": p.get("categoryL3") or p.get("category"),
        "price": price,
        "mrp": mrp if mrp is not None else price,
        "unit": unit,
        "pack_qty": pack_qty,
        "base_unit": base_unit,
        "price_per_unit": unit_price(price, pack_qty, base_unit),
        "in_stock": 1 if (stock is None or stock > 0) else 0,
        "image_url": p.get("image"),
        "product_url": f"https://www.lotswholesale.com/product/{slug}" if slug else None,
        "pincode": pincode,
        "location_note": location_note,
    }


def _scrape_for_pincode(session: requests.Session, pincode: str):
    store_code, resolved = find_store_code(session, pincode)
    location_note = config.lots_location_note(pincode, store_code, resolved)

    seen_ids = set()
    results = []
    for slug in config.LOTS_CATEGORY_SLUGS:
        try:
            menu_id = _get_menu_id(session, slug)
            if menu_id is None:
                logger.warning("lots[%s]: could not resolve menuId for %s", pincode, slug)
                continue
            time.sleep(config.REQUEST_DELAY_SECONDS)

            page = 1
            total_pages = 1
            count = 0
            while page <= min(total_pages, config.LOTS_MAX_PAGES_PER_CATEGORY):
                data = _search_page(session, menu_id, page, pincode, store_code)
                total_pages = data.get("totalPages", 1)
                for p in data.get("content", []):
                    norm = _normalize(p, pincode, location_note)
                    if not norm["external_id"] or norm["external_id"] in seen_ids:
                        continue
                    seen_ids.add(norm["external_id"])
                    results.append(norm)
                    count += 1
                page += 1
                time.sleep(config.REQUEST_DELAY_SECONDS)
            logger.info("lots[%s]: %s (menuId=%s, storeCode=%s) -> %d products",
                        pincode, slug, menu_id, store_code, count)
        except Exception as exc:
            logger.warning("lots[%s]: failed on %s: %s", pincode, slug, exc)
        time.sleep(config.REQUEST_DELAY_SECONDS)
    return results


def scrape():
    """Runs one full category pass per configured pincode, each on its own
    requests.Session() so storeCode resolution from one pincode never leaks
    into another's requests."""
    all_results = []
    seen_keys = set()
    for pincode in config.LOTS_TARGET_PINCODES:
        session = requests.Session()
        try:
            pincode_results = _scrape_for_pincode(session, pincode)
        except Exception as exc:
            # A failure scraping one pincode must not cost the results
            # already gathered from other pincodes.
            logger.warning("lots[%s]: pincode scrape failed entirely: %s", pincode, exc)
            pincode_results = []
        finally:
            session.close()
        for norm in pincode_results:
            key = (norm["external_id"], norm["pincode"])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            all_results.append(norm)
    return all_results
