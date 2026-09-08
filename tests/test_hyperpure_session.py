from __future__ import annotations

import logging
import stat
from collections import deque

import pytest
import requests
from cryptography.fernet import Fernet

import config
from procurement_assistant.hyperpure_session import (
    AuthenticationStatus,
    CorruptedSessionState,
    EncryptedHyperpureSessionStore,
    HyperpureReauthenticationRequired,
    HyperpureSessionProvider,
    HyperpureSessionState,
    HyperpureUnverifiedOutlet,
    LocalSessionEnvelopeBackend,
)
from scrapers import hyperpure


class MemoryBackend:
    def __init__(self, envelope=None):
        self.envelope = envelope
        self.writes = 0

    def read(self):
        return self.envelope

    def write(self, envelope):
        self.envelope = envelope
        self.writes += 1


class FakeResponse:
    def __init__(self, body=None, *, status_code=200, headers=None):
        self.body = body if body is not None else {"response": {}}
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


class FakeSession:
    def __init__(self, responses):
        self.responses = deque(responses)
        self.headers = {}
        self.cookies = requests.cookies.RequestsCookieJar()
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, dict(self.headers), kwargs))
        return self.responses.popleft()

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)


def state(token="opaque-token", outlet_id="42"):
    return HyperpureSessionState(
        authorization=token,
        device_id="device-id",
        cookies={"deviceId": "device-id"},
        created_at="2026-09-06T00:00:00+00:00",
        updated_at="2026-09-06T00:00:00+00:00",
        outlet_id=outlet_id,
    )


def provider_with_state(responses, initial=None):
    backend = MemoryBackend()
    store = EncryptedHyperpureSessionStore(backend, Fernet.generate_key().decode())
    store.save(initial or state())
    provider = HyperpureSessionProvider(store, session=FakeSession(responses))
    return provider, store, backend


def user_data(outlet=None):
    return {
        "response": {
            "accountId": "account-7",
            "outlet": outlet
            or {
                "id": "42",
                "name": "Verified Kitchen",
                "address": "12 Market Road",
                "pincode": "560001",
                "city": "Bengaluru",
                "serviceZoneId": "zone-9",
            },
        }
    }


def test_valid_session_resolves_verified_location_and_sends_auth_header() -> None:
    provider, _store, _backend = provider_with_state(
        [
            FakeResponse(user_data()),
            FakeResponse({"response": {"outlets": [{"id": "42"}]}}),
        ]
    )

    provider.load_session()
    assert provider.validate_session() == AuthenticationStatus.AUTHENTICATED
    location = provider.resolve_location()

    assert location.external_location_id == "outlet:42"
    assert location.pincode == "560001"
    assert location.service_zone_id == "zone-9"
    assert location.as_dict()["verified"] is False
    assert provider.session.calls[0][2]["Authorization"] == "opaque-token"
    assert provider.session.calls[0][2]["X-OutletId"] == "42"


def test_replacement_authorization_is_encrypted_and_persisted() -> None:
    provider, store, backend = provider_with_state(
        [FakeResponse(user_data(), headers={"Authorization": "rotated-token"})]
    )
    provider.load_session()

    assert provider.refresh_session_if_possible() == AuthenticationStatus.REFRESHED
    assert store.load().authorization == "rotated-token"
    assert "rotated-token" not in str(backend.envelope)
    assert backend.writes >= 2


def test_bootstrap_sends_otp_before_sign_in_and_captures_session() -> None:
    backend = MemoryBackend()
    store = EncryptedHyperpureSessionStore(backend, Fernet.generate_key().decode())
    session = FakeSession(
        [
            FakeResponse(),
            FakeResponse({"response": {"sent": True}}),
            FakeResponse(headers={"Authorization": "captured-token"}),
            FakeResponse(user_data()),
            FakeResponse({"response": {"outlets": [{"id": "42"}]}}),
        ]
    )
    provider = HyperpureSessionProvider(store, session=session)

    provider.request_otp("9000000000")
    assert [call[1] for call in session.calls] == [
        config.HYPERPURE_VERIFY_USER_API.format(phone="9000000000"),
        config.HYPERPURE_SEND_OTP_API.format(phone="9000000000"),
    ]
    location = provider.complete_otp("9000000000", "123456")

    assert location.external_location_id == "outlet:42"
    assert session.calls[2][3]["json"] == {
        "Name": "9000000000",
        "Password": "",
        "OTP": "123456",
    }
    assert store.load().authorization == "captured-token"
    assert "captured-token" not in str(backend.envelope)


