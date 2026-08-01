"""Local development artifact storage and idempotent stage cache for E0 only."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generic, TypeVar

from pydantic import BaseModel

from .canonical import canonical_hash, pretty_json


T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class CachedResult(Generic[T]):
    value: T
    stage_key: str
    reused: bool


class LocalArtifactStore:
    """Filesystem adapter for fixtures and replay, never an operational DB."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.cache_root = self.root / ".stage_cache"
        self.cache_root.mkdir(parents=True, exist_ok=True)

    def _path(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("artifact path escapes the local store")
        return candidate

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temporary, path)

    def write_json(self, relative: str, value: object) -> Path:
        path = self._path(relative)
        self._atomic_write(path, pretty_json(value))
        return path

    def stage_key(
        self,
        stage_name: str,
        inputs: object,
        *,
        policy_hash: str,
        component_version: str,
    ) -> str:
        return canonical_hash(
            {
                "stage_name": stage_name,
                "inputs": inputs,
                "policy_hash": policy_hash,
                "component_version": component_version,
            }
        )

    def run_cached(
        self,
        *,
        stage_name: str,
        inputs: object,
        policy_hash: str,
        component_version: str,
        output_model: type[T],
        producer: Callable[[], T],
    ) -> CachedResult[T]:
        key = self.stage_key(
            stage_name,
            inputs,
            policy_hash=policy_hash,
            component_version=component_version,
        )
        path = self.cache_root / f"{key.removeprefix('sha256:')}.json"
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("stage_key") != key or raw.get("output_model") != output_model.__name__:
                raise ValueError("stage cache metadata mismatch")
            value = output_model.model_validate(raw["output"])
            return CachedResult(value=value, stage_key=key, reused=True)
        value = producer()
        if not isinstance(value, output_model):
            raise TypeError(f"stage {stage_name} returned {type(value).__name__}")
        payload = {
            "stage_key": key,
            "stage_name": stage_name,
            "component_version": component_version,
            "policy_hash": policy_hash,
            "output_model": output_model.__name__,
            "output": value,
        }
        self._atomic_write(path, pretty_json(payload))
        return CachedResult(value=value, stage_key=key, reused=False)

