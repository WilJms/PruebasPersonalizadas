"""Single bridge to the canonical Pydantic contracts under ``specification``.

The downloaded canonical artifact currently includes ``(1)`` in its filename.
This module deliberately loads it in place instead of copying domain models into
the implementation package.  ADR-028 therefore remains true: there is exactly
one manually maintained model definition.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import TypeVar

from pydantic import BaseModel


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_MODELS_PATH = REPOSITORY_ROOT / "specification" / "models_v1.1(1).py"
CANONICAL_SCHEMA_PATH = (
    REPOSITORY_ROOT / "specification" / "contracts.schema_v1.1(1).json"
)
_MODULE_NAME = "comprehension_verification._canonical_models_v1_1"


def _load_models() -> ModuleType:
    if not CANONICAL_MODELS_PATH.is_file():
        raise RuntimeError(f"Canonical model artifact is missing: {CANONICAL_MODELS_PATH}")
    existing = sys.modules.get(_MODULE_NAME)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, CANONICAL_MODELS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load canonical models: {CANONICAL_MODELS_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


models = _load_models()
SCHEMA_VERSION: str = models.SCHEMA_VERSION
CONTRACT_MODELS: tuple[type[BaseModel], ...] = models.CONTRACT_MODELS
CONTRACT_BY_NAME: dict[str, type[BaseModel]] = {
    model.__name__: model for model in CONTRACT_MODELS
}

ModelT = TypeVar("ModelT", bound=BaseModel)


def model_by_name(name: str) -> type[BaseModel]:
    """Resolve only exported canonical roots."""

    try:
        return CONTRACT_BY_NAME[name]
    except KeyError as exc:
        raise ValueError(f"Unknown canonical contract root: {name}") from exc


def embedded_model_by_name(name: str) -> type[BaseModel]:
    """Resolve a canonical root or embedded model for documented fixtures."""

    candidate = getattr(models, name, None)
    if not isinstance(candidate, type) or not issubclass(candidate, BaseModel):
        raise ValueError(f"Unknown canonical model: {name}")
    return candidate

