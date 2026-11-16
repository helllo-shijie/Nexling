"""Priority ladder + conflict resolution (deterministic, zero model)."""
from __future__ import annotations

from typing import Dict, List

from laa_core.shared import TermHit
from laa_core.shared.types import SCOPE_ORDER

_SCOPE_INDEX = {s.value: i for i, s in enumerate(SCOPE_ORDER)}
_MATCH_INDEX = {"exact": 0, "lemma": 1, "fuzzy": 2}


class PriorityLadder:
    @staticmethod
    def rank(hit: TermHit) -> int:
        return _SCOPE_INDEX.get(hit.scope, 1000)

    @classmethod
    def compare(cls, a: TermHit, b: TermHit) -> int:
        """Return -1 if a outranks b, 1 if b outranks a, 0 if tied."""
        ra, rb = cls.rank(a), cls.rank(b)
        if ra != rb:
            return -1 if ra < rb else 1
        if a.forced != b.forced:
            return -1 if a.forced else 1
        ma, mb = _MATCH_INDEX.get(a.match_mode, 2), _MATCH_INDEX.get(b.match_mode, 2)
        if ma != mb:
            return -1 if ma < mb else 1
        if a.version != b.version:
            return -1 if a.version > b.version else 1
        return 0


class ConflictResolver:
    @staticmethod
    def resolve(hits: List[TermHit], risk_tier: str = "L0") -> Dict:
        # group by overlapping span (using representative source term)
        by_source: Dict[str, List[TermHit]] = {}
        for h in hits:
            by_source.setdefault(h.source_term.lower(), []).append(h)
        applied: List[TermHit] = []
        conflicts: List[Dict] = []
        for source, group in by_source.items():
            unique_targets = {h.target_term for h in group}
            if len(unique_targets) == 1:
                applied.append(max(group, key=lambda h: (-PriorityLadder.rank(h), h.version)))
                continue
            ordered = sorted(group, key=lambda h: (PriorityLadder.rank(h), -(h.version if h.version else 0),
                                                   -int(h.forced)))
            if PriorityLadder.compare(ordered[0], ordered[1]) == 0:
                # genuine tie: cannot auto-decide
                winner = None if risk_tier in ("L2", "L3") else ordered[0]
                conflicts.append({
                    "source_term": source,
                    "candidates": [{"target": h.target_term, "scope": h.scope, "entry_id": h.entry_id,
                                    "version": h.version, "forced": h.forced} for h in ordered],
                    "winner": winner.target_term if winner else None,
                    "entry_id": winner.entry_id if winner else None,
                })
                if winner:
                    applied.append(winner)
            else:
                winner = ordered[0]
                applied.append(winner)
        return {"applied": applied, "conflicts": conflicts,
                "shadowed": [h for h in hits if not h.resolved]}