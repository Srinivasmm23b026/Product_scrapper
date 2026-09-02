from __future__ import annotations

import boto3
import jwt
from botocore.exceptions import BotoCoreError, ClientError
from jwt import PyJWKClient

from procurement_assistant.providers.auth.base import AuthProviderError, AuthTokens, SignupResult


def _error_code(exc: Exception) -> str:
    return getattr(exc, "response", {}).get("Error", {}).get("Code", "IdentityProviderError")


class CognitoAuthProvider:
    def __init__(self, *, region: str, app_client_id: str):
        self.app_client_id = app_client_id
        self.client = boto3.client("cognito-idp", region_name=region)

    def _call(self, callback):
        try:
            return callback()
        except (BotoCoreError, ClientError) as exc:
            raise AuthProviderError(_error_code(exc)) from exc

    def signup(self, email: str, password: str) -> SignupResult:
        response = self._call(
            lambda: self.client.sign_up(
                ClientId=self.app_client_id,
                Username=email,
                Password=password,
                UserAttributes=[{"Name": "email", "Value": email}],
            )
        )
        return SignupResult(
            user_confirmed=response.get("UserConfirmed", False),
            delivery=response.get("CodeDeliveryDetails"),
        )

    def confirm_signup(self, email: str, code: str) -> None:
        self._call(
            lambda: self.client.confirm_sign_up(
                ClientId=self.app_client_id, Username=email, ConfirmationCode=code
            )
        )

    def login(self, email: str, password: str) -> AuthTokens:
        response = self._call(
            lambda: self.client.initiate_auth(
                ClientId=self.app_client_id,
                AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters={"USERNAME": email, "PASSWORD": password},
            )
        ).get("AuthenticationResult", {})
        return self._tokens(response, "AuthenticationFailed")

    def forgot_password(self, email: str) -> None:
        self._call(lambda: self.client.forgot_password(ClientId=self.app_client_id, Username=email))

    def confirm_forgot_password(self, email: str, code: str, password: str) -> None:
        self._call(
            lambda: self.client.confirm_forgot_password(
                ClientId=self.app_client_id,
                Username=email,
                ConfirmationCode=code,
                Password=password,
            )
        )

    def refresh(self, refresh_token: str) -> AuthTokens:
        response = self._call(
            lambda: self.client.initiate_auth(
                ClientId=self.app_client_id,
                AuthFlow="REFRESH_TOKEN_AUTH",
                AuthParameters={"REFRESH_TOKEN": refresh_token},
            )
        ).get("AuthenticationResult", {})
        return self._tokens(response, "RefreshFailed")

    def logout(self, access_token: str) -> None:
        self._call(lambda: self.client.global_sign_out(AccessToken=access_token))

    @staticmethod
    def _tokens(response: dict, error_code: str) -> AuthTokens:
        access_token = response.get("AccessToken")
        if not access_token:
            raise AuthProviderError(error_code, status_code=401)
        return AuthTokens(
            access_token=access_token,
            refresh_token=response.get("RefreshToken"),
            id_token=response.get("IdToken"),
            expires_in=response.get("ExpiresIn"),
            token_type=response.get("TokenType", "Bearer"),
        )


class CognitoTokenVerifier:
    def __init__(self, *, region: str, user_pool_id: str, app_client_id: str):
        self.app_client_id = app_client_id
        self.issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self.jwks = PyJWKClient(f"{self.issuer}/.well-known/jwks.json", cache_jwk_set=True)

    def verify(self, token: str):
        from procurement_assistant.auth import AuthPrincipal, invalid_token

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
            raise invalid_token() from exc
        client = claims.get("client_id") or claims.get("aud")
        if client != self.app_client_id or claims.get("token_use") not in {"access", "id"}:
            raise invalid_token()
        return AuthPrincipal(provider_id=claims["sub"], email=claims.get("email"))
