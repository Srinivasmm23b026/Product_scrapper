from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from procurement_assistant.auth import (
    AuthPrincipal,
    IdentityProvider,
    TenantContext,
    get_current_principal,
    get_identity_provider,
    get_session,
    get_tenant_context,
)
from procurement_assistant.models import (
    CanonicalProduct,
    InventoryItem,
    InventoryTransaction,
    Purchase,
    PurchaseItem,
    Restaurant,
    RestaurantLocation,
    RestaurantMembership,
    ScrapeRun,
    Supplier,
    SupplierLocation,
    User,
)
from procurement_assistant.providers.auth import AuthProviderError, AuthTokens
from procurement_assistant.schemas import (
    CompareRequest,
    ConfirmationRequest,
    ForgotPasswordRequest,
    InventoryAdjustmentRequest,
    LoginRequest,
    PurchaseRequest,
    RefreshRequest,
    ResetPasswordRequest,
    RestaurantBootstrapRequest,
    SignupRequest,
)
from procurement_assistant.services import (
    adjust_inventory,
    compare_product_offers,
    get_offer_rows,
    get_product,
    price_history,
    record_purchase,
    search_products,
    serialize_offers,
    spending_analytics,
)
from procurement_assistant.settings import Settings, get_settings

router = APIRouter(prefix="/api")


def _provider_call(callback):
    try:
        return callback()
    except AuthProviderError as exc:
        raise HTTPException(exc.status_code, f"Authentication failed: {exc.code}") from exc


def _set_auth_cookies(response: Response, tokens: AuthTokens, settings: Settings) -> None:
    common = {
        "httponly": True,
        "secure": settings.cookie_secure,
        "samesite": "lax",
        "path": "/",
    }
    response.set_cookie(
        "access_token", tokens.access_token, max_age=tokens.expires_in, **common
    )
    if tokens.refresh_token:
        response.set_cookie("refresh_token", tokens.refresh_token, max_age=30 * 86400, **common)


@router.post("/auth/signup", status_code=202)
def signup(payload: SignupRequest, provider: IdentityProvider = Depends(get_identity_provider)):
    result = _provider_call(lambda: provider.signup(payload.email, payload.password))
    return {"user_confirmed": result.user_confirmed, "delivery": result.delivery}


@router.post("/auth/confirm")
def confirm_signup(
    payload: ConfirmationRequest, provider: IdentityProvider = Depends(get_identity_provider)
):
    _provider_call(lambda: provider.confirm_signup(payload.email, payload.code))
    return {"confirmed": True}


@router.post("/auth/login")
def login(
    payload: LoginRequest,
    response: Response,
    provider: IdentityProvider = Depends(get_identity_provider),
    settings: Settings = Depends(get_settings),
):
    tokens = _provider_call(lambda: provider.login(payload.email, payload.password))
    _set_auth_cookies(response, tokens, settings)
    return {
        "access_token": tokens.access_token,
        "id_token": tokens.id_token,
        "refresh_token": tokens.refresh_token,
        "expires_in": tokens.expires_in,
        "token_type": tokens.token_type,
    }


@router.post("/auth/forgot-password", status_code=202)
def forgot_password(
    payload: ForgotPasswordRequest, provider: IdentityProvider = Depends(get_identity_provider)
):
    _provider_call(lambda: provider.forgot_password(payload.email))
    return {"accepted": True}


@router.post("/auth/reset-password")
def reset_password(
    payload: ResetPasswordRequest, provider: IdentityProvider = Depends(get_identity_provider)
):
    _provider_call(
        lambda: provider.confirm_forgot_password(payload.email, payload.code, payload.password)
    )
    return {"reset": True}


@router.post("/auth/refresh")
def refresh_session(
    payload: RefreshRequest,
    request: Request,
    response: Response,
    provider: IdentityProvider = Depends(get_identity_provider),
    settings: Settings = Depends(get_settings),
):
    refresh_token = payload.refresh_token or request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token required")
    tokens = _provider_call(lambda: provider.refresh(refresh_token))
    _set_auth_cookies(response, tokens, settings)
    return {"access_token": tokens.access_token, "expires_in": tokens.expires_in}


@router.post("/auth/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    provider: IdentityProvider = Depends(get_identity_provider),
):
    token = request.cookies.get("access_token")
    if token:
        _provider_call(lambda: provider.logout(token))
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")


