"""Error model: unified envelope + full ``LAA-xxxx`` catalog.

Single source of truth for error codes so frontend constants can be generated
and the ``三态封闭`` / no-duplicate-code constraints can be statically checked.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

JsonDict = Dict[str, Any]


@dataclass(frozen=True)
class ErrorMeta:
    code: str
    name: str
    default_message: str
    retryable: bool
    log_level: str = "error"


# order mirrors §5.3. Each entry: code -> (name, message, retryable)
_ERRORS: Dict[str, tuple] = {
    # 1xxx bridge
    "LAA-1001": ("UNKNOWN_COMMAND", "调用了不存在的命令", False),
    "LAA-1002": ("INVALID_PAYLOAD", "参数校验失败", False),
    "LAA-1003": ("UI_DISCONNECTED", "窗口已关闭仍推送", False),
    "LAA-1004": ("STREAM_LIMIT", "并发流超限", True),
    # 2xxx config & capability gate
    "LAA-2001": ("CONFIG_INVALID", "配置不合法", False),
    "LAA-2002": ("SECRET_UNAVAILABLE", "密钥读取失败", True),
    "LAA-2003": ("PROVIDER_NOT_CONFIGURED", "未配置供应商", False),
    "LAA-2004": ("NOT_IMPLEMENTED", "能力尚未实现", False),
    "LAA-2005": ("CAPABILITY_UNAVAILABLE", "能力暂不可用", False),
    "LAA-2006": ("CAPABILITY_UNKNOWN", "未知能力标识", False),
    # 3xxx input & task
    "LAA-3001": ("EMPTY_INPUT", "空输入", False),
    "LAA-3002": ("TEXT_TOO_LONG", "文本超长", False),
    "LAA-3003": ("LANG_UNSUPPORTED", "目标语言不支持", False),
    "LAA-3004": ("SEGMENT_FAILED", "分段失败", True),
    "LAA-3005": ("TASK_CANCELLED", "任务已取消", False),
    "LAA-3006": ("TASK_NOT_FOUND", "任务不存在", False),
    "LAA-3007": ("MODE_SWITCH_LOCKED", "模式切换被锁定", False),
    "LAA-3008": ("RETRANSLATE_NOT_ALLOWED", "禁止重译", False),
    "LAA-3010": ("PAUSE_NOT_ALLOWED", "当前无法暂停", False),
    "LAA-3011": ("EXPORT_FORMAT_UNSUPPORTED", "导出格式不支持", False),
    # 4xxx glossary
    "LAA-4001": ("TERM_CONFLICT", "术语冲突无法自动裁决", False),
    "LAA-4002": ("GLOSSARY_SCHEMA_INVALID", "术语文件 schema 不符", False),
    "LAA-4003": ("TERM_NOT_FOUND", "术语条目不存在", False),
    "LAA-4004": ("BANK_READONLY", "术语库只读", False),
    "LAA-4005": ("IMPORT_PARTIAL", "导入部分失败", False),
    "LAA-4006": ("COMMUNITY_REPO_INVALID", "第三方术语仓库不符合规范", False),
    "LAA-4007": ("PACK_SIGNATURE_INVALID", "包签名校验失败", False),
    "LAA-4008": ("PACK_HASH_MISMATCH", "包内容校验不合", False),
    "LAA-4009": ("PACK_VERSION_INCOMPATIBLE", "包版本不兼容", False),
    "LAA-4010": ("PACK_DEPENDENCY_MISSING", "包依赖缺失", False),
    "LAA-4011": ("BANK_EXISTS", "词库已存在", False),
    # 5xxx analysis
    "LAA-5001": ("RISK_RULE_INVALID", "风险规则包语法错误", False),
    "LAA-5002": ("EMOTION_TAG_PARSE_FAILED", "情感标注解析失败", True),
    "LAA-5003": ("RISK_POLICY_MISSING", "场景缺风险策略", False),
    # 6xxx version / fix
    "LAA-6003": ("VERSION_CONFLICT", "基线版本已变", True),
    "LAA-6004": ("FIX_PARSE_FAILED", "修正解析失败", False),
    # 7xxx storage
    "LAA-7001": ("DB_MIGRATION_FAILED", "迁移失败", False),
    "LAA-7002": ("SCHEMA_VERSION_MISMATCH", "数据版本高于程序", False),
    "LAA-7003": ("FILE_CORRUPTED", "文件损坏", False),
    "LAA-7004": ("TM_INDEX_ERROR", "翻译记忆索引异常", True),
    "LAA-7005": ("STORAGE_LIMIT", "存储达到上限", False),
    "LAA-7006": ("SCENE_NOT_FOUND", "场景档案不存在", False),
    # 8xxx provider
    "LAA-8001": ("PROVIDER_AUTH", "供应商密钥错误", False),
    "LAA-8002": ("PROVIDER_RATE_LIMIT", "供应商限流", True),
    "LAA-8003": ("PROVIDER_TIMEOUT", "供应商超时", True),
    "LAA-8004": ("PROVIDER_UNAVAILABLE", "供应商不可用", True),
    "LAA-8005": ("PROVIDER_CONTENT_POLICY", "供应商内容拦截", False),
    "LAA-8006": ("OUTPUT_SCHEMA_INVALID", "结构化输出不合规", True),
    "LAA-8007": ("CONTEXT_OVERFLOW", "超上下文", False),
    # 9xxx budget / reserved
    "LAA-9001": ("BUDGET_EXCEEDED", "预算闸门拦截", False),
    "LAA-9002": ("PLUGIN_INVALID", "插件清单非法", False),
    "LAA-9003": ("PLUGIN_PERMISSION", "插件越权", False),
    # reserved (M4/M5), only占号
    "LAA-9004": ("MEDIA_UNSUPPORTED", "媒体类型不受支持", False),
    "LAA-9005": ("MEDIA_PIPELINE_FAILED", "媒体管线执行失败", False),
    "LAA-9006": ("PLUGIN_HOST_UNAVAILABLE", "插件宿主不可用", False),
    "LAA-9007": ("TRANSPORT_UNAVAILABLE", "传输层不可用", False),
}


class ErrorCatalog:
    _entries: Dict[str, ErrorMeta] = {
        code: ErrorMeta(code=code, name=meta[0], default_message=meta[1], retryable=meta[2])
        for code, meta in _ERRORS.items()
    }

    @classmethod
    def get(cls, code: str) -> ErrorMeta:
        try:
            return cls._entries[code]
        except KeyError:
            return ErrorMeta(code=code, name="UNKNOWN", default_message="unknown error", retryable=False)

    @classmethod
    def all(cls) -> List[ErrorMeta]:
        return list(cls._entries.values())


@dataclass
class LaaError(Exception):
    code: str
    message: Optional[str] = None
    retryable: Optional[bool] = None
    details: JsonDict = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(self.code)
        meta = ErrorCatalog.get(self.code)
        if self.message is None:
            self.message = meta.default_message
        if self.retryable is None:
            self.retryable = meta.retryable

    def to_envelope(self, trace_id: str) -> JsonDict:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "details": self.details,
            },
            "trace_id": trace_id,
        }

    def is_retryable(self) -> bool:
        return bool(self.retryable)


def err(code: str, message: Optional[str] = None, **details: Any) -> LaaError:
    return LaaError(code, message=message, details=dict(details))


def ok(data: Any, trace_id: str) -> JsonDict:
    return {"ok": True, "data": data, "trace_id": trace_id}