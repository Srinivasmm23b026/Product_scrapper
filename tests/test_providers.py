from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
import requests
from cryptography.hazmat.primitives.asymmetric import rsa

from procurement_assistant.auth import configure_auth
from procurement_assistant.database import Base, normalize_database_url
from procurement_assistant.providers.auth import AuthProviderError
from procurement_assistant.providers.auth.supabase import (
    SupabaseAuthProvider,
    SupabaseTokenVerifier,
    validate_supabase_url,
)
from procurement_assistant.providers.storage import (
    LocalObjectStorage,
    SupabaseObjectStorage,
    configure_storage,
)
from procurement_assistant.settings import Settings


class FakeResponse:
    def __init__(self, body=None, *, status_code=200):
        self.body = body or {}
        self.status_code = status_code
        self.ok = status_code < 400
        self.content = b"" if status_code == 204 else b"json"

    def json(self):
        return self.body

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(str(self.status_code))


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)


def test_supabase_auth_contract_uses_server_side_rest_adapter() -> None:
    session = FakeSession(
        [
            FakeResponse({"user": {"confirmed_at": None}}),
            FakeResponse({"user": {"id": "user-1"}}),
            FakeResponse(
                {
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_in": 3600,
                    "token_type": "bearer",
                }
            ),
            FakeResponse(),
            FakeResponse({"access_token": "recovery", "expires_in": 60}),
            FakeResponse({"user": {"id": "user-1"}}),
            FakeResponse({"access_token": "new-access", "expires_in": 3600}),
            FakeResponse(status_code=204),
        ]
    )
    provider = SupabaseAuthProvider(
        url="https://project.supabase.co",
        anon_key="public-anon-key",
        redirect_url="https://beta.example/reset",
        session=session,
    )

    assert provider.signup("buyer@example.test", "Password123!").user_confirmed is False
    provider.confirm_signup("buyer@example.test", "123456")
    assert provider.login("buyer@example.test", "Password123!").access_token == "access"
    provider.forgot_password("buyer@example.test")
    provider.confirm_forgot_password("buyer@example.test", "654321", "NewPassword123!")
    assert provider.refresh("refresh").access_token == "new-access"
    provider.logout("new-access")

    assert "/auth/v1/signup?redirect_to=" in session.calls[0][1]
    assert session.calls[2][1].endswith("/auth/v1/token?grant_type=password")
    assert "/auth/v1/recover?redirect_to=" in session.calls[3][1]
    assert session.calls[5][0] == "PUT"
    assert session.calls[5][2]["headers"]["Authorization"] == "Bearer recovery"
    assert session.calls[-1][1].endswith("/auth/v1/logout?scope=local")
    assert "Authorization" not in session.calls[0][2]["headers"]


def test_supabase_auth_errors_are_reduced_to_provider_code() -> None:
    provider = SupabaseAuthProvider(
        url="https://project.supabase.co",
        anon_key="public-anon-key",
        session=FakeSession([FakeResponse({"error_code": "invalid_credentials"}, status_code=400)]),
    )
    with pytest.raises(AuthProviderError, match="invalid_credentials"):
        provider.login("buyer@example.test", "WrongPassword!")


@pytest.mark.parametrize("upstream_status, expected_status", [(429, 429), (500, 503)])
def test_supabase_auth_preserves_retryable_error_classes(
    upstream_status: int, expected_status: int
) -> None:
    provider = SupabaseAuthProvider(
        url="https://project.supabase.co",
        anon_key="public-anon-key",
        session=FakeSession([FakeResponse(status_code=upstream_status)]),
    )
    with pytest.raises(AuthProviderError) as exc_info:
        provider.login("buyer@example.test", "Password123!")
    assert exc_info.value.status_code == expected_status


