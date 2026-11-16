"""Ports (abstract contracts) that application/domain code may depend on.

Concrete implementations live in ``laa_core/infra``; nothing here imports infra.
"""
from __future__ import annotations

from typing import Any, Dict, List, Protocol, runtime_checkable

from .shared.dto import PromptPlan


@runtime_checkable
class ProviderPort(Protocol):
    """Model gateway abstraction (§6.15): business code depends on this, never a vendor SDK."""

    provider_id: str
    kind: str

    def translate(self, plan: PromptPlan, segments: list) -> Dict[str, Any]:
        """Return {"segments": [{"segment_id","target_text"}], "emotions": [...]}.

        ``segments`` is a list of ``TextSegment`` (or dicts with id/text) to translate.
        """

    def complete(self, messages: List[Dict[str, str]], *, response_format: str = "json_object", max_tokens: int = 2048) -> Dict[str, Any]:
        """Generic chat completion returning parsed JSON dict plus raw usage."""

    def health(self) -> Dict[str, Any]:
        """Return {"ok": bool, "latency_ms": int, "detail": str}."""

    def capabilities(self) -> Dict[str, Any]:
        """Return {"input": [...], "output": [...], "supports_stream": bool, ...}."""


@runtime_checkable
class ReleaseFeedPort(Protocol):
    """Read-only feed of published (official/community) glossary packages (§6.19.1)."""

    def list_manifests(self) -> List[Dict[str, Any]]:
        """List ReleaseManifest dicts across registered sources."""

    def fetch_package(self, pack_id: str, version: str) -> Dict[str, Any]:
        """Return a package dict {"manifest":..., "files":..., "namespace":...}."""