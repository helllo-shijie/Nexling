"""Direct-fix planning, parsing, and application (spec §6.12 + §6.13 fix flow).

No model call happens here: ``QAFixPlanner.plan`` only bundles the issues per
segment into a request; ``FixParser``/``FixApplier`` consume the model's raw
output and apply it deterministically.
"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional


def _as_dict(obj: Any) -> Dict[str, Any]:
    """把 issue/术语命中统一转成 dict（dataclass、带 to_dict 的对象、普通 dict 都兼容）。"""
    if hasattr(obj, "to_dict"):
        try:
            return obj.to_dict()
        except Exception:  # noqa: BLE001 - 退化到 asdict
            pass
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    try:
        return dict(obj)
    except (TypeError, ValueError):
        return {"value": str(obj)}


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (0 if ca == cb else 1)))
        prev = cur
    return prev[-1]


def _change_ratio(base: str, fixed: str) -> float:
    denom = max(len(base), len(fixed), 1)
    return round(_levenshtein(base, fixed) / denom, 4)


class QAFixPlanner:
    """Merge a segment's issues into a single fix request (zero model)."""

    @staticmethod
    def plan(reports, segments, drafts, terms, risk) -> Dict[str, Any]:
        seg_map = {s.id: s for s in (segments or [])}
        if isinstance(drafts, dict):
            draft_map = drafts
        else:
            draft_map = {}
            for s in (segments or []):
                idx = getattr(s, "index", 0)
                if idx < len(list(drafts or [])):
                    draft_map[s.id] = list(drafts)[idx]
                else:
                    draft_map[s.id] = ""

        requests: List[Dict[str, Any]] = []
        for rep in (reports or []):
            issues = list(getattr(rep, "issues", []) or [])
            if not issues:
                continue
            seg_id = getattr(rep, "segment_id", "")
            seg = seg_map.get(seg_id)
            requests.append({
                "segment_id": seg_id,
                "base_text": draft_map.get(seg_id, ""),
                "issues": [_as_dict(i) for i in issues],
                "hard_terms": [_as_dict(t) for t in (terms or []) if t is not None],
                "context": {
                    "source_text": getattr(seg, "text", "") if seg else "",
                    "risk_tier": (risk.get("tier")
                                  if isinstance(risk, dict)
                                  else getattr(risk, "tier", None)),
                },
            })
        return {"requests": requests, "count": len(requests)}


class FixParser:
    """Parse a model's raw fix output (dict or JSON string) into items."""

    @staticmethod
    def parse(raw) -> Dict[str, Any]:
        try:
            if isinstance(raw, str):
                data = json.loads(raw)
            elif isinstance(raw, dict):
                data = raw
            else:
                return {"items": [], "parse_status": "failed"}

            if isinstance(data, dict):
                if "items" in data:
                    raw_items = data["items"]
                elif "segment_id" in data:
                    raw_items = [data]
                else:
                    raw_items = []
            elif isinstance(data, list):
                raw_items = data
            else:
                raw_items = []

            items: List[Dict[str, Any]] = []
            for it in raw_items:
                if not isinstance(it, dict):
                    continue
                items.append({
                    "segment_id": str(it.get("segment_id", "")),
                    "action": str(it.get("action", "keep")),
                    "fixed_text": str(it.get("fixed_text", "")),
                    "confidence": float(it.get("confidence", 0.0)),
                    "reason": str(it.get("reason", "")),
                })
            return {"items": items, "parse_status": "ok"}
        except Exception:
            return {"items": [], "parse_status": "failed"}


class FixApplier:
    """Apply a parsed fix item iff it is a bounded rewrite."""

    @staticmethod
    def apply(base, result_item, policy=None) -> Dict[str, Any]:
        policy = dict(policy or {})
        max_change_ratio = float(policy.get("max_change_ratio", 0.4))
        # min_confidence is accepted for interface parity; per spec the gate is
        # action == rewrite AND change_ratio within the limit.
        base = base or ""
        item = dict(result_item or {})
        action = str(item.get("action", "keep"))
        fixed_text = str(item.get("fixed_text", ""))
        ratio = _change_ratio(base, fixed_text)

        if action == "rewrite" and ratio <= max_change_ratio:
            return {"applied": True, "new_text": fixed_text, "change_ratio": ratio}
        return {"applied": False, "new_text": base, "change_ratio": ratio}


if __name__ == "__main__":  # pragma: no cover - smoke test
    raw = json.dumps({"items": [
        {"segment_id": "s1", "action": "rewrite",
         "fixed_text": "用户应支付100美元。", "confidence": 0.9, "reason": "数字单位"}]})
    parsed = FixParser.parse(raw)
    print(parsed)
    print(FixApplier.apply("用户应 用户 支付 100 美元。", parsed["items"][0]))