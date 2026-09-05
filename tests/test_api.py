from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from procurement_assistant.app import create_app
from procurement_assistant.auth import AuthPrincipal
from procurement_assistant.database import Base
from procurement_assistant.models import (
    CanonicalProduct,
    ExpenseEntry,
    InventoryTransaction,
    PriceObservation,
    ProductMatch,
    ProductVariant,
    Purchase,
    Restaurant,
    RestaurantLocation,
    RestaurantMembership,
    ScrapeRun,
    Supplier,
    SupplierLocation,
    SupplierLocationMapping,
    SupplierOffer,
    SupplierProduct,
    User,
)
from procurement_assistant.providers.auth import AuthTokens, SignupResult
from procurement_assistant.settings import Settings


class FakeVerifier:
    def verify(self, token: str) -> AuthPrincipal:
        return AuthPrincipal(provider_id=f"sub-{token}", email=f"{token}@example.test")


class FakeIdentityProvider:
    def __init__(self):
        self.calls = []

    def signup(self, email, password):
        self.calls.append(("signup", email))
        return SignupResult(False, {"Destination": email})

    def confirm_signup(self, email, code):
        self.calls.append(("confirm", email, code))
        return {}

    def login(self, email, password):
        self.calls.append(("login", email))
        return AuthTokens(
            access_token=email.split("@")[0],
            refresh_token="refresh",
            id_token="id-token",
            expires_in=3600,
        )

    def forgot_password(self, email):
        self.calls.append(("forgot", email))
        return {}

    def confirm_forgot_password(self, email, code, password):
        self.calls.append(("reset", email, code))
        return {}

    def refresh(self, refresh_token):
        self.calls.append(("refresh", refresh_token))
        return AuthTokens(access_token="tenant-a", expires_in=3600)

    def logout(self, access_token):
        self.calls.append(("logout", access_token))


@pytest.fixture
def api_context():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        users = [
            User(auth_provider_id="sub-tenant-a", email="tenant-a@example.test"),
            User(auth_provider_id="sub-tenant-b", email="tenant-b@example.test"),
        ]
        restaurants = [Restaurant(name="Restaurant A"), Restaurant(name="Restaurant B")]
        supplier = Supplier(code="lots", name="Lots", base_url="https://lots.example")
        product = CanonicalProduct(
            normalized_name="basmati rice",
            display_name="Basmati Rice",
            canonical_brand="Test",
            category="Rice",
            status="active",
        )
        session.add_all([*users, *restaurants, supplier, product])
        session.flush()
        locations = [
            RestaurantLocation(
                restaurant_id=restaurants[0].id,
                label="Beta",
                city="Delhi",
                pincode="110001",
                is_beta_default=True,
            ),
            RestaurantLocation(
                restaurant_id=restaurants[1].id,
                label="Beta",
                city="Delhi",
                pincode="110001",
                is_beta_default=True,
            ),
        ]
        memberships = [
            RestaurantMembership(user_id=users[0].id, restaurant_id=restaurants[0].id, role="owner"),
            RestaurantMembership(user_id=users[1].id, restaurant_id=restaurants[1].id, role="owner"),
        ]
        supplier_location = SupplierLocation(
            supplier_id=supplier.id,
            external_location_id="fallback-store:101",
            location_type="store",
            name="Lots fallback store 101 (unverified)",
            location_metadata={"verified": False, "resolution_method": "fallback"},
            active=True,
        )
        variant = ProductVariant(
            canonical_product_id=product.id,
            quantity=Decimal("1"),
            base_unit="kg",
            pack_count=1,
            total_quantity=Decimal("1"),
            normalized_pack_text="1 kg",
        )
        source_product = SupplierProduct(
            supplier_id=supplier.id,
            external_product_id="rice-1",
            source_name="Test Basmati Rice 1 kg",
            source_brand="Test",
            source_category="Rice",
            source_pack_text="1 kg",
            product_url="https://lots.example/rice",
        )
        session.add_all([*locations, *memberships, supplier_location, variant, source_product])
        session.flush()
        mappings = [
            SupplierLocationMapping(
                restaurant_location_id=location.id,
                supplier_id=supplier.id,
                supplier_location_id=supplier_location.id,
                resolution_method="manual",
                verified_at=datetime.now(UTC),
                active=True,
            )
            for location in locations
        ]
        match = ProductMatch(
            supplier_product_id=source_product.id,
            canonical_product_id=product.id,
            product_variant_id=variant.id,
            match_method="fixture",
            confidence=Decimal("1"),
            review_status="MANUAL_MATCH",
        )
        offer = SupplierOffer(
            supplier_product_id=source_product.id,
            product_variant_id=variant.id,
            supplier_location_id=supplier_location.id,
            current_price=Decimal("100"),
            current_mrp=Decimal("110"),
            current_availability=True,
            last_seen_at=datetime.now(UTC),
            active=True,
        )
        session.add_all([*mappings, match, offer])
        session.flush()
        run = ScrapeRun(
            supplier_id=supplier.id,
            supplier_location_id=supplier_location.id,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            status="complete",
            expected_count=1,
            observed_count=1,
        )
        session.add(run)
        session.flush()
        observation = PriceObservation(
            supplier_offer_id=offer.id,
            scrape_run_id=run.id,
            price=Decimal("100"),
            mrp=Decimal("110"),
            availability=True,
            observed_at=datetime.now(UTC),
        )
        session.add(observation)
        ids = {
            "supplier": supplier.id,
            "product": product.id,
            "variant": variant.id,
            "offer": offer.id,
        }
    provider = FakeIdentityProvider()
    app = create_app(
        settings=Settings(database_url="sqlite://"),
        session_factory=factory,
        identity_provider=provider,
        token_verifier=FakeVerifier(),
    )
    return TestClient(app), factory, provider, ids


