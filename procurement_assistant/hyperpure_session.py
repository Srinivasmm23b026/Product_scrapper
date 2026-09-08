"""Persistent, fail-closed Hyperpure HTTP authentication.

Hyperpure's web application stores its authorization value in a cookie but
sends it to the API in the Authorization header. The authenticated user-data
endpoint can return a replacement Authorization header. This module persists
that mutable state as an encrypted JSON object and deliberately has no
anonymous fallback.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import requests
from cryptography.fernet import Fernet, InvalidToken

import config
from procurement_assistant.providers.auth.supabase import validate_supabase_url
from procurement_assistant.scraping.types import ScrapeAuthenticationRequired
from procurement_assistant.settings import Settings


class HyperpureAuthError(RuntimeError):
    """A non-secret operational authentication failure."""


class HyperpureReauthenticationRequired(ScrapeAuthenticationRequired):
    """The stored Hyperpure state is missing, invalid, or expired."""


class HyperpureUnverifiedOutlet(HyperpureAuthError):
    """Authentication succeeded but outlet identity is incomplete."""


class CorruptedSessionState(HyperpureReauthenticationRequired):
    """Encrypted state could not be safely decoded or validated."""


class AuthenticationStatus(StrEnum):
    AUTHENTICATED = "authenticated"
    REFRESHED = "refreshed"
    REAUTHENTICATION_REQUIRED = "reauthentication-required"
    FAILED = "failed"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CorruptedSessionState(f"stored Hyperpure session has invalid {field}")
    return value.strip()


@dataclass(frozen=True, slots=True)
class HyperpureSessionState:
    authorization: str
    device_id: str
    cookies: dict[str, str]
    created_at: str
    updated_at: str
    validated_at: str | None = None
    outlet_id: str | None = None
    routing_context: str | None = None
    version: int = 1

    @classmethod
    def from_dict(cls, value: object) -> HyperpureSessionState:
        if not isinstance(value, dict) or value.get("version") != 1:
            raise CorruptedSessionState("stored Hyperpure session has an unsupported format")
        cookies = value.get("cookies")
        if not isinstance(cookies, dict) or not all(
            isinstance(key, str) and isinstance(item, str) for key, item in cookies.items()
        ):
            raise CorruptedSessionState("stored Hyperpure session has invalid cookies")
        optional = ("validated_at", "outlet_id", "routing_context")
        if any(value.get(key) is not None and not isinstance(value.get(key), str) for key in optional):
            raise CorruptedSessionState("stored Hyperpure session has invalid metadata")
        return cls(
            authorization=_required_text(value.get("authorization"), "authorization"),
            device_id=_required_text(value.get("device_id"), "device ID"),
            cookies=dict(cookies),
            created_at=_required_text(value.get("created_at"), "creation time"),
            updated_at=_required_text(value.get("updated_at"), "update time"),
            validated_at=value.get("validated_at"),
            outlet_id=value.get("outlet_id"),
            routing_context=value.get("routing_context"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "authorization": self.authorization,
            "device_id": self.device_id,
            "cookies": self.cookies,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "validated_at": self.validated_at,
            "outlet_id": self.outlet_id,
            "routing_context": self.routing_context,
        }


class SessionEnvelopeBackend(Protocol):
    def read(self) -> dict | None: ...

    def write(self, envelope: dict) -> None: ...


class LocalSessionEnvelopeBackend:
    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()

    def read(self) -> dict | None:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise CorruptedSessionState("stored Hyperpure session is unreadable") from exc
        if not isinstance(value, dict):
            raise CorruptedSessionState("stored Hyperpure session envelope is invalid")
        return value

    def write(self, envelope: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix=".hyperpure-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(envelope, handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


class SupabaseSessionEnvelopeBackend:
    def __init__(
        self,
        *,
        url: str,
        service_role_key: str,
        bucket: str,
        object_key: str,
        timeout_seconds: int = 15,
        session: requests.Session | None = None,
    ):
        self.url = validate_supabase_url(url)
        self.service_role_key = service_role_key
        self.bucket = bucket
        self.object_key = object_key
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        headers = {"apikey": self.service_role_key}
        if not self.service_role_key.startswith("sb_"):
            headers["Authorization"] = f"Bearer {self.service_role_key}"
        return headers

    def _url(self) -> str:
        encoded_key = "/".join(quote(part, safe="") for part in self.object_key.split("/"))
        return (
            f"{self.url}/storage/v1/object/{quote(self.bucket, safe='')}/{encoded_key}"
        )

    def read(self) -> dict | None:
        response = self.session.get(
            self._url(), headers=self._headers(), timeout=self.timeout_seconds
        )
        if response.status_code == 404:
            return None
        try:
            response.raise_for_status()
            value = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise HyperpureAuthError("Hyperpure session storage could not be read") from exc
        if not isinstance(value, dict):
            raise CorruptedSessionState("stored Hyperpure session envelope is invalid")
        return value

    def write(self, envelope: dict) -> None:
        headers = {
            **self._headers(),
            "Content-Type": "application/json",
            "x-upsert": "true",
        }
        try:
            response = self.session.post(
                self._url(),
                headers=headers,
                data=json.dumps(envelope, separators=(",", ":")).encode(),
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise HyperpureAuthError("Hyperpure session storage could not be updated") from exc


class EncryptedHyperpureSessionStore:
    def __init__(self, backend: SessionEnvelopeBackend, encryption_key: str):
        self.backend = backend
        try:
            self.cipher = Fernet(encryption_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise HyperpureAuthError("HYPERPURE_SESSION_ENCRYPTION_KEY is invalid") from exc

    def load(self) -> HyperpureSessionState | None:
        envelope = self.backend.read()
        if envelope is None:
            return None
        if envelope.get("format") != "fernet-json-v1" or not isinstance(
            envelope.get("ciphertext"), str
        ):
            raise CorruptedSessionState("stored Hyperpure session envelope is invalid")
        try:
            plaintext = self.cipher.decrypt(envelope["ciphertext"].encode("ascii"))
            value = json.loads(plaintext)
        except (InvalidToken, UnicodeEncodeError, ValueError) as exc:
            raise CorruptedSessionState("stored Hyperpure session cannot be decrypted") from exc
        return HyperpureSessionState.from_dict(value)

    def save(self, state: HyperpureSessionState) -> None:
        plaintext = json.dumps(state.as_dict(), separators=(",", ":")).encode()
        envelope = {
            "format": "fernet-json-v1",
            "ciphertext": self.cipher.encrypt(plaintext).decode("ascii"),
        }
        self.backend.write(envelope)


@dataclass(frozen=True, slots=True)
class AuthenticatedLocation:
    external_location_id: str
    name: str
    address: str
    pincode: str
    city: str | None
    account_id: str | None = None
    service_zone_id: str | None = None
    warehouse_city_id: str | None = None

    def as_dict(self, *, catalogue_verified: bool = False) -> dict[str, object]:
        return {
            "external_location_id": self.external_location_id,
            "name": self.name,
            "address": self.address,
            "pincode": self.pincode,
            "city": self.city,
            "verified": catalogue_verified,
            "verification_method": (
                "authenticated_hyperpure_outlet_catalogue_api"
                if catalogue_verified
                else "authenticated_hyperpure_outlet_identity"
            ),
            "verification_metadata": {
                "backend_outlet_id": self.external_location_id.removeprefix("outlet:"),
                "account_id": self.account_id,
                "service_zone_id": self.service_zone_id,
                "warehouse_city_id": self.warehouse_city_id,
                "catalogue_context": (
                    "consumer/v2/search:getGlobalCatalog=false"
                    if catalogue_verified
                    else None
                ),
            },
        }


def _text(mapping: dict, *keys: str) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _response_data(response: requests.Response) -> dict:
    try:
        body = response.json()
    except ValueError as exc:
        raise HyperpureAuthError("Hyperpure returned a non-JSON authenticated response") from exc
    data = body.get("response", body)
    if not isinstance(data, dict):
        raise HyperpureAuthError("Hyperpure returned an invalid authenticated response")
    return data


def _outlet_from_user_data(data: dict) -> dict:
    outlet = data.get("outlet") or data.get("Outlet") or data.get("OutletInfo")
    if not isinstance(outlet, dict):
        raise HyperpureUnverifiedOutlet("authenticated account has no outlet identity")
    return outlet


def _as_location(outlet: dict, user_data: dict) -> AuthenticatedLocation:
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
            ("stable outlet ID", outlet_id),
            ("outlet name", name),
            ("address", address),
            ("pincode", pincode),
        )
        if not value
    ]
    if missing:
        raise HyperpureUnverifiedOutlet(
            "authenticated outlet cannot be verified because it lacks " + ", ".join(missing)
        )
    return AuthenticatedLocation(
        external_location_id=f"outlet:{outlet_id}",
        name=name,
        address=address,
        pincode=pincode,
        city=city,
        account_id=_text(user_data, "accountId", "AccountId", "buyerAccountId"),
        service_zone_id=_text(outlet, "serviceZoneId", "ServiceZoneId", "storeId", "StoreId"),
        warehouse_city_id=_text(
            outlet, "warehouseCityId", "WarehouseCityId", "warehouse_city_id"
        ),
    )


class HyperpureSessionProvider:
    def __init__(
        self,
        store: EncryptedHyperpureSessionStore,
        *,
        session: requests.Session | None = None,
        timeout_seconds: int = 20,
    ):
        self.store = store
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds
        self.state: HyperpureSessionState | None = None
        self.last_status = AuthenticationStatus.REAUTHENTICATION_REQUIRED
        self.user_data: dict | None = None

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> HyperpureSessionProvider:
        settings = settings or Settings()
        key = settings.hyperpure_session_encryption_key
        if not key:
            raise HyperpureReauthenticationRequired(
                "Hyperpure encrypted session key is not configured; run the auth bootstrap"
            )
        if settings.hyperpure_session_storage_provider == "supabase":
            if not settings.supabase_url or not settings.supabase_service_role_key:
                raise HyperpureAuthError(
                    "Supabase Hyperpure session storage requires server credentials"
                )
            backend: SessionEnvelopeBackend = SupabaseSessionEnvelopeBackend(
                url=settings.supabase_url,
                service_role_key=settings.supabase_service_role_key,
                bucket=settings.hyperpure_session_bucket,
                object_key=settings.hyperpure_session_object_key,
                timeout_seconds=settings.provider_timeout_seconds,
            )
        else:
            backend = LocalSessionEnvelopeBackend(settings.hyperpure_session_file)
        return cls(
            EncryptedHyperpureSessionStore(backend, key),
            timeout_seconds=settings.provider_timeout_seconds,
        )

    def _base_headers(self, device_id: str) -> dict[str, str]:
        return {
            **config.HEADERS,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Client": "consumer",
            "HeaderRoute": "v2",
            "APIVersion": "12.1",
            "AppType": "web",
            "X-ClientPlatform": "web",
            "DeviceId": device_id,
            "DeviceName": "Chrome",
        }

    def _apply_state(self) -> None:
        if self.state is None:
            raise HyperpureReauthenticationRequired("Hyperpure session is not loaded")
        self.session.headers.update(self._base_headers(self.state.device_id))
        self.session.headers["Authorization"] = self.state.authorization
        if self.state.outlet_id:
            self.session.headers["X-OutletId"] = self.state.outlet_id
        else:
            self.session.headers.pop("X-OutletId", None)
        if self.state.routing_context:
            self.session.headers["routing_context"] = self.state.routing_context
        else:
            self.session.headers.pop("routing_context", None)
        self.session.cookies.clear()
        for name, value in self.state.cookies.items():
            self.session.cookies.set(name, value)

    def load_session(self) -> HyperpureSessionState:
        state = self.store.load()
        if state is None:
            raise HyperpureReauthenticationRequired(
                "No stored Hyperpure session exists; run the auth bootstrap"
            )
        self.state = state
        self._apply_state()
        return state

    def _capture_response_state(self, response: requests.Response) -> bool:
        if self.state is None:
            raise HyperpureReauthenticationRequired("Hyperpure session is not loaded")
        replacement = response.headers.get("Authorization")
        authorization = replacement.strip() if replacement and replacement.strip() else self.state.authorization
        cookies = self.session.cookies.get_dict()
        changed = authorization != self.state.authorization or cookies != self.state.cookies
        self.state = replace(
            self.state,
            authorization=authorization,
            cookies=cookies,
            updated_at=_now(),
        )
        self._apply_state()
        return changed

    def persist_rotated_state(self) -> None:
        if self.state is None:
            raise HyperpureReauthenticationRequired("Hyperpure session is not loaded")
        self.store.save(self.state)

    def authenticated_request(self, method: str, url: str, **kwargs) -> requests.Response:
        if self.state is None:
            raise HyperpureReauthenticationRequired("Hyperpure session is not loaded")
        headers = dict(kwargs.pop("headers", {}))
        headers["X-TrackingId"] = str(uuid.uuid4())
        try:
            response = self.session.request(
                method, url, headers=headers, timeout=self.timeout_seconds, **kwargs
            )
        except requests.RequestException as exc:
            raise HyperpureAuthError("Hyperpure authenticated request failed") from exc
        if response.status_code in (401, 403):
            raise HyperpureReauthenticationRequired(
                "Hyperpure rejected the stored session; run the auth bootstrap"
            )
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise HyperpureAuthError(
                f"Hyperpure authenticated request returned HTTP {response.status_code}"
            ) from exc
        if self._capture_response_state(response):
            self.last_status = AuthenticationStatus.REFRESHED
            self.persist_rotated_state()
        return response

    def validate_session(self) -> AuthenticationStatus:
        response = self.authenticated_request("GET", config.HYPERPURE_USER_DATA_API)
        data = _response_data(response)
        self.user_data = data
        if self.state is None:
            raise HyperpureReauthenticationRequired("Hyperpure session is not loaded")
        outlet = _outlet_from_user_data(data)
        outlet_id = _text(outlet, "id", "Id", "OutletId", "outletId")
        routing = _text(data, "routingContext", "RoutingContext", "routing_context")
        changed = outlet_id != self.state.outlet_id or (
            routing is not None and routing != self.state.routing_context
        )
        self.state = replace(
            self.state,
            outlet_id=outlet_id or self.state.outlet_id,
            routing_context=routing or self.state.routing_context,
            validated_at=_now(),
            updated_at=_now(),
        )
        self._apply_state()
        self.persist_rotated_state()
        if changed:
            self.last_status = AuthenticationStatus.REFRESHED
        elif self.last_status != AuthenticationStatus.REFRESHED:
            self.last_status = AuthenticationStatus.AUTHENTICATED
        return self.last_status

    def refresh_session_if_possible(self) -> AuthenticationStatus:
        # The inspected web application uses this account call to accept and
        # persist replacement Authorization headers. No separate refresh-token
        # endpoint has been observed.
        return self.validate_session()

    def requires_reauthentication(self) -> bool:
        try:
            if self.state is None:
                self.load_session()
            self.validate_session()
        except HyperpureReauthenticationRequired:
            self.last_status = AuthenticationStatus.REAUTHENTICATION_REQUIRED
            return True
        return False

    def resolve_location(self, requested_outlet_id: str | None = None) -> AuthenticatedLocation:
        if self.user_data is None:
            self.validate_session()
        assert self.user_data is not None
        active = _outlet_from_user_data(self.user_data)
        response = self.authenticated_request("GET", config.HYPERPURE_OUTLETS_API)
        outlets = _response_data(response).get("outlets", [])
        if not isinstance(outlets, list) or not all(isinstance(item, dict) for item in outlets):
            raise HyperpureUnverifiedOutlet("authenticated outlet list is invalid")
        active_id = _text(active, "id", "Id", "OutletId", "outletId")
        target_id = requested_outlet_id or (self.state.outlet_id if self.state else None) or active_id
        if not target_id:
            raise HyperpureUnverifiedOutlet("authenticated account has no stable outlet ID")
        if active_id != target_id:
            if not any(_text(item, "id", "Id", "OutletId", "outletId") == target_id for item in outlets):
                raise HyperpureUnverifiedOutlet("configured outlet is unavailable to this account")
            self.authenticated_request(
                "POST", config.HYPERPURE_SWITCH_OUTLET_API, json={"OutletId": target_id}
            )
            self.validate_session()
            assert self.user_data is not None
            active = _outlet_from_user_data(self.user_data)
            active_id = _text(active, "id", "Id", "OutletId", "outletId")
        if active_id != target_id:
            raise HyperpureUnverifiedOutlet("Hyperpure did not select the requested outlet")
        listed = next(
            (
                item
                for item in outlets
                if _text(item, "id", "Id", "OutletId", "outletId") == target_id
            ),
            {},
        )
        merged = {**listed, **{key: value for key, value in active.items() if value is not None}}
        location = _as_location(merged, self.user_data)
        if self.state and self.state.outlet_id != target_id:
            self.state = replace(self.state, outlet_id=target_id, updated_at=_now())
            self._apply_state()
            self.persist_rotated_state()
        return location

    def request_otp(self, phone: str) -> None:
        phone = phone.strip()
        if not phone:
            raise HyperpureAuthError("a Hyperpure account phone number is required")
        device_id = str(uuid.uuid4())
        self.session.headers.update(self._base_headers(device_id))
        try:
            verify = self.session.get(
                config.HYPERPURE_VERIFY_USER_API.format(phone=phone),
                timeout=self.timeout_seconds,
            )
            verify.raise_for_status()
            sent = self.session.post(
                config.HYPERPURE_SEND_OTP_API.format(phone=phone),
                json={"isForgotPassword": True, "userPhoneNumber": phone},
                timeout=self.timeout_seconds,
            )
            sent.raise_for_status()
        except requests.RequestException as exc:
            raise HyperpureAuthError("Hyperpure did not confirm the OTP request") from exc
        now = _now()
        self.state = HyperpureSessionState(
            authorization="pending-otp",
            device_id=device_id,
            cookies=self.session.cookies.get_dict(),
            created_at=now,
            updated_at=now,
        )

    def complete_otp(self, phone: str, otp: str, outlet_id: str | None = None) -> AuthenticatedLocation:
        if self.state is None or self.state.authorization != "pending-otp":
            raise HyperpureAuthError("request an OTP before completing sign-in")
        try:
            response = self.session.post(
                config.HYPERPURE_SIGN_IN_API,
                json={"Name": phone.strip(), "Password": "", "OTP": otp.strip()},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise HyperpureAuthError("Hyperpure OTP sign-in failed") from exc
        authorization = response.headers.get("Authorization")
        if not authorization or not authorization.strip():
            raise HyperpureAuthError("Hyperpure sign-in returned no reusable authorization")
        now = _now()
        self.state = replace(
            self.state,
            authorization=authorization.strip(),
            cookies=self.session.cookies.get_dict(),
            updated_at=now,
        )
        self._apply_state()
        # Save immediately so the successful OTP is not wasted if later outlet
        # inspection fails. The artifact remains encrypted and server-only.
        self.persist_rotated_state()
        self.validate_session()
        return self.resolve_location(outlet_id)


def build_session_provider(settings: Settings | None = None) -> HyperpureSessionProvider:
    return HyperpureSessionProvider.from_settings(settings)
