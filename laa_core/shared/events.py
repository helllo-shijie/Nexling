"""Event topics + ``UiEvent`` envelope (single source of truth)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

JsonDict = Dict[str, Any]


class Topic:
    TASK_CREATED = "task.created"
    TASK_PROGRESS = "task.progress"
    TASK_PAUSED = "task.paused"
    TASK_CANCELLING = "task.cancelling"
    TASK_CANCELLED = "task.cancelled"
    TASK_FINALIZING = "task.finalizing"
    TASK_CHECKPOINT = "task.checkpoint"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TRANSLATION_DELTA = "translation.delta"
    SEGMENT_DRAFT = "segment.draft"
    SEGMENT_VIEW = "segment.view"
    SEGMENT_QA = "segment.qa"
    TRANSLATION_FIXED = "translation.fixed"
    TRANSLATION_FIX_FAILED = "translation.fix_failed"
    RISK_ASSESSED = "risk.assessed"
    GLOSSARY_CHANGED = "glossary.changed"
    GLOSSARY_CANDIDATES = "glossary.candidates"
    COST_WARNING = "cost.warning"
    PROVIDER_STATUS = "provider.status"
    STARTUP_PROGRESS = "startup.progress"
    SCENE_CHANGED = "scene.changed"
    MODE_CHANGED = "mode.changed"
    TRANSLATION_RETRANSLATED = "translation.retranslated"
    STORAGE_WARNING = "storage.warning"
    RELEASE_PROGRESS = "release.progress"
    COMMUNITY_REPO_CHANGED = "community.repo.changed"
    CAPABILITY_STATUS_CHANGED = "capability.status.changed"


# Reserved (M4/M5) topics — registered, never published in M3.
RESERVED_TOPICS: tuple[str, ...] = (
    "media.transcribed",
    "tts.chunk",
    "document.parsed",
    "document.written",
    "plugin.job.progress",
    "translation.offline_first",
    "translation.replaced",
)


@dataclass
class UiEvent:
    topic: str
    payload: JsonDict = field(default_factory=dict)
    task_id: Optional[str] = None
    seq: int = 0
    trace_id: Optional[str] = None

    def to_dict(self) -> JsonDict:
        d: JsonDict = {"topic": self.topic, "payload": self.payload, "seq": self.seq}
        if self.task_id is not None:
            d["task_id"] = self.task_id
        if self.trace_id is not None:
            d["trace_id"] = self.trace_id
        return d


class EventBus:
    """In-process pub/sub, topic prefix aware."""

    def __init__(self) -> None:
        self._subs: Dict[str, List] = {}

    def subscribe(self, topic: str, handler) -> None:
        self._subs.setdefault(topic, []).append(handler)

    def publish(self, event: UiEvent) -> None:
        for prefix in list(self._subs.keys()):
            if event.topic.startswith(prefix):
                for handler in list(self._subs.get(prefix, [])):
                    handler(event)

    def close(self) -> None:
        self._subs.clear()