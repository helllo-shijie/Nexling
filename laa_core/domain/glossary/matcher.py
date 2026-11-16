"""Deterministic multi-strategy term matcher (longest match first)."""
from __future__ import annotations

from typing import Dict, List, Optional

from laa_core.shared import TermEntry, TermHit


class TermMatcher:
    def __init__(self):
        self._entries: List[TermEntry] = []

    def build_index(self, entries: List[TermEntry]) -> None:
        self._entries = [e for e in entries if e.deleted_at is None and e.status in ("active", "pending")]
        self._entries.sort(key=lambda e: (-len(e.source_term), e.source_term))

    def _findall(self, text: str, needle: str, case_sensitive: bool) -> List[int]:
        if not needle:
            return []
        hay = text if case_sensitive else text.lower()
        nd = needle if case_sensitive else needle.lower()
        idxs: List[int] = []
        start = 0
        while True:
            i = hay.find(nd, start)
            if i < 0:
                break
            idxs.append(i)
            start = i + max(1, len(needle))
        return idxs

    def scan(self, text: str, src_lang: str, tgt_lang: str, scene_id: Optional[str] = None) -> List[TermHit]:
        hits: List[TermHit] = []
        for e in self._entries:
            if e.src_lang not in ("*", src_lang):
                continue
            if e.tgt_lang not in ("*", tgt_lang):
                continue
            target = e.target_term
            if scene_id and e.scene_variants and scene_id in e.scene_variants:
                target = e.scene_variants[scene_id]
            for start in self._findall(text, e.source_term, e.case_sensitive):
                hits.append(TermHit(
                    entry_id=e.id, source_term=e.source_term, target_term=target,
                    bank_id=e.bank_id, scope=e.refs.get("scope", "personal") if isinstance(e.refs, dict) else "personal",
                    forced=e.forced, span=[start, start + len(e.source_term)],
                    match_mode=e.match_mode or "exact", domain=e.domain, version=e.version,
                    resolved=True, shadowed_by=None,
                ))
        # longest match wins: sort by (len desc, start asc), greedily accept non-overlapping
        hits.sort(key=lambda h: (-(h.span[1] - h.span[0]), h.span[0]))
        accepted: List[TermHit] = []
        occupied: List[List[int]] = []
        for h in hits:
            if any(not (h.span[1] <= s[0] or h.span[0] >= s[1]) for s in occupied):
                h.resolved = False
            else:
                occupied.append(h.span)
                accepted.append(h)
        return hits  # return all (with shadowing info for resolver to present conflicts)


def build_hits(entries: List[TermEntry], text: str, src_lang: str, tgt_lang: str) -> List[TermHit]:
    m = TermMatcher()
    m.build_index(entries)
    return m.scan(text, src_lang, tgt_lang)