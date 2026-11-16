"""Deterministic QA checks and confidence estimation (spec §6.12).

Every checker is a pure function ``f(ctx) -> list[QAIssue]`` operating on
``ctx`` (a dict with ``source``, ``target``, ``hard_terms``, ``mode``,
``bindings`` and optional ``source_lang`` / ``target_lang`` / ``segment_id``).
No network, no model.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from laa_core.shared import (
    ConfidenceBand,
    ConfidenceResult,
    QAIssue,
    QAReport,
)

# categories used across checkers (shared vocabulary)
CAT_LENGTH = "长度"
CAT_NUMBER = "数字"
CAT_TERM = "术语"
CAT_RESIDUAL = "残留"
CAT_STRUCTURE = "结构"
CAT_CONSISTENCY = "一致性"


def _term_fields(term) -> Dict[str, Any]:
    """Coerce a term entry (dataclass or dict) into a plain dict."""
    if isinstance(term, dict):
        return term
    return {
        "id": getattr(term, "id", None),
        "source_term": getattr(term, "source_term", ""),
        "target_term": getattr(term, "target_term", ""),
    }


def LengthRatioCheck(ctx: Dict[str, Any]) -> List[QAIssue]:
    source = ctx.get("source", "") or ""
    target = ctx.get("target", "") or ""
    mode = ctx.get("mode", "fluent")
    if not source:
        return []
    ratio = len(target) / len(source)
    if mode == "literal":
        # 直译是按词义项对应，长度天然偏离目标语习惯（如英文→中文常只有原文的 1/3），
        # 只做粗粒度离群检查，且不升级为需要修复的问题。
        lo, hi, sev = 0.15, 3.5, "low"
    else:
        lo, hi, sev = 0.4, 2.5, "medium"
    if lo <= ratio <= hi:
        return []
    return [QAIssue(
        check_id="length_ratio", category=CAT_LENGTH, severity=sev,
        span=[0, len(target)],
        evidence=f"ratio={ratio:.2f} (期望 {lo}-{hi})",
    )]


_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*(?:\s*(?:%|％|ms|s|m|mm|cm|km|kg|g|mb|gb|"
                     r"秒|毫秒|米|千米|公斤|克|小时|分钟|天|年|月|日))?")
_UNIT_RE = re.compile(r"(?:ms|s|m|mm|cm|km|kg|g|mb|gb|%|％|秒|毫秒|米|千米|"
                      r"公斤|克|小时|分钟|天|年|月|日)\b", re.IGNORECASE)


def NumberUnitCheck(ctx: Dict[str, Any]) -> List[QAIssue]:
    source = ctx.get("source", "") or ""
    target = ctx.get("target", "") or ""
    issues: List[QAIssue] = []
    for m in _NUM_RE.finditer(source):
        token = m.group(0)
        num = re.search(r"\d+(?:[.,]\d+)*", token)
        if not num:
            continue
        if num.group(0) not in target:
            issues.append(QAIssue(
                check_id="number_missing", category=CAT_NUMBER, severity="high",
                span=[m.start(), m.end()], evidence=token,
            ))
            continue
        # unit presence / change
        src_unit = _UNIT_RE.search(token)
        if src_unit:
            u = src_unit.group(0)
            if u.lower() not in target.lower():
                issues.append(QAIssue(
                    check_id="unit_changed", category=CAT_NUMBER, severity="high",
                    span=[m.start(), m.end()], evidence=token,
                ))
    return issues


def TerminologyCheck(ctx: Dict[str, Any]) -> List[QAIssue]:
    target = ctx.get("target", "") or ""
    hard_terms = ctx.get("hard_terms", []) or []
    issues: List[QAIssue] = []
    for term in hard_terms:
        t = _term_fields(term)
        expected = (t.get("target_term") or "").strip()
        if not expected:
            continue
        if expected not in target:
            issues.append(QAIssue(
                check_id="term_missing", category=CAT_TERM, severity="high",
                span=[], evidence=f"{t.get('source_term')} -> {expected}",
                term_ref=str(t.get("id") or t.get("source_term") or ""),
            ))
    return issues


def UntranslatedCheck(ctx: Dict[str, Any]) -> List[QAIssue]:
    target = ctx.get("target", "") or ""
    tgt_lang = (ctx.get("target_lang") or "").lower()
    issues: List[QAIssue] = []
    if tgt_lang.startswith("zh"):
        for m in re.finditer(r"[A-Za-z]{8,}", target):
            issues.append(QAIssue(
                check_id="residual_source", category=CAT_RESIDUAL, severity="low",
                span=[m.start(), m.end()], evidence=m.group(0),
            ))
    elif tgt_lang.startswith("en"):
        for m in re.finditer(r"[\u4e00-\u9fff]{4,}", target):
            issues.append(QAIssue(
                check_id="residual_source", category=CAT_RESIDUAL, severity="low",
                span=[m.start(), m.end()], evidence=m.group(0),
            ))
    return issues


_STRUCT_PATTERNS = (
    r"(?m)^\s*\d+[.、．]\s",
    r"(?m)^\s*[-–•]\s",
    r"[①-⑩]",
)


def _count_structure(text: str) -> int:
    total = 0
    for pat in _STRUCT_PATTERNS:
        total += len(re.findall(pat, text))
    return total


def StructureCheck(ctx: Dict[str, Any]) -> List[QAIssue]:
    source = ctx.get("source", "") or ""
    target = ctx.get("target", "") or ""
    mode = ctx.get("mode", "fluent")
    sc = _count_structure(source)
    tc = _count_structure(target)
    if sc == tc:
        return []
    sev = "high" if mode == "literal" else "medium"
    return [QAIssue(
        check_id="structure_mismatch", category=CAT_STRUCTURE, severity=sev,
        span=[0, len(target)],
        evidence=f"列表/编号数量 source={sc} target={tc}",
    )]


def CrossSegmentConsistencyCheck(ctx: Dict[str, Any]) -> List[QAIssue]:
    source = ctx.get("source", "") or ""
    target = ctx.get("target", "") or ""
    bindings = ctx.get("bindings", []) or []
    issues: List[QAIssue] = []
    for b in bindings:
        if isinstance(b, dict):
            chosen = b.get("chosen_target") or ""
            src = b.get("source") or ""
            seg_ids = b.get("segment_ids", []) or []
        else:
            chosen = getattr(b, "chosen_target", "") or ""
            src = getattr(b, "source", "") or ""
            seg_ids = getattr(b, "segment_ids", []) or []
        if not chosen or not src:
            continue
        # the binding applies to this segment only if the source term appears
        if src and src not in source:
            continue
        if chosen not in target:
            issues.append(QAIssue(
                check_id="binding_inconsistent", category=CAT_CONSISTENCY,
                severity="medium", span=[],
                evidence=f"{src} 应译为 {chosen}",
                segment_ids=list(seg_ids),
                variants=[chosen],
            ))
    return issues


# order-independent list of checkers
CHECKERS = (
    LengthRatioCheck,
    NumberUnitCheck,
    TerminologyCheck,
    UntranslatedCheck,
    StructureCheck,
    CrossSegmentConsistencyCheck,
)


class QAService:
    """Run all deterministic checks for a segment draft."""

    def __init__(self, checkers=CHECKERS) -> None:
        self.checkers = tuple(checkers)

    def check(self, seg, draft_target: str, ctx: Dict[str, Any] = None) -> QAReport:
        ctx = dict(ctx or {})
        data = {
            "source": getattr(seg, "text", "") or "",
            "target": draft_target or "",
            "hard_terms": ctx.get("hard_terms", []),
            "mode": ctx.get("mode", "fluent"),
            "bindings": ctx.get("bindings", []),
            "source_lang": ctx.get("source_lang", ""),
            "target_lang": ctx.get("target_lang", ""),
            "segment_id": getattr(seg, "id", ""),
        }
        issues: List[QAIssue] = []
        for checker in self.checkers:
            issues.extend(list(checker(data)))
        has_blocking = any(i.severity == "high" for i in issues)
        return QAReport(
            segment_id=getattr(seg, "id", ""),
            issues=issues,
            has_blocking=has_blocking,
        )


class ConfidenceEstimator:
    """Heuristic confidence from QA penalty accumulation."""

    @staticmethod
    def estimate(report: QAReport, signals=None) -> ConfidenceResult:
        score = 1.0
        drivers: List[Dict[str, Any]] = []
        high = sum(1 for i in report.issues if i.severity == "high")
        medium = sum(1 for i in report.issues if i.severity == "medium")
        low = sum(1 for i in report.issues if i.severity == "low")

        if high:
            score -= 0.25 * high
            drivers.append({"kind": "qa_high", "delta": -0.25 * high, "count": high})
        if medium:
            score -= 0.10 * medium
            drivers.append({"kind": "qa_medium", "delta": -0.10 * medium, "count": medium})
        if low:
            score -= 0.03 * low
            drivers.append({"kind": "qa_low", "delta": -0.03 * low, "count": low})

        score = max(0.0, round(score, 4))
        if score >= 0.75:
            band = ConfidenceBand.HIGH.value
        elif score >= 0.60:
            band = ConfidenceBand.MEDIUM.value
        else:
            band = ConfidenceBand.LOW.value

        return ConfidenceResult(
            segment_id=report.segment_id,
            score=score,
            band=band,
            drivers=drivers,
            method="heuristic",
        )


if __name__ == "__main__":  # pragma: no cover - smoke test
    from laa_core.shared import TextSegment

    seg = TextSegment(id="s1", index=0, text="The user shall pay 100 USD.", span=[0, 26])
    ctx = {"target_lang": "zh-Hans", "mode": "fluent",
           "hard_terms": [{"id": "t1", "source_term": "user", "target_term": "用户"}]}
    report = QAService().check(seg, "用户应 用户 支付 100 美元。", ctx)
    print(report.to_dict())
    print(ConfidenceEstimator.estimate(report).to_dict())