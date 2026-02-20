import base64
import json
import logging
import os
from functools import lru_cache
from typing import Any

import jwt


LOGGER = logging.getLogger(__name__)
_AAD_OBJECT_ID_CLAIM = "http://schemas.microsoft.com/identity/claims/objectidentifier"
_AAD_TENANT_ID_CLAIM = "http://schemas.microsoft.com/identity/claims/tenantid"


def is_easyauth_enabled() -> bool:
    value = os.getenv("EASYAUTH_ENABLED", "").strip().lower()
    if value in {"1", "true", "yes"}:
        return True
    if value in {"0", "false", "no"}:
        return False
    return False


def _is_truthy_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _normalize_headers(request_headers) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in (request_headers or {}).items()}


def _extract_bearer_token(headers: dict[str, str]) -> str | None:
    raw = headers.get("authorization", "").strip()
    if not raw:
        return None
    prefix = "bearer "
    if raw.lower().startswith(prefix):
        token = raw[len(prefix) :].strip()
        return token or None
    return None


def _allowed_audiences() -> list[str]:
    values: list[str] = []
    raw = os.getenv("AAD_ALLOWED_AUDIENCES", "").strip()
    if raw:
        values.extend([item.strip() for item in raw.split(",") if item.strip()])
    for env_name in ("AAD_FRONTEND_CLIENT_ID", "AAD_BACKEND_CLIENT_ID", "AZURE_CLIENT_ID"):
        value = os.getenv(env_name, "").strip()
        if value:
            values.append(value)
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _tenant_id_hint() -> str | None:
    for env_name in ("AAD_TENANT_ID", "AZURE_TENANT_ID"):
        value = os.getenv(env_name, "").strip()
        if value:
            return value
    return None


def _token_validation_required() -> bool:
    if _is_truthy_env("AAD_TOKEN_VALIDATION_ENABLED", default=False):
        return True
    # In production with EasyAuth enabled, default to strict token validation.
    return is_easyauth_enabled()


def _token_issuers(tenant_id: str | None) -> list[str]:
    configured = os.getenv("AAD_ALLOWED_ISSUERS", "").strip()
    if configured:
        return [item.strip() for item in configured.split(",") if item.strip()]
    if not tenant_id:
        return []
    return [
        f"https://login.microsoftonline.com/{tenant_id}/v2.0",
        f"https://sts.windows.net/{tenant_id}/",
    ]


@lru_cache(maxsize=8)
def _jwks_client_for_tenant(tenant_id: str):
    jwks_url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
    return jwt.PyJWKClient(jwks_url)


def _decode_unverified(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_aud": False,
                "verify_iss": False,
            },
            algorithms=["RS256", "RS384", "RS512"],
        )
        if isinstance(payload, dict):
            return payload
    except Exception:
        return {}
    return {}


def _validate_bearer_token(token: str) -> dict[str, Any] | None:
    unverified = _decode_unverified(token)
    tenant_id = str(unverified.get("tid") or _tenant_id_hint() or "").strip()
    if not tenant_id:
        LOGGER.warning("Token validation skipped: tenant id unavailable.")
        return None

    try:
        jwk_client = _jwks_client_for_tenant(tenant_id)
        signing_key = jwk_client.get_signing_key_from_jwt(token)
    except Exception:
        LOGGER.exception("Failed to resolve Entra signing key.")
        return None

    audiences = _allowed_audiences()
    issuers = _token_issuers(tenant_id)
    options = {
        "verify_signature": True,
        "verify_exp": True,
        "verify_aud": bool(audiences),
        "verify_iss": bool(issuers),
    }

    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audiences if audiences else None,
            issuer=tuple(issuers) if issuers else None,
            options=options,
        )
    except Exception:
        LOGGER.exception("Failed to validate Entra bearer token.")
        return None

    if not isinstance(claims, dict):
        return None
    return claims


def _claims_from_client_principal(client_principal_b64: str) -> dict[str, Any]:
    if not client_principal_b64:
        return {}
    try:
        decoded_bytes = base64.b64decode(client_principal_b64)
        decoded_string = decoded_bytes.decode("utf-8")
        payload = json.loads(decoded_string)
        if isinstance(payload, dict):
            return payload
    except Exception:
        LOGGER.exception("Failed to decode x-ms-client-principal header.")
    return {}


def _claims_list_to_map(principal_payload: dict[str, Any]) -> dict[str, str]:
    claims_map: dict[str, str] = {}
    for item in principal_payload.get("claims", []) or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("typ") or "").strip()
        value = str(item.get("val") or "").strip()
        if key and value and key not in claims_map:
            claims_map[key] = value
    return claims_map


def _user_id_from_claims(claims: dict[str, Any]) -> str | None:
    for key in ("oid", _AAD_OBJECT_ID_CLAIM, "sub"):
        value = str(claims.get(key) or "").strip()
        if value:
            return value
    return None


def _user_name_from_claims(claims: dict[str, Any]) -> str | None:
    for key in ("name", "preferred_username", "upn", "email"):
        value = str(claims.get(key) or "").strip()
        if value:
            return value
    return None


def _tenant_id_from_claims(claims: dict[str, Any]) -> str | None:
    for key in ("tid", _AAD_TENANT_ID_CLAIM):
        value = str(claims.get(key) or "").strip()
        if value:
            return value
    return None


