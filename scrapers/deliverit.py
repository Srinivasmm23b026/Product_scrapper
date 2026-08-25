"""Scraper for deliverit.net.in product pages.

robots.txt allows everything except /checkout/, /cart/, /search/. Product
pages are discovered via the site's own sitemap-products.xml files, then
each page's schema.org JSON-LD <script type="application/ld+json"> block
is parsed directly -- no headless browser needed, it's present in the
plain server response.
"""
import json
import logging
import re
import time
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

import config
from scrapers.units import parse_unit, unit_price

logger = logging.getLogger(__name__)

LOCATION = config.LOCATION_CONTEXT["deliverit"]

LOC_RE = re.compile(r"<loc>([^<]+)</loc>")


def _extract_sitemap_urls(xml: str):
    return LOC_RE.findall(xml)


def _discover_product_urls():
    urls = []
    for page in range(1, config.DELIVERIT_MAX_SITEMAP_PAGES + 1):
        sitemap_url = f"https://www.deliverit.net.in/sitemap-products.xml?page={page}"
        try:
            resp = requests.get(sitemap_url, headers=config.HEADERS, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            found = _extract_sitemap_urls(resp.text)
        except Exception as exc:
            if not urls:
                # A request failure (DNS/timeout/5xx) on the very first page
                # means the whole site was unreachable this run, not "no
                # more products" -- that's a real failure and must propagate
                # so main.py records it in scrape_runs.error instead of a
                # silent "0 products stored" that looks like success.
                raise
            logger.warning("deliverit: failed to fetch sitemap page %d: %s", page, exc)
            break
        if not found:
            break
        urls.extend(found)
        time.sleep(config.REQUEST_DELAY_SECONDS)
        if len(urls) >= config.DELIVERIT_MAX_PRODUCTS_PER_RUN:
            break
    return urls[: config.DELIVERIT_MAX_PRODUCTS_PER_RUN]


def _pid_from_url(url: str):
    qs = parse_qs(urlparse(url).query)
    return (qs.get("pid") or [None])[0]


def _normalize(ld: dict, url: str, out_of_stock: bool) -> dict:
    offers = ld.get("offers") or {}
    brand = (ld.get("brand") or {}).get("name")
    price = offers.get("price")
    try:
        price = float(price) if price is not None else None
    except (TypeError, ValueError):
        price = None
    name = ld.get("name")
    # JSON-LD has no explicit pack-size field; best-effort parse from the
    # name/description text (e.g. "Amul Cheese Block 200 g").
    pack_qty, base_unit = parse_unit(name, ld.get("description"))
    return {
        "source": "deliverit",
        "external_id": str(ld.get("sku") or _pid_from_url(url) or url),
        "name": name,
        "brand": brand,
        "category": None,
        "price": price,
        "mrp": price,
        "unit": None,
        "pack_qty": pack_qty,
        "base_unit": base_unit,
        "price_per_unit": unit_price(price, pack_qty, base_unit),
        "in_stock": 0 if out_of_stock else 1,
        "image_url": ld.get("image"),
        "product_url": offers.get("url") or url,
        "pincode": LOCATION["pincode"],
        "location_note": LOCATION["location_note"],
    }


def _extract_product_document(html: str, url: str):
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", attrs={"type": "application/ld+json"})
    if not script or not script.string:
        return None
    ld = json.loads(script.string)
    out_of_stock = bool(re.search(r"out of stock", html, re.I))
    return _normalize(ld, url, out_of_stock)


def scrape():
    results = []
    product_urls = _discover_product_urls()
    logger.info("deliverit: discovered %d product URLs to scrape this run", len(product_urls))
    for url in product_urls:
        try:
            resp = requests.get(url, headers=config.HEADERS, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            product = _extract_product_document(resp.text, url)
            if product is None:
                logger.warning("deliverit: no JSON-LD on %s", url)
                continue
            results.append(product)
        except Exception as exc:
            logger.warning("deliverit: failed on %s: %s", url, exc)
        time.sleep(config.REQUEST_DELAY_SECONDS)
    return results
