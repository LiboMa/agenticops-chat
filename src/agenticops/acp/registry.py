"""Pluggable backend registry. Adding a backend = register_backend(name, cls)."""
from __future__ import annotations

from typing import Type

from agenticops.acp.types import EnhancedBackend

_BACKENDS: dict[str, Type[EnhancedBackend]] = {}


def register_backend(name: str, cls: Type[EnhancedBackend]) -> None:
    _BACKENDS[name] = cls


def available_backends() -> list[str]:
    return sorted(_BACKENDS)


def get_backend(name: str) -> EnhancedBackend:
    if name not in _BACKENDS:
        raise KeyError(f"Unknown enhanced backend: {name!r}. Available: {available_backends()}")
    return _BACKENDS[name]()
