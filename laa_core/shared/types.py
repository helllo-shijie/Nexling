"""Closed enumerations (single source of truth for value sets).

Using ``str``-based ``Enum`` keeps validation + the ``三态封闭`` static check
trivial while values remain plain strings at the JSON/bridge boundary.
"""
from __future__ import annotations

from enum import Enum


class TranslateMode(str, Enum):
    FLUENT = "fluent"
    LITERAL = "literal"


class TaskInputKind(str, Enum):
    TEXT = "text"
    AUDIO = "audio"
    DOCUMENT = "document"
    IMAGE = "image"


class CapabilityStatus(str, Enum):
    AVAILABLE = "available"
    IN_DEVELOPMENT = "in_development"
    UNAVAILABLE = "unavailable"
    ROADMAP = "roadmap"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    PREPARING = "preparing"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FINALIZING = "finalizing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RiskTier(str, Enum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class RoutingDecision(str, Enum):
    AUTO_FINALIZE = "auto_finalize"
    # 不自动导出、由用户自行处理（L2/L3）。审校流程已移除，这里只是导出策略。
    MANUAL_EXPORT = "manual_export"
    # 遗留值：旧数据里可能仍存 human_review，仅用于兼容读取，不再产生。
    HUMAN_REVIEW = "human_review"
    BLOCKED = "blocked"


class TermScope(str, Enum):
    """Terminology pool scope, ordered by priority (highest first)."""

    SESSION = "session"
    IN_DOCUMENT = "document"  # 篇内绑定
    PERSONAL = "personal"
    TEAM = "team"
    OFFICIAL = "official"
    COMMUNITY = "community"
    BUILTIN = "builtin"


# Priority ladder order (highest -> lowest), mirrors §6.7 / 8.5.
SCOPE_ORDER: tuple[TermScope, ...] = (
    TermScope.SESSION,
    TermScope.IN_DOCUMENT,
    TermScope.PERSONAL,
    TermScope.TEAM,
    TermScope.OFFICIAL,
    TermScope.COMMUNITY,
    TermScope.BUILTIN,
)


class TermStatus(str, Enum):
    ACTIVE = "active"
    PENDING = "pending"
    DEPRECATED = "deprecated"
    REJECTED = "rejected"


class MatchMode(str, Enum):
    EXACT = "exact"
    LEMMA = "lemma"
    FUZZY = "fuzzy"


class AnnotationKind(str, Enum):
    ALTERNATE_TRANSLATION = "alternate_translation"
    COMMON_TRANSLATION = "common_translation"
    SOURCE_LANG_KEPT = "source_lang_kept"
    LOW_CONFIDENCE = "low_confidence"
    TERMINOLOGY_APPLIED = "terminology_applied"
    LITERAL_STYLE = "literal_style"
    RISK_FLAG = "risk_flag"
    EMOTION_TAG = "emotion_tag"
    QA_FIXED = "qa_fixed"


class ConfidenceBand(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class EmotionKind(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    URGENT = "urgent"
    APOLOGY = "apology"
    EMPHASIS = "emphasis"
    HUMOR = "humor"


class ModeScope(str, Enum):
    REST = "rest"
    SESSION = "session"


class TempCategory(str, Enum):
    DRAFT = "draft"
    QA = "qa"
    FIX = "fix"


class ProviderKind(str, Enum):
    TRANSLATE = "translate"
    CHAT = "chat"


# Domain tags (single vocabulary used by terms / scenes / tasks)
VALID_DOMAINS = ("tech", "legal", "finance", "academic", "general", "education", "medical")

CAPABILITY_STATUS_VALUES = tuple(c.value for c in CapabilityStatus)
TASK_STATUS_VALUES = tuple(t.value for t in TaskStatus)


def is_term_scope_order_valid(order: tuple) -> bool:
    return set(order) == {s for s in TermScope}