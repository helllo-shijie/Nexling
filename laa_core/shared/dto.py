"""Public DTOs and value objects shared across layers (JSON-serializable).

Cross-language JSON uses snake_case field names; dataclasses here double as
the in-process value objects (no separate to_dto/from_dto in core).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .types import (
    AnnotationKind,
    ConfidenceBand,
    EmotionKind,
    MatchMode,
    ModeScope,
    RiskTier,
    RoutingDecision,
    TaskInputKind,
    TaskStatus,
    TermScope,
    TermStatus,
    TranslateMode,
)


def _d(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (dict, list)):
        return obj
    if hasattr(obj, "value") and not isinstance(obj, type):  # Enum
        return obj.value
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if isinstance(obj, tuple):
        return list(obj)
    raise TypeError(f"unsupported type {type(obj)}")


def dump(obj) -> dict:
    return asdict(obj, dict_factory=lambda pairs: {k: _d(v) for k, v in pairs})


@dataclass
class TranslateRequest:
    text: str
    target_lang: str = "zh-Hans"
    source_lang: Optional[str] = None
    mode: Optional[str] = None
    scene_profile_id: Optional[str] = None
    domain: str = "general"
    task_hint: Optional[str] = None
    session_id: Optional[str] = None
    input_kind: str = "text"
    media_refs: Optional[list] = None
    stream: bool = False
    request_id: Optional[str] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TranslateRequest":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class TextSegment:
    id: str
    index: int
    text: str
    span: List[int]
    lang: str = ""
    token_estimate: int = 0
    status: str = "pending"
    # 单句超长被强制按字数切开（标记给界面与导出）
    forced: bool = False

    def to_dict(self) -> dict:
        return dump(self)


@dataclass
class TermEntry:
    id: str
    bank_id: str
    source_term: str
    target_term: str
    src_lang: str
    tgt_lang: str
    domain: str = "general"
    part_of_speech: Optional[str] = None
    definition: Optional[str] = None
    case_sensitive: bool = False
    match_mode: str = "exact"
    forced: bool = False
    status: str = "active"
    confidence: float = 1.0
    origin: str = "manual"
    tags: List[str] = field(default_factory=list)
    version: int = 1
    refs: Dict[str, Any] = field(default_factory=dict)
    scene_variants: Dict[str, str] = field(default_factory=dict)
    deleted_at: Optional[str] = None

    def to_dict(self) -> dict:
        return dump(self)


@dataclass
class TermBank:
    id: str
    scope: str
    name: str
    src_lang: str = "*"
    tgt_lang: str = "*"
    domain: str = "general"
    readonly: bool = False
    version: int = 1
    entry_count: int = 0
    owner: str = "local"
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return dump(self)


@dataclass
class TermHit:
    """A terminology match with the slot that produced it."""

    entry_id: str
    source_term: str
    target_term: str
    bank_id: str
    scope: str
    forced: bool = False
    span: List[int] = field(default_factory=list)
    match_mode: str = "exact"
    domain: str = "general"
    version: int = 1
    # resolution result
    resolved: bool = True
    shadowed_by: Optional[str] = None


@dataclass
class TermOverride:
    task_id: str
    source: str
    target: str
    expires_at: str = ""

    def is_active(self, now_ms: int, expires_ms: Optional[int] = None) -> bool:
        return expires_ms is None or now_ms < expires_ms


@dataclass
class TermBinding:
    normalized: str
    chosen_target: str
    source: str
    segment_ids: List[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return dump(self)


@dataclass
class TermMention:
    surface: str
    normalized: str
    segment_id: str
    span: List[int]
    kind: str = "compound"


@dataclass
class TermCandidate:
    id: str
    source_term: str
    lang_pair: str
    domain: str = "general"
    origin_source_id: Optional[str] = None
    occurrences: int = 0
    novelty: float = 0.0
    target_text: Optional[str] = None
    target_source: str = "none"  # glossary/tm/user/none
    status: str = "pending"
    score: Dict[str, Any] = field(default_factory=dict)
    evidence_spans: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = ""

    def overall_score(self) -> float:
        return float(self.score.get("total", 0.0))

    def to_dict(self) -> dict:
        return dump(self)


@dataclass
class RiskSignal:
    rule_id: str
    category: str
    severity: int
    span: List[int]
    evidence: str = ""
    message: str = ""


@dataclass
class RiskAssessment:
    id: str
    task_id: str
    score: int = 0
    tier: str = RiskTier.L0.value
    policy_id: str = ""
    routing: str = RoutingDecision.AUTO_FINALIZE.value
    drivers: Dict[str, Any] = field(default_factory=dict)
    signals: List[Dict[str, Any]] = field(default_factory=list)
    auto_export_allowed: bool = True
    created_at: str = ""

    def to_dict(self) -> dict:
        return dump(self)


@dataclass
class SceneProfile:
    id: str
    name: str
    description: str = ""
    labels: List[str] = field(default_factory=list)
    mode_default: str = TranslateMode.FLUENT.value
    register: str = "formal"
    descriptors: List[str] = field(default_factory=list)
    do: List[str] = field(default_factory=list)
    dont: List[str] = field(default_factory=list)
    examples: List[Dict[str, str]] = field(default_factory=list)
    bank_ids: List[str] = field(default_factory=list)
    rules: List[Dict[str, Any]] = field(default_factory=list)
    template_id: str = "default"
    is_builtin: bool = False
    is_default: bool = False
    version: int = 1
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return dump(self)


@dataclass
class ResolvedScene:
    profile_id: str
    name: str
    mode: str
    bank_ids: List[str]
    rules_hash: str
    version: int

    def to_dict(self) -> dict:
        return dump(self)


@dataclass
class PromptPlan:
    template_id: str
    template_version: str
    messages: List[Dict[str, str]]
    mode: str
    scene_profile_id: Optional[str]
    scene_version: int
    glossary_terms: List[TermHit] = field(default_factory=list)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    max_output_tokens: int = 1024
    literal_flag: bool = False
    fingerprint: str = ""

    def to_dict(self) -> dict:
        return dump(self)


@dataclass
class EmotionAnnotation:
    emotion: str
    intensity: int
    segment_id: str
    span: Optional[List[int]] = None
    evidence: str = ""
    note: str = ""
    confidence: float = 1.0
    align_status: str = "matched"

    def to_dict(self) -> dict:
        return dump(self)


@dataclass
class QAIssue:
    check_id: str
    category: str
    severity: str  # high/medium/low
    span: List[int] = field(default_factory=list)
    evidence: str = ""
    term_ref: Optional[str] = None
    segment_ids: List[str] = field(default_factory=list)
    variants: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return dump(self)


@dataclass
class QAReport:
    segment_id: str
    issues: List[QAIssue] = field(default_factory=list)
    has_blocking: bool = False

    def to_dict(self) -> dict:
        return {"segment_id": self.segment_id, "issues": [i.to_dict() for i in self.issues],
                "has_blocking": self.has_blocking}


@dataclass
class ConfidenceResult:
    segment_id: str
    score: float
    band: str
    drivers: List[Dict[str, Any]] = field(default_factory=list)
    method: str = "heuristic"
    threshold: float = 0.60

    def to_dict(self) -> dict:
        return dump(self)


@dataclass
class TranslationVersion:
    id: str
    segment_id: str
    parent_version_id: Optional[str]
    target_text: str
    origin: str
    provider: str
    model: str
    prompt_fingerprint: str = ""
    term_bank_version: Optional[int] = None
    routing_at_creation: str = ""
    source_channel: str = "online"
    confidence: Optional[float] = None
    created_at: str = ""

    def to_dict(self) -> dict:
        return dump(self)


@dataclass
class AnnotatedSpan:
    id: str
    text: str
    span: List[int]
    kinds: List[str] = field(default_factory=list)
    term_ref: Optional[str] = None
    variants: List[Dict[str, str]] = field(default_factory=list)
    confidence: Optional[float] = None
    fix_ref: Optional[str] = None
    note: str = ""

    def to_dict(self) -> dict:
        return dump(self)


@dataclass
class SentimentDistribution:
    """段落情感概率分布（积极/消极/中性，总和 1）。"""
    positive: float
    negative: float
    neutral: float
    threshold: float = 0.6
    needs_review: bool = False

    def to_dict(self) -> dict:
        return dump(self)


@dataclass
class SegmentView:
    segment_id: str
    source_text: str
    target_text: str
    spans: List[AnnotatedSpan] = field(default_factory=list)
    words: List[Dict[str, Any]] = field(default_factory=list)  # 直译模式逐词对齐：[{src,target,alternatives}]
    tones: List[Dict[str, Any]] = field(default_factory=list)  # 原文语气识别：[{span:[s,e],label}]（相对 source_text）
    confidence: Optional[ConfidenceResult] = None
    emotions: List[EmotionAnnotation] = field(default_factory=list)
    sentiment: Optional[Dict[str, Any]] = None  # {positive,negative,neutral,threshold,needs_review}
    risk: Optional[Dict[str, Any]] = None
    mode: str = TranslateMode.FLUENT.value
    fix_record_id: Optional[str] = None
    channel: str = "online"
    version_id: str = ""  # 当前译文版本 id（覆盖/替换时的基线）

    def to_dict(self) -> dict:
        return dump(self)


@dataclass
class TranslationTask:
    id: str
    source_text: str
    src_lang: str
    tgt_lang: str
    detected_lang: Optional[str] = None
    mode: str = TranslateMode.FLUENT.value
    scene_profile_id: Optional[str] = None
    resolved_scene: Dict[str, Any] = field(default_factory=dict)
    domain: str = "general"
    input_kind: str = "text"
    media_refs: Optional[list] = None
    status: str = TaskStatus.QUEUED.value
    checkpoint_seq: int = 0
    resumable: bool = False
    risk_tier: str = RiskTier.L0.value
    routing: str = RoutingDecision.AUTO_FINALIZE.value
    budget_limit: float = 0.5
    cost_total: float = 0.0
    segment_count: int = 0
    created_at: str = ""
    completed_at: Optional[str] = None

    def to_dict(self) -> dict:
        return dump(self)


@dataclass
class TMEntry:
    id: str
    source_hash: str
    source_text: str
    target_text: str
    lang_pair: str
    domain: str = "general"
    scene_profile_id: Optional[str] = None
    approved: bool = False
    quality: float = 0.0
    glossary_version: int = 0
    prompt_fingerprint: str = ""
    stale: bool = False
    use_count: int = 0
    last_used_at: str = ""
    created_at: str = ""

    def to_dict(self) -> dict:
        return dump(self)


@dataclass
class TmHit:
    entry_id: str
    source_text: str
    target_text: str
    score: float
    match_kind: str  # exact/fuzzy/keyword
    glossary_version: int = 0
    stale: bool = False

    def to_dict(self) -> dict:
        return dump(self)


@dataclass
class CostEstimate:
    input_tokens: int
    output_tokens: int
    segments: int
    calls: int
    amount: float
    currency: str = "USD"
    assumptions: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return dump(self)


@dataclass
class CapabilitySpec:
    id: str
    name: str
    group: str
    stage: str
    status: str
    entry_points: List[str] = field(default_factory=list)
    command: Optional[str] = None
    message_key: str = ""
    placeholder: bool = False
    available_since: Optional[str] = None
    details_url: Optional[str] = None

    def to_view(self) -> dict:
        return dump(self)