"""Scraper for bigbasket.com category (listing) pages, now location-aware.

bigbasket's robots.txt disallows /p/, /product/, /ps/ and /pd/<id>/* (the
individual product-detail paths) but allows /pc/<category>/<subcategory>/
listing pages, which embed full product data (name, brand, price, mrp,
images, stock) per SKU in a __NEXT_DATA__ script. We stay within that
allowance and never fetch a disallowed product-detail URL directly.

Anonymous requests always resolve to BigBasket's default fallback city
(City_id=1) -- a bare `_bb_pin_code` cookie is ignored by the server (see
README.md "Location verification"). To actually get region-specific
pricing, set_location() drives the same stateful address-set call
BigBasket's own frontend makes, on a requests.Session() that then carries
the resulting city/location cookies into every subsequent category request.
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


def _extract_raw_products(html: str):
    m = NEXT_DATA_RE.search(html)
    if not m:
        return []
    data = json.loads(m.group(1))
    ssr = data.get("props", {}).get("pageProps", {}).get("SSRData", {})
    products = []
    for tab in ssr.get("tabs", []):
        products.extend(tab.get("product_info", {}).get("products", []))
    return products


def _price_fields(p: dict):
    discount = (p.get("pricing") or {}).get("discount") or {}
    mrp = discount.get("mrp")
    sp = (discount.get("prim_price") or {}).get("sp")
    try:
        mrp = float(mrp) if mrp is not None else None
    except ValueError:
        mrp = None
    try:
        sp = float(sp) if sp is not None else None
    except ValueError:
        sp = None
    return sp, (mrp if mrp is not None else sp)


def set_location(session: requests.Session, pincode: str) -> bool:
    """POST to BigBasket's address-set API so subsequent requests on `session`
    resolve to `pincode` instead of the anonymous default city.

    Returns True only if the session's city cookie (_bb_cid) is verifiably
    different afterwards than the pre-call baseline -- we don't trust a 200
    response alone, since BigBasket has previously been observed accepting
    location-looking input while silently keeping City_id=1 (see
    README.md). Callers must treat a False return as "still anonymous
    default city" and stamp results accordingly, never as a hard failure.
    """
    # Touch the homepage first so the session has the baseline guest
    # cookies (_bb_cid, csrftoken, etc.) that the address-set call expects.
    try:
        session.get("https://www.bigbasket.com/", headers=config.HEADERS, timeout=config.REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("bigbasket: set_location(%s) baseline homepage fetch failed: %s", pincode, exc)
        return False
    baseline_cid = session.cookies.get("_bb_cid")

    payload = {"pincode": pincode, "address_type": "home"}
    req_headers = {
        **config.HEADERS,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Referer": "https://www.bigbasket.com/",
        "X-CSRFToken": session.cookies.get("csrftoken", ""),
    }
    try:
        resp = session.post(
            config.BIGBASKET_SET_LOCATION_API,
            headers=req_headers,
            data=json.dumps(payload),
            timeout=config.REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning("bigbasket: set_location(%s) request failed: %s", pincode, exc)
        return False

    new_cid = session.cookies.get("_bb_cid")
    resolved = resp.ok and new_cid is not None and new_cid != baseline_cid
    if not resolved:
        logger.warning(
            "bigbasket: set_location(%s) did not verifiably change city "
            "(status=%s, _bb_cid before=%s after=%s) -- continuing with "
            "the anonymous default city instead of a silent guess",
            pincode, resp.status_code, baseline_cid, new_cid,
        )
    return resolved


def _normalize(p: dict, pincode: str, location_note: str) -> dict:
    sp, mrp = _price_fields(p)
    images = p.get("images") or []
    image_url = images[0].get("l") if images else None
    category = (p.get("category") or {}).get("mlc_name")
    brand = (p.get("brand") or {}).get("name")
    absolute_url = p.get("absolute_url")
    availability = p.get("availability") or {}
    name = p.get("desc")
    unit_str = p.get("w") or p.get("pack_desc")
    pack_qty, base_unit = parse_unit(unit_str, name)
    return {
        "source": "bigbasket",
        "external_id": str(p.get("id")),
        "name": name,
        "brand": brand,
        "category": category,
        "price": sp,
        "mrp": mrp,
        "unit": unit_str,
        "pack_qty": pack_qty,
        "base_unit": base_unit,
        "price_per_unit": unit_price(sp, pack_qty, base_unit),
        "in_stock": 0 if availability.get("not_for_sale") else 1,
        "image_url": image_url,
        "product_url": f"https://www.bigbasket.com{absolute_url}" if absolute_url else None,
        "pincode": pincode,
        "location_note": location_note,
    }


def _scrape_for_pincode(session: requests.Session, pincode: str):
    resolved = set_location(session, pincode)
    location_note = config.bigbasket_location_note(pincode, resolved)
    effective_pincode = pincode if resolved else None

    seen_ids = set()
    results = []
    for url in config.BIGBASKET_CATEGORY_URLS:
        try:
            resp = session.get(url, headers=config.HEADERS, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            raw_products = _extract_raw_products(resp.text)
            count = 0
            for p in raw_products:
                for entry in [p, *p.get("children", [])]:
                    norm = _normalize(entry, effective_pincode, location_note)
                    if not norm["external_id"] or norm["external_id"] in seen_ids:
                        continue
                    seen_ids.add(norm["external_id"])
                    results.append(norm)
                    count += 1
            logger.info("bigbasket[%s]: %s -> %d products", pincode, url, count)
        except Exception as exc:
            logger.warning("bigbasket[%s]: failed on %s: %s", pincode, url, exc)
        time.sleep(config.REQUEST_DELAY_SECONDS)
    return results


def scrape():
    """Runs one full category pass per configured pincode, each on its own
    requests.Session() so location state from one pincode never leaks into
    another's requests."""
    all_results = []
    seen_keys = set()
    for pincode in config.BIGBASKET_TARGET_PINCODES:
        session = requests.Session()
        try:
            pincode_results = _scrape_for_pincode(session, pincode)
        except Exception as exc:
            # A failure scraping one pincode must not cost the results
            # already gathered from other pincodes -- same resilience
            # contract as the per-category/per-slug try/excepts below.
            logger.warning("bigbasket[%s]: pincode scrape failed entirely: %s", pincode, exc)
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