def auth(name="tenant-a"):
    return {"Authorization": f"Bearer {name}"}


def test_protected_routes_require_authentication(api_context) -> None:
    client, _factory, _provider, _ids = api_context
    assert client.get("/api/products/search?q=rice").status_code == 401


def test_search_offer_compare_and_history_flow(api_context) -> None:
    client, _factory, _provider, ids = api_context
    search = client.get("/api/products/search?q=basmati", headers=auth())
    assert search.status_code == 200
    assert search.json()["items"][0]["id"] == str(ids["product"])
    typo = client.get("/api/products/search?q=basmti", headers=auth()).json()
    assert typo["items"][0]["id"] == str(ids["product"])

    offers = client.get(f"/api/products/{ids['product']}/offers", headers=auth()).json()
    assert offers["items"][0]["supplier"] == "Lots"
    assert offers["items"][0]["supplier_location"] == "Lots fallback store 101 (unverified)"
    assert offers["items"][0]["stale"] is False
    comparison = client.post(
        "/api/compare",
        headers=auth(),
        json={"product_id": str(ids["product"]), "required_quantity": "2.5", "unit": "kg"},
    ).json()
    assert comparison["offers"][0]["packs_required"] == 3
    assert comparison["offers"][0]["total_cost"] == 300.0
    history = client.get(f"/api/products/{ids['product']}/history", headers=auth()).json()
    assert len(history["observations"]) == 1
    assert history["current_price"] == 100.0
    assert history["last_observed_at"] is not None
    assert history["observations"][0]["trusted_for_statistics"] is True
    assert history["observations"][0]["supplier_location"] == "Lots fallback store 101 (unverified)"


