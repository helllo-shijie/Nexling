"""Shared contracts: types, errors, events, identifiers, clock, container."""
from .clock import CancellationToken, Clock, FakeClock, Span, Score, Paginated, TraceContext, utc_now
from .container import ServiceContainer
from .dto import (  # noqa: F401
    AnnotatedSpan,
    CapabilitySpec,
    ConfidenceResult,
    CostEstimate,
    EmotionAnnotation,
    PromptPlan,
    QAReport,
    QAIssue,
    ResolvedScene,
    RiskAssessment,
    RiskSignal,
    SceneProfile,
    SegmentView,
    TermBank,
    TermBinding,
    TermCandidate,
    TermEntry,
    TermHit,
    TermMention,
    TermOverride,
    TextSegment,
    TmHit,
    TMEntry,
    TranslationTask,
    TranslationVersion,
    TranslateRequest,
    dump,
)
from .errors import ErrorCatalog, ErrorMeta, JsonDict, LaaError, err, ok
from .events import RESERVED_TOPICS, EventBus, Topic, UiEvent
from .ids import Ulid, id_from, new_id
from .types import (  # noqa: F401
    AnnotationKind,
    CapabilityStatus,
    ConfidenceBand,
    EmotionKind,
    MatchMode,
    ModeScope,
    RiskTier,
    RoutingDecision,
    TermScope,
    TermStatus,
    TaskInputKind,
    TaskStatus,
    TranslateMode,
    SCOPE_ORDER,
    VALID_DOMAINS,
)

__all__ = [
    "CancellationToken", "Clock", "FakeClock", "Span", "Score", "Paginated", "TraceContext",
    "utc_now", "ServiceContainer", "ErrorCatalog", "ErrorMeta", "LaaError", "err", "ok",
    "JsonDict", "EventBus", "Topic", "UiEvent", "RESERVED_TOPICS", "Ulid", "id_from", "new_id",
    "dump",
]