@pytest.mark.parametrize("status_code", [401, 403])
def test_expired_or_invalid_session_requires_reauthentication(status_code) -> None:
    provider, _store, _backend = provider_with_state([FakeResponse(status_code=status_code)])
    provider.load_session()

    with pytest.raises(HyperpureReauthenticationRequired, match="auth bootstrap"):
        provider.validate_session()


def test_missing_and_corrupted_state_require_reauthentication() -> None:
    key = Fernet.generate_key().decode()
    missing = HyperpureSessionProvider(
        EncryptedHyperpureSessionStore(MemoryBackend(), key), session=FakeSession([])
    )
    with pytest.raises(HyperpureReauthenticationRequired, match="No stored"):
        missing.load_session()

    corrupted = HyperpureSessionProvider(
        EncryptedHyperpureSessionStore(
            MemoryBackend({"format": "fernet-json-v1", "ciphertext": "invalid"}), key
        ),
        session=FakeSession([]),
    )
    with pytest.raises(CorruptedSessionState, match="cannot be decrypted"):
        corrupted.load_session()


def test_local_encrypted_state_uses_owner_only_permissions(tmp_path) -> None:
    target = tmp_path / "private" / "session.enc"
    store = EncryptedHyperpureSessionStore(
        LocalSessionEnvelopeBackend(target), Fernet.generate_key().decode()
    )
    store.save(state())

    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert "opaque-token" not in target.read_text()


def test_guest_outlet_without_location_evidence_remains_unverified() -> None:
    guest = {"id": "guest-1", "name": "Guest Outlet"}
    provider, _store, _backend = provider_with_state(
        [
            FakeResponse(user_data(guest)),
            FakeResponse({"response": {"outlets": [guest]}}),
        ],
        state(outlet_id="guest-1"),
    )
    provider.load_session()
    provider.validate_session()

    with pytest.raises(HyperpureUnverifiedOutlet, match="address, pincode"):
        provider.resolve_location()


def test_auth_failure_never_calls_catalogue_or_logs_secret(monkeypatch, caplog) -> None:
    secret = "authorization-that-must-not-appear"
    provider, _store, _backend = provider_with_state(
        [FakeResponse(status_code=401)], state(token=secret)
    )
    provider.load_session()
    with caplog.at_level(logging.DEBUG), pytest.raises(HyperpureReauthenticationRequired):
        provider.validate_session()
    assert secret not in caplog.text

    class RejectedProvider:
        def load_session(self):
            raise HyperpureReauthenticationRequired("stored session rejected")

    monkeypatch.setattr(
        hyperpure,
        "scrape_authenticated_catalogue",
        lambda *_args: pytest.fail("catalogue must not run after auth failure"),
    )
    with caplog.at_level(logging.DEBUG), pytest.raises(HyperpureReauthenticationRequired):
        hyperpure.scrape_authenticated(RejectedProvider())


def test_authenticated_catalogue_uses_outlet_api_and_attaches_evidence() -> None:
    products = [
        {
            "Id": 101,
            "Name": "Test Sunflower Oil, 2 x 500 ml",
            "Price": {"PriceVal": 180, "CompareAtPriceVal": 200},
            "Quantity": {"DisplayValue": "2 x 500 ml"},
            "IsInStock": True,
            "Slug": "test-oil",
        }
    ]
    provider, _store, _backend = provider_with_state(
        [
            FakeResponse(user_data()),
            FakeResponse({"response": {"outlets": [{"id": "42"}]}}),
            FakeResponse({"response": {"Products": products, "HasNextPage": False}}),
        ]
    )

    result = hyperpure.scrape_authenticated(provider)

    assert len(result) == 1
    assert result[0]["external_id"] == "101"
    assert result[0]["authenticated_location"]["external_location_id"] == "outlet:42"
    assert result[0]["authenticated_location"]["verified"] is True
    search_call = provider.session.calls[-1]
    assert search_call[1] == config.HYPERPURE_SEARCH_API
    assert search_call[3]["params"]["outletId"] == "42"
    assert search_call[3]["params"]["getGlobalCatalog"] == "false"
