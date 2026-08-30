from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from fastapi import Depends, Header
from jwt import PyJWKClient

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.db.store import Store, get_store

_jwks_client: PyJWKClient | None = None
_jwks_url: str = ""


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str | None
    full_name: str | None
    claims: dict[str, Any]


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    email: str | None
    full_name: str | None
    organization_id: str | None
    role: str | None


def _jwks(settings: Settings) -> PyJWKClient:
    global _jwks_client, _jwks_url
    url = settings.jwks_url
    if _jwks_client is None or _jwks_url != url:
        _jwks_client = PyJWKClient(url, cache_jwk_set=True, lifespan=3600)
        _jwks_url = url
    return _jwks_client


def decode_access_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    """Verify a Supabase access token (HS256 secret or JWKS)."""
    settings = settings or get_settings()
    if not token:
        raise ApiError(401, "Not signed in.", "unauthorized")

    unverified = jwt.get_unverified_header(token)
    alg = unverified.get("alg", "HS256")

    try:
        if alg == "HS256":
            secret = settings.supabase_jwt_secret
            if not secret:
                raise ApiError(401, "Session expired.", "unauthorized")
            return jwt.decode(
                token,
                secret,
                algorithms=["HS256"],
                audience="authenticated",
                options={"require": ["sub", "exp"]},
            )
        signing_key = _jwks(settings).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=[alg],
            audience="authenticated",
            options={"require": ["sub", "exp"]},
        )
    except ApiError:
        raise
    except jwt.ExpiredSignatureError as e:
        raise ApiError(401, "Session expired.", "unauthorized") from e
    except jwt.InvalidTokenError as e:
        raise ApiError(401, "Session expired.", "unauthorized") from e
    except httpx.HTTPError as e:
        raise ApiError(401, "Session expired.", "unauthorized") from e


def principal_from_claims(claims: dict[str, Any]) -> Principal:
    user_id = claims.get("sub")
    if not user_id or not isinstance(user_id, str):
        raise ApiError(401, "Not signed in.", "unauthorized")
    meta = claims.get("user_metadata") if isinstance(claims.get("user_metadata"), dict) else {}
    full_name = (
        meta.get("full_name")
        or meta.get("name")
        or claims.get("name")
        or None
    )
    email = claims.get("email") or meta.get("email")
    return Principal(
        user_id=user_id,
        email=email if isinstance(email, str) else None,
        full_name=full_name if isinstance(full_name, str) else None,
        claims=claims,
    )


def _bearer(authorization: str | None) -> str:
    if not authorization:
        raise ApiError(401, "Not signed in.", "unauthorized")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(401, "Not signed in.", "unauthorized")
    return token


async def get_principal(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> Principal:
    return principal_from_claims(decode_access_token(_bearer(authorization), settings))


async def get_current_user_no_org(
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> CurrentUser:
    """Identity only. Used by /auth/me so a first-run user can be provisioned."""
    profile = await store.upsert_profile(principal.user_id, principal.email, principal.full_name)
    org_id, role = await store.default_membership(principal.user_id)
    return CurrentUser(
        user_id=principal.user_id,
        email=profile.get("email") or principal.email,
        full_name=profile.get("full_name") or principal.full_name,
        organization_id=org_id,
        role=role,
    )


async def get_current_user(
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
    x_organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
) -> CurrentUser:
    """Full gate: verified JWT plus an active org membership."""
    await store.upsert_profile(principal.user_id, principal.email, principal.full_name)
    org_id, role = await store.resolve_membership(principal.user_id, x_organization_id)
    if not org_id:
        # First legal-tool call before /auth/me ran: provision then retry.
        await store.ensure_personal_org(principal.user_id, principal.full_name, principal.email)
        org_id, role = await store.resolve_membership(principal.user_id, x_organization_id)
    if not org_id:
        raise ApiError(401, "No organization membership.", "unauthorized")
    return CurrentUser(
        user_id=principal.user_id,
        email=principal.email,
        full_name=principal.full_name,
        organization_id=org_id,
        role=role,
    )


# Keep a clock hook so tests can freeze expiry without patching jwt internals.
def now() -> int:
    return int(time.time())
