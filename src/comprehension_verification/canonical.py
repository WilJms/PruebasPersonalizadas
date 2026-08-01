"""Deterministic serialization, hashing, IDs and time for offline replay."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=False)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("naive datetime is not canonical")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        to_jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def pretty_json(value: Any) -> str:
    return (
        json.dumps(
            to_jsonable(value),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )


def sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def canonical_hash(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def stable_id(prefix: str, *parts: Any, length: int = 20) -> str:
    """Create a valid opaque canonical ID without embedding personal data."""

    normalized_prefix = "".join(
        character for character in prefix.lower() if character.isalnum() or character == "_"
    ).strip("_")
    if not normalized_prefix or not normalized_prefix[0].isalpha():
        raise ValueError("stable ID prefix must begin with a letter")
    digest = hashlib.sha256(canonical_bytes(parts)).hexdigest()[:length]
    return f"{normalized_prefix}_{digest}"


@dataclass(frozen=True)
class StableClock:
    """Injected UTC clock; golden fixtures never depend on wall-clock time."""

    instant: datetime = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        if self.instant.tzinfo is None or self.instant.utcoffset() is None:
            raise ValueError("StableClock requires a timezone-aware instant")
        return self.instant.astimezone(timezone.utc)

