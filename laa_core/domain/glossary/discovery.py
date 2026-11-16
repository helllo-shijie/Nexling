"""Term discovery: rule-only extraction, binding, review queue, backfill planning."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from laa_core.shared import TermBinding, TermCandidate, TermMention, new_id, utc_now

_ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{1,}\b")
_CAMEL = re.compile(r"\b[a-z]+(?:[A-Z][a-z0-9]+)+\b")
_PASCAL = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b")  # PascalCase：KubernetesPod / WebSocket
_PROPER = re.compile(r"(?<![.!?]\s)(?<!\n)\b[A-Z][a-z]{2,}\b")  # 句中普通专名（跳过句首大写）
_MIXED = re.compile(r"\b[a-z]+[A-Z][A-Za-z0-9]{1,}\b")  # gRPC / iOS / eBay 这类混合大小写
_SNAKE = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b")
_DEFINE_CN = re.compile(r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z\- ]{0,20})[((（]\s*([A-Z][A-Za-z0-9]{1,14})\s*[))）]")
_EN_SUFFIX = re.compile(r"\b[a-z][a-z0-9]{3,}(?:tion|ing|ment|ness|ity|er|or|sion|ance|ence)\b")


class TermExtractor:
    def extract(self, text: str, segments=None, lang: str = "") -> List[TermMention]:
        mentions: List[TermMention] = []
        segs = list(segments) if segments else None
        seen = set()
        n = len(text)

        def add(surface: str, start: int, end: int, kind: str, segment_id: str = "") -> None:
            key = (surface.lower(), start, end)
            if key in seen:
                return
            seen.add(key)
            mentions.append(TermMention(surface=surface, normalized=surface.lower().strip(),
                                        segment_id=segment_id, span=[start, end], kind=kind))

        for pat, kind in ((_ACRONYM, "acronym"), (_MIXED, "camel"), (_CAMEL, "camel"),
                          (_PASCAL, "camel"), (_PROPER, "proper"),
                          (_SNAKE, "snake"), (_EN_SUFFIX, "derived")):
            for m in pat.finditer(text):
                add(m.group(0), m.start(), m.end(), kind)

        for m in _DEFINE_CN.finditer(text):
            add(m.group(2), m.start(2), m.end(2), "definition")

        # Chinese frequent n-gram
        han = re.findall(r"[\u4e00-\u9fff]{2,6}", text)
        freq = Counter(w for w in han if 2 <= len(w) <= 6)
        for w, c in freq.items():
            if c >= 2:
                idx = text.find(w)
                add(w, idx, idx + len(w), "ngram")

        # attach segment id if requested
        if segs:
            for mt in mentions:
                for s in segs:
                    if mt.span[0] >= s.span[0] and mt.span[1] <= s.span[1]:
                        mt.segment_id = s.id
                        break
        return mentions


class TermBinder:
    def bind(self, mentions: List[TermMention], resolved: Dict[str, str]) -> List[TermBinding]:
        groups: Dict[str, List[TermMention]] = defaultdict(list)
        for m in mentions:
            groups[m.normalized].append(m)
        out: List[TermBinding] = []
        for norm, ms in groups.items():
            seg_ids = sorted({m.segment_id for m in ms if m.segment_id})
            source = max(ms, key=lambda m: len(m.surface)).surface
            conf = min(1.0, round(len(ms) / 10.0 + 0.5, 3))
            out.append(TermBinding(
                normalized=norm,
                chosen_target=resolved.get(norm),
                source=source,
                segment_ids=seg_ids,
                confidence=conf,
            ))
        return out


class CandidateExtractor:
    def extract(self, docs: List[dict], domain: str = "general") -> List[TermCandidate]:
        freq: Counter = Counter()
        spans: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        origins: Dict[str, str] = {}
        ex = TermExtractor()
        for doc in docs:
            text = (doc.get("text") or doc.get("snippet") or "")
            doc_id = str(doc.get("title") or doc.get("origin") or "doc")
            for m in ex.extract(text):
                freq[m.normalized] += 1
                spans[m.normalized].append({"doc": doc_id, "span": m.span, "surface": m.surface})
                origins.setdefault(m.normalized, doc_id)
        if not freq:
            return []
        total = sum(freq.values())
        out: List[TermCandidate] = []
        for norm, count in freq.items():
            surface = max(spans[norm], key=lambda s: len(s["surface"]))["surface"]
            # novelty: heuristic 1 - overlap with a tiny common-word stoplist
            stop_penalty = 1.0 if norm in _COMMON_STOP else 0.7
            occ = min(1.0, count / max(1, total) * 4 + 0.5)
            shape = 1.0 if (surface.upper() == surface or "_" in surface or surface[0].isupper()) else 0.7
            define = 1.0 if any(s["surface"].isupper() for s in spans[norm]) else 0.6
            score = round(min(1.0, occ * 0.30 + shape * 0.25 + define * 0.20 + stop_penalty * 0.15 + (0.10 if domain != "general" else 0.05)), 4)
            out.append(TermCandidate(
                id=new_id(), source_term=surface, lang_pair="*",
                domain=domain, origin_source_id=origins.get(norm), occurrences=count,
                novelty=round(score, 3), target_text=None, target_source="none",
                status="pending",
                score={"occurrence": round(occ, 3), "shape": shape, "definition": define,
                       "stop_penalty": stop_penalty, "domain": 0.10 if domain != "general" else 0.05,
                       "total": score},
                evidence_spans=list(spans[norm])[:20],
                created_at=utc_now(),
            ))
        out.sort(key=lambda c: -c.overall_score())
        return out


_COMMON_STOP = {"the", "and", "for", "with", "this", "that", "from", "have", "will", "would",
                "这样", "我们", "他们", "一个", "这个", "因为", "所以"}


class CandidateReviewQueue:
    def __init__(self, candidates: Optional[List[TermCandidate]] = None):
        self._items = list(candidates or [])

    def list(self, filter: Optional[dict] = None) -> List[TermCandidate]:
        items = self._items
        if filter and filter.get("status"):
            items = [c for c in items if c.status == filter["status"]]
        return sorted(items, key=lambda c: -c.overall_score())

    def accept(self, ids: List[str], target_map: Dict[str, str]) -> List[TermCandidate]:
        idset = set(ids)
        changed = []
        for c in self._items:
            if c.id in idset:
                c.status = "accepted"
                if target_map.get(c.id):
                    c.target_text = target_map[c.id]
                    c.target_source = "user"
                changed.append(c)
        return changed

    def reject(self, ids: List[str]) -> List[TermCandidate]:
        idset = set(ids)
        changed = []
        for c in self._items:
            if c.id in idset:
                c.status = "rejected"
                changed.append(c)
        return changed


class BackfillService:
    @staticmethod
    def plan(task_id: str, bindings: List[TermBinding], versions_by_segment: Dict[str, str],
             entry: Optional[dict] = None) -> List[dict]:
        out: List[dict] = []
        for b in bindings:
            if not b.chosen_target:
                continue
            for sid in b.segment_ids:
                seg_text = versions_by_segment.get(sid)
                if seg_text and b.chosen_target not in seg_text:
                    out.append({
                        "task_id": task_id, "term_source": b.source, "normalized": b.normalized,
                        "segment_id": sid, "observed": seg_text,
                        "recommended_target": b.chosen_target,
                        "evidence_spans": [],
                        "confidence": b.confidence,
                    })
        return out