def test_supabase_jwt_verifier_returns_internal_principal() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    issuer = "https://project.supabase.co/auth/v1"
    token = jwt.encode(
        {
            "sub": "auth-user-id",
            "email": "buyer@example.test",
            "aud": "authenticated",
            "iss": issuer,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    verifier = SupabaseTokenVerifier(url="https://project.supabase.co")
    verifier.jwks = SimpleNamespace(
        get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=private_key.public_key())
    )
    principal = verifier.verify(token)
    assert principal.provider_id == "auth-user-id"
    assert principal.email == "buyer@example.test"


def test_storage_adapters_keep_service_key_out_of_object_uri(tmp_path: Path) -> None:
    local = LocalObjectStorage(tmp_path)
    uri = local.put_json("raw/lots/one.json", {"price": 100})
    assert Path(uri).read_text() == '{"price": 100}'
    with pytest.raises(ValueError, match="escapes"):
        local.put_json("../secret.json", {})

    session = FakeSession([FakeResponse({"Key": "raw/lots/one.json"})])
    remote = SupabaseObjectStorage(
        url="https://project.supabase.co",
        service_role_key="server-secret",
        bucket="raw-scrapes",
        session=session,
    )
    remote_uri = remote.put_json("raw/lots/one.json", {"price": 100})
    assert remote_uri == "supabase://raw-scrapes/raw/lots/one.json"
    assert "server-secret" not in remote_uri
    assert session.calls[0][2]["headers"]["Authorization"] == "Bearer server-secret"

    current_session = FakeSession([FakeResponse({"Key": "raw/lots/two.json"})])
    current = SupabaseObjectStorage(
        url="https://project.supabase.co",
        service_role_key="sb_secret_current",
        bucket="raw-scrapes",
        session=current_session,
    )
    current.put_json("raw/lots/two.json", {})
    assert "Authorization" not in current_session.calls[0][2]["headers"]


def test_provider_configuration_and_postgres_url_portability(monkeypatch) -> None:
    assert configure_auth(Settings())[0] is None
    provider, verifier = configure_auth(
        Settings(
            supabase_url="https://project.supabase.co",
            supabase_anon_key="public-anon-key",
        )
    )
    assert isinstance(provider, SupabaseAuthProvider)
    assert isinstance(verifier, SupabaseTokenVerifier)
    assert normalize_database_url("postgres://user:pass@host/db") == (
        "postgresql+psycopg://user:pass@host/db"
    )
    with pytest.raises(ValueError, match="HTTPS"):
        validate_supabase_url("http://project.supabase.co")
    with pytest.raises(ValueError, match="HTTPS"):
        validate_supabase_url("ftp://localhost")
    with pytest.raises(ValueError, match="RAW_SNAPSHOT_BUCKET"):
        configure_storage(Settings(object_storage_provider="s3"))
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_current")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_current")
    current_settings = Settings()
    assert current_settings.supabase_anon_key == "sb_publishable_current"
    assert current_settings.supabase_service_role_key == "sb_secret_current"


def test_supabase_rls_covers_every_application_table() -> None:
    policy = Path("infrastructure/supabase/rls.sql").read_text()
    for table_name in Base.metadata.tables:
        assert f"alter table public.{table_name} enable row level security;" in policy
    assert "from anon, authenticated" in policy
    assert "service_role" not in policy


def test_beta_deployment_keeps_server_secrets_out_of_web_configuration() -> None:
    render = Path("render.yaml").read_text()
    workflow = Path(".github/workflows/scheduled-scrape.yml").read_text()
    validation = Path(".github/workflows/ci.yml").read_text()
    assert "SUPABASE_SECRET_KEY" not in render
    assert "autoDeployTrigger: checksPass" in render
    assert "secrets.SUPABASE_SECRET_KEY" in workflow
    assert "DB_USE_NULL_POOL: 'true'" in workflow
    assert "optional_location: true" in workflow
    assert "Skip Hyperpure without a verified location" in workflow
    assert "Skipping Hyperpure: no verified Hyperpure supplier location is configured." in workflow
    assert "matrix.optional_location && env.SUPPLIER_LOCATION_ID == ''" in workflow
    assert "bigbasket" not in workflow
    assert "deliverit" not in workflow
    assert "image: postgres:16-alpine" in validation
    assert "branches: [main]" not in validation
    assert "python -m alembic upgrade head" in validation
    assert "python scripts/audit_repository.py" in validation
    assert "docker build" in validation


def test_procurement_domain_has_no_cloud_provider_imports() -> None:
    domain_files = [
        "models.py",
        "services.py",
        "matching.py",
        "normalization.py",
        "procurement.py",
        "scraping/service.py",
    ]
    for relative in domain_files:
        source = (Path("procurement_assistant") / relative).read_text()
        assert "boto3" not in source
        assert "supabase" not in source.casefold()
