"""Post-attestation credential resolver for the one-shot synthetic worker."""

from __future__ import annotations

import base64

import google.auth
from google.auth.transport.requests import AuthorizedSession
from pydantic import SecretStr

from ..provider_authorization import validate_pinned_secret_resource


class ProviderCredentialUnavailable(RuntimeError):
    code = "SYNTHETIC_PROVIDER_CREDENTIAL_UNAVAILABLE"


def resolve_openai_api_key(secret_version_resource: str) -> SecretStr:
    """Resolve a pinned secret only after the caller consumed a job grant."""

    resource = validate_pinned_secret_resource(secret_version_resource)
    try:
        credentials, _project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        session = AuthorizedSession(credentials)
        try:
            response = session.get(
                f"https://secretmanager.googleapis.com/v1/{resource}:access",
                timeout=15,
            )
            if response.status_code != 200:
                raise ProviderCredentialUnavailable
            payload = response.json().get("payload", {})
            encoded = payload.get("data")
            if not isinstance(encoded, str):
                raise ProviderCredentialUnavailable
            value = base64.b64decode(encoded, validate=True).decode("utf-8").strip()
            if not value:
                raise ProviderCredentialUnavailable
            return SecretStr(value)
        finally:
            session.close()
    except ProviderCredentialUnavailable:
        raise
    except Exception:
        # Replace every SDK/HTTP/credential detail with one content-free code.
        raise ProviderCredentialUnavailable from None
