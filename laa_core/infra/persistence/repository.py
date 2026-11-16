"""Convenience repositories: in-memory (offline tests) + task-focused facade."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .database import LaaRepository


class InMemoryRepository:
    """Dict-backed repository implementing the same duck-typed interface, for tests/CLI."""

    def __init__(self) -> None:
        self._banks: Dict[str, dict] = {}
        self._entries: Dict[str, dict] = {}
        self._scenes: Dict[str, dict] = {}
        self._tasks: Dict[str, dict] = {}
        self._segments: Dict[str, list] = {}
        self._versions: Dict[str, list] = {}
        self._tm: Dict[str, dict] = {}
        self._usage: List[dict] = []
        self._calls: List[dict] = []
        self._config: Dict[str, Any] = {}
        self._providers: Dict[str, dict] = {}
        self._term_candidates: Dict[str, dict] = {}
        self._task_terms: Dict[str, Dict[str, dict]] = {}

    # glossary
    def list_banks(self) -> List[dict]:
        return list(self._banks.values())

    def get_bank(self, bank_id: str) -> Optional[dict]:
        return self._banks.get(bank_id)

    def save_bank(self, bank: dict) -> None:
        self._banks[bank["id"]] = dict(bank)

    def list_entries(self, bank_id: str) -> List[dict]:
        return sorted(
            (dict(e) for e in self._entries.values() if e.get("bank_id") == bank_id and not e.get("deleted_at")),
            key=lambda e: e["source_term"],
        )

    def get_entry(self, entry_id: str) -> Optional[dict]:
        e = self._entries.get(entry_id)
        return dict(e) if e else None

    def save_entry(self, entry: dict) -> None:
        e = dict(entry)
        e.setdefault("tags", [])
        e.setdefault("refs", {})
        e.setdefault("scene_variants", {})
        self._entries[e["id"]] = e

    def delete_entry(self, entry_id: str, hard: bool = False) -> None:
        if hard:
            self._entries.pop(entry_id, None)
        elif entry_id in self._entries:
            self._entries[entry_id]["deleted_at"] = "2026-01-01T00:00:00.000Z"

    def next_bank_version(self, bank_id: str) -> int:
        b = self._banks.get(bank_id)
        return (b["version"] if b else 0) + 1

    # scenes
    def list_scenes(self) -> List[dict]:
        return sorted(self._scenes.values(), key=lambda s: (-int(s.get("is_default", 0)), s["name"]))

    def get_scene(self, scene_id: str) -> Optional[dict]:
        s = self._scenes.get(scene_id)
        return dict(s) if s else None

    def save_scene(self, scene: dict) -> None:
        self._scenes[scene["id"]] = dict(scene)

    def delete_scene(self, scene_id: str, hard: bool = False) -> None:
        self._scenes.pop(scene_id, None)

    # tasks/segments/versions
    def save_task(self, task: dict) -> None:
        self._tasks[task["id"]] = dict(task)

    def get_task(self, task_id: str) -> Optional[dict]:
        t = self._tasks.get(task_id)
        return dict(t) if t else None

    def list_tasks(self) -> List[dict]:
        return list(self._tasks.values())

    def list_tasks_page(self, limit: int = 30, offset: int = 0) -> dict:
        items = sorted(self._tasks.values(), key=lambda t: (t.get("created_at") or "", t.get("id") or ""), reverse=True)
        page = items[offset: offset + limit]
        out = [{
            "task_id": t["id"], "source_text": t.get("source_text") or "",
            "src_lang": t.get("src_lang") or "auto", "tgt_lang": t.get("tgt_lang") or "",
            "mode": t.get("mode") or "fluent", "status": t.get("status") or "",
            "segment_count": int(t.get("segment_count") or 0),
            "created_at": t.get("created_at") or "", "completed_at": t.get("completed_at"),
        } for t in page]
        return {"items": out, "total": len(items)}

    # model call log（调用历史）
    def append_call(self, entry: dict) -> None:
        self._calls.append(dict(entry))

    def list_calls(self, limit: int = 20, offset: int = 0, task_id: Optional[str] = None) -> dict:
        items = [c for c in self._calls if not task_id or c.get("task_id") == task_id]
        items.sort(key=lambda c: (c.get("created_at") or "", c.get("id") or ""), reverse=True)
        return {"items": items[offset: offset + limit], "total": len(items)}

    def get_call(self, call_id: str) -> Optional[dict]:
        for c in self._calls:
            if c.get("id") == call_id:
                return dict(c)
        return None

    def count_calls(self) -> int:
        return len(self._calls)

    def trim_calls(self, keep: int) -> int:
        keep = max(0, int(keep))
        ordered = sorted(self._calls, key=lambda c: (c.get("created_at") or "", c.get("id") or ""),
                         reverse=True)
        removed = len(ordered) - keep
        if removed <= 0:
            return 0
        self._calls = ordered[:keep]
        return removed

    def delete_calls_before(self, cutoff: str) -> int:
        before = len(self._calls)
        self._calls = [c for c in self._calls if (c.get("created_at") or "") >= cutoff]
        return before - len(self._calls)

    def clear_calls(self) -> int:
        removed = len(self._calls)
        self._calls = []
        return removed

    def update_task(self, task_id: str, patch: dict) -> Optional[dict]:
        cur = self._tasks.get(task_id)
        if not cur:
            return None
        merged = {**cur, **patch}
        self._tasks[task_id] = merged
        return merged

    def save_segment(self, seg: dict) -> None:
        self._segments.setdefault(seg["task_id"], [])
        lst = self._segments[seg["task_id"]]
        for i, s in enumerate(lst):
            if s["id"] == seg["id"]:
                lst[i] = seg
                return
        lst.append(seg)

    def list_segments(self, task_id: str) -> List[dict]:
        return sorted(self._segments.get(task_id, []), key=lambda s: s["idx"])

    def get_segment(self, segment_id: str) -> Optional[dict]:
        for lst in self._segments.values():
            for s in lst:
                if s["id"] == segment_id:
                    return dict(s)
        return None

    # 任务级术语译法（全篇一致性）
    _TERM_ORIGIN_RANK = {"model": 1, "glossary": 2, "user": 3}

    def list_task_terms(self, task_id: str) -> List[dict]:
        return [dict(v) for v in self._task_terms.get(task_id, {}).values()]

    def upsert_task_term(self, row: dict) -> dict:
        task_terms = self._task_terms.setdefault(row["task_id"], {})
        source = row["source_term"]
        origin = row.get("origin") or "model"
        prev = task_terms.get(source)
        if prev and self._TERM_ORIGIN_RANK.get(origin, 0) < self._TERM_ORIGIN_RANK.get(prev.get("origin"), 0):
            return dict(prev)
        item = {
            "task_id": row["task_id"], "source_term": source, "target_term": row["target_term"],
            "term_id": row.get("term_id") or "", "origin": origin,
            "segment_id": row.get("segment_id") or "", "updated_at": row.get("updated_at") or "",
        }
        task_terms[source] = item
        return dict(item)

    def save_version(self, version: dict) -> None:
        v = dict(version)
        v["spans"] = [s.to_dict() if hasattr(s, "to_dict") else s for s in (v.get("spans") or [])]
        v["words"] = [dict(w) for w in (v.get("words") or []) if isinstance(w, dict)]
        self._versions.setdefault(v["segment_id"], []).append(v)

    def list_versions(self, segment_id: str) -> List[dict]:
        return list(self._versions.get(segment_id, []))

    def latest_version(self, segment_id: str) -> Optional[dict]:
        vs = self._versions.get(segment_id, [])
        return vs[-1] if vs else None

    def get_version(self, version_id: str) -> Optional[dict]:
        for lst in self._versions.values():
            for v in lst:
                if v.get("id") == version_id:
                    return dict(v)
        return None

    # tm
    def upsert_tm(self, entry: dict) -> None:
        self._tm[entry["id"]] = dict(entry)

    def list_tm(self) -> List[dict]:
        # dict 保持插入顺序，先按 created_at 再按插入顺序即为「最老优先」
        return sorted(self._tm.values(), key=lambda e: (e.get("created_at") or "",))

    def find_tm_exact(self, source_hash: str, lang_pair: str) -> List[dict]:
        return [e for e in self._tm.values() if e.get("source_hash") == source_hash and e.get("lang_pair") == lang_pair]

    def delete_tm(self, entry_id: str) -> bool:
        return self._tm.pop(entry_id, None) is not None

    # usage
    def append_usage(self, entry: dict) -> None:
        self._usage.append(dict(entry))

    def sum_usage(self, group_by: str = "provider", exclude_providers=None) -> List[dict]:
        col = group_by if group_by in ("provider", "purpose", "model") else "provider"
        excluded = {p for p in (exclude_providers or []) if p}
        agg: Dict[str, dict] = {}
        for e in self._usage:
            if e.get("provider") in excluded:
                continue
            k = e.get("created_at", "")[:10] if group_by == "day" else e.get(col, "n/a")
            a = agg.setdefault(k, {"k": k, "input_tokens": 0, "output_tokens": 0, "amount": 0.0, "n": 0})
            a["input_tokens"] += e.get("input_tokens", 0)
            a["output_tokens"] += e.get("output_tokens", 0)
            a["amount"] += e.get("amount", 0.0)
            a["n"] += 1
        return list(agg.values())

    def usage_totals(self, exclude_providers=None) -> dict:
        excluded = {p for p in (exclude_providers or []) if p}
        totals = {"input_tokens": 0, "output_tokens": 0, "amount": 0.0, "calls": 0}
        for e in self._usage:
            if e.get("provider") in excluded:
                continue
            totals["input_tokens"] += e.get("input_tokens", 0)
            totals["output_tokens"] += e.get("output_tokens", 0)
            totals["amount"] += e.get("amount", 0.0)
            totals["calls"] += 1
        return totals

    def usage_range(self) -> dict:
        stamps = sorted(e.get("created_at", "") for e in self._usage if e.get("created_at"))
        return {"first_at": stamps[0] if stamps else None,
                "last_at": stamps[-1] if stamps else None}

    def list_usage(self, limit: int = 50, offset: int = 0, provider=None) -> dict:
        indexed = [(i, e) for i, e in enumerate(self._usage)
                   if provider is None or e.get("provider") == provider]
        indexed.sort(key=lambda ie: (ie[1].get("created_at", ""), ie[0]), reverse=True)
        items = [e for _, e in indexed]
        total = len(items)
        return {"items": items[offset:offset + limit], "total": total}

    # config/providers
    def get_config(self, key: str, default=None):
        return self._config.get(key, default)

    def set_config(self, key: str, value) -> None:
        self._config[key] = value

    def list_providers(self) -> List[dict]:
        return list(self._providers.values())

    def save_provider(self, profile: dict) -> None:
        self._providers[profile["id"]] = dict(profile)

    def delete_provider(self, provider_id: str) -> None:
        self._providers.pop(provider_id, None)

    # term candidates（术语发现闭环）
    def upsert_term_candidate(self, cand: dict) -> None:
        key = (cand.get("normalized", ""), cand.get("target_lang", ""), cand.get("task_id", ""))
        for cid, cur in self._term_candidates.items():
            if (cur.get("normalized", ""), cur.get("target_lang", ""), cur.get("task_id", "")) == key:
                if (cur.get("status") or "pending") != "pending":
                    return
                merged = dict(cur)
                merged["occurrences"] = max(
                    int(cur.get("occurrences", 1)), int(cand.get("occurrences", 1))
                )
                merged["confidence"] = max(float(cur.get("confidence") or 0), float(cand.get("confidence") or 0))
                merged["updated_at"] = cand.get("updated_at", merged.get("updated_at", ""))
                merged["context"] = cand.get("context", merged.get("context", ""))
                self._term_candidates[cid] = merged
                return
        self._term_candidates[cand["id"]] = dict(cand)

    def list_term_candidates(self, status: Optional[str] = None, limit: int = 200,
                             task_id: Optional[str] = None) -> List[dict]:
        items = [dict(c) for c in self._term_candidates.values()
                 if (not status or c.get("status") == status)
                 and (not task_id or str(c.get("task_id") or "") == task_id)]
        items.sort(key=lambda c: (-(c.get("confidence") or 0), -(c.get("occurrences") or 0),
                                  c.get("updated_at") or ""))
        return items[:limit]

    def get_term_candidate(self, cand_id: str) -> Optional[dict]:
        hit = self._term_candidates.get(cand_id)
        return dict(hit) if hit else None

    def update_term_candidate(self, cand_id: str, patch: dict) -> Optional[dict]:
        cur = self._term_candidates.get(cand_id)
        if cur is None:
            return None
        merged = {**cur, **patch, "id": cand_id}
        self._term_candidates[cand_id] = merged
        return dict(merged)

    def count_term_candidates(self, task_id: Optional[str] = None) -> dict:
        out = {"pending": 0, "accepted": 0, "ignored": 0}
        for c in self._term_candidates.values():
            if task_id and str(c.get("task_id") or "") != task_id:
                continue
            out[c.get("status") or "pending"] = out.get(c.get("status") or "pending", 0) + 1
        return out

    def trim_term_candidates(self, status: str, keep: int) -> int:
        """只保留最新 keep 条（按 created_at 最老优先删除），返回删除条数。"""
        if keep < 0:
            return 0
        rows = [c for c in self._term_candidates.values() if (c.get("status") or "pending") == status]
        excess = len(rows) - keep
        if excess <= 0:
            return 0
        rows.sort(key=lambda c: (c.get("created_at") or "",))
        for c in rows[:excess]:
            self._term_candidates.pop(c.get("id"), None)
        return excess

    def delete_term_candidates(self, status: Optional[str] = None, task_id: Optional[str] = None) -> int:
        ids = [cid for cid, c in self._term_candidates.items()
               if (not status or (c.get("status") or "pending") == status)
               and (not task_id or str(c.get("task_id") or "") == task_id)]
        for cid in ids:
            self._term_candidates.pop(cid, None)
        return len(ids)


class TaskRepository:
    """Task-focused facade over the underlying repository."""

    def __init__(self, repo):
        self._repo = repo

    def get(self, task_id: str) -> Optional[dict]:
        return self._repo.get_task(task_id)

    def save(self, task: dict) -> None:
        self._repo.save_task(task)

    def update(self, task_id: str, patch: dict) -> Optional[dict]:
        return self._repo.update_task(task_id, patch)

    def list(self) -> List[dict]:
        return self._repo.list_tasks()