@router.get("/auth/session")
def auth_session(
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    row = session.execute(
        select(User, RestaurantMembership, Restaurant, RestaurantLocation)
        .join(RestaurantMembership, RestaurantMembership.user_id == User.id)
        .join(Restaurant, Restaurant.id == RestaurantMembership.restaurant_id)
        .join(
            RestaurantLocation,
            RestaurantLocation.restaurant_id == RestaurantMembership.restaurant_id,
        )
        .where(
            User.auth_provider_id == principal.provider_id,
            RestaurantLocation.is_beta_default.is_(True),
        )
    ).first()
    if row is None:
        return {"email": principal.email, "onboarded": False}
    user, membership, restaurant, location = row
    return {
        "email": user.email,
        "onboarded": True,
        "role": membership.role,
        "restaurant": {"id": restaurant.id, "name": restaurant.name},
        "location": {
            "id": location.id,
            "label": location.label,
            "city": location.city,
            "pincode": location.pincode,
        },
    }


@router.post("/restaurants/bootstrap", status_code=201)
def bootstrap_restaurant(
    payload: RestaurantBootstrapRequest,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    user = session.scalar(select(User).where(User.auth_provider_id == principal.provider_id))
    if user is not None:
        existing = session.scalar(
            select(RestaurantMembership).where(RestaurantMembership.user_id == user.id)
        )
        if existing is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Restaurant already configured")
    else:
        user = User(
            auth_provider_id=principal.provider_id,
            email=principal.email or f"{principal.provider_id}@unknown.invalid",
        )
        session.add(user)
        session.flush()
    restaurant = Restaurant(name=payload.restaurant_name)
    session.add(restaurant)
    session.flush()
    membership = RestaurantMembership(user_id=user.id, restaurant_id=restaurant.id, role="owner")
    location = RestaurantLocation(
        restaurant_id=restaurant.id,
        label=payload.location_label,
        city=payload.city,
        pincode=payload.pincode,
        is_beta_default=True,
    )
    session.add_all([membership, location])
    session.commit()
    return {"restaurant_id": restaurant.id, "location_id": location.id}


@router.get("/products/search")
def product_search(
    q: str = Query(min_length=1, max_length=200),
    _tenant: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return {"items": search_products(session, q)}


@router.get("/products/{product_id}")
def product_detail(
    product_id: uuid.UUID,
    _tenant: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    product = get_product(session, product_id)
    return {
        "id": product.id,
        "display_name": product.display_name,
        "brand": product.canonical_brand,
        "category": product.category,
        "subcategory": product.subcategory,
        "aliases": product.aliases,
        "status": product.status,
    }


@router.get("/products/{product_id}/offers")
def product_offers(
    product_id: uuid.UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    get_product(session, product_id)
    return {
        "items": serialize_offers(
            get_offer_rows(session, tenant, product_id),
            stale_after_hours=settings.offer_stale_after_hours,
        ),
        "disclaimer": "Supplier price may have changed since the last check.",
    }


@router.get("/products/{product_id}/history")
def product_history(
    product_id: uuid.UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    get_product(session, product_id)
    return price_history(session, tenant, product_id)


@router.post("/compare")
def compare(
    payload: CompareRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    return compare_product_offers(
        session,
        tenant,
        product_id=payload.product_id,
        required_quantity=payload.required_quantity,
        unit=payload.unit,
        stale_after_hours=settings.offer_stale_after_hours,
    )


@router.post("/purchases", status_code=201)
def create_purchase(
    payload: PurchaseRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    purchase = record_purchase(session, tenant, payload)
    return {"id": purchase.id, "total_amount": purchase.total_amount}


@router.get("/purchases")
def list_purchases(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    tenant: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    rows = session.execute(
        select(Purchase, Supplier)
        .join(Supplier, Supplier.id == Purchase.supplier_id)
        .where(Purchase.restaurant_id == tenant.restaurant_id)
        .order_by(Purchase.purchased_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "items": [
            {
                "id": purchase.id,
                "supplier": supplier.name,
                "purchased_at": purchase.purchased_at,
                "total_amount": purchase.total_amount,
                "notes": purchase.notes,
            }
            for purchase, supplier in rows
        ]
    }


@router.get("/purchases/{purchase_id}")
def purchase_detail(
    purchase_id: uuid.UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    purchase = session.scalar(
        select(Purchase).where(
            Purchase.id == purchase_id, Purchase.restaurant_id == tenant.restaurant_id
        )
    )
    if purchase is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Purchase not found")
    items = session.execute(
        select(PurchaseItem, CanonicalProduct)
        .join(CanonicalProduct, CanonicalProduct.id == PurchaseItem.canonical_product_id)
        .where(PurchaseItem.purchase_id == purchase.id)
    ).all()
    return {
        "id": purchase.id,
        "purchased_at": purchase.purchased_at,
        "total_amount": purchase.total_amount,
        "notes": purchase.notes,
        "items": [
            {
                "id": item.id,
                "product": product.display_name,
                "quantity": item.quantity,
                "unit": item.unit,
                "packs": item.packs,
                "scraped_price_snapshot": item.scraped_price_snapshot,
                "actual_unit_price": item.actual_unit_price,
                "actual_total_price": item.actual_total_price,
                "supplier_url": item.supplier_product_url_snapshot,
            }
            for item, product in items
        ],
    }


@router.get("/inventory")
def inventory(
    tenant: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    rows = session.execute(
        select(InventoryItem, CanonicalProduct)
        .join(CanonicalProduct, CanonicalProduct.id == InventoryItem.canonical_product_id)
        .where(
            InventoryItem.restaurant_id == tenant.restaurant_id,
            InventoryItem.restaurant_location_id == tenant.restaurant_location_id,
        )
        .order_by(CanonicalProduct.display_name)
    ).all()
    return {
        "items": [
            {
                "id": item.id,
                "canonical_product_id": product.id,
                "product": product.display_name,
                "quantity": item.current_quantity,
                "unit": item.base_unit,
                "low_stock_threshold": item.low_stock_threshold,
                "updated_at": item.updated_at,
            }
            for item, product in rows
        ]
    }


@router.post("/inventory/adjustments")
def inventory_adjustment(
    payload: InventoryAdjustmentRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    item = adjust_inventory(session, tenant, payload)
    return {"inventory_item_id": item.id, "current_quantity": item.current_quantity}


@router.get("/inventory/{inventory_item_id}/transactions")
def inventory_transactions(
    inventory_item_id: uuid.UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    item = session.scalar(
        select(InventoryItem).where(
            InventoryItem.id == inventory_item_id,
            InventoryItem.restaurant_id == tenant.restaurant_id,
        )
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inventory item not found")
    rows = session.scalars(
        select(InventoryTransaction)
        .where(InventoryTransaction.inventory_item_id == item.id)
        .order_by(InventoryTransaction.created_at.desc())
    )
    return {
        "items": [
            {
                "id": row.id,
                "transaction_type": row.transaction_type,
                "quantity_delta": row.quantity_delta,
                "purchase_item_id": row.purchase_item_id,
                "created_by_user_id": row.created_by_user_id,
                "created_at": row.created_at,
                "note": row.note,
            }
            for row in rows
        ]
    }


@router.get("/analytics/spending")
def analytics_spending(
    tenant: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return spending_analytics(session, tenant)


@router.get("/scrape-runs")
def scrape_runs(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _tenant: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    runs = session.execute(
        select(ScrapeRun, Supplier, SupplierLocation)
        .join(Supplier, Supplier.id == ScrapeRun.supplier_id)
        .join(SupplierLocation, SupplierLocation.id == ScrapeRun.supplier_location_id)
        .order_by(ScrapeRun.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [
            _serialize_run(run, supplier=supplier, location=location)
            for run, supplier, location in runs
        ]
    }


@router.get("/scrape-runs/{run_id}")
def scrape_run_detail(
    run_id: uuid.UUID,
    _tenant: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    run = session.get(ScrapeRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scrape run not found")
    supplier = session.get(Supplier, run.supplier_id)
    location = session.get(SupplierLocation, run.supplier_location_id)
    return _serialize_run(run, supplier=supplier, location=location)


def _serialize_run(
    run: ScrapeRun, *, supplier: Supplier | None = None, location: SupplierLocation | None = None
) -> dict:
    result = {
        "id": run.id,
        "supplier_id": run.supplier_id,
        "supplier_location_id": run.supplier_location_id,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "status": run.status,
        "expected_count": run.expected_count,
        "observed_count": run.observed_count,
        "failed_page_count": run.failed_page_count,
        "warning_count": run.warning_count,
        "error_summary": run.error_summary,
        "metadata": run.run_metadata,
    }
    if supplier:
        result["supplier"] = supplier.name
    if location:
        result["supplier_location"] = location.name
    return result


@router.get("/health")
def health(session: Session = Depends(get_session)):
    session.execute(select(1))
    return {"status": "ok", "time": datetime.now(UTC)}
