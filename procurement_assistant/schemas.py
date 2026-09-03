from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EMAIL_PATTERN = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SignupRequest(APIModel):
    email: str = Field(min_length=3, max_length=320, pattern=EMAIL_PATTERN)
    password: str = Field(min_length=12, max_length=256)


class ConfirmationRequest(APIModel):
    email: str = Field(max_length=320, pattern=EMAIL_PATTERN)
    code: str = Field(min_length=1, max_length=20)


class LoginRequest(SignupRequest):
    pass


class ForgotPasswordRequest(APIModel):
    email: str = Field(max_length=320, pattern=EMAIL_PATTERN)


class ResetPasswordRequest(ConfirmationRequest):
    password: str = Field(min_length=12, max_length=256)


class RefreshRequest(APIModel):
    refresh_token: str | None = None


class RestaurantBootstrapRequest(APIModel):
    restaurant_name: str = Field(min_length=1, max_length=200)
    location_label: str = Field(default="Beta location", min_length=1, max_length=120)
    city: str = Field(min_length=1, max_length=120)
    pincode: str = Field(pattern=r"^\d{6}$")


class CompareRequest(APIModel):
    product_id: uuid.UUID
    required_quantity: Decimal = Field(gt=0)
    unit: Literal["kg", "l", "piece"]


class PurchaseItemRequest(APIModel):
    canonical_product_id: uuid.UUID
    product_variant_id: uuid.UUID
    supplier_offer_id: uuid.UUID | None = None
    supplier_product_url_snapshot: str | None = Field(default=None, max_length=2048)
    packs: int = Field(gt=0)
    quantity: Decimal = Field(gt=0)
    unit: Literal["kg", "l", "piece"]
    scraped_price_snapshot: Decimal | None = Field(default=None, ge=0)
    actual_unit_price: Decimal = Field(ge=0)
    actual_total_price: Decimal = Field(ge=0)


class PurchaseRequest(APIModel):
    supplier_id: uuid.UUID
    purchased_at: datetime
    notes: str | None = Field(default=None, max_length=4000)
    items: list[PurchaseItemRequest] = Field(min_length=1, max_length=100)


class InventoryAdjustmentRequest(APIModel):
    canonical_product_id: uuid.UUID
    base_unit: Literal["kg", "l", "piece"]
    quantity_delta: Decimal
    transaction_type: Literal["manual_add", "manual_remove", "correction"]
    note: str | None = Field(default=None, max_length=1000)
