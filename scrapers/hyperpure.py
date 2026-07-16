"""Scraper for hyperpure.com, now with an optional login flow for real
per-account (B2B contract) pricing.

robots.txt for hyperpure.com is fully open (Disallow: <empty>), so plain
HTTP GET + parsing the Next.js __NEXT_DATA__ script is enough for the
anonymous public listing; no headless browser needed either way.

Hyperpure is a B2B platform: the public landing pages show a generic,
anonymous listing price, but real localized/contract pricing is only
returned once you're logged into a specific business account. Its own
frontend bundle confirms the login flow is phone-number + OTP (an "OTP
request limit" modal exists; there is no password field anywhere), so
login() below drives that flow and attaches the resulting Authorization
bearer token to the session for every subsequent request.

Because completing an OTP flow requires an SMS the account holder actually
receives, this cannot be made fully unattended without a separate
SMS-receiving integration -- login() takes an otp_provider callback so you
can wire that up later; by default it reads the HYPERPURE_OTP environment
variable (set it right after the SMS arrives) and falls back to an
interactive prompt.
"""
import json
import logging
import os
import re
import time

import requests

import config
from scrapers.units import parse_unit, unit_price

logger = logging.getLogger(__name__)

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)


def _default_otp_provider():
    env_otp = os.environ.get("HYPERPURE_OTP")
    if env_otp:
        return env_otp.strip()
    try:
        return input("Enter the Hyperpure login OTP just sent by SMS: ").strip()
    except EOFError:
        return None


def login(session: requests.Session, account: dict, otp_provider=None) -> bool:
    """Logs `session` into Hyperpure as `account` (a dict with "phone" and
    "region") via the phone+OTP flow, attaching `Authorization: Bearer
    <token>` to session.headers on success. Returns False (and logs why)
    on any failure -- callers must treat that as "stay anonymous for this
    account" rather than crash the whole run.
    """
    phone = account.get("phone")
    region = account.get("region", phone)
    otp_provider = otp_provider or _default_otp_provider
    req_headers = {**config.HEADERS, "Accept": "application/json", "Content-Type": "application/json"}

    try:
        send_resp = session.post(
            config.HYPERPURE_LOGIN_SEND_OTP_API,
            data=json.dumps({"phone": phone}),
            headers=req_headers,
            timeout=config.REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning("hyperpure: send-otp request failed for %s: %s", region, exc)
        return False
    if not send_resp.ok:
        logger.warning("hyperpure: send-otp returned %s for %s", send_resp.status_code, region)
        return False

    otp = otp_provider()
    if not otp:
        logger.warning("hyperpure: no OTP supplied for %s, aborting login", region)
        return False

    try:
        verify_resp = session.post(
            config.HYPERPURE_LOGIN_VERIFY_OTP_API,
            data=json.dumps({"phone": phone, "otp": otp}),
            headers=req_headers,
            timeout=config.REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning("hyperpure: verify-otp request failed for %s: %s", region, exc)
        return False
    if not verify_resp.ok:
        logger.warning("hyperpure: verify-otp returned %s for %s", verify_resp.status_code, region)
        return False

    try:
        body = verify_resp.json()
    except ValueError:
        logger.warning("hyperpure: verify-otp response for %s was not JSON", region)
        return False

    token = body.get("token") or body.get("access_token") or (body.get("data") or {}).get("token")
    if not token:
        logger.warning("hyperpure: verify-otp response had no bearer token for %s", region)
        return False

    session.headers["Authorization"] = f"Bearer {token}"
    return True


def _extract_products(html: str):
    m = NEXT_DATA_RE.search(html)
    if not m:
        return []
    data = json.loads(m.group(1))
    catalog = (
        data.get("props", {})
        .get("pageProps", {})
        .get("initialState", {})
        .get("catalog", {})
    )
    products = []
    for key in (
        "searchProductsForBuyer",
        "categoryProductsForBuyer",
        "allProductsForBuyer",
        "categoryProducts",
        "allProducts",
    ):
        products.extend(catalog.get(key, {}).get("products", []))
    return products


def _normalize(p: dict, pincode, location_note: str) -> dict:
    price_val = (p.get("Price") or {}).get("PriceVal")
    compare_val = (p.get("Price") or {}).get("CompareAtPriceVal") or 0
    mrp = compare_val if compare_val else price_val
    slug = p.get("Slug") or ""
    name = p.get("Name")
    unit_str = (p.get("Quantity") or {}).get("DisplayValue")
    pack_qty, base_unit = parse_unit(unit_str, name)
    return {
        "source": "hyperpure",
        "external_id": str(p.get("Id")),
        "name": name,
        "brand": p.get("Brand"),
        "category": p.get("CategoryName") or p.get("ParentCategoryName"),
        "price": price_val,
        "mrp": mrp,
        "unit": unit_str,
        "pack_qty": pack_qty,
        "base_unit": base_unit,
        "price_per_unit": unit_price(price_val, pack_qty, base_unit),
        "in_stock": 1 if p.get("IsInStock") else 0,
        "image_url": p.get("ImagePath"),
        "product_url": f"https://www.hyperpure.com/in/{slug}" if slug else None,
        "pincode": pincode,
        "location_note": location_note,
    }


def _scrape_pages(session: requests.Session, pincode, location_note: str):
    seen_ids = set()
    results = []
    for url in config.HYPERPURE_LANDING_URLS:
        try:
            resp = session.get(url, headers=config.HEADERS, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            products = _extract_products(resp.text)
            for p in products:
                norm = _normalize(p, pincode, location_note)
                if norm["external_id"] in seen_ids:
                    continue
                seen_ids.add(norm["external_id"])
                results.append(norm)
            logger.info("hyperpure: %s -> %d products", url, len(products))
        except Exception as exc:
            logger.warning("hyperpure: failed on %s: %s", url, exc)
        time.sleep(config.REQUEST_DELAY_SECONDS)
    return results


def scrape():
    """With no HYPERPURE_ACCOUNTS configured, keeps today's anonymous
    public-listing behavior (pincode=None). With accounts configured, logs
    into each one and scrapes the same landing pages authenticated, so the
    __NEXT_DATA__ payload's *ForBuyer catalog keys resolve to that
    account's real contract pricing instead of the public fallback."""
    if not config.HYPERPURE_ACCOUNTS:
        session = requests.Session()
        try:
            note = config.LOCATION_CONTEXT["hyperpure"]["location_note"]
            return _scrape_pages(session, None, note)
        finally:
            session.close()

    all_results = []
    seen_keys = set()
    for account in config.HYPERPURE_ACCOUNTS:
        session = requests.Session()
        try:
            logged_in = login(session, account)
            note = config.hyperpure_location_note(account, logged_in)
            pincode = account.get("region") if logged_in else None
            account_results = _scrape_pages(session, pincode, note)
        except Exception as exc:
            # A failure on one account must not cost the results already
            # gathered from other accounts.
            logger.warning("hyperpure: account '%s' scrape failed entirely: %s",
                            account.get("region"), exc)
            account_results = []
        finally:
            session.close()
        for norm in account_results:
            key = (norm["external_id"], norm["pincode"])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            all_results.append(norm)
    return all_results
