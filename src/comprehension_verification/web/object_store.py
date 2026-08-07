"""Private object-store seam with an R2 adapter and an authenticated fake."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import RLock
from typing import Protocol

import boto3
from botocore.exceptions import ClientError
import jwt

from .settings import Settings, WorkerSettings


@dataclass(frozen=True, slots=True)
class SignedObjectUrl:
    url: str
    expires_at: datetime
    headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    key: str
    byte_size: int
    content_type: str


class ObjectSizeExceeded(ValueError):
    """Raised before an object-store adapter can materialize oversized bytes."""


class ObjectStore(Protocol):
    def sign_put(
        self, key: str, content_type: str, expected_byte_size: int | None = None
    ) -> SignedObjectUrl: ...
    def sign_get(self, key: str) -> SignedObjectUrl: ...
    def get_bytes(self, key: str, *, max_bytes: int) -> bytes: ...
    def head(self, key: str) -> ObjectMetadata: ...
    def put_immutable(self, key: str, data: bytes, content_type: str) -> None: ...


class MemoryObjectStore:
    """Process-local fake used only for tests/development, never cloud mode."""

    def __init__(
        self,
        *,
        secret: str,
        upload_ttl_seconds: int = 900,
        download_ttl_seconds: int = 300,
    ) -> None:
        self.secret = secret
        self.upload_ttl_seconds = upload_ttl_seconds
        self.download_ttl_seconds = download_ttl_seconds
        self._objects: dict[str, tuple[bytes, str]] = {}
        self._lock = RLock()

    def _token(
        self,
        key: str,
        method: str,
        ttl_seconds: int,
        content_type: str | None = None,
        expected_byte_size: int | None = None,
    ) -> str:
        now = datetime.now(UTC)
        payload = {
            "iss": "cva-object-fake",
            "aud": "cva-object-fake",
            "key": key,
            "method": method,
            "content_type": content_type,
            "expected_byte_size": expected_byte_size,
            "iat": now,
            "exp": now + timedelta(seconds=ttl_seconds),
        }
        return jwt.encode(payload, self.secret, algorithm="HS256")

    def _decode(self, token: str, method: str) -> dict[str, object]:
        claims = jwt.decode(
            token,
            self.secret,
            algorithms=["HS256"],
            issuer="cva-object-fake",
            audience="cva-object-fake",
            options={"require": ["exp", "key", "method"]},
        )
        if claims["method"] != method:
            raise PermissionError("signed object method mismatch")
        return claims

    def sign_put(
        self, key: str, content_type: str, expected_byte_size: int | None = None
    ) -> SignedObjectUrl:
        expires = datetime.now(UTC) + timedelta(seconds=self.upload_ttl_seconds)
        token = self._token(
            key,
            "PUT",
            self.upload_ttl_seconds,
            content_type,
            expected_byte_size,
        )
        headers = {"Content-Type": content_type}
        return SignedObjectUrl(
            url=f"/api/v1/object-uploads/{token}",
            expires_at=expires,
            headers=headers,
        )

    def sign_get(self, key: str) -> SignedObjectUrl:
        expires = datetime.now(UTC) + timedelta(seconds=self.download_ttl_seconds)
        token = self._token(key, "GET", self.download_ttl_seconds)
        return SignedObjectUrl(
            url=f"/api/v1/objects/{token}",
            expires_at=expires,
            headers={},
        )

    def put_signed(self, token: str, data: bytes, content_type: str) -> None:
        claims = self._decode(token, "PUT")
        if claims.get("content_type") != content_type:
            raise PermissionError("signed content type mismatch")
        expected_byte_size = claims.get("expected_byte_size")
        if expected_byte_size is not None and len(data) != int(expected_byte_size):
            raise ObjectSizeExceeded("signed object size mismatch")
        with self._lock:
            self._objects[str(claims["key"])] = (bytes(data), content_type)

    def get_signed(self, token: str) -> tuple[bytes, str]:
        claims = self._decode(token, "GET")
        with self._lock:
            return self._objects[str(claims["key"])]

    def get_bytes(self, key: str, *, max_bytes: int) -> bytes:
        with self._lock:
            data = self._objects[key][0]
        if len(data) > max_bytes:
            raise ObjectSizeExceeded("object exceeds bounded read")
        return data

    def head(self, key: str) -> ObjectMetadata:
        with self._lock:
            data, content_type = self._objects[key]
        return ObjectMetadata(key=key, byte_size=len(data), content_type=content_type)

    def put_immutable(self, key: str, data: bytes, content_type: str) -> None:
        value = (bytes(data), content_type)
        with self._lock:
            existing = self._objects.get(key)
            if existing is not None and existing != value:
                raise PermissionError("immutable object already exists with different bytes")
            self._objects[key] = value


class R2ObjectStore:
    """Cloudflare R2 private S3-compatible adapter.

    URLs are returned to the caller but never persisted or logged. Completion
    always downloads and hashes bytes in the workflow; browser metadata is not
    trusted as a content checksum.
    """

    def __init__(self, settings: Settings | WorkerSettings) -> None:
        assert settings.r2_endpoint_url and settings.r2_bucket
        self.bucket = settings.r2_bucket
        self.upload_ttl_seconds = settings.upload_url_ttl_seconds
        self.download_ttl_seconds = settings.download_url_ttl_seconds
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint_url,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
            config=__import__("botocore.config", fromlist=["Config"]).Config(
                signature_version="s3v4"
            ),
        )

    def sign_put(
        self, key: str, content_type: str, expected_byte_size: int | None = None
    ) -> SignedObjectUrl:
        params: dict[str, object] = {
            "Bucket": self.bucket,
            "Key": key,
            "ContentType": content_type,
        }
        headers = {"Content-Type": content_type}
        if expected_byte_size is not None:
            params["ContentLength"] = expected_byte_size
        url = self.client.generate_presigned_url(
            "put_object",
            Params=params,
            ExpiresIn=self.upload_ttl_seconds,
        )
        return SignedObjectUrl(
            url=url,
            expires_at=datetime.now(UTC)
            + timedelta(seconds=self.upload_ttl_seconds),
            headers=headers,
        )

    def sign_get(self, key: str) -> SignedObjectUrl:
        url = self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=self.download_ttl_seconds,
        )
        return SignedObjectUrl(
            url=url,
            expires_at=datetime.now(UTC)
            + timedelta(seconds=self.download_ttl_seconds),
            headers={},
        )

    def get_bytes(self, key: str, *, max_bytes: int) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"]
        try:
            data = body.read(max_bytes + 1)
        finally:
            body.close()
        if len(data) > max_bytes:
            raise ObjectSizeExceeded("object exceeds bounded read")
        return data

    def head(self, key: str) -> ObjectMetadata:
        response = self.client.head_object(Bucket=self.bucket, Key=key)
        return ObjectMetadata(
            key=key,
            byte_size=int(response["ContentLength"]),
            content_type=str(response.get("ContentType") or "application/octet-stream"),
        )

    def put_immutable(self, key: str, data: bytes, content_type: str) -> None:
        digest = sha256(data).digest()
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                ChecksumSHA256=base64.b64encode(digest).decode("ascii"),
                Metadata={"cva-sha256": digest.hex()},
                IfNoneMatch="*",
            )
        except ClientError as exc:
            error = exc.response.get("Error", {})
            if str(error.get("Code")) not in {"PreconditionFailed", "412"}:
                raise
            metadata = self.head(key)
            if metadata.content_type != content_type or metadata.byte_size != len(data):
                raise PermissionError(
                    "immutable object already exists with different metadata"
                ) from exc
            if self.get_bytes(key, max_bytes=len(data)) != data:
                raise PermissionError(
                    "immutable object already exists with different bytes"
                ) from exc
