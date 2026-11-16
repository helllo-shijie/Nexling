"""Glossary service: pools, matching, import/export, package reader (deterministic)."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Dict, List, Optional

from laa_core.shared import TermBank, TermEntry, TermHit, TermOverride, err, new_id, utc_now
from .matcher import TermMatcher
from .resolver import ConflictResolver
from .discovery import BackfillService

BUILTIN_ENTRIES = [
    ("garbage collection", "垃圾回收"), ("neural network", "神经网络"), ("deadlock", "死锁"),
    ("cache", "缓存"), ("compiler", "编译器"), ("latency", "延迟"), ("throughput", "吞吐量"),
    ("deadline", "截止时间"), ("workflow", "工作流"), ("agent", "智能体"), ("token", "令牌"),
    ("embedding", "嵌入"), ("fine-tuning", "微调"), ("inference", "推理"), ("open source", "开源"),
]

READONLY_SCOPES = {"builtin", "official", "community", "team"}


class GlossaryService:
    def __init__(self, repo=None):
        self._repo = repo
        self._overrides: Dict[str, List[TermOverride]] = {}
        self._seed()

    def _seed(self) -> None:
        if self._repo is not None:
            banks = {b["id"] for b in self._repo.list_banks()}
            if "builtin-default" not in banks:
                self._repo.save_bank({"id": "builtin-default", "scope": "builtin", "name": "内置基础术语",
                                      "src_lang": "*", "tgt_lang": "*", "domain": "general",
                                      "readonly": 1, "version": 1, "entry_count": 0,
                                      "owner": "builtin", "created_at": utc_now(), "updated_at": utc_now()})
                for i, (src, tgt) in enumerate(BUILTIN_ENTRIES):
                    self._repo.save_entry(self._mk_entry("builtin-default", src, tgt, "builtin", i, forced=True))
            if "personal-default" not in banks:
                self._repo.save_bank({"id": "personal-default", "scope": "personal", "name": "个人术语库",
                                      "src_lang": "*", "tgt_lang": "*", "domain": "general",
                                      "readonly": 0, "version": 1, "entry_count": 0,
                                      "owner": "local", "created_at": utc_now(), "updated_at": utc_now()})

    def _mk_entry(self, bank_id, src, tgt, scope, idx, forced=False) -> dict:
        eid = new_id()
        return {"id": eid, "bank_id": bank_id, "source_term": src, "target_term": tgt,
                "src_lang": "*", "tgt_lang": "*", "domain": "general", "case_sensitive": 0,
                "match_mode": "exact", "forced": int(forced), "status": "active", "confidence": 1.0,
                "origin": "builtin" if scope == "builtin" else "manual", "tags": [],
                "version": 1, "refs": {"scope": scope, "bank_name": scope},
                "scene_variants": {}, "deleted_at": None}

    def _all_entries(self, bank_ids=None) -> List[TermEntry]:
        out: List[TermEntry] = []
        if self._repo is not None:
            for bank in self._repo.list_banks():
                if bank_ids and bank["id"] not in bank_ids:
                    continue
                for d in self._repo.list_entries(bank["id"]):
                    refs = dict(d.get("refs") or {})
                    refs.setdefault("scope", bank.get("scope", "personal"))
                    out.append(TermEntry(id=d["id"], bank_id=d["bank_id"], source_term=d["source_term"],
                                         target_term=d["target_term"], src_lang=d["src_lang"],
                                         tgt_lang=d["tgt_lang"], domain=d.get("domain", "general"),
                                         part_of_speech=d.get("part_of_speech"), definition=d.get("definition"),
                                         case_sensitive=bool(d.get("case_sensitive")), match_mode=d.get("match_mode", "exact"),
                                         forced=bool(d.get("forced")), status=d.get("status", "active"),
                                         confidence=d.get("confidence", 1.0), origin=d.get("origin", "manual"),
                                         tags=d.get("tags", []), version=d.get("version", 1), refs=refs,
                                         scene_variants=d.get("scene_variants") or {},
                                         deleted_at=d.get("deleted_at")))
        return out

    def match(self, text: str, src_lang: str, tgt_lang: str, bank_ids: Optional[List[str]] = None,
              risk_tier: str = "L0", scene_id: Optional[str] = None) -> List[TermHit]:
        entries = self._all_entries(bank_ids)
        matcher = TermMatcher()
        matcher.build_index(entries)
        hits = matcher.scan(text, src_lang, tgt_lang, scene_id)
        result = ConflictResolver.resolve(hits, risk_tier)
        return result["applied"]

    def conflicts(self, text: str, src_lang: str, tgt_lang: str) -> List[dict]:
        entries = self._all_entries(None)
        matcher = TermMatcher()
        matcher.build_index(entries)
        hits = matcher.scan(text, src_lang, tgt_lang)
        return ConflictResolver.resolve(hits, "L0")["conflicts"]

    def add_entry(self, bank_id: str, entry: dict) -> dict:
        bank = self._repo.get_bank(bank_id) if self._repo else None
        if bank is None:
            # require a personal bank; default to personal-default
            bank_id = "personal-default"
            bank = self._repo.get_bank(bank_id) if self._repo else {"scope": "personal"}
        if bank.get("scope", "personal") in READONLY_SCOPES or bank.get("readonly"):
            raise err("LAA-4004", message="只读术语库不可新增")
        eid = entry.get("id") or new_id()
        rec = self._mk_entry(bank_id, entry.get("source_term", ""), entry.get("target_term", ""),
                             bank.get("scope", "personal"), 0)
        rec.update({"id": eid, "domain": entry.get("domain", "general"),
                    "forced": int(entry.get("forced", False)), "match_mode": entry.get("match_mode", "exact"),
                    "case_sensitive": int(entry.get("case_sensitive", False)),
                    "scene_variants": entry.get("scene_variants") or {}})
        if not rec["source_term"] or not rec["target_term"]:
            raise err("LAA-1002", message="术语必须填写源词与译词")
        self._repo.save_entry(rec)
        return self._repo.get_entry(eid)

    def promote_to_personal(self, entry_id: str) -> dict:
        src = self._repo.get_entry(entry_id) if self._repo else None
        if src is None:
            raise err("LAA-4003")
        rec = deepcopy(src)
        rec["id"] = new_id()
        rec["bank_id"] = "personal-default"
        rec["origin"] = "promoted"
        rec["refs"] = {**(rec.get("refs") or {}), "scope": "personal", "promoted_from": entry_id}
        self._repo.save_entry(rec)
        return rec

    def session_override(self, task_id: str, source: str, target: str, ttl_min: int = 120) -> TermOverride:
        ov = TermOverride(task_id=task_id, source=source, target=target,
                          expires_at=utc_now())
        self._overrides.setdefault(task_id, []).append(ov)
        return ov

    def current_bank_version(self) -> int:
        if self._repo is None:
            return 1
        banks = self._repo.list_banks()
        personal = [b for b in banks if b.get("scope") == "personal"]
        return max((b.get("version", 1) for b in personal), default=1)

    def import_package(self, pkg: dict, mode: str = "merge", target_bank_id: str = "personal-default") -> dict:
        entries = pkg.get("entries", [])
        inserted = skipped = updated = 0
        for e in entries:
            src = (e.get("source_term") or "").strip()
            tgt = (e.get("target_term") or "").strip()
            if not src or not tgt:
                skipped += 1
                continue
            existing = self._find_by_source(src, target_bank_id)
            if existing and mode != "append":
                rec = {**existing, "target_term": tgt,
                       "domain": e.get("domain", existing.get("domain", "general")),
                       "forced": int(bool(e.get("forced", existing.get("forced")))),
                       "match_mode": e.get("match_mode", existing.get("match_mode", "exact")),
                       "version": int(existing.get("version", 1)) + 1}
                if e.get("scene_variants"):
                    rec["scene_variants"] = {**(existing.get("scene_variants") or {}),
                                             **(e.get("scene_variants") or {})}
                if e.get("part_of_speech") is not None:
                    rec["part_of_speech"] = e["part_of_speech"]
                if e.get("definition") is not None:
                    rec["definition"] = e["definition"]
                self._repo.save_entry(rec)
                updated += 1
            elif existing:
                skipped += 1  # append 模式下冲突跳过
            else:
                rec = self._mk_entry(target_bank_id, src, tgt, "personal", 0)
                rec.update({"domain": e.get("domain", "general"),
                            "forced": int(bool(e.get("forced", False))),
                            "match_mode": e.get("match_mode", "exact"),
                            "scene_variants": e.get("scene_variants") or {}})
                if e.get("part_of_speech") is not None:
                    rec["part_of_speech"] = e["part_of_speech"]
                if e.get("definition") is not None:
                    rec["definition"] = e["definition"]
                self._repo.save_entry(rec)
                inserted += 1
        return {"inserted": inserted, "skipped": skipped, "updated": updated}

    def _find_by_source(self, source_term: str, bank_id: str = "personal-default") -> Optional[dict]:
        if self._repo is None:
            return None
        for d in self._repo.list_entries(bank_id):
            if d["source_term"] == source_term:
                return d
        return None

    def export_package(self, bank_id: str) -> dict:
        entries = self._repo.list_entries(bank_id) if self._repo else []
        return {
            "schema_version": "glossary-package/v1",
            "pack_id": bank_id, "version": "1.0.0",
            "langs": ["*", "*"], "license": "personal", "attribution": "local",
            "entry_count": len(entries),
            "entries": [{"source_term": e["source_term"], "target_term": e["target_term"],
                         "domain": e.get("domain", "general"), "forced": bool(e.get("forced"))}
                        for e in entries],
        }

    def find_backfill_candidates(self, task_id: str, bindings, versions_by_segment, entry=None) -> List[dict]:
        return BackfillService.plan(task_id, bindings, versions_by_segment, entry)


class PersonalGlossaryExporter:
    def __init__(self, service: GlossaryService):
        self._srv = service

    def export(self, bank_id: str) -> dict:
        return self._srv.export_package(bank_id)

    def import_package(self, pkg: dict, target_bank_id: str = "personal-default", mode: str = "merge") -> dict:
        return self._srv.import_package(pkg, mode)


class RepoPackReader:
    """In-memory package reader/validator (§6.19.1). No network, no writes."""

    def __init__(self, package: dict):
        self.package = package
        self._entries: List[dict] = []

    def verify(self) -> dict:
        pkg = self.package or {}
        manifest = pkg.get("manifest") or {}
        files = pkg.get("files") or {}
        namespace = pkg.get("namespace") or "official"
        if not manifest.get("pack_id") or not manifest.get("version"):
            return {"ok": False, "stage": "structure", "error_code": "LAA-4006", "bad_rows": 0, "warnings": []}
        if not files:
            return {"ok": False, "stage": "structure", "error_code": "LAA-4006", "bad_rows": 0, "warnings": []}
        # signature requirement for official namespace
        if namespace == "official" and not manifest.get("signature"):
            return {"ok": False, "stage": "signature", "error_code": "LAA-4007", "bad_rows": 0, "warnings": ["缺失签名"]}
        # version compatibility (min_client simple check)
        req = (manifest.get("requires") or {}).get("min_client")
        if req:
            try:
                if tuple(int(x) for x in str(req).split(".")) > (0, 3, 0):
                    return {"ok": False, "stage": "version", "error_code": "LAA-4009", "bad_rows": 0, "warnings": []}
            except ValueError:
                return {"ok": False, "stage": "version", "error_code": "LAA-4009", "bad_rows": 0, "warnings": []}
        # per-file sha256
        for fname, fmeta in (files or {}).items():
            if fmeta is None:
                continue
            content = fmeta if isinstance(fmeta, str) else fmeta.get("content", "")
            expected = fmeta.get("sha256") if isinstance(fmeta, dict) else None
            actual = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if expected and actual != expected:
                return {"ok": False, "stage": "hash", "error_code": "LAA-4008", "bad_rows": 0, "warnings": []}
            if isinstance(fmeta, dict):
                self._parse_rows(fmeta.get("rows", []))
        content_hash = manifest.get("content_hash")
        if content_hash and self._entries:
            recalc = hashlib.sha256(json.dumps(self._entries, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if recalc != content_hash:
                return {"ok": False, "stage": "content_hash", "error_code": "LAA-4008", "bad_rows": 0, "warnings": []}
        return {"ok": True, "stage": "done", "error_code": None, "bad_rows": self._bad_rows, "warnings": []}

    _bad_rows = 0

    def _parse_rows(self, rows: List[dict]) -> None:
        for r in rows or []:
            if isinstance(r, dict) and r.get("source_term") and r.get("target_term"):
                self._entries.append({
                    "source_term": str(r["source_term"]), "target_term": str(r["target_term"]),
                    "src_lang": r.get("src_lang", "*"), "tgt_lang": r.get("tgt_lang", "*"),
                    "domain": r.get("domain", "general"), "forced": bool(r.get("forced", False)),
                })
            else:
                self._bad_rows += 1

    def read_entries(self) -> List[dict]:
        return list(self._entries)