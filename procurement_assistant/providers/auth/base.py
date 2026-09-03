from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SignupResult:
    user_confirmed: bool
    delivery: dict | None = None


@dataclass(frozen=True, slots=True)
class AuthTokens:
    access_token: str
    refresh_token: str | None = None
    id_token: str | None = None
    expires_in: int | None = None
    token_type: str = "Bearer"


class AuthProviderError(RuntimeError):
    def __init__(self, code: str, *, status_code: int = 400):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class AuthProvider(Protocol):
    def signup(self, email: str, password: str) -> SignupResult: ...

    def confirm_signup(self, email: str, code: str) -> None: ...

    def login(self, email: str, password: str) -> AuthTokens: ...

    def forgot_password(self, email: str) -> None: ...

    def confirm_forgot_password(self, email: str, code: str, password: str) -> None: ...

    def refresh(self, refresh_token: str) -> AuthTokens: ...

    def logout(self, access_token: str) -> None: ...


class TokenVerifier(Protocol):
    def verify(self, token: str): ...
