"""Deterministic offline provider (FakeProvider) for tests and keyless demo.

Produces valid, reproducible output structure directly from the PromptPlan with no
network, no model, and no randomness. Real translation requires a real provider.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List

from ...shared.dto import PromptPlan


def _pseudo_sentiment(text: str) -> Dict[str, float]:
    """离线演示用的确定性情感概率（真实概率由模型给出）。"""
    t = (text or "").lower()
    if any(w in t for w in ("error", "fail", "bug", "错误", "失败", "无法", "崩溃")):
        return {"positive": 0.06, "negative": 0.82, "neutral": 0.12}
    if any(w in t for w in ("thank", "great", "nice", "谢谢", "很好", "棒")):
        return {"positive": 0.79, "negative": 0.04, "neutral": 0.17}
    if t.strip().endswith("?"):
        return {"positive": 0.18, "negative": 0.10, "neutral": 0.72}
    return {"positive": 0.16, "negative": 0.09, "neutral": 0.75}


class FakeProvider:
    provider_id = "fake"
    kind = "translate"

    def __init__(self, label: str = "离线演示(确定性)"):
        self.label = label

    def _pseudo(self, source: str, terms: list, mode: str) -> str:
        gloss = " ".join(f"{t.source_term}→{t.target_term}" for t in terms[:4])
        prefix = "〔离线引擎·未接入真实 API，译文未生成〕"
        if terms:
            return f"{prefix}\n原文：{source}\n术语：{gloss}"
        return f"{prefix}\n原文：{source}"

    def translate(self, plan: PromptPlan, segments: list) -> Dict[str, Any]:
        terms = plan.glossary_terms or []
        mode = plan.mode or "fluent"
        out_segments = []
        for seg in segments:
            sid = seg["id"] if isinstance(seg, dict) else seg.id
            stext = seg["text"] if isinstance(seg, dict) else seg.text
            out_segments.append({"segment_id": sid, "target_text": self._pseudo(stext, terms, mode),
                                 "sentiment": _pseudo_sentiment(stext)})
        emotions: List[Dict[str, Any]] = []
        for seg in segments:
            stext = seg["text"] if isinstance(seg, dict) else seg.text
            t = stext.lstrip()
            if t.lower().startswith(("thanks", "thank you", "谢谢", "please")):
                emotions.append({"emotion": "positive", "segment_id": seg.get("id") if isinstance(seg, dict) else seg.id,
                                 "evidence": t[:24].strip(), "intensity": 1, "note": "offline-demo"})
        return {"segments": out_segments, "emotions": emotions}

    def split_sentences(self, text: str, lang: str = "") -> Dict[str, Any]:
        """离线兜底分句：稳定、可复现，短碎片并入相邻句。"""
        from ...domain.text.service import _merge_tiny_spans, _sentence_spans

        spans = _merge_tiny_spans(_sentence_spans(text), text)
        return {"sentences": [text[s:e] for s, e in spans],
                "usage": {"input_tokens": 0, "output_tokens": 0}}

    def complete(self, messages: List[Dict[str, str]], *, response_format: str = "json_object", max_tokens: int = 2048) -> Dict[str, Any]:
        return {"content": '{"segments": [], "emotions": "空"}', "usage": {"input_tokens": 0, "output_tokens": 0}}

    def health(self) -> Dict[str, Any]:
        return {"ok": True, "latency_ms": 0, "detail": "fake provider always healthy"}

    def capabilities(self) -> Dict[str, Any]:
        return {"input": ["text"], "output": ["text"], "supports_stream": False, "source_channel": "offline"}