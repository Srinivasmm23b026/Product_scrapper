from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from scrapers import bigbasket, deliverit, hyperpure, lots

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(path: str) -> str:
    return (FIXTURES / path).read_text(encoding="utf-8")


def test_hyperpure_fixture_extracts_and_normalizes_location_metadata() -> None:
    products = hyperpure._extract_products(fixture_text("hyperpure/landing.html"))
    assert len(products) == 1
    normalized = hyperpure._normalize(products[0], "110001", "verified fixture")
    assert normalized["external_id"] == "101"
    assert normalized["pack_qty"] == 1.0
    assert normalized["base_unit"] == "l"
    assert normalized["price_per_unit"] == 180.0
    assert normalized["pincode"] == "110001"


def test_bigbasket_fixture_extracts_parent_and_variant() -> None:
    products = bigbasket._extract_raw_products(fixture_text("bigbasket/category.html"))
    assert len(products) == 1
    parent, child = products[0], products[0]["children"][0]
    normalized_parent = bigbasket._normalize(parent, "110001", "fixture")
    normalized_child = bigbasket._normalize(child, "110001", "fixture")
    assert normalized_parent["price"] == 100.0
    assert normalized_parent["pack_qty"] == 1.0
    assert normalized_child["external_id"] == "202"
    assert normalized_child["pack_qty"] == 2.0
    assert normalized_child["in_stock"] == 0


def test_deliverit_sitemap_and_product_fixtures() -> None:
    urls = deliverit._extract_sitemap_urls(fixture_text("deliverit/sitemap.xml"))
    assert urls == ["https://www.deliverit.net.in/product/test-milk?pid=301"]
    product = deliverit._extract_product_document(
        fixture_text("deliverit/product.html"), urls[0]
    )
    assert product["external_id"] == "301"
    assert product["price"] == 60.5
    assert product["pack_qty"] == 0.75
    assert product["in_stock"] == 0


def test_deliverit_first_sitemap_failure_propagates(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise requests.ConnectionError("fixture network failure")

    monkeypatch.setattr(deliverit.requests, "get", fail)
    with pytest.raises(requests.ConnectionError, match="fixture network failure"):
        deliverit._discover_product_urls()


def test_deliverit_sitemap_pagination_stops_on_empty_page(monkeypatch) -> None:
    calls = []

    class Response:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            return None

    def get(url, **_kwargs):
        calls.append(url)
        payload = fixture_text("deliverit/sitemap.xml") if "page=1" in url else "<urlset/>"
        return Response(payload)

    monkeypatch.setattr(deliverit.requests, "get", get)
    monkeypatch.setattr(deliverit.time, "sleep", lambda _seconds: None)
    assert deliverit._discover_product_urls() == [
        "https://www.deliverit.net.in/product/test-milk?pid=301"
    ]
    assert calls == [
        "https://www.deliverit.net.in/sitemap-products.xml?page=1",
        "https://www.deliverit.net.in/sitemap-products.xml?page=2",
    ]


def test_lots_category_search_and_normalization_fixtures() -> None:
    assert lots._extract_menu_id(fixture_text("lots/category.html")) == 130
    response = json.loads(fixture_text("lots/search.json"))
    assert response["totalElements"] == 1
    normalized = lots._normalize(response["content"][0], "110001", "fixture")
    assert normalized["external_id"] == "401"
    assert normalized["price"] == 240
    assert normalized["pack_qty"] == 5.0
    assert normalized["base_unit"] == "kg"
    assert normalized["pincode"] == "110001"


def test_lots_paginates_to_reported_total(monkeypatch) -> None:
    base_product = json.loads(fixture_text("lots/search.json"))["content"][0]
    pages = []
    monkeypatch.setattr(lots.config, "LOTS_CATEGORY_SLUGS", ["fixture-category"])
    monkeypatch.setattr(lots.config, "LOTS_MAX_PAGES_PER_CATEGORY", 3)
    monkeypatch.setattr(lots.config, "REQUEST_DELAY_SECONDS", 0)
    monkeypatch.setattr(lots, "find_store_code", lambda _session, _pincode: ("101", False))
    monkeypatch.setattr(lots, "_get_menu_id", lambda _session, _slug: 130)

    def search(_session, _menu_id, page, _pincode, _store_code):
        pages.append(page)
        product = {**base_product, "productCode": str(400 + page)}
        return {"content": [product], "totalPages": 2}

    monkeypatch.setattr(lots, "_search_page", search)
    results = lots._scrape_for_pincode(object(), "110001")
    assert pages == [1, 2]
    assert [row["external_id"] for row in results] == ["401", "402"]
    assert all(row["pincode"] is None for row in results)
    assert all("unverified fallback store" in row["location_note"] for row in results)


def test_lots_collapses_multiple_unresolved_pincodes_to_one_fallback_store(monkeypatch) -> None:
    monkeypatch.setattr(lots.config, "LOTS_TARGET_PINCODES", ["110001", "560001"])
    calls = []

    def scrape_once(_session, pincode, **kwargs):
        calls.append((pincode, kwargs))
        return [{"external_id": "401", "pincode": None, "location_note": "fallback"}]

    monkeypatch.setattr(lots, "find_store_code", lambda _session, _pincode: ("101", False))
    monkeypatch.setattr(lots, "_scrape_for_pincode", scrape_once)

    assert lots.scrape() == [{"external_id": "401", "pincode": None, "location_note": "fallback"}]
    assert calls == [
        (
            "110001",
            {
                "store_code": "101",
                "resolved": False,
                "attempted_pincodes": ("110001", "560001"),
            },
        )
    ]


def test_lots_refuses_to_mix_distinct_stores_in_one_worker_run(monkeypatch) -> None:
    monkeypatch.setattr(lots.config, "LOTS_TARGET_PINCODES", ["110001", "560001"])
    store_codes = iter([("101", True), ("102", True)])
    monkeypatch.setattr(lots, "find_store_code", lambda _session, _pincode: next(store_codes))

    with pytest.raises(RuntimeError, match="multiple effective stores"):
        lots.scrape()


@pytest.mark.parametrize(
    ("extractor", "payload"),
    [
        (hyperpure._extract_products, "<html>missing payload</html>"),
        (bigbasket._extract_raw_products, "<html>missing payload</html>"),
        (lots._extract_menu_id, "<html>missing payload</html>"),
    ],
)
def test_missing_structured_payload_is_explicitly_empty(extractor, payload) -> None:
    assert extractor(payload) in ([], None)
