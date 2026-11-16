"""Command router + payload validator (the bridge's dispatch layer)."""
from __future__ import annotations

from typing import Any, Callable, Dict

from ..shared import UiEvent, err
from .desktop_native import save_dialog as desktop_save_dialog


def ok_response(data: Any = None) -> Dict[str, Any]:
    return {"ok": True, "data": data}


def err_response(e: BaseException) -> Dict[str, Any]:
    code = getattr(e, "code", "LAA-9001")
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": getattr(e, "message", str(e)),
            "retryable": bool(getattr(e, "retryable", False)),
            "details": getattr(e, "details", None),
            "message_key": getattr(e, "message_key", None),
            "capability": getattr(e, "capability", None),
        },
    }


class PayloadValidator:
    """Lightweight request validation; business rules also re-check in Application."""

    @staticmethod
    def require(obj: Dict[str, Any], *fields: str) -> None:
        for f in fields:
            if obj.get(f) is None or obj.get(f) == "":
                raise err("LAA-1002", message=f"缺少字段 {f}")

    @classmethod
    def translation_start(cls, payload: Dict[str, Any]) -> None:
        cls.require(payload, "text")

    @classmethod
    def task_id(cls, payload: Dict[str, Any], key: str = "task_id") -> None:
        cls.require(payload, key)


