from __future__ import annotations

from urllib.parse import quote, urlparse

import jwt
import requests
from jwt import PyJWKClient

from procurement_assistant.providers.auth.base import AuthProviderError, AuthTokens, SignupResult


def validate_supabase_url(value: str) -> str:
    url = value.rstrip("/")
    parsed = urlparse(url)
    is_local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
    if parsed.scheme != "https" and not is_local_http:
        raise ValueError("SUPABASE_URL must use HTTPS outside local development")
    if not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("SUPABASE_URL is invalid")
    return url


class SupabaseAuthProvider:
    def __init__(
        self,
        *,
        url: str,
        anon_key: str,
        redirect_url: str | None = None,
        timeout_seconds: int = 15,
        session: requests.Session | None = None,
    ):
        self.url = validate_supabase_url(url)
        self.anon_key = anon_key
        self.redirect_url = redirect_url
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict | None = None,
        access_token: str | None = None,
    ) -> dict:
        headers = {
            "apikey": self.anon_key,
            "Content-Type": "application/json",
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        try:
            response = self.session.request(
                method,
                f"{self.url}/auth/v1{path}",
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise AuthProviderError("IdentityProviderUnavailable", status_code=503) from exc
        if not response.ok:
            try:
                body = response.json()
            except ValueError:
                body = {}
            code = body.get("error_code") or body.get("code") or "AuthenticationFailed"
            if response.status_code in {401, 403}:
                error_status = 401
            elif response.status_code == 429:
                error_status = 429
            elif response.status_code >= 500:
                error_status = 503
            else:
                error_status = 400
            raise AuthProviderError(str(code), status_code=error_status)
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    @staticmethod
    def _tokens(body: dict) -> AuthTokens:
        access_token = body.get("access_token")
        if not access_token:
            raise AuthProviderError("AuthenticationFailed", status_code=401)
        return AuthTokens(
            access_token=access_token,
            refresh_token=body.get("refresh_token"),
            expires_in=body.get("expires_in"),
            token_type=body.get("token_type", "Bearer").title(),
        )

    def signup(self, email: str, password: str) -> SignupResult:
        payload = {"email": email, "password": password}
        path = "/signup"
        if self.redirect_url:
            path = f"{path}?redirect_to={quote(self.redirect_url, safe=':/')}"
        body = self._request("POST", path, payload=payload)
        user = body.get("user") or body
        confirmed = bool(body.get("access_token") or user.get("confirmed_at"))
        return SignupResult(user_confirmed=confirmed, delivery={"provider": "email"})

    def confirm_signup(self, email: str, code: str) -> None:
        self._request(
            "POST", "/verify", payload={"email": email, "token": code, "type": "email"}
        )

    def login(self, email: str, password: str) -> AuthTokens:
        body = self._request(
            "POST",
            "/token?grant_type=password",
            payload={"email": email, "password": password},
        )
        return self._tokens(body)

    def forgot_password(self, email: str) -> None:
        path = "/recover"
        if self.redirect_url:
            path = f"{path}?redirect_to={quote(self.redirect_url, safe=':/')}"
        self._request("POST", path, payload={"email": email})

    def confirm_forgot_password(self, email: str, code: str, password: str) -> None:
        session = self._request(
            "POST",
            "/verify",
            payload={"email": email, "token": code, "type": "recovery"},
        )
        token = self._tokens(session).access_token
        self._request("PUT", "/user", payload={"password": password}, access_token=token)

    def refresh(self, refresh_token: str) -> AuthTokens:
        body = self._request(
            "POST",
            "/token?grant_type=refresh_token",
            payload={"refresh_token": refresh_token},
        )
        return self._tokens(body)

    def logout(self, access_token: str) -> None:
        self._request("POST", "/logout?scope=local", access_token=access_token)


class SupabaseTokenVerifier:
    def __init__(self, *, url: str, audience: str = "authenticated"):
        self.url = validate_supabase_url(url)
        self.issuer = f"{self.url}/auth/v1"
        self.audience = audience
        self.jwks = PyJWKClient(
            f"{self.url}/auth/v1/.well-known/jwks.json", cache_jwk_set=True
        )

    def verify(self, token: str):
        from procurement_assistant.auth import AuthPrincipal, invalid_token

        try:
            key = self.jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256", "ES256"],
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["aud", "exp", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise invalid_token() from exc
        return AuthPrincipal(provider_id=claims["sub"], email=claims.get("email"))
