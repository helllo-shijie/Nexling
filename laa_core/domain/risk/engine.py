"""Deterministic risk engine (spec §6.9 / §8.2).

Rule-packs scan the source text with pure substring/regex matching, score each
category, map to a risk tier, and route to auto-finalize / human-review /
blocked. No network, no model, fully reproducible.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from laa_core.shared import (
    RiskAssessment,
    RiskSignal,
    RiskTier,
    RoutingDecision,
    new_id,
    utc_now,
)

# ---------------------------------------------------------------------------
# Built-in rule pack. rule_id -> {category, severity, kind, pattern|terms,
# weight, message}. kind is one of "terms" (substring scan, case-insensitive
# for ASCII), "pattern" (regex scan), or "length" (long-sentence heuristic).
# ---------------------------------------------------------------------------
RULES: Dict[str, Dict[str, Any]] = {
    "legal_clause": {
        "category": "legal",
        "severity": 4,
        "weight": 8,
        "kind": "terms",
        "terms": ["条款", "甲方", "乙方", "违约", "shall", "hereby", "herein",
                  "indemnif", "warrant"],
        "message": "含法律/合同条款用语",
    },
    "financial_figure": {
        "category": "financial",
        "severity": 4,
        "weight": 8,
        "kind": "pattern",
        "pattern": r"(?:￥|¥|\$|€|£|USD|CNY|RMB)\s*\d+(?:[.,]\d+)*"
                  r"|\d+(?:[.,]\d+)*\s*(?:元|美元|欧元|英镑|万元|亿元|千元|%|％)",
        "message": "含金额或财务数字",
    },
    "numeric_unit": {
        "category": "numeric",
        "severity": 2,
        "weight": 4,
        "kind": "pattern",
        "pattern": r"\d+(?:\.\d+)?\s*(?:ms|mbps|kbps|km|mm|cm|kg|mg|gb|mb|kb|"
                  r"m|s|g|%|％|秒|毫秒|米|千米|公斤|克|小时|分钟|个月|天|年|月|日)\b"
                  r"|\d{4}[-/年]\d{1,2}[-/月]?\d{0,2}",
        "message": "含数字+单位或日期",
    },
    "negation": {
        "category": "negation",
        "severity": 3,
        "weight": 6,
        "kind": "pattern",
        "pattern": r"\bnot\b|\bnever\b|\bno\b|除非|不得|不能|禁止|无须|无需"
                  r"|不承担|不保证|不构成",
        "message": "含否定/排除性表述",
    },
    "disclaimer": {
        "category": "disclaimer",
        "severity": 3,
        "weight": 6,
        "kind": "pattern",
        "pattern": r"不构成.{0,8}(?:建议|意见|保证|承诺)|仅供参考|不作保证"
                  r"|概不负责|免责|不提供.{0,6}(?:建议|保证)",
        "message": "含免责声明",
    },
    "regulatory_ref": {
        "category": "regulatory",
        "severity": 2,
        "weight": 3,
        "kind": "pattern",
        "pattern": r"\bISO\s*[0-9]+\b|\bGDPR\b|\bGB/[Tt]?\s*[0-9]+"
                  r"|\bGB\s?[0-9]{3,}\b",
        "message": "含法规/标准引用",
    },
    "proper_noun": {
        "category": "proper_noun",
        "severity": 1,
        "weight": 2,
        "kind": "pattern",
        "pattern": r"\b[A-Z][a-z]{1,}[A-Z][A-Za-z]*\b|\b[A-Z]{2,}\b",
        "message": "含连续大写/专有名词",
    },
    "pii": {
        "category": "pii",
        "severity": 5,
        "weight": 8,
        "kind": "pattern",
        "pattern": r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
                  r"|1[3-9][0-9]{9}",
        "message": "含个人敏感信息(邮箱/手机号)",
    },
    "ambiguity": {
        "category": "ambiguity",
        "severity": 3,
        "weight": 6,
        "kind": "pattern",
        "pattern": r"合理(?:地)?(?:认为|判断)|酌情|适当|视情况(?:而定)?"
                  r"|由.{0,6}(?:决定|认定)",
        "message": "含模糊/歧义表述",
    },
    "long_sentence": {
        "category": "ambiguity",
        "severity": 2,
        "weight": 3,
        "kind": "length",
        "max_len": 120,
        "message": "长句可能导致歧义",
    },
    "out_of_scope": {
        "category": "out_of_scope",
        "severity": 5,
        "weight": 6,
        "kind": "terms",
        "terms": ["诊断", "处方", "剂量", "手术", "用药", "服用", "服用量"],
        "message": "超出通用翻译范畴(疑似医疗建议)",
    },
}

DOMAIN_MULTIPLIERS: Dict[str, float] = {
    "legal": 1.30,
    "finance": 1.25,
}

CATEGORY_CN: Dict[str, str] = {
    "legal": "法律条款",
    "financial": "金额数字",
    "numeric": "数字单位",
    "negation": "否定表述",
    "disclaimer": "免责声明",
    "regulatory": "法规引用",
    "proper_noun": "专有名词",
    "pii": "个人敏感信息",
    "ambiguity": "模糊表述",
    "out_of_scope": "超出范围",
}

TIER_CN: Dict[str, str] = {"L0": "低", "L1": "低", "L2": "中", "L3": "高"}

TIER_THRESHOLDS = ((25, "L0"), (50, "L1"), (75, "L2"))


def tier_for(score: int) -> str:
    if score < 25:
        return RiskTier.L0.value
    if score < 50:
        return RiskTier.L1.value
    if score < 75:
        return RiskTier.L2.value
    return RiskTier.L3.value


def _scan_terms(terms: List[str], text: str) -> List[tuple]:
    """Substring scan, case-insensitive for ASCII terms, returns (start, end, evidence)."""
    hits: List[tuple] = []
    low = text.lower()
    for term in terms:
        t = term.lower()
        idx = low.find(t)
        while idx >= 0:
            hits.append((idx, idx + len(term), text[idx:idx + len(term)]))
            idx = low.find(t, idx + 1)
    return hits


def _scan_pattern(pattern: str, text: str) -> List[tuple]:
    hits: List[tuple] = []
    for m in re.finditer(pattern, text):
        if m.end() > m.start():
            hits.append((m.start(), m.end(), m.group(0)))
    return hits


def _scan_length(max_len: int, text: str) -> List[tuple]:
    """Flag over-long sentences as an ambiguity driver."""
    hits: List[tuple] = []
    # split on sentence-ish boundaries, keep the matched sentence as evidence
    parts = re.split(r"(?<=[。！？!?；;])\s*", text)
    for part in parts:
        stripped = part.strip()
        if len(stripped) > max_len:
            start = text.find(stripped)
            hits.append((start, start + len(stripped), stripped))
    return hits


def _sig_to_dict(s: RiskSignal) -> Dict[str, Any]:
    return {
        "rule_id": s.rule_id,
        "category": s.category,
        "severity": s.severity,
        "span": s.span,
        "evidence": s.evidence,
        "message": s.message,
    }


def _scan_rule(rule: Dict[str, Any], text: str) -> List[RiskSignal]:
    kind = rule.get("kind", "terms")
    if kind == "terms":
        raw = _scan_terms(rule.get("terms", []), text)
    elif kind == "pattern":
        raw = _scan_pattern(rule.get("pattern", ""), text)
    elif kind == "length":
        raw = _scan_length(rule.get("max_len", 120), text)
    else:
        raw = []

    seen = set()
    signals: List[RiskSignal] = []
    for start, end, evidence in raw:
        key = (start, end, evidence)
        if key in seen:
            continue
        seen.add(key)
        signals.append(RiskSignal(
            rule_id=rule.get("rule_id", ""),  # placeholder, replaced below
            category=rule["category"],
            severity=int(rule.get("severity", 1)),
            span=[start, end],
            evidence=evidence,
            message=rule.get("message", ""),
        ))
    return signals


class RiskScorer:
    """Score signals into a 0-100 score, tier, and per-category drivers."""

    @staticmethod
    def score(signals: List[RiskSignal], domain: str = "general") -> Dict[str, Any]:
        by_cat: Dict[str, List[RiskSignal]] = {}
        blocked = False
        for s in list(signals):
            cat = s.category
            by_cat.setdefault(cat, []).append(s)
            if cat == "out_of_scope":
                blocked = True

        raw = 0.0
        drivers: Dict[str, Any] = {}
        for cat, sigs in by_cat.items():
            def sev(x: RiskSignal) -> int:
                return int(x.severity)

            best = max(sigs, key=sev)
            weight = int(RULES.get(best.rule_id, {}).get("weight", 1) or 1)
            n = len(sigs)
            mult = 1 + 0.2 * (n - 1)
            contrib = weight * best.severity * mult
            raw += contrib
            drivers[cat] = {
                "label": CATEGORY_CN.get(cat, cat),
                "severity": best.severity,
                "count": n,
                "weight": weight,
                "contribution": round(contrib, 2),
            }

        multiplier = DOMAIN_MULTIPLIERS.get(domain, 1.0)
        score = int(round(min(100.0, raw * multiplier)))
        tier = RiskTier.L3.value if blocked else tier_for(score)
        return {
            "score": score,
            "tier": tier,
            "drivers": drivers,
            "signals": [_sig_to_dict(s) for s in signals],
            "blocked": blocked,
        }


class RiskRouter:
    """Map a scored result to a routing decision + auto-export permission."""

    @staticmethod
    def route(score, policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if isinstance(score, dict):
            if score.get("blocked"):
                return {
                    "routing": RoutingDecision.BLOCKED.value,
                    "auto_export_allowed": False,
                }
            tier = str(score.get("tier", RiskTier.L0.value))
        else:
            tier = tier_for(int(score))

        if tier in (RiskTier.L0.value, RiskTier.L1.value):
            return {
                "routing": RoutingDecision.AUTO_FINALIZE.value,
                "auto_export_allowed": True,
            }
        if tier in (RiskTier.L2.value, RiskTier.L3.value):
            # 审校流程已移除：这里只表示“不自动导出”，由用户自行确认/处理。
            return {
                "routing": RoutingDecision.MANUAL_EXPORT.value,
                "auto_export_allowed": False,
            }
        return {
            "routing": RoutingDecision.BLOCKED.value,
            "auto_export_allowed": False,
        }


class RiskPolicy:
    """Default per-domain thresholds and the highest auto-finalize tier."""

    @staticmethod
    def default_for(domain: str = "general") -> Dict[str, Any]:
        return {
            "domain": domain,
            "thresholds": {"L0": 0, "L1": 25, "L2": 50, "L3": 75},
            "max_auto_tier": RiskTier.L1.value,
            "domain_multiplier": DOMAIN_MULTIPLIERS.get(domain, 1.0),
        }


class RiskEngine:
    """Scan text for risk signals, score, tier, and route."""

    def __init__(self, rules: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self.rules: Dict[str, Dict[str, Any]] = {}
        for rule_id, rule in (rules or RULES).items():
            self.rules[rule_id] = dict(rule)
            self.rules[rule_id]["rule_id"] = rule_id

    def collect_signals(self, text: str) -> List[RiskSignal]:
        signals: List[RiskSignal] = []
        # include a whole-text "scan" for length based on the raw source
        text = text or ""
        for _, rule in self.rules.items():
            signals.extend(_scan_rule(rule, text))
        return signals

    def assess(self, text: str, segments=None, domain: str = "general") -> RiskAssessment:
        if segments:
            try:
                iter(segments)
            except TypeError:
                segments = None
        # segments are informational here; the full source `text` is scanned.
        signals = self.collect_signals(text)
        scored = RiskScorer.score(signals, domain)
        policy = RiskPolicy.default_for(domain)
        routed = RiskRouter.route(scored, policy)

        return RiskAssessment(
            id=new_id(),
            task_id="",
            score=scored["score"],
            tier=scored["tier"],
            policy_id=str(policy.get("domain", domain)),
            routing=routed["routing"],
            drivers=scored["drivers"],
            signals=scored["signals"],
            auto_export_allowed=bool(routed["auto_export_allowed"]),
            created_at=utc_now(),
        )

    @staticmethod
    def explain(assessment: RiskAssessment) -> str:
        tier = str(assessment.tier)
        label = TIER_CN.get(tier, "中")
        cats = sorted({str(s.get("category", "")) for s in assessment.signals if s})
        desc = "、".join(CATEGORY_CN.get(c, c) for c in cats if c)
        if not desc:
            desc = "未发现明显风险"
        if tier in (RiskTier.L0.value, RiskTier.L1.value):
            advice = "可自动定稿"
        elif tier == RiskTier.L2.value:
            advice = "建议人工确认后手动导出"
        else:
            advice = "不可自动导出，需人工处理"
        return f"{label}风险({tier})：含{desc}，{advice}"


if __name__ == "__main__":  # pragma: no cover - acceptance smoke test
    r = RiskEngine().assess("乙方应承担违约责任并支付违约金", "", domain="legal")
    print(r.to_dict())