def _user_from_bearer_token(headers: dict[str, str]) -> dict[str, Any] | None:
    token = _extract_bearer_token(headers)
    if not token:
        return None

    validated_claims = _validate_bearer_token(token)
    if validated_claims is None:
        if _token_validation_required():
            return {}
        validated_claims = _decode_unverified(token)

    user_id = _user_id_from_claims(validated_claims)
    if not user_id:
        return {}

    return {
        "user_principal_id": user_id,
        "user_name": _user_name_from_claims(validated_claims),
        "auth_provider": "aad_bearer_token",
        "auth_token": token,
        "client_principal_b64": headers.get("x-ms-client-principal"),
        "aad_id_token": headers.get("x-ms-token-aad-id-token") or token,
        "tenant_id": _tenant_id_from_claims(validated_claims),
        "claims": validated_claims,
    }


def _user_from_client_principal(headers: dict[str, str]) -> dict[str, Any] | None:
    principal_b64 = headers.get("x-ms-client-principal", "")
    if not principal_b64:
        user_id = str(headers.get("x-ms-client-principal-id") or "").strip()
        if not user_id:
            return None
        if not _is_truthy_env("ALLOW_UNVERIFIED_IDENTITY_HEADERS", default=False):
            # Reject header-only identity to prevent caller spoofing.
            # In production, rely on validated bearer tokens or x-ms-client-principal payload.
            return {}
        return {
            "user_principal_id": user_id,
            "user_name": str(headers.get("x-ms-client-principal-name") or "").strip() or None,
            "auth_provider": str(headers.get("x-ms-client-principal-idp") or "").strip() or "easyauth",
            "auth_token": headers.get("x-ms-token-aad-id-token"),
            "client_principal_b64": None,
            "aad_id_token": headers.get("x-ms-token-aad-id-token"),
            "tenant_id": None,
            "claims": {},
        }
    principal_payload = _claims_from_client_principal(principal_b64)
    claims = _claims_list_to_map(principal_payload)

    user_id = (
        str(principal_payload.get("user_id") or "").strip()
        or str(headers.get("x-ms-client-principal-id") or "").strip()
        or _user_id_from_claims(claims)
    )
    if not user_id:
        return {}

    user_name = (
        str(principal_payload.get("userDetails") or "").strip()
        or str(headers.get("x-ms-client-principal-name") or "").strip()
        or _user_name_from_claims(claims)
    )
    auth_provider = (
        str(principal_payload.get("auth_typ") or "").strip()
        or str(headers.get("x-ms-client-principal-idp") or "").strip()
        or "easyauth"
    )
    tenant_id = _tenant_id_from_claims(claims)

    return {
        "user_principal_id": user_id,
        "user_name": user_name or None,
        "auth_provider": auth_provider,
        "auth_token": headers.get("x-ms-token-aad-id-token"),
        "client_principal_b64": principal_b64,
        "aad_id_token": headers.get("x-ms-token-aad-id-token"),
        "tenant_id": tenant_id,
        "claims": claims,
    }


def _should_use_sample_user(request_headers) -> bool:
    normalized = _normalize_headers(request_headers)
    if normalized.get("x-ms-client-principal-id"):
        return False
    if normalized.get("x-ms-client-principal"):
        return False
    if _extract_bearer_token(normalized):
        return False
    return _allow_sample_user_fallback()


def _allow_sample_user_fallback() -> bool:
    configured = os.getenv("ALLOW_SAMPLE_USER_FALLBACK", "").strip().lower()
    if configured in {"1", "true", "yes", "on"}:
        return True
    if configured in {"0", "false", "no", "off"}:
        return False
    return os.getenv("APP_ENV", "").strip().lower() == "dev"


def get_authenticated_user_details(request_headers):
    user_object: dict[str, Any] = {}
    normalized_headers = _normalize_headers(request_headers)

    token_user = _user_from_bearer_token(normalized_headers)
    if token_user:
        return token_user

    principal_user = _user_from_client_principal(normalized_headers)
    if principal_user:
        return principal_user

    # Optional backward-compat for development only.
    if _should_use_sample_user(normalized_headers):
        logging.info("No authenticated principal found. Using sample user in development mode.")
        from . import sample_user

        normalized_sample = _normalize_headers(sample_user.sample_user)
        return {
            "user_principal_id": normalized_sample.get("x-ms-client-principal-id"),
            "user_name": normalized_sample.get("x-ms-client-principal-name"),
            "auth_provider": normalized_sample.get("x-ms-client-principal-idp"),
            "auth_token": normalized_sample.get("x-ms-token-aad-id-token"),
            "client_principal_b64": normalized_sample.get("x-ms-client-principal"),
            "aad_id_token": normalized_sample.get("x-ms-token-aad-id-token"),
            "tenant_id": _tenant_id_hint(),
        }

    # Keep the response shape stable for existing callers.
    user_object["user_principal_id"] = None
    user_object["user_name"] = None
    user_object["auth_provider"] = None
    user_object["auth_token"] = None
    user_object["client_principal_b64"] = normalized_headers.get("x-ms-client-principal")
    user_object["aad_id_token"] = normalized_headers.get("x-ms-token-aad-id-token")
    user_object["tenant_id"] = None
    return user_object


def get_tenantid(client_principal_b64):
    tenant_id = ""
    if client_principal_b64:
        try:
            user_info = _claims_from_client_principal(client_principal_b64)
            tenant_id = str(user_info.get("tid") or "").strip()
        except Exception as ex:
            LOGGER.exception(ex)
    return tenant_id
