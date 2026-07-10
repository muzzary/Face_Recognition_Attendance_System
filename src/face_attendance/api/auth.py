"""Authentication and authorization primitives for the HTTP API.

Password hashing is stdlib-only (PBKDF2-HMAC-SHA256 with a per-password random
salt, stored as ``salt_hex$hash_hex``). Tokens are HS256 JWTs signed with
``FA_JWT_SECRET`` - the secret has no default, so the API refuses to issue or
verify a token until it is configured (``require_jwt_secret``).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel

from face_attendance.api.dependencies import get_settings
from face_attendance.config import AppSettings, SettingsError
from face_attendance.contracts import UserRecord, UserRole
from face_attendance.storage import AttendanceStorage

# PBKDF2 cost. 200k SHA256 iterations is the design-specified work factor.
_PBKDF2_ITERATIONS = 200_000
_SALT_BYTES = 16

_JWT_ALGORITHM = "HS256"
# Tokens are short-lived; a local dev/skeleton session doesn't need long-lived
# credentials, and a shorter window limits the blast radius of a leaked token.
ACCESS_TOKEN_TTL = timedelta(hours=8)

# A well-formed but intentionally-nonmatching hash. When a login email is
# unknown we still run one PBKDF2 verify against this so response timing does
# not reveal whether the email exists (the message is already identical).
_DUMMY_HASH = f"{'00' * _SALT_BYTES}${'00' * 32}"


def hash_password(password: str) -> str:
    """Hash a plaintext password as ``salt_hex$hash_hex`` (PBKDF2-HMAC-SHA256)."""

    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, _PBKDF2_ITERATIONS
    )
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of a plaintext password against a stored hash."""

    try:
        salt_hex, hash_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, _PBKDF2_ITERATIONS
    )
    return hmac.compare_digest(digest, expected)


def authenticate_user(
    storage: AttendanceStorage, email: str, password: str
) -> UserRecord | None:
    """Return the user for valid credentials, else None.

    An unknown email still runs one PBKDF2 verify against a dummy hash so its
    response timing matches a wrong-password attempt - neither the message nor
    the latency reveals which of email/password was wrong.
    """

    user = storage.get_user_by_email(email)
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def require_jwt_secret(settings: AppSettings) -> str:
    """Return the configured JWT secret or fail loudly if it is unset."""

    if not settings.jwt_secret:
        raise SettingsError(
            "FA_JWT_SECRET is not set; the API cannot issue or verify tokens"
        )
    return settings.jwt_secret


class AuthenticatedUser(BaseModel):
    """The identity carried by a verified token, injected into guarded routes."""

    user_id: str
    org_id: str
    role: UserRole
    employee_id: str | None = None


def create_access_token(user: UserRecord, secret: str) -> str:
    """Issue a signed JWT for a user with the standard claim set."""

    now = datetime.now(timezone.utc)
    claims = {
        "sub": user.user_id,
        "org_id": user.org_id,
        "role": user.role.value,
        "employee_id": user.employee_id,
        "exp": now + ACCESS_TOKEN_TTL,
    }
    return jwt.encode(claims, secret, algorithm=_JWT_ALGORITHM)


SettingsDep = Annotated[AppSettings, Depends(get_settings)]


def get_current_user(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedUser:
    """Decode and verify the ``Authorization: Bearer <token>`` header.

    401 on a missing, malformed, invalid, or expired token - never
    distinguishing which, so a caller learns nothing beyond "not authorized".
    """

    unauthorized = HTTPException(
        status_code=401,
        detail="missing or invalid authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if authorization is None or not authorization.startswith("Bearer "):
        raise unauthorized
    token = authorization[len("Bearer ") :]
    secret = require_jwt_secret(settings)
    try:
        payload = jwt.decode(token, secret, algorithms=[_JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise unauthorized from exc

    try:
        return AuthenticatedUser(
            user_id=str(payload["sub"]),
            org_id=str(payload["org_id"]),
            role=UserRole(payload["role"]),
            employee_id=payload.get("employee_id"),
        )
    except (KeyError, ValueError) as exc:
        raise unauthorized from exc


CurrentUserDep = Annotated[AuthenticatedUser, Depends(get_current_user)]


def require_org_match(user: AuthenticatedUser, org_id: str) -> None:
    """403 unless the token's org matches the org in the request path."""

    if user.org_id != org_id:
        raise HTTPException(
            status_code=403, detail="token is not authorized for this organization"
        )
