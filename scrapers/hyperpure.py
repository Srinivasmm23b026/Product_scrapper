"""Scraper for hyperpure.com with authenticated outlet verification.

robots.txt for hyperpure.com is fully open (Disallow: <empty>), so plain
HTTP GET + parsing the Next.js __NEXT_DATA__ script is enough for the
anonymous public listing; no headless browser needed either way.

Hyperpure is a B2B platform: the public landing pages show a generic,
anonymous listing price, but real localized/contract pricing is only
returned once you're logged into a specific business account and outlet.
The current public web bundle verifies the account phone, requests an OTP,
signs in, then exposes the selected outlet through authenticated account APIs.
This module requires the real outlet id, name, address, and pincode before it
returns any authenticated location context.

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
from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class AuthenticatedLocation:
    """A supplier outlet identity returned by Hyperpure after authentication."""

    external_location_id: str
    name: str
    address: str
    pincode: str
    city: str | None

    def as_dict(self) -> dict:
        return {
            "external_location_id": self.external_location_id,
            "name": self.name,
            "address": self.address,
            "pincode": self.pincode,
            "city": self.city,
            "verified": True,
            "verification_method": "authenticated_hyperpure_outlet_api",
        }


def _response_data(response: requests.Response) -> dict:
    try:
        body = response.json()
    except ValueError as exc:
        raise ValueError("Hyperpure returned a non-JSON authenticated response") from exc
    data = body.get("response", body)
    if not isinstance(data, dict):
        raise ValueError("Hyperpure authenticated response has no object payload")
    return data


def _text(mapping: dict, *keys: str) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _outlet_from_user_data(data: dict) -> dict:
    outlet = data.get("outlet") or data.get("Outlet") or data.get("OutletInfo")
    if not isinstance(outlet, dict):
        raise ValueError("Hyperpure authenticated account response has no outlet")
    return outlet


def _as_location(outlet: dict) -> AuthenticatedLocation:
    outlet_id = _text(outlet, "id", "Id", "OutletId", "outletId")
    name = _text(outlet, "name", "Name", "OutletName", "outletName", "restaurant_name")
    address = _text(
        outlet,
        "formattedAddress",
        "FormattedAddress",
        "address",
        "Address",
        "store_address",
        "OutletAddress",
    )
    pincode = _text(outlet, "pincode", "Pincode", "zipCode", "ZipCode", "store_pincode")
    city = _text(outlet, "city", "City", "cityName", "CityName")
    missing = [
        field
        for field, value in (
            ("outlet id", outlet_id),
            ("outlet name", name),
            ("address", address),
            ("pincode", pincode),
        )
        if not value
    ]
    if missing:
        raise ValueError("Hyperpure authenticated outlet is missing " + ", ".join(missing))
    return AuthenticatedLocation(
        external_location_id=f"outlet:{outlet_id}",
        name=name,
        address=address,
        pincode=pincode,
        city=city,
    )


def _get_user_data(session: requests.Session) -> dict:
    response = session.get(config.HYPERPURE_USER_DATA_API, timeout=config.REQUEST_TIMEOUT)
    response.raise_for_status()
    refreshed_token = response.headers.get("Authorization")
    if refreshed_token:
        session.headers["Authorization"] = refreshed_token
    return _response_data(response)


def _get_outlets(session: requests.Session) -> list[dict]:
    response = session.get(config.HYPERPURE_OUTLETS_API, timeout=config.REQUEST_TIMEOUT)
    response.raise_for_status()
    outlets = _response_data(response).get("outlets", [])
    if not isinstance(outlets, list) or not all(isinstance(outlet, dict) for outlet in outlets):
        raise ValueError("Hyperpure authenticated outlet list is invalid")
    return outlets


def _merge_outlet(active: dict, outlets: list[dict]) -> dict:
    active_id = _text(active, "id", "Id", "OutletId", "outletId")
    listed = next(
        (
            outlet
            for outlet in outlets
            if _text(outlet, "id", "Id", "OutletId", "outletId") == active_id
        ),
        {},
    )
    # ``consumer/outlets`` carries store address/pincode on some accounts,
    # while the selected-outlet response carries it on others. Preserve both.
    return {**listed, **{key: value for key, value in active.items() if value is not None}}


def authenticate_location(
    session: requests.Session, account: dict, otp_provider=None
) -> AuthenticatedLocation | None:
    """Authenticate and resolve a real outlet without exposing its bearer token.

    Accounts with multiple outlets must configure Hyperpure's own ``outlet_id``;
    that outlet is selected through the authenticated switch endpoint before its
    address and pincode are accepted as location evidence.
    """
    phone = account.get("phone")
    label = account.get("label", "configured account")
    otp_provider = otp_provider or _default_otp_provider
    if not phone:
        logger.warning("hyperpure: no phone configured for %s", label)
        return None
    headers = {**config.HEADERS, "Accept": "application/json", "Content-Type": "application/json"}
    try:
        verify_response = session.get(
            config.HYPERPURE_VERIFY_USER_API.format(phone=phone),
            headers=headers,
            timeout=config.REQUEST_TIMEOUT,
        )
        verify_response.raise_for_status()
        otp = otp_provider()
        if not otp:
            logger.warning("hyperpure: no OTP supplied for %s", label)
            return None
        send_response = session.post(
            config.HYPERPURE_SEND_OTP_API.format(phone=phone),
            json={"isForgotPassword": True, "userPhoneNumber": phone},
            headers=headers,
            timeout=config.REQUEST_TIMEOUT,
        )
        send_response.raise_for_status()
        sign_in = session.post(
            config.HYPERPURE_SIGN_IN_API,
            json={"Name": phone, "Password": "", "OTP": otp},
            headers=headers,
            timeout=config.REQUEST_TIMEOUT,
        )
        sign_in.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("hyperpure: authentication request failed for %s: %s", label, exc)
        return None

    token = sign_in.headers.get("Authorization")
    if not token:
        logger.warning("hyperpure: sign-in returned no authorization header for %s", label)
        return None
    session.headers["Authorization"] = token
    requested_outlet_id = str(account["outlet_id"]) if account.get("outlet_id") else None
    try:
        active_outlet = _outlet_from_user_data(_get_user_data(session))
        outlets = _get_outlets(session)
        active_outlet_id = _text(active_outlet, "id", "Id", "OutletId", "outletId")
        if not requested_outlet_id and len(outlets) > 1:
            raise ValueError("multiple Hyperpure outlets are available; configure outlet_id")
        if requested_outlet_id and active_outlet_id != requested_outlet_id:
            if not any(
                _text(outlet, "id", "Id", "OutletId", "outletId") == requested_outlet_id
                for outlet in outlets
                if isinstance(outlet, dict)
            ):
                raise ValueError("configured Hyperpure outlet_id is not available to this account")
            switch_response = session.post(
                config.HYPERPURE_SWITCH_OUTLET_API,
                json={"OutletId": requested_outlet_id},
                timeout=config.REQUEST_TIMEOUT,
            )
            switch_response.raise_for_status()
            active_outlet = _outlet_from_user_data(_get_user_data(session))
        location = _as_location(_merge_outlet(active_outlet, outlets))
    except (requests.RequestException, ValueError) as exc:
        logger.warning("hyperpure: could not resolve authenticated outlet for %s: %s", label, exc)
        return None
    if requested_outlet_id and location.external_location_id != f"outlet:{requested_outlet_id}":
        logger.warning("hyperpure: outlet switch did not select configured outlet for %s", label)
        return None
    return location


def login(session: requests.Session, account: dict, otp_provider=None) -> bool:
    """Compatibility wrapper retained for callers that only need login state."""
    return authenticate_location(session, account, otp_provider) is not None


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
            location = authenticate_location(session, account)
            if location is None:
                # Never write anonymous rows through a configured authenticated
                # supplier location when account/outlet verification failed.
                account_results = []
            else:
                location_data = location.as_dict()
                note = config.hyperpure_location_note(location_data)
                account_results = _scrape_pages(session, location.pincode, note)
                for row in account_results:
                    # The worker and raw snapshot retain this evidence so an
                    # operator can prove the configured supplier location was
                    # the authenticated outlet, not a pincode assertion.
                    row["authenticated_location"] = location_data
        except Exception as exc:
            # A failure on one account must not cost the results already
            # gathered from other accounts.
            logger.warning(
                "hyperpure: account '%s' scrape failed entirely: %s",
                account.get("label", "configured account"),
                exc,
            )
            account_results = []
        finally:
            session.close()
        for norm in account_results:
            location_id = norm["authenticated_location"]["external_location_id"]
            key = (norm["external_id"], location_id)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            all_results.append(norm)
    return all_results
