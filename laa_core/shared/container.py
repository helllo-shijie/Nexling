"""Explicit dependency injection container (constructor injection)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from .errors import err


class ServiceContainer:
    def __init__(self) -> None:
        self._registry: Dict[Any, Any] = {}
        self._started = False

    def register(self, token: Any, impl: Any, *, lazy: bool = False) -> None:
        # lazy is accepted for API compatibility; singletons are constructed eagerly by caller.
        self._registry[token] = impl

    def resolve(self, token: Any) -> Any:
        if token not in self._registry:
            raise err("LAA-2001", message=f"service not registered: {token}")
        return self._registry[token]

    def has(self, token: Any) -> bool:
        return token in self._registry

    def startup(self) -> None:
        self._started = True

    def shutdown(self, timeout_s: float = 10.0) -> None:
        self._started = False

    @property
    def started(self) -> bool:
        return self._started