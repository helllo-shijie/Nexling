"""Capability registry + gate (§6.25/M24): single source of "what exists, what is voice-only".

Available capabilities route to real commands; ``in_development``/``unavailable``
capabilities exist in the registry and are blocked uniformly with LAA-2005, without
any fake function behind them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..shared.dto import CapabilitySpec
from ..shared.errors import err
from ..shared.types import CapabilityStatus

# id -> (group, status, entry_points, command, placeholder, message_key)
_CAPABILITIES: List[CapabilitySpec] = [
    CapabilitySpec(id="translation.text", name="文本翻译", group="input", stage="M0", status=CapabilityStatus.AVAILABLE.value,
                   entry_points=["input.text"], command="translation.start", message_key="", placeholder=False),
    CapabilitySpec(id="glossary.personal", name="个人术语库", group="extend", stage="M1", status=CapabilityStatus.AVAILABLE.value,
                   entry_points=["glossary.manage"], command="glossary.manage", message_key="", placeholder=False),
    CapabilitySpec(id="glossary.official", name="官方术语包", group="extend", stage="M2", status=CapabilityStatus.AVAILABLE.value,
                   entry_points=["settings.glossary.official"], command="glossary.package.list", message_key="", placeholder=False),
    CapabilitySpec(id="glossary.discovery", name="术语自动发现", group="extend", stage="M3", status=CapabilityStatus.AVAILABLE.value,
                   entry_points=["glossary.candidates"], command="term.scan", message_key="", placeholder=False),
    CapabilitySpec(id="glossary.community", name="开源术语仓库", group="extend", stage="M3", status=CapabilityStatus.ROADMAP.value,
                   entry_points=["settings.glossary.community"], command="community.add", message_key="", placeholder=False),
    CapabilitySpec(id="input.voice", name="语音输入", group="input", stage="M4", status=CapabilityStatus.ROADMAP.value,
                   entry_points=["input.voice"], command=None, message_key="capability.voice.input.in_development", placeholder=True),
    CapabilitySpec(id="output.voice", name="语音朗读", group="output", stage="M4", status=CapabilityStatus.ROADMAP.value,
                   entry_points=["output.voice"], command=None, message_key="capability.voice.output.in_development", placeholder=True),
    CapabilitySpec(id="input.document", name="文档翻译", group="input", stage="M4", status=CapabilityStatus.ROADMAP.value,
                   entry_points=["input.document"], command=None, message_key="capability.document.in_development", placeholder=True),
    CapabilitySpec(id="extend.plugin", name="插件", group="extend", stage="M4", status=CapabilityStatus.ROADMAP.value,
                   entry_points=["extend.plugin"], command=None, message_key="capability.plugin.in_development", placeholder=True),
    CapabilitySpec(id="platform.multi", name="多端使用", group="platform", stage="M5", status=CapabilityStatus.ROADMAP.value,
                   entry_points=["platform.multi"], command=None, message_key="capability.platform.multi.in_development", placeholder=True),
    CapabilitySpec(id="model.local", name="本地能力", group="extend", stage="M4", status=CapabilityStatus.ROADMAP.value,
                   entry_points=["settings.model.local"], command=None, message_key="capability.model.local.in_development", placeholder=True),
]

# command -> capability id (only for available commands that need gating)
_COMMAND_TO_CAPABILITY = {
    "translation.start": "translation.text",
    "translation.cancel": "translation.text",
    "translation.retranslate": "translation.text",
    "translation.export": "translation.text",
    "mode.set": "translation.text",
    "mode.get": "translation.text",
    "translation.snapshot": "translation.text",
    "translation.estimate": "translation.text",
    "translation.retry": "translation.text",
    "glossary.manage": "glossary.personal",
    "glossary.search": "glossary.personal",
    "glossary.import": "glossary.personal",
    "glossary.export": "glossary.personal",
    "glossary.package.list": "glossary.official",
    "glossary.package.install": "glossary.official",
    "glossary.discover": "glossary.discovery",
    "glossary.discover.accept": "glossary.discovery",
    "glossary.discover.reject": "glossary.discovery",
    "term.list": "glossary.discovery",
    "term.scan": "glossary.discovery",
    "term.accept": "glossary.discovery",
    "term.accept_bulk": "glossary.discovery",
    "term.ignore": "glossary.discovery",
    "term.clear": "glossary.discovery",
    "term.auto_review": "glossary.discovery",
    "term.auto_review.status": "glossary.discovery",
    "term.auto_review.undo": "glossary.discovery",
    "community.list": "glossary.community",
    "community.add": "glossary.community",
    "community.sync": "glossary.community",
    "community.remove": "glossary.community",
}


class CapabilityRegistry:
    def __init__(self) -> None:
        self._items = {c.id: c for c in _CAPABILITIES}
        self._overrides: Dict[str, str] = {}

    def list(self, group: Optional[str] = None) -> Dict[str, Any]:
        items = [c.to_view() for c in self._items.values() if group is None or c.group == group]
        return {"version": "1", "items": items}

    def get(self, capability_id: str) -> CapabilitySpec:
        spec = self._items.get(capability_id)
        if spec is None:
            raise err("LAA-2006", message=f"未知能力 {capability_id}")
        return spec

    def is_available(self, capability_id: str) -> bool:
        try:
            spec = self.get(capability_id)
        except Exception:
            return False
        return spec.status == CapabilityStatus.AVAILABLE.value or spec.status == self._overrides.get(capability_id)

    def override(self, capability_id: str, status: str) -> None:
        if capability_id not in self._items:
            raise err("LAA-2006", message=f"未知能力 {capability_id}")
        if status not in (s.value for s in CapabilityStatus):
            raise err("LAA-2001", message=f"非法状态 {status}")
        self._overrides[capability_id] = status

    @property
    def message_keys(self) -> Dict[str, str]:
        keys = {
            "capability.voice.input.in_development": "语音输入正在开发中",
            "capability.voice.output.in_development": "语音朗读正在开发中",
            "capability.document.in_development": "文档翻译正在开发中",
            "capability.plugin.in_development": "插件正在开发中",
            "capability.platform.multi.in_development": "多端使用正在开发中",
            "capability.model.local.in_development": "本地能力正在开发中",
        }
        return keys


class CapabilityGate:
    def __init__(self, registry: CapabilityRegistry):
        self.registry = registry

    def check_command(self, command: str) -> None:
        cap_id = _COMMAND_TO_CAPABILITY.get(command)
        if cap_id is None:
            return  # un-gated commands (app.info, capability.list, settings.*, etc.)
        if not self.registry.is_available(cap_id):
            spec = self.registry.get(cap_id)
            raise err("LAA-2005", capability=spec.id, message_key=spec.message_key)