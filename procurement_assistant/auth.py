from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

import boto3
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from procurement_assistant.models import (
    RestaurantLocation,
    RestaurantMembership,
    User,
)
from procurement_assistant.settings import Settings


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


class IdentityProvider(Protocol):
    def signup(self, email: str, password: str) -> dict: ...

    def confirm_signup(self, email: str, code: str) -> dict: ...

    def login(self, email: str, password: str) -> dict: ...

    def forgot_password(self, email: str) -> dict: ...

    def confirm_forgot_password(self, email: str, code: str, password: str) -> dict: ...

    def refresh(self, refresh_token: str) -> dict: ...

    def logout(self, access_token: str) -> None: ...


class CognitoIdentityProvider:
    def __init__(self, *, region: str, app_client_id: str):
        self.app_client_id = app_client_id
        self.client = boto3.client("cognito-idp", region_name=region)

    def signup(self, email: str, password: str) -> dict:
        return self.client.sign_up(
            ClientId=self.app_client_id,
            Username=email,
            Password=password,
            UserAttributes=[{"Name": "email", "Value": email}],
        )

    def confirm_signup(self, email: str, code: str) -> dict:
        return self.client.confirm_sign_up(
            ClientId=self.app_client_id, Username=email, ConfirmationCode=code
        )

    def login(self, email: str, password: str) -> dict:
        response = self.client.initiate_auth(
            ClientId=self.app_client_id,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": email, "PASSWORD": password},
        )
        return response.get("AuthenticationResult", {})

    def forgot_password(self, email: str) -> dict:
        return self.client.forgot_password(ClientId=self.app_client_id, Username=email)

    def confirm_forgot_password(self, email: str, code: str, password: str) -> dict:
        return self.client.confirm_forgot_password(
            ClientId=self.app_client_id,
            Username=email,
            ConfirmationCode=code,
            Password=password,
        )

    def refresh(self, refresh_token: str) -> dict:
        response = self.client.initiate_auth(
            ClientId=self.app_client_id,
            AuthFlow="REFRESH_TOKEN_AUTH",
            AuthParameters={"REFRESH_TOKEN": refresh_token},
        )
        return response.get("AuthenticationResult", {})

    def logout(self, access_token: str) -> None:
        self.client.global_sign_out(AccessToken=access_token)


class CognitoTokenVerifier:
    def __init__(self, *, region: str, user_pool_id: str, app_client_id: str):
        self.app_client_id = app_client_id
        self.issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self.jwks = PyJWKClient(f"{self.issuer}/.well-known/jwks.json", cache_jwk_set=True)

    def verify(self, token: str) -> AuthPrincipal:
        try:
            key = self.jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                issuer=self.issuer,
                options={"verify_aud": False, "require": ["exp", "sub", "token_use"]},
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid authentication token") from exc
        client = claims.get("client_id") or claims.get("aud")
        if client != self.app_client_id or claims.get("token_use") not in {"access", "id"}:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid authentication token")
        return AuthPrincipal(provider_id=claims["sub"], email=claims.get("email"))


bearer = HTTPBearer(auto_error=False)


def get_identity_provider(request: Request) -> IdentityProvider:
    provider = getattr(request.app.state, "identity_provider", None)
    if provider is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Authentication is not configured")
    return provider


def get_token_verifier(request: Request):
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
    verifier=Depends(get_token_verifier),
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


def configure_cognito(settings: Settings):
    if not settings.cognito_user_pool_id or not settings.cognito_app_client_id:
        return None, None
    return (
        CognitoIdentityProvider(
            region=settings.aws_region, app_client_id=settings.cognito_app_client_id
        ),
        CognitoTokenVerifier(
            region=settings.aws_region,
            user_pool_id=settings.cognito_user_pool_id,
            app_client_id=settings.cognito_app_client_id,
        ),
    )