def test_purchase_updates_inventory_expense_but_not_price_history(api_context) -> None:
    client, factory, _provider, ids = api_context
    before = client.get(f"/api/products/{ids['product']}/history", headers=auth()).json()
    response = client.post(
        "/api/purchases",
        headers=auth(),
        json={
            "supplier_id": str(ids["supplier"]),
            "purchased_at": datetime.now(UTC).isoformat(),
            "notes": "weekly rice",
            "items": [
                {
                    "canonical_product_id": str(ids["product"]),
                    "product_variant_id": str(ids["variant"]),
                    "supplier_offer_id": str(ids["offer"]),
                    "supplier_product_url_snapshot": "https://lots.example/rice",
                    "packs": 3,
                    "quantity": "3",
                    "unit": "kg",
                    "scraped_price_snapshot": "100",
                    "actual_unit_price": "105",
                    "actual_total_price": "315",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    purchase_id = response.json()["id"]
    inventory = client.get("/api/inventory", headers=auth()).json()["items"]
    assert inventory[0]["quantity"] == 3.0
    history_rows = client.get(
        f"/api/inventory/{inventory[0]['id']}/transactions", headers=auth()
    ).json()["items"]
    assert history_rows[0]["transaction_type"] == "purchase"
    analytics = client.get("/api/analytics/spending", headers=auth()).json()
    assert analytics["current_month_spend"] == 315.0
    assert analytics["by_supplier"][0]["amount"] == 315.0
    assert analytics["by_product"][0]["product"] == "Basmati Rice"
    assert analytics["by_category"][0] == {"category": "Rice", "amount": 315.0}
    after = client.get(f"/api/products/{ids['product']}/history", headers=auth()).json()
    assert len(after["observations"]) == len(before["observations"])
    assert client.get(f"/api/purchases/{purchase_id}", headers=auth("tenant-b")).status_code == 404
    assert (
        client.get(f"/api/inventory/{inventory[0]['id']}/transactions", headers=auth("tenant-b")).status_code
        == 404
    )
    with factory() as session:
        assert session.scalar(select(ExpenseEntry)).amount == Decimal("315.00")
        transaction = session.scalar(select(InventoryTransaction))
        assert transaction.quantity_delta == Decimal("3.000000")
        purchase = session.scalar(select(Purchase))
        purchase.notes = "attempted rewrite"
        with pytest.raises(ValueError, match="immutable"):
            session.commit()


def test_scrape_run_contract_and_pagination(api_context) -> None:
    client, _factory, _provider, _ids = api_context
    response = client.get("/api/scrape-runs?limit=1&offset=0", headers=auth())
    assert response.status_code == 200
    run = response.json()["items"][0]
    assert run["status"] == "complete"
    assert run["metadata"] == {}
    assert client.get("/api/scrape-runs?limit=101", headers=auth()).status_code == 422


def test_inventory_adjustment_and_negative_guard(api_context) -> None:
    client, _factory, _provider, ids = api_context
    add = client.post(
        "/api/inventory/adjustments",
        headers=auth(),
        json={
            "canonical_product_id": str(ids["product"]),
            "base_unit": "kg",
            "quantity_delta": "2",
            "transaction_type": "manual_add",
            "note": "opening balance",
        },
    )
    assert add.status_code == 200
    remove = client.post(
        "/api/inventory/adjustments",
        headers=auth(),
        json={
            "canonical_product_id": str(ids["product"]),
            "base_unit": "kg",
            "quantity_delta": "-3",
            "transaction_type": "manual_remove",
        },
    )
    assert remove.status_code == 400


def test_auth_contracts_and_cookie_session(api_context) -> None:
    client, _factory, provider, _ids = api_context
    assert client.post(
        "/api/auth/signup", json={"email": "tenant-a@example.test", "password": "Password123!"}
    ).status_code == 202
    login = client.post(
        "/api/auth/login", json={"email": "tenant-a@example.test", "password": "Password123!"}
    )
    assert login.status_code == 200
    assert login.cookies.get("access_token") == "tenant-a"
    assert client.get("/api/products/search?q=rice").status_code == 200
    assert client.post(
        "/api/auth/confirm", json={"email": "tenant-a@example.test", "code": "123456"}
    ).status_code == 200
    assert client.post(
        "/api/auth/forgot-password", json={"email": "tenant-a@example.test"}
    ).status_code == 202
    assert client.post(
        "/api/auth/reset-password",
        json={
            "email": "tenant-a@example.test",
            "code": "123456",
            "password": "New-password123!",
        },
    ).status_code == 200
    assert client.post("/api/auth/refresh", json={"refresh_token": "refresh"}).status_code == 200
    assert client.post("/api/auth/logout").status_code == 204
    assert ("login", "tenant-a@example.test") in provider.calls
    assert ("forgot", "tenant-a@example.test") in provider.calls
    assert ("refresh", "refresh") in provider.calls


def test_session_reports_onboarding_state(api_context) -> None:
    client, _factory, _provider, _ids = api_context
    existing = client.get("/api/auth/session", headers=auth()).json()
    assert existing["onboarded"] is True
    assert existing["restaurant"]["name"] == "Restaurant A"
    assert client.get("/api/auth/session", headers=auth("new")).json()["onboarded"] is False


def test_authenticated_user_can_bootstrap_one_fixed_restaurant(api_context) -> None:
    client, _factory, _provider, _ids = api_context
    payload = {
        "restaurant_name": "New Cafe",
        "location_label": "Beta kitchen",
        "city": "Delhi",
        "pincode": "110001",
    }
    created = client.post("/api/restaurants/bootstrap", headers=auth("new"), json=payload)
    assert created.status_code == 201
    assert client.post(
        "/api/restaurants/bootstrap", headers=auth("new"), json=payload
    ).status_code == 409
    assert client.get("/api/products/search?q=rice", headers=auth("new")).status_code == 200


@pytest.mark.parametrize(
    "route",
    [
        "/dashboard",
        "/compare",
        "/inventory",
        "/purchases",
        "/spending",
        "/login",
        "/onboarding",
    ],
)
def test_primary_ui_routes_render_responsive_shell(api_context, route) -> None:
    client, _factory, _provider, _ids = api_context
    response = client.get(route)
    assert response.status_code == 200
    assert 'name="viewport"' in response.text
    assert "Procurement Assistant" in response.text


def test_pwa_assets_are_served(api_context) -> None:
    client, _factory, _provider, _ids = api_context
    assert client.get("/static/manifest.webmanifest").status_code == 200
    assert client.get("/static/sw.js").status_code == 200
