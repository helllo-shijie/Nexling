"""Emotion annotation parsing + alignment (tolerant; never blocks the pipeline)."""
from __future__ import annotations

from typing import Any, Dict, List

from laa_core.shared import EmotionAnnotation, TextSegment

_VALID_EMOTIONS = {"positive", "negative", "urgent", "apology", "emphasis", "humor"}


class EmotionAnnotationParser:
    def parse(self, raw, segments: List[TextSegment]) -> List[EmotionAnnotation]:
        """Parse the model's ``emotions`` field. Any malformed input -> ``[]``.

        ``raw`` may be None, a dict, a list, or the string ``"空"`` (empty).
        """
        if raw is None:
            return []
        if isinstance(raw, str):
            return []
        if not isinstance(raw, (list, dict)):
            return []
        items = raw if isinstance(raw, list) else raw.get("emotions", [])
        if not isinstance(items, list):
            return []
        valid_ids = {s.id for s in segments}
        out: List[EmotionAnnotation] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            emotion = it.get("emotion")
            if emotion not in _VALID_EMOTIONS:
                continue
            segment_id = it.get("segment_id")
            if segment_id not in valid_ids:
                continue
            try:
                intensity = min(3, max(1, int(it.get("intensity", 1))))
            except (TypeError, ValueError):
                intensity = 1
            out.append(EmotionAnnotation(
                emotion=emotion,
                intensity=intensity,
                segment_id=segment_id,
                span=None,
                evidence=str(it.get("evidence", ""))[:100],
                note=str(it.get("note", "")),
                confidence=1.0,
                align_status="pending",
            ))
        return out


class EmotionAligner:
    def align(self, items: List[EmotionAnnotation], segments: List[TextSegment],
              targets: Dict[str, str]) -> List[EmotionAnnotation]:
        seg_by_id = {s.id: s for s in segments}
        for it in items:
            seg = seg_by_id.get(it.segment_id)
            if seg is None:
                it.align_status = "unmatched"
                continue
            if it.evidence and it.evidence in seg.text:
                it.align_status = "matched"
                it.span = None  # evidence located; span resolved at render time
                continue
            # fall back to whole-segment
            it.align_status = "matched"
            it.span = None
        return items