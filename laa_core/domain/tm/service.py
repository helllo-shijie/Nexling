"""Deterministic translation-memory recall (spec §6.14).

Three recall channels — exact (source hash), fuzzy (normalized edit distance),
keyword (substring/token overlap) — merged and deduped to a top-5 list.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from laa_core.shared import TmHit, TMEntry, new_id
from laa_core.shared.terms import term_hit

EXACT_QUALITY = 0.8
FUZZY_THRESHOLD = 0.85
TOP_K = 5
KEYWORD_K = 3

_KIND_RANK = {"exact": 0, "fuzzy": 1, "keyword": 2}
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


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


def _similarity(a: str, b: str) -> float:
    denom = max(len(a), len(b), 1)
    return 1.0 - _levenshtein(a, b) / denom


def _keyword_overlap(a: str, b: str) -> float:
    ta = {t for t in _TOKEN_RE.findall(a) if t}
    tb = {t for t in _TOKEN_RE.findall(b) if t}
    if not ta and not tb:
        return 0.0
    if len(ta) == 0 or len(tb) == 0:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    score = inter / union if union else 0.0
    # substring bonus: one source contained in the other is a strong signal
    if (a in b or b in a) and score < 0.6:
        score = max(score, 0.6)
    return score


def _hit(entry: Dict[str, Any], score: float, kind: str) -> TmHit:
    return TmHit(
        entry_id=entry.get("id", ""),
        source_text=entry.get("source_text", ""),
        target_text=entry.get("target_text", ""),
        score=round(float(score), 4),
        match_kind=kind,
        glossary_version=int(entry.get("glossary_version", 0) or 0),
        stale=False,
    )


class TranslationMemoryService:
    """Recall + write-back against a duck-typed repo."""

    def __init__(self, repo) -> None:
        self.repo = repo

    def lookup(self, source_text: str, src_lang: str, tgt_lang: str,
               domain: str = "general", include_drafts: bool = False) -> List[TmHit]:
        norm_src = _normalize(source_text)
        lang_pair = f"{src_lang}-{tgt_lang}"
        by_id: Dict[str, TmHit] = {}

        def usable(e: Dict[str, Any]) -> bool:
            """未审草稿默认不参与召回，避免机器草稿被当成可靠记忆复用。"""
            if e.get("stale"):
                return False
            return bool(e.get("approved")) or include_drafts

        # 1) exact channel
        digest = hashlib.sha256(norm_src.encode("utf-8")).hexdigest()
        for e in self.repo.find_tm_exact(digest, lang_pair) or []:
            if not usable(e):
                continue
            by_id[e.get("id")] = _hit(e, 1.0, "exact")

        # 2) fuzzy + keyword channels over the whole (same lang pair) memory
        fuzzy: List[Tuple[float, Dict[str, Any]]] = []
        keyword: List[Tuple[float, Dict[str, Any]]] = []
        for e in self.repo.list_tm() or []:
            if not usable(e):
                continue
            if e.get("lang_pair") != lang_pair:
                continue
            e_src = _normalize(e.get("source_text", ""))
            sim = _similarity(norm_src, e_src)
            if sim >= FUZZY_THRESHOLD:
                fuzzy.append((sim, e))
            else:
                kw = _keyword_overlap(norm_src, e_src)
                if kw > 0.0:
                    keyword.append((kw, e))

        for sim, e in fuzzy:
            eid = e.get("id")
            if eid not in by_id:
                by_id[eid] = _hit(e, sim, "fuzzy")

        keyword.sort(key=lambda x: (-x[0], x[1].get("id", "")))
        for kw, e in keyword[:KEYWORD_K]:
            eid = e.get("id")
            if eid not in by_id:
                by_id[eid] = _hit(e, kw, "keyword")

        hits = list(by_id.values())
        hits.sort(key=lambda h: (-h.score, _KIND_RANK.get(h.match_kind, 9),
                                 h.entry_id))
        return hits[:TOP_K]

    def store(self, draft_src: str, draft_tgt: str, src_lang: str, tgt_lang: str,
              domain: str = "general", approved: bool = False,
              scene_profile_id: Optional[str] = None,
              quality: Optional[float] = None,
              skip_if_exists: bool = False) -> TMEntry:
        norm_src = _normalize(draft_src)
        digest = hashlib.sha256(norm_src.encode("utf-8")).hexdigest()
        lang_pair = f"{src_lang}-{tgt_lang}"
        existing = None
        if skip_if_exists:
            existing = next(
                (e for e in self.repo.find_tm_exact(digest, lang_pair) or []
                 if bool(e.get("approved"))), None,
            )
        if existing is not None:
            # 同句对译法未变：直接复用，不产生重复条目；
            # 若此前因术语变更被标 stale，重新确认同一句对即视为再次确认，清掉失效标记。
            if _normalize(str(existing.get("target_text") or "")) == _normalize(draft_tgt or ""):
                if int(existing.get("stale") or 0):
                    existing = dict(existing)
                    existing["stale"] = 0
                    self.repo.upsert_tm(existing)
                return TMEntry(**{k: existing.get(k) for k in (
                    "id", "source_hash", "source_text", "target_text", "lang_pair",
                    "domain", "scene_profile_id", "approved", "quality",
                    "glossary_version", "prompt_fingerprint", "stale", "use_count",
                    "last_used_at", "created_at",
                ) if k in existing})
            # 同句对译法已更新：就地覆盖旧记忆，避免 skip_if_exists 把记忆永久锁死
            existing = dict(existing)
            existing.update({
                "target_text": draft_tgt or "",
                "domain": domain,
                "scene_profile_id": scene_profile_id,
                "quality": float(quality if quality is not None else 1.0),
                "glossary_version": int(existing.get("glossary_version") or 0),
                "stale": 0,
                "last_used_at": existing.get("last_used_at") or "",
                "created_at": existing.get("created_at") or "",
            })
            self.repo.upsert_tm(existing)
            return TMEntry(**{k: existing.get(k) for k in (
                "id", "source_hash", "source_text", "target_text", "lang_pair",
                "domain", "scene_profile_id", "approved", "quality",
                "glossary_version", "prompt_fingerprint", "stale", "use_count",
                "last_used_at", "created_at",
            ) if k in existing})
        entry = TMEntry(
            id=new_id(),
            source_hash=digest,
            source_text=draft_src or "",
            target_text=draft_tgt or "",
            lang_pair=lang_pair,
            domain=domain,
            scene_profile_id=scene_profile_id,
            approved=bool(approved),
            quality=float(quality if quality is not None else (1.0 if approved else 0.6)),
            stale=False,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self.repo.upsert_tm(entry.to_dict())
        return entry

    def enforce_limit(self, max_entries: int) -> int:
        """按条数上限清理记忆：最老优先删除，返回删除条数。0 表示无上限。"""
        if max_entries <= 0:
            return 0
        rows = list(self.repo.list_tm() or [])
        excess = len(rows) - max_entries
        if excess <= 0:
            return 0
        rows.sort(key=lambda e: (str(e.get("created_at") or ""),))
        removed = 0
        for e in rows[:excess]:
            if self.repo.delete_tm(str(e.get("id") or "")):
                removed += 1
        return removed

    def mark_used(self, entry_id: str) -> bool:
        """采用某条记忆时累加使用次数（透明化面板展示的是真实数据）。"""
        if not entry_id:
            return False
        for e in self.repo.list_tm() or []:
            if e.get("id") == entry_id:
                e = dict(e)
                e["use_count"] = int(e.get("use_count") or 0) + 1
                e["last_used_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                self.repo.upsert_tm(e)
                return True
        return False

    def invalidate_by_terms(self, terms) -> int:
        """只让 source_text 命中这些术语的句对失效。返回受影响条数。

        术语命中规则与任务术语统一共用 `shared.terms.term_hit`：ASCII 词按词边界
        （cache 不会命中 CacheGate），CJK 词按子串（"神经元" 会命中 "神经元的"）。
        空术语忽略，重复去重。
        """
        needles: List[str] = []
        seen = set()
        for raw in terms or []:
            term = str(raw or "").strip()
            if not term or term.lower() in seen:
                continue
            seen.add(term.lower())
            needles.append(term)
        if not needles:
            return 0
        count = 0
        for e in list(self.repo.list_tm() or []):
            if int(e.get("stale") or 0):
                continue
            src = str(e.get("source_text") or "")
            if any(term_hit(src, term) for term in needles):
                e = dict(e)
                e["stale"] = 1
                self.repo.upsert_tm(e)
                count += 1
        return count

    def restore(self, entry_id: str) -> bool:
        """用户确认后恢复一条失效记忆（清 stale），不影响其它句对。"""
        if not entry_id:
            return False
        for e in self.repo.list_tm() or []:
            if e.get("id") == entry_id:
                if not int(e.get("stale") or 0):
                    return True
                e = dict(e)
                e["stale"] = 0
                self.repo.upsert_tm(e)
                return True
        return False


if __name__ == "__main__":  # pragma: no cover - smoke test
    class _Mem:
        def __init__(self):
            self.rows = []

        def find_tm_exact(self, h, lp):
            return [e for e in self.rows if e["source_hash"] == h and e["lang_pair"] == lp]

        def list_tm(self):
            return list(self.rows)

        def upsert_tm(self, e):
            self.rows.append(e)

    repo = _Mem()
    svc = TranslationMemoryService(repo)
    svc.store("你好世界", "Hello world", "zh-Hans", "en")
    print([h.to_dict() for h in svc.lookup("你好世界", "zh-Hans", "en")])