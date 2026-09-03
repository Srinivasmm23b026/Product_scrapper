from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from procurement_assistant.models import RestaurantLocation, RestaurantMembership, User
from procurement_assistant.providers.auth import AuthProvider, TokenVerifier
from procurement_assistant.settings import Settings

# Compatibility name retained for existing extensions and tests.
IdentityProvider = AuthProvider


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    provider_id: str
    email: str | None


@dataclass(frozen=True, slots=True)
class TenantContext:
    user_id: uuid.UUID
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID
    role: str


def invalid_token() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid authentication token")


bearer = HTTPBearer(auto_error=False)


def get_identity_provider(request: Request) -> AuthProvider:
    provider = getattr(request.app.state, "identity_provider", None)
    if provider is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Authentication is not configured")
    return provider


def get_token_verifier(request: Request) -> TokenVerifier:
    verifier = getattr(request.app.state, "token_verifier", None)
    if verifier is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Authentication is not configured")
    return verifier


def get_session(request: Request):
    factory = request.app.state.session_factory
    with factory() as session:
        yield session


def get_current_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    verifier: TokenVerifier = Depends(get_token_verifier),
) -> AuthPrincipal:
    token = credentials.credentials if credentials else request.cookies.get("access_token")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    return verifier.verify(token)


def get_tenant_context(
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> TenantContext:
    row = session.execute(
        select(User, RestaurantMembership, RestaurantLocation)
        .join(RestaurantMembership, RestaurantMembership.user_id == User.id)
        .join(
            RestaurantLocation,
            RestaurantLocation.restaurant_id == RestaurantMembership.restaurant_id,
        )
        .where(
            User.auth_provider_id == principal.provider_id,
            RestaurantLocation.is_beta_default.is_(True),
        )
        .order_by(RestaurantLocation.created_at)
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Restaurant onboarding is required")
    user, membership, location = row
    return TenantContext(user.id, membership.restaurant_id, location.id, membership.role)


def configure_auth(settings: Settings) -> tuple[AuthProvider | None, TokenVerifier | None]:
    if settings.auth_provider == "supabase":
        if not settings.supabase_url or not settings.supabase_anon_key:
            return None, None
        from procurement_assistant.providers.auth.supabase import (
            SupabaseAuthProvider,
            SupabaseTokenVerifier,
        )

        return (
            SupabaseAuthProvider(
                url=settings.supabase_url,
                anon_key=settings.supabase_anon_key,
                redirect_url=settings.auth_redirect_url,
                timeout_seconds=settings.provider_timeout_seconds,
            ),
            SupabaseTokenVerifier(
                url=settings.supabase_url, audience=settings.supabase_jwt_audience
            ),
        )
    if not settings.cognito_user_pool_id or not settings.cognito_app_client_id:
        return None, None
    from procurement_assistant.providers.auth.cognito import (
        CognitoAuthProvider,
        CognitoTokenVerifier,
    )

    return (
        CognitoAuthProvider(
            region=settings.aws_region, app_client_id=settings.cognito_app_client_id
        ),
        CognitoTokenVerifier(
            region=settings.aws_region,
            user_pool_id=settings.cognito_user_pool_id,
            app_client_id=settings.cognito_app_client_id,
        ),
    )


configure_cognito = configure_auth