class CommandRouter:
    def __init__(self, app, validator: PayloadValidator = None):
        self.app = app
        self.validator = validator or PayloadValidator()
        self._table: Dict[str, Callable[[Dict[str, Any]], Any]] = {
            "app.info": lambda p: self.app.app_info(),
            "capability.list": lambda p: self.app.capability_list(p.get("group")),
            "message_keys": lambda p: self.app.message_keys(),
            "translation.start": lambda p: self.app.start_translation(p),
            "translation.snapshot": lambda p: self.app.snapshot(p["task_id"]),
            "translation.cancel": lambda p: self.app.cancel_task(p["task_id"]),
            "translation.estimate": lambda p: self.app.estimate_translation(p),
            "translation.retry": lambda p: self.app.retry_translation(p, p.get("trace_id", "")),
            "translation.retranslate": lambda p: self.app.retranslate(p.get("task_id"), p.get("segment_ids"), p.get("trace_id", "")),
            "task.term.list": lambda p: self.app.task_terms(p),
            "task.term.set": lambda p: self.app.set_task_term(p, p.get("trace_id", "")),
            "translation.export": lambda p: self.app.export(p.get("task_id"), p.get("format", "txt"), p.get("include_meta", True)),
            "mode.set": lambda p: self.app.set_mode(p["task_id"], p["mode"], p.get("scope", "rest"), p.get("trace_id", "")),
            "mode.get": lambda p: self.app.mode_get(p["task_id"]),
            "segment.word.pick": lambda p: self.app.pick_word(p),
            "segment.variant.pick": lambda p: self.app.pick_variant(p),
            "segment.override": lambda p: self.app.override_target(p),
            "scene.list": lambda p: self.app.scene_list(),
            "scene.manage": lambda p: self.app.scene_manage(p),
            "scene.ai": lambda p: self.app.scene_ai(p),
            "glossary.search": lambda p: self.app.glossary_search(p),
            "glossary.manage": lambda p: self._glossary_manage(p),
            "glossary.update": lambda p: self.app.glossary_update(p),
            "glossary.import": lambda p: self.app.glossary_import(p),
            "glossary.export": lambda p: self.app.glossary_export(p),
            "glossary.bank.create": lambda p: self.app.glossary_bank_create(p),
            "glossary.package.list": lambda p: self.app.glossary_package_list(p),
            "glossary.package.install": lambda p: self.app.glossary_import(p),
            "glossary.discover": lambda p: self.app.glossary_discover(p),
            "glossary.discover.accept": lambda p: self.app.glossary_discover_accept(p),
            "glossary.discover.reject": lambda p: self.app.glossary_discover_reject(p),
            "term.list": lambda p: self.app.term_list(p),
            "term.scan": lambda p: self.app.term_scan(p),
            "term.accept": lambda p: self.app.term_accept(p),
            "term.accept_bulk": lambda p: self.app.term_accept_bulk(p),
            "term.ignore": lambda p: self.app.term_ignore(p),
            "term.clear": lambda p: self.app.term_clear(p),
            "term.auto_review": lambda p: self.app.term_auto_review(p),
            "term.auto_review.status": lambda p: self.app.term_auto_review_status(p),
            "term.auto_review.undo": lambda p: self.app.term_auto_review_undo(p),
            "settings.get": lambda p: self.app.settings_get(),
            "settings.save": lambda p: self.app.settings_save(p),
            "community.list": lambda p: self.app.community_list(p),
            "community.add": lambda p: self.app.community_add(p),
            "community.sync": lambda p: self.app.community_sync(p),
            "community.remove": lambda p: self.app.community_remove(p),
            "provider.list": lambda p: self.app.provider_list(),
            "provider.upsert": lambda p: self.app.provider_upsert(p),
            "provider.test": lambda p: self.app.provider_test(p),
            "provider.delete": lambda p: self.app.provider_delete(p),
            "cost.summary": lambda p: self.app.cost_summary(p),
            "usage.summary": lambda p: self.app.usage_summary(p),
            "usage.list": lambda p: self.app.usage_list(p),
            "history.list": lambda p: self.app.history_list(p),
            "calls.list": lambda p: self.app.calls_list(p),
            "calls.get": lambda p: self.app.call_get(p),
            "usage.stats": lambda p: self.app.usage_stats(p),
            "usage.calls.status": lambda p: self.app.usage_calls_status(p),
            "usage.settings.save": lambda p: self.app.usage_settings_save(p),
            "usage.calls.cleanup": lambda p: self.app.usage_calls_cleanup(p),
            "usage.calls.clear": lambda p: self.app.usage_calls_clear(p),
            "skin.list": lambda p: self.app.skin_list(p),
            "skin.active": lambda p: self.app.skin_active(p),
            "skin.select": lambda p: self.app.skin_select(p),
            "skin.import": lambda p: self.app.skin_import(p),
            "skin.export": lambda p: self.app.skin_export(p),
            "skin.delete": lambda p: self.app.skin_delete(p),
            "memory.lookup": lambda p: self.app.memory_lookup(p),
            "memory.list": lambda p: self.app.memory_list(p),
            "memory.add": lambda p: self.app.memory_add(p),
            "memory.restore": lambda p: self.app.memory_restore(p),
            "memory.delete": lambda p: self.app.memory_delete(p),
            "diagnostics.export": lambda p: self.app.diagnostics_export(),
            "file.save_dialog": lambda p: desktop_save_dialog(
                str(p.get("suggested_name", "")), str(p.get("content", "")),
                bool(p.get("base64_encoded"))),
        }

    def _glossary_manage(self, p: Dict[str, Any]) -> Any:
        action = p.get("action")
        if action == "remove":
            return self.app.glossary_remove(p)
        if action == "promote":
            return self.app.glossary_promote(p)
        if action == "update":
            return self.app.glossary_update(p)
        return self.app.glossary_add(p)

    def dispatch(self, cmd: str, payload: Dict[str, Any], trace_id: str = "") -> Dict[str, Any]:
        self.app.capability_gate.check_command(cmd)
        handler = self._table.get(cmd)
        if handler is None:
            raise err("LAA-1001", message=f"未知命令 {cmd}")
        return handler(payload)


class EventPump:
    """Poll-oriented event relay for the bridge (SSE or polling)."""

    def __init__(self, app):
        self.app = app

    def poll(self, task_id: str, from_seq: int = 0) -> Dict[str, Any]:
        return self.app.events(task_id, from_seq)