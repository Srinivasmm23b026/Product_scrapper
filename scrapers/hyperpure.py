"""Hyperpure catalogue adapters.

The scheduled adapter uses Hyperpure's authenticated, outlet-aware search API
through ``HyperpureSessionProvider``. The public HTML parser remains available
for fixture/legacy discovery, but authenticated workers never fall back to it.
"""

import json
import logging
import re

import requests

import config
from procurement_assistant.hyperpure_session import (
    AuthenticatedLocation,
    HyperpureSessionProvider,
    build_session_provider,
)
from scrapers.units import parse_unit, unit_price

logger = logging.getLogger(__name__)

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)


def _extract_products(html: str) -> list[dict]:
    """Parse public page data for offline fixtures and discovery only."""
    match = NEXT_DATA_RE.search(html)
    if not match:
        return []
    data = json.loads(match.group(1))
    catalog = (
        data.get("props", {})
        .get("pageProps", {})
        .get("initialState", {})
        .get("catalog", {})
    )
    products: list[dict] = []
    for key in (
        "searchProductsForBuyer",
        "categoryProductsForBuyer",
        "allProductsForBuyer",
        "categoryProducts",
        "allProducts",
    ):
        values = catalog.get(key, {}).get("products", [])
        if isinstance(values, list):
            products.extend(value for value in values if isinstance(value, dict))
    return products


def _unwrap_product(value: dict) -> dict:
    for key in ("Product", "product", "ProductInfo", "productInfo"):
        nested = value.get(key)
        if isinstance(nested, dict):
            return nested
    return value


def _product_price(product: dict) -> tuple[object, object]:
    price = product.get("Price")
    if isinstance(price, dict):
        current = price.get("PriceVal")
        compare = price.get("CompareAtPriceVal")
    else:
        current = product.get("SellingPrice") or product.get("sellingPrice") or price
        compare = product.get("MRP") or product.get("Mrp") or product.get("mrp")
    return current, compare or current


def _normalize(product: dict, pincode: str | None, location_note: str) -> dict:
    product = _unwrap_product(product)
    price_value, mrp = _product_price(product)
    slug = product.get("Slug") or product.get("slug") or ""
    name = product.get("Name") or product.get("name")
    quantity = product.get("Quantity") or product.get("quantity") or {}
    unit_text = (
        quantity.get("DisplayValue") if isinstance(quantity, dict) else str(quantity)
    ) or product.get("Unit") or product.get("unit")
    pack_quantity, base_unit = parse_unit(unit_text, name)
    product_id = product.get("Id") or product.get("id") or product.get("ProductId")
    availability = product.get("IsInStock")
    if availability is None:
        availability = product.get("isInStock")
    return {
        "source": "hyperpure",
        "external_id": str(product_id) if product_id is not None else "",
        "name": name,
        "brand": product.get("Brand") or product.get("brand"),
        "category": (
            product.get("CategoryName")
            or product.get("categoryName")
            or product.get("ParentCategoryName")
        ),
        "price": price_value,
        "mrp": mrp,
        "unit": unit_text,
        "pack_qty": pack_quantity,
        "base_unit": base_unit,
        "price_per_unit": unit_price(price_value, pack_quantity, base_unit),
        "in_stock": 1 if availability is True else 0 if availability is False else None,
        "image_url": product.get("ImagePath") or product.get("imagePath"),
        "product_url": f"https://www.hyperpure.com/in/{slug}" if slug else None,
        "pincode": pincode,
        "location_note": location_note,
    }


def _search_page(
    provider: HyperpureSessionProvider, outlet_id: str, page_number: int
) -> tuple[list[dict], bool]:
    response = provider.authenticated_request(
        "GET",
        config.HYPERPURE_SEARCH_API,
        params={
            "query": "",
            "outletId": outlet_id,
            "pageNo": page_number,
            "categoryIds": "",
            "productIds": "",
            "sortBy": "",
            "sortType": "",
            "onOffer": "",
            "productNumbers": "",
            "referenceType": "",
            "referenceId": "",
            "fetchThroughV2": "true",
            "searchDebugFlag": "false",
            "onlyInStock": "false",
            "getGlobalCatalog": "false",
        },
    )
    try:
        body = response.json()
    except ValueError as exc:
        raise ValueError("Hyperpure search returned non-JSON data") from exc
    payload = body.get("response", body) if isinstance(body, dict) else None
    if not isinstance(payload, dict) or not isinstance(payload.get("Products"), list):
        raise ValueError("Hyperpure search response has no product list")
    products = [item for item in payload["Products"] if isinstance(item, dict)]
    has_next = payload.get("HasNextPage")
    if not isinstance(has_next, bool):
        raise ValueError("Hyperpure search response has invalid pagination state")
    return products, has_next


def scrape_authenticated_catalogue(
    provider: HyperpureSessionProvider, location: AuthenticatedLocation
) -> list[dict]:
    outlet_id = location.external_location_id.removeprefix("outlet:")
    location_data = location.as_dict(catalogue_verified=True)
    note = config.hyperpure_location_note(location_data)
    seen: set[str] = set()
    results: list[dict] = []
    for page_number in range(1, config.HYPERPURE_MAX_PAGES + 1):
        products, has_next = _search_page(provider, outlet_id, page_number)
        for raw in products:
            normalized = _normalize(raw, location.pincode, note)
            if (
                not normalized["external_id"]
                or not normalized["name"]
                or normalized["price"] is None
                or normalized["in_stock"] is None
            ):
                raise ValueError(
                    "Hyperpure returned a product without identity, name, price, or availability"
                )
            if normalized["external_id"] in seen:
                continue
            seen.add(normalized["external_id"])
            normalized["authenticated_location"] = location_data
            normalized["authentication_status"] = provider.last_status.value
            results.append(normalized)
        logger.info(
            "hyperpure: authenticated catalogue page %d -> %d products",
            page_number,
            len(products),
        )
        if not has_next:
            return results
    raise ValueError("Hyperpure catalogue exceeded the configured page safety limit")


def scrape_authenticated(provider: HyperpureSessionProvider | None = None) -> list[dict]:
    """Restore, validate, and scrape one authenticated outlet.

    Missing, corrupt, or rejected state raises a reauthentication-required
    signal. No public catalogue request is attempted on any auth failure.
    """
    provider = provider or build_session_provider()
    provider.load_session()
    provider.refresh_session_if_possible()
    location = provider.resolve_location()
    logger.info("hyperpure: authentication status=%s", provider.last_status.value)
    return scrape_authenticated_catalogue(provider, location)


def scrape_public() -> list[dict]:
    """Public discovery adapter; never used by the scheduled cloud worker."""
    session = requests.Session()
    try:
        seen: set[str] = set()
        results: list[dict] = []
        note = config.LOCATION_CONTEXT["hyperpure"]["location_note"]
        for url in config.HYPERPURE_LANDING_URLS:
            response = session.get(url, headers=config.HEADERS, timeout=config.REQUEST_TIMEOUT)
            response.raise_for_status()
            for raw in _extract_products(response.text):
                normalized = _normalize(raw, None, note)
                if normalized["external_id"] not in seen:
                    seen.add(normalized["external_id"])
                    results.append(normalized)
        return results
    finally:
        session.close()


scrape = scrape_authenticated
