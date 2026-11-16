"""Application services: the use-case layer the bridge commands call."""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ..shared import (
    CapabilitySpec,
    TranslateRequest,
    TranslationTask,
    UiEvent,
    err,
    new_id,
    ok,
    utc_now,
)
from ..shared.clock import CancellationToken, TraceContext
from ..shared.events import Topic
from ..shared.terms import replace_term, term_hit
from ..shared.types import TaskStatus, TranslateMode
from .facades import (
    CostFacade,
    EmotionFacade,
    GlossaryFacade,
    QAFacade,
    RiskFacade,
    SceneFacade,
    TextFacade,
)
from ..domain.text.service import plan_batches
from .pipeline import build_kept_spans, build_literal_spans, drop_overlaps, join_words, strip_sentences


SCENE_AI_SYSTEM_PROMPT = """你是"翻译场景助理"，唯一职责是帮助用户创建与调整"翻译场景档案"。你只能围绕场景档案进行对话与修改；任何与场景设计无关的问题，都要礼貌拒绝并把话题拉回场景档案。

你每次只输出一个 JSON 对象，不要输出任何多余文字，结构固定为：
{"reply": "对用户这句话的自然语言回复(中文、简洁、说明你改了什么)",
 "scene_profile": {"name": "场景名称(简短)", "description": "场景说明(一句话)",
   "register": "formal 或 semiformal 或 informal",
   "mode_default": "fluent 或 literal",
   "descriptors": ["风格要点1", "风格要点2"], "do": ["应做1"], "dont": ["避免1"],
   "labels": ["标签1"]}}

规则：
1. 用户在做初始描述时，据此补全整个 scene_profile；用户发的 current_scene 里已有的字段要尽量保留并改进。
2. 用户在做局部调整（如"语气再正式点""加一条避免口语化"）时，只改动相关字段，其余字段原样带上。
3. reply 用中文、简短，说明本次改动了哪些字段。
4. register 只能是 formal/semiformal/informal；mode_default 只能是 fluent/literal。
5. 不要回答翻译、写代码、以及其他与场景档案无关的请求。"""


class EventBuffer:
    """Per-task ordered event log with sequence numbers, replayable by the bridge."""

    def __init__(self, capacity: int = 5000, default_max: int = 100):
        self._buf: Dict[str, List[dict]] = {}
        self._lock = threading.RLock()
        self.capacity = capacity
        self.default_max = default_max

    def append(self, task_id: str, topic: str, payload: Dict[str, Any], trace_id: str = "") -> dict:
        with self._lock:
            lst = self._buf.setdefault(task_id, [])
            seq = len(lst) + 1
            event = {"topic": topic, "payload": payload, "seq": seq, "task_id": task_id}
            if trace_id:
                event["trace_id"] = trace_id
            lst.append(event)
            if len(lst) > self.capacity:
                self._buf[task_id] = lst[-self.capacity:]
            return event

    def replay(self, task_id: str, from_seq: int = 0) -> Dict[str, Any]:
        with self._lock:
            lst = self._buf.get(task_id, [])
            events = [e for e in lst if e["seq"] > from_seq]
            next_seq = lst[-1]["seq"] if lst else from_seq
            return {"events": events, "next_seq": next_seq}

    def latest_seq(self, task_id: str) -> int:
        with self._lock:
            lst = self._buf.get(task_id, [])
            return lst[-1]["seq"] if lst else 0


class Application:
    def __init__(self, repo, orchestrator, gateway, capability_registry, capability_gate,
                 scene: SceneFacade, glossary: GlossaryFacade, qa: QAFacade,
                 risk: RiskFacade, tm, cost: CostFacade, emotion: EmotionFacade, text: TextFacade,
                 secrets=None, event_bus=None, clock=None, skin=None):
        self.repo = repo
        self.orchestrator = orchestrator
        self.gateway = gateway
        self.capabilities = capability_registry
        self.capability_gate = capability_gate
        self.scene = scene
        self.glossary = glossary
        self.qa = qa
        self.risk = risk
        self.tm = tm
        self.cost = cost
        self.emotion = emotion
        self.text = text
        self.secrets = secrets
        self.bus = event_bus
        self.clock = clock
        self.skin = skin
        self.buffer = EventBuffer()
        self._tokens: Dict[str, CancellationToken] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._candidates: List = []

    # ---------- translation ----------
    def start_translation(self, payload: Dict[str, Any], trace_id: str = "") -> Dict[str, Any]:
        text = (payload.get("text") or "").strip()
        if not text:
            raise err("LAA-3001")
        opts = self._long_text_options()
        max_chars = int(opts.get("max_chars") or 200000)
        if len(text) > max_chars:
            raise err("LAA-3002",
                      message=f"文本 {len(text)} 字符，超过上限 {max_chars} 字符；"
                              f"可在设置 → 翻译中调高「长文本上限」，或拆分文本后再译")
        estimate = self._estimate(text, opts)
        tgt = payload.get("target_lang") or "zh-Hans"
        if tgt != "auto" and tgt.split("-")[0].lower() not in ("zh", "en", "ja", "ko", "fr", "de", "es", "ru", "pt", "ar", "it", "nl", "pl", "tr", "vi", "th"):
            raise err("LAA-3003", message=f"目标语言不支持 {tgt}")
        req = TranslateRequest.from_dict(payload)
        task_id = new_id()
        mode = req.mode if req.mode in (TranslateMode.FLUENT.value, TranslateMode.LITERAL.value) else TranslateMode.FLUENT.value
        task = {
            "id": task_id, "source_text": text, "src_lang": req.source_lang or "auto", "tgt_lang": tgt,
            "detected_lang": None, "mode": mode, "scene_profile_id": req.scene_profile_id,
            "resolved_scene": {}, "domain": req.domain or "general", "input_kind": req.input_kind or "text",
            "media_refs": req.media_refs, "status": TaskStatus.QUEUED.value, "checkpoint_seq": 0,
            "resumable": False, "risk_tier": "L0", "routing": "auto_finalize",
            "budget_limit": 0.5,
            "cost_total": 0.0, "segment_count": 0, "created_at": utc_now(), "completed_at": None,
        }
        self.repo.save_task(task)
        self.buffer.append(task_id, Topic.TASK_CREATED, {"status": TaskStatus.QUEUED.value}, trace_id)
        token = CancellationToken()
        self._tokens[task_id] = token
        thread = threading.Thread(target=self._run, args=(task_id, req, token, trace_id), daemon=True, name=f"task-{task_id}")
        self._threads[task_id] = thread
        thread.start()
        return {"task_id": task_id, "stream": {"checkpoint_seq": 0, "resumable": True},
                "estimate": estimate}

    def _run(self, task_id: str, req: TranslateRequest, token: CancellationToken, trace_id: str,
             only_segment_ids: Optional[List[str]] = None) -> None:
        try:
            with TraceContext(trace_id, task_id):
                def sink(topic: str, payload: Dict[str, Any]) -> None:
                    self.buffer.append(task_id, topic, payload, trace_id)
                self.orchestrator.run(task_id, req, token, sink,
                                      options=self._long_text_options(),
                                      only_segment_ids=only_segment_ids)
        except Exception as e:  # noqa: BLE001
            code = getattr(e, "code", None)
            if code == "LAA-3005":
                # 取消发生在首批开始前时，流水线还没机会给片段落状态；这里统一收口，
                # 让未开始/运行中的片段都变成 cancelled，前端才能显示“重试失败片段”并恢复。
                for row in self.repo.list_segments(task_id):
                    if (row.get("status") or "pending") not in ("done", "cancelled", "failed"):
                        row["status"] = "cancelled"
                        self.repo.save_segment(row)
                self.repo.update_task(task_id, {"status": TaskStatus.CANCELLED.value})
                self.buffer.append(task_id, Topic.TASK_CANCELLED,
                                   {"status": TaskStatus.CANCELLED.value,
                                    "progress": self.task_progress(task_id)}, trace_id)
            else:
                self.repo.update_task(task_id, {"status": TaskStatus.FAILED.value})
                self.buffer.append(task_id, Topic.TASK_FAILED, {"status": TaskStatus.FAILED.value,
                                                                "error": getattr(e, "message", str(e)),
                                                                "code": code or "LAA-8004"}, trace_id)

    def cancel_task(self, task_id: str, trace_id: str = "") -> Dict[str, Any]:
        task = self.repo.get_task(task_id)
        if not task:
            raise err("LAA-3006")
        if task["status"] in (TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value):
            return {"cancelled": False}
        self.repo.update_task(task_id, {"status": TaskStatus.CANCELLING.value})
        token = self._tokens.get(task_id)
        if token:
            token.cancel("用户取消")
        self.buffer.append(task_id, Topic.TASK_CANCELLING, {"status": TaskStatus.CANCELLING.value}, trace_id)
        return {"cancelled": True}

    # ---------- long text（V10） ----------
    def _long_text_options(self) -> Dict[str, Any]:
        return dict(self.settings_get().get("long_text") or {})

    def _estimate(self, text: str, opts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        cfg = opts or self._long_text_options()
        max_chars = int(cfg.get("max_chars") or 200000)
        chars = len(text)
        if not text.strip():
            return {"chars": chars, "max_chars": max_chars, "over_limit": False,
                    "segments": 0, "batches": 0, "est_calls": 0}
        segments = self.text.segment_text(text, "")
        batches = plan_batches(segments, int(cfg.get("batch_chars") or 2000),
                               int(cfg.get("batch_segments") or 8))
        return {"chars": chars, "max_chars": max_chars, "over_limit": chars > max_chars,
                "segments": len(segments), "batches": len(batches), "est_calls": len(batches)}

    def estimate_translation(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._estimate(payload.get("text") or "")

    def retry_translation(self, payload: Dict[str, Any], trace_id: str = "") -> Dict[str, Any]:
        task_id = str(payload.get("task_id") or "")
        task = self.repo.get_task(task_id)
        if not task:
            raise err("LAA-3006")
        if task["status"] in (TaskStatus.QUEUED.value, TaskStatus.PREPARING.value,
                              TaskStatus.RUNNING.value, TaskStatus.CANCELLING.value,
                              TaskStatus.FINALIZING.value):
            raise err("LAA-1002", message="任务仍在运行，无法重试")
        rows = self.repo.list_segments(task_id)
        pending = [r["id"] for r in rows
                   if (r.get("status") or "pending") in ("failed", "pending", "cancelled")]
        if not pending:
            if rows and all((r.get("status") or "pending") == "done" for r in rows):
                # 旧状态机遗留：任务被置 paused 但所有片段其实已完成，直接收尾为成功，避免永久 paused。
                self.repo.update_task(task_id, {
                    "status": TaskStatus.SUCCEEDED.value, "completed_at": utc_now(),
                    "failed_batches": "[]",
                    "cost_total": self.cost.task_total(task_id) if hasattr(self.cost, "task_total") else 0.0,
                })
                self.buffer.append(task_id, Topic.TASK_COMPLETED, {
                    "status": TaskStatus.SUCCEEDED.value, "finalized": True,
                    "progress": self.task_progress(task_id),
                }, trace_id)
                return {"task_id": task_id, "queued": False, "finalized": True,
                        "segment_count": len(rows)}
            raise err("LAA-1002", message="没有需要重试的片段")
        self.repo.update_task(task_id, {"status": TaskStatus.QUEUED.value, "completed_at": None,
                                        "failed_batches": "[]"})
        req = TranslateRequest(
            text=task.get("source_text") or "", target_lang=task.get("tgt_lang") or "zh-Hans",
            source_lang=task.get("src_lang") or "auto",
            mode=task.get("mode") or TranslateMode.FLUENT.value,
            scene_profile_id=task.get("scene_profile_id"), domain=task.get("domain") or "general",
            input_kind=task.get("input_kind") or "text",
        )
        token = CancellationToken()
        self._tokens[task_id] = token
        self.buffer.append(task_id, Topic.TASK_CREATED,
                           {"status": TaskStatus.QUEUED.value, "retry": len(pending)}, trace_id)
        thread = threading.Thread(target=self._run, args=(task_id, req, token, trace_id, pending),
                                  daemon=True, name=f"task-{task_id}-retry")
        self._threads[task_id] = thread
        thread.start()
        return {"task_id": task_id, "queued": True, "segment_count": len(pending)}

    def task_terms(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        task_id = str(payload.get("task_id") or "")
        if not self.repo.get_task(task_id):
            raise err("LAA-3006")
        return {"task_id": task_id, "items": self.repo.list_task_terms(task_id)}

    def set_task_term(self, payload: Dict[str, Any], trace_id: str = "") -> Dict[str, Any]:
        """用户指定某术语的译法：落库后只重译受影响的片段，并立即全篇生效。"""
        task_id = str(payload.get("task_id") or "")
        source = str(payload.get("source_term") or "").strip()
        target = str(payload.get("target_term") or "").strip()
        task = self.repo.get_task(task_id)
        if not task:
            raise err("LAA-3006")
        if not source or not target:
            raise err("LAA-4001", message="术语原文与译法都不能为空")
        if len(source) > 80 or len(target) > 200:
            raise err("LAA-4001", message="术语原文或译法过长")
        if task["status"] in (TaskStatus.QUEUED.value, TaskStatus.PREPARING.value,
                              TaskStatus.RUNNING.value, TaskStatus.CANCELLING.value,
                              TaskStatus.FINALIZING.value):
            raise err("LAA-1002", message="任务仍在运行，无法修改术语译法")
        now = utc_now()
        prev = {r["source_term"]: r for r in self.repo.list_task_terms(task_id)}.get(source)
        prev_target = (prev or {}).get("target_term") or ""
        term = self.repo.upsert_task_term({
            "task_id": task_id, "source_term": source, "target_term": target,
            "term_id": "", "origin": "user", "segment_id": "", "updated_at": now,
        })
        needs: List[str] = []
        rewritten = 0
        matched = 0
        already = 0
        for row in self.repo.list_segments(task_id):
            if not term_hit(row.get("text") or "", source):
                continue
            matched += 1
            version = self.repo.latest_version(row["id"])
            text = (version or {}).get("target_text") or ""
            # 先按旧译法精确替换：新译法可能只是旧译法的一部分（server-side cache → cache），
            # 不能用“子串已存在”判定无需改动，否则面板显示新译法而正文其实没动。
            if text and prev_target and prev_target != target and term_hit(text, prev_target):
                new_text, count = replace_term(text, prev_target, target)
                if count:
                    self.override_target({
                        "task_id": task_id, "segment_id": row["id"],
                        "target_text": new_text,
                        "origin": "term_override", "trace_id": trace_id,
                    })
                    rewritten += 1
                    continue
            if term_hit(text, target):
                already += 1
                continue
            needs.append(row["id"])
        if needs:
            self.repo.update_task(task_id, {"status": TaskStatus.QUEUED.value, "completed_at": None})
            req = TranslateRequest(
                text=task.get("source_text") or "", target_lang=task.get("tgt_lang") or "zh-Hans",
                source_lang=task.get("src_lang") or "auto",
                mode=task.get("mode") or TranslateMode.FLUENT.value,
                scene_profile_id=task.get("scene_profile_id"), domain=task.get("domain") or "general",
                input_kind=task.get("input_kind") or "text",
            )
            token = CancellationToken()
            self._tokens[task_id] = token
            self.buffer.append(task_id, Topic.TASK_CREATED,
                               {"status": TaskStatus.QUEUED.value, "term_override": source,
                                "retry": len(needs)}, trace_id)
            thread = threading.Thread(target=self._run, args=(task_id, req, token, trace_id, needs),
                                      daemon=True, name=f"task-{task_id}-term")
            self._threads[task_id] = thread
            thread.start()
        return {"task_id": task_id, "term": term, "affected": rewritten + len(needs),
                "rewritten": rewritten, "segment_ids": needs, "queued": bool(needs),
                "matched": matched, "already": already}

    def task_progress(self, task_id: str) -> Dict[str, Any]:
        task = self.repo.get_task(task_id) or {}
        rows = self.repo.list_segments(task_id)
        counts: Dict[str, int] = {}
        for r in rows:
            k = r.get("status") or "pending"
            counts[k] = counts.get(k, 0) + 1
        done = counts.get("done", 0)
        failed = counts.get("failed", 0)
        cancelled = counts.get("cancelled", 0)
        calls = in_tok = out_tok = 0
        amount = 0.0
        for u in self.repo.list_usage(limit=1_000_000).get("items", []):
            if u.get("task_id") != task_id:
                continue
            calls += 1
            in_tok += int(u.get("input_tokens") or 0)
            out_tok += int(u.get("output_tokens") or 0)
            amount += float(u.get("amount") or 0.0)
        return {"total": len(rows), "done": done, "failed": failed, "cancelled": cancelled,
                "remaining": max(0, len(rows) - done - failed - cancelled),
                "batch_total": int(task.get("batch_total") or 0),
                "calls": calls, "input_tokens": in_tok, "output_tokens": out_tok,
                "cost": round(amount, 6)}

    def recover_tasks(self) -> Dict[str, Any]:
        """启动时把上次异常退出留下的运行中任务标记为 paused，可重试续传。"""
        changed = 0
        for t in self.repo.list_tasks():
            status = t.get("status")
            if status in (TaskStatus.QUEUED.value, TaskStatus.PREPARING.value,
                          TaskStatus.RUNNING.value, TaskStatus.CANCELLING.value,
                          TaskStatus.FINALIZING.value):
                self.repo.update_task(t["id"], {"status": TaskStatus.PAUSED.value})
                status = TaskStatus.PAUSED.value
                changed += 1
            if status == TaskStatus.PAUSED.value:
                rows = self.repo.list_segments(t["id"])
                if rows and all((r.get("status") or "pending") == "done" for r in rows):
                    # 片段全部完成却停在 paused：启动时直接收尾，避免死胡同。
                    self.repo.update_task(t["id"], {"status": TaskStatus.SUCCEEDED.value,
                                                    "completed_at": utc_now()})
                    changed += 1
        return {"recovered": changed}

    def snapshot(self, task_id: str, from_seq: int = 0) -> Dict[str, Any]:
        task = self.repo.get_task(task_id)
        if not task:
            raise err("LAA-3006")
        segs = self._segment_views(task_id)
        return {"task": task, "segments": segs, "checkpoint_seq": self.buffer.latest_seq(task_id),
                "terms": self.repo.list_task_terms(task_id),
                "progress": self.task_progress(task_id)}

    def _segment_views(self, task_id: str) -> List[Dict[str, Any]]:
        task = self.repo.get_task(task_id) or {}
        mode = task.get("mode") or TranslateMode.FLUENT.value
        risk_meta = (task.get("resolved_scene") or {}).get("risk") or {}
        risk_view = {
            "tier": task.get("risk_tier") or "L0",
            "reason": risk_meta.get("reason") or risk_meta.get("explain") or "",
        }
        out = []
        for seg in self.repo.list_segments(task_id):
            version = self.repo.latest_version(seg["id"])
            try:
                tm_hits = [h.to_dict() for h in self.tm.lookup(
                    seg["text"], task.get("src_lang") or "auto", task.get("tgt_lang") or "",
                    task.get("domain") or "general")[:3]]
            except Exception:  # noqa: BLE001 - 记忆查询失败不影响译文展示
                tm_hits = []
            out.append({
                "segment_id": seg["id"], "source_text": seg["text"],
                "target_text": version["target_text"] if version else "",
                "spans": (version.get("spans") or []) if version else [],
                "words": (version.get("words") or []) if version else [],
                "tones": (version.get("tones") or []) if version else [],
                "emotions": (version.get("emotions") or []) if version else [],
                "sentiment": (version.get("sentiment") or None) if version else None,
                "tm_hits": tm_hits,
                "risk": risk_view,
                "span": seg["span"], "index": seg["idx"],
                "status": seg.get("status") or ("done" if version else "pending"),
                "forced": bool(seg.get("forced")),
                "confidence": {"score": version.get("confidence")} if version and version.get("confidence") is not None else None,
                "mode": mode,
                "channel": version.get("source_channel") if version else "online",
                "version_id": version.get("id") if version else "",
            })
        return out

    def events(self, task_id: str, from_seq: int = 0) -> Dict[str, Any]:
        if not self.repo.get_task(task_id):
            raise err("LAA-3006")
        return self.buffer.replay(task_id, from_seq)

    def set_mode(self, task_id: str, mode: str, scope: str = "rest", trace_id: str = "") -> Dict[str, Any]:
        task = self.repo.get_task(task_id)
        if not task:
            raise err("LAA-3006")
        if mode not in (TranslateMode.FLUENT.value, TranslateMode.LITERAL.value):
            raise err("LAA-1002", message=f"非法模式 {mode}")
        if task["status"] in (TaskStatus.RUNNING.value, TaskStatus.FINALIZING.value):
            raise err("LAA-3007")
        self.repo.update_task(task_id, {"mode": mode})
        self.buffer.append(task_id, Topic.MODE_CHANGED, {"mode": mode, "scope": scope}, trace_id)
        return {"task_id": task_id, "mode": mode, "scope": scope}

    def mode_get(self, task_id: str, trace_id: str = "") -> Dict[str, Any]:
        task = self.repo.get_task(task_id)
        if not task:
            raise err("LAA-3006")
        return {"task_id": task_id, "mode": task["mode"]}

    def pick_word(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """直译模式：为某个词选定义项，重建整句并保存为新版本。"""
        task_id = payload.get("task_id")
        segment_id = payload.get("segment_id")
        task = self.repo.get_task(task_id) if task_id else None
        if not task:
            raise err("LAA-3006")
        version = self.repo.latest_version(segment_id) if segment_id else None
        if not version:
            raise err("LAA-3005", message="该分段尚无译文")
        words = [dict(w) for w in (version.get("words") or [])]
        try:
            word_index = int(payload.get("word_index"))
        except (TypeError, ValueError):
            raise err("LAA-1002", message="word_index 非法")
        if not (0 <= word_index < len(words)):
            raise err("LAA-1002", message="word_index 越界")
        word = words[word_index]
        choice = str(payload.get("choice") or "").strip()
        allowed = [str(word.get("target") or "")] + [str(a) for a in (word.get("alternatives") or [])]
        if not choice or choice not in allowed:
            raise err("LAA-1002", message="该词没有这个义项")
        # 选中只改变“当前采用项”，其余义项原样保留（含原来的推荐项），
        # 避免旧推荐被顶掉后所有选项都变成同一个译文。
        old_target = str(word.get("target") or "").strip()
        prev_options = [str(o).strip() for o in (word.get("options") or []) if str(o).strip()]
        if not prev_options:
            for item in [old_target] + [str(a).strip() for a in (word.get("alternatives") or [])]:
                if item and item not in prev_options:
                    prev_options.append(item)
        # 推荐项是首次生成的默认译文，选中备选后也不得改变它的标记与位置。
        recommended = str(word.get("recommended") or "").strip() or old_target
        options = [recommended] + [o for o in prev_options if o != recommended]
        word["recommended"] = recommended
        word["options"] = options
        word["target"] = choice
        word["alternatives"] = [o for o in options if o != choice]
        words[word_index] = word

        tgt = task.get("tgt_lang") or "zh-Hans"
        target_text = join_words(words, tgt)
        if task.get("mode") == TranslateMode.LITERAL.value and hasattr(self.scene, "ensure_marker"):
            target_text = self.scene.ensure_marker(target_text)
        spans = [s.to_dict() if hasattr(s, "to_dict") else s for s in build_literal_spans(words, target_text)]
        version_id = new_id()
        self.repo.save_version({
            "id": version_id, "segment_id": segment_id, "parent_version_id": version.get("id"),
            "target_text": target_text, "origin": "literal_pick",
            "provider": version.get("provider", ""), "model": version.get("model", ""),
            "prompt_fingerprint": version.get("prompt_fingerprint", ""),
            "routing_at_creation": version.get("routing_at_creation", ""),
            "source_channel": version.get("source_channel", "online"),
            "confidence": version.get("confidence"),
            "spans": spans, "words": words,
            "tones": version.get("tones") or [],
            "sentiment": version.get("sentiment") or {},
            "emotions": version.get("emotions") or [],
            "created_at": utc_now(),
        })
        seg = next((s for s in self.repo.list_segments(task_id) if s["id"] == segment_id), None)
        view = {
            "segment_id": segment_id,
            "source_text": seg["text"] if seg else "",
            "target_text": target_text,
            "spans": spans,
            "words": words,
            "tones": version.get("tones") or [],
            "sentiment": version.get("sentiment") or {},
            "emotions": version.get("emotions") or [],
            "span": seg["span"] if seg else [],
            "index": seg["idx"] if seg else 0,
            "confidence": {"score": version.get("confidence")} if version.get("confidence") is not None else None,
            "mode": task.get("mode"),
            "channel": version.get("source_channel", "online"),
            "version_id": version_id,
        }
        self.buffer.append(task_id, Topic.SEGMENT_VIEW, view, payload.get("trace_id", ""))
        return view

    def pick_variant(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """流畅模式：用候选译法替换译文中的片段，重建 span 并保存为新版本。"""
        task_id = payload.get("task_id")
        segment_id = payload.get("segment_id")
        task = self.repo.get_task(task_id) if task_id else None
        if not task:
            raise err("LAA-3006")
        version = self.repo.latest_version(segment_id) if segment_id else None
        if not version:
            raise err("LAA-3005", message="该分段尚无译文")
        target_text = str(version.get("target_text") or "")
        span = payload.get("span") or []
        choice = str(payload.get("choice") or "").strip()
        if not choice:
            raise err("LAA-1002", message="候选译法为空")
        try:
            start, end = int(span[0]), int(span[1])
        except (TypeError, ValueError, IndexError):
            raise err("LAA-1002", message="span 非法")
        if not (0 <= start < end <= len(target_text)):
            raise err("LAA-1002", message="span 越界")
        if len(choice) > 200:
            raise err("LAA-1002", message="候选译法过长")

        old_spans = [dict(s) for s in (version.get("spans") or [])]
        active = next((s for s in old_spans
                       if "alternate_translation" in (s.get("kinds") or [])
                       and s.get("span") == [start, end]), None)
        if active is None:
            raise err("LAA-1002", message="该片段没有候选译法")
        allowed = {str(v.get("label") or ""): str(v.get("text") or v.get("label") or "")
                   for v in (active.get("variants") or []) if isinstance(v, dict)}
        if choice not in allowed:
            raise err("LAA-1002", message="该片段没有这个候选译法")

        new_text = target_text[:start] + choice + target_text[end:]
        delta = len(choice) - (end - start)
        rebuilt: List[Dict[str, Any]] = []
        for s in old_spans:
            sp = s.get("span") or []
            if len(sp) != 2 or s is active:
                continue
            ss, se = int(sp[0]), int(sp[1])
            if ss >= end:
                ss, se = ss + delta, se + delta
            elif se > start:
                continue  # 与替换区间重叠的其他标注直接丢弃
            rebuilt.append({**s, "span": [ss, se]})

        # 替换后的片段仍是“可切换译法”：保留原候选集，当前译文排在最前
        labels = [str(v.get("label") or "") for v in (active.get("variants") or []) if v.get("label")]
        labels = [choice] + [x for x in labels if x and x != choice]
        variants = [{"id": f"{segment_id}-pick-{i}", "label": x, "text": x, "source": "model"}
                    for i, x in enumerate(labels)]
        rebuilt = [s for s in rebuilt if not ("alternate_translation" in (s.get("kinds") or [])
                                              and int(s["span"][0]) < start + len(choice) and int(s["span"][1]) > start)]
        rebuilt.append({
            "id": f"{segment_id}-var-pick", "text": choice, "span": [start, start + len(choice)],
            "kinds": ["alternate_translation"], "term_ref": None, "variants": variants,
            "confidence": None, "fix_ref": None, "note": "可替换译法",
        })
        seg = next((s for s in self.repo.list_segments(task_id) if s["id"] == segment_id), None)
        kept = drop_overlaps(
            build_kept_spans(segment_id, seg["text"] if seg else "", new_text, task.get("tgt_lang") or "zh-Hans"),
            [dict(s) for s in rebuilt] if rebuilt else [],
        )
        spans = rebuilt + [s.to_dict() for s in kept]

        version_id = new_id()
        self.repo.save_version({
            "id": version_id, "segment_id": segment_id, "parent_version_id": version.get("id"),
            "target_text": new_text, "origin": "variant_pick",
            "provider": version.get("provider", ""), "model": version.get("model", ""),
            "prompt_fingerprint": version.get("prompt_fingerprint", ""),
            "routing_at_creation": version.get("routing_at_creation", ""),
            "source_channel": version.get("source_channel", "online"),
            "confidence": version.get("confidence"),
            "spans": spans, "words": version.get("words") or [],
            "tones": version.get("tones") or [],
            "sentiment": strip_sentences(version.get("sentiment")),
            "emotions": version.get("emotions") or [],
            "created_at": utc_now(),
        })
        view = {
            "segment_id": segment_id,
            "source_text": seg["text"] if seg else "",
            "target_text": new_text,
            "spans": spans,
            "words": version.get("words") or [],
            "tones": version.get("tones") or [],
            "sentiment": strip_sentences(version.get("sentiment")) or None,
            "emotions": version.get("emotions") or [],
            "span": seg["span"] if seg else [],
            "index": seg["idx"] if seg else 0,
            "confidence": {"score": version.get("confidence")} if version.get("confidence") is not None else None,
            "mode": task.get("mode"),
            "channel": version.get("source_channel", "online"),
            "version_id": version_id,
        }
        self.buffer.append(task_id, Topic.SEGMENT_VIEW, view, payload.get("trace_id", ""))
        return view

    def retranslate(self, task_id: str, segment_ids: Optional[List[str]] = None, trace_id: str = "") -> Dict[str, Any]:
        task = self.repo.get_task(task_id)
        if not task:
            raise err("LAA-3006")
        if task["status"] == TaskStatus.RUNNING.value:
            raise err("LAA-3008")
        return self.start_translation({
            "text": task["source_text"], "target_lang": task["tgt_lang"], "source_lang": task["src_lang"],
            "mode": task["mode"], "scene_profile_id": task["scene_profile_id"], "domain": task["domain"],
        }, trace_id)

    def override_target(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """人工/记忆覆写整段译文：保存为新版本并丢弃旧标注。"""
        task_id = payload.get("task_id")
        segment_id = payload.get("segment_id")
        task = self.repo.get_task(task_id) if task_id else None
        if not task:
            raise err("LAA-3006")
        seg = next((s for s in self.repo.list_segments(task_id) if s["id"] == segment_id), None)
        if not seg:
            raise err("LAA-3005", message="分段不存在")
        text = str(payload.get("target_text") or "").strip()
        if not text:
            raise err("LAA-1002", message="译文为空")
        if len(text) > 20000:
            raise err("LAA-1002", message="译文过长")
        version = self.repo.latest_version(segment_id)
        prev_channel = str((version or {}).get("source_channel") or "").lower()
        kept = build_kept_spans(segment_id, seg["text"], text, task.get("tgt_lang") or "zh-Hans",
                                prev_channel)
        spans = [s.to_dict() for s in kept]
        self.repo.save_version({
            "id": new_id(), "segment_id": segment_id,
            "parent_version_id": version.get("id") if version else None,
            "target_text": text, "origin": str(payload.get("origin") or "manual_edit"),
            "provider": version.get("provider", "") if version else "",
            "model": version.get("model", "") if version else "",
            "prompt_fingerprint": version.get("prompt_fingerprint", "") if version else "",
            "routing_at_creation": version.get("routing_at_creation", "") if version else "",
            "source_channel": version.get("source_channel", "offline") if version else "offline",
            "confidence": None,
            "spans": spans, "words": [], "tones": [],
            "sentiment": strip_sentences((version or {}).get("sentiment")),
            "emotions": (version or {}).get("emotions") or [],
            "created_at": utc_now(),
        })
        view = next((v for v in self._segment_views(task_id) if v["segment_id"] == segment_id), None)
        if view:
            self.buffer.append(task_id, Topic.SEGMENT_VIEW, view, payload.get("trace_id", ""))
        # 采用翻译记忆：累加该条记忆的使用次数（透明化区展示真实 use_count）
        if str(payload.get("origin") or "") == "tm_apply":
            entry_id = str(payload.get("tm_entry_id") or "").strip()
            if not entry_id:
                matched = next((e for e in self.repo.list_tm()
                                if str(e.get("target_text") or "") == text
                                and str(e.get("lang_pair") or "").endswith(
                                    f"-{task.get('tgt_lang') or ''}")), None)
                entry_id = str((matched or {}).get("id") or "")
            self.tm.mark_used(entry_id)
        return view or {}

    EXPORT_FORMATS = ("txt", "json", "md")

    def export(self, task_id: str, fmt: str = "txt", include_meta: bool = True) -> Dict[str, Any]:
        # 参数白名单：未知格式显式拒绝，不依赖上游一定传对
        if fmt not in self.EXPORT_FORMATS:
            raise err("LAA-3011", message=f"导出格式不支持：{fmt}")
        task = self.repo.get_task(task_id)
        if not task:
            raise err("LAA-3006")
        segs = self.repo.list_segments(task_id)

        if fmt == "json":
            items = []
            for seg in segs:
                v = self.repo.latest_version(seg["id"])
                items.append({
                    "index": seg["idx"], "source": seg["text"],
                    "target": v["target_text"] if v else "",
                    "sentiment": (v.get("sentiment") or None) if v else None,
                })
            payload = {
                "task_id": task_id, "src_lang": task["src_lang"], "tgt_lang": task["tgt_lang"],
                "mode": task["mode"], "risk_tier": task["risk_tier"], "segments": items,
            }
            return {"path": f"{task_id}.json", "content": json.dumps(payload, ensure_ascii=False, indent=2)}

        lines: List[str] = []
        for seg in segs:
            v = self.repo.latest_version(seg["id"])
            tt = v["target_text"] if v else ""
            if fmt == "md":
                lines.append(f"### {seg['idx'] + 1}\n\n**原文**  \n{seg['text']}\n\n**译文**  \n{tt}")
            else:
                lines.append(tt)
        body = "\n\n".join(lines)
        meta = ""
        if include_meta:
            meta = (f"[task {task_id} src={task['src_lang']} tgt={task['tgt_lang']} "
                    f"tier={task['risk_tier']} mode={task['mode']}]\n")
        return {"path": f"{task_id}.{fmt}", "content": meta + body}

    # ---------- scene ----------
    def scene_list(self) -> List[Dict[str, Any]]:
        return self.scene.list()

    def scene_manage(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        action = payload.get("action")
        if action == "create":
            prof = payload.get("scene_profile") or {}
            saved = self.scene.save_from_dict(payload.get("scene_profile") or {})
            return saved
        sid = payload.get("scene_id")
        if action == "set_default":
            return self.scene.set_default(sid)
        if action == "delete":
            return self.scene.delete(sid)
        if action == "save":
            return self.scene.save_from_dict(payload.get("scene_profile") or {})
        raise err("LAA-1002", message=f"未知场景动作 {action}")

    def scene_ai(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """对话式场景助理：返回自然语言回复 + 更新后的场景档案字段。"""
        message = (payload.get("message") or "").strip()
        if not message:
            raise err("LAA-1002", message="对话内容不能为空")
        current = payload.get("scene_profile") if isinstance(payload.get("scene_profile"), dict) else {}
        history = payload.get("history") if isinstance(payload.get("history"), list) else []

        messages: List[Dict[str, str]] = [{"role": "system", "content": SCENE_AI_SYSTEM_PROMPT}]
        for h in history:
            if isinstance(h, dict) and h.get("role") in ("user", "assistant") and h.get("content"):
                messages.append({"role": str(h["role"]), "content": str(h["content"])})
        messages.append({"role": "user", "content": json.dumps(
            {"message": message, "current_scene": current}, ensure_ascii=False)})

        result = self.gateway.complete(messages, response_format="json_object")
        content = result.get("content")
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                raise err("LAA-8005", message="场景助手输出不是合法 JSON")
        if not isinstance(content, dict):
            raise err("LAA-8006", message="场景助手输出不合规")

        reply = str(content.get("reply") or "").strip()
        profile = content.get("scene_profile")
        norm = self._norm_scene_ai_profile(profile, current)
        return {"reply": reply, "scene_profile": norm}

    @staticmethod
    def _norm_scene_ai_profile(profile: Any, current: dict) -> dict:
        """归一化 AI 返回的场景字段：类型校正 + 非法枚举回退 + 缺失字段保留现值。"""
        p = profile if isinstance(profile, dict) else {}

        def _str(v: Any, fallback: Any) -> str:
            return str(v).strip() if v not in (None, "") else str(fallback or "")

        def _lines(v: Any) -> List[str]:
            if isinstance(v, list):
                return [str(x).strip() for x in v if str(x).strip()]
            if isinstance(v, str):
                return [ln.strip() for ln in v.splitlines() if ln.strip()]
            return []

        register = p.get("register")
        if register not in ("formal", "semiformal", "informal"):
            register = current.get("register") if current.get("register") in ("formal", "semiformal", "informal") else "semiformal"
        mode = p.get("mode_default")
        if mode not in ("fluent", "literal"):
            mode = current.get("mode_default") if current.get("mode_default") in ("fluent", "literal") else "fluent"

        return {
            "name": _str(p.get("name"), current.get("name", "")),
            "description": _str(p.get("description"), current.get("description", "")),
            "register": register,
            "mode_default": mode,
            "descriptors": _lines(p.get("descriptors")) or list(current.get("descriptors") or []),
            "do": _lines(p.get("do")) or list(current.get("do") or []),
            "dont": _lines(p.get("dont")) or list(current.get("dont") or []),
            "labels": _lines(p.get("labels")) or list(current.get("labels") or []),
        }

    # ---------- glossary ----------
    def glossary_search(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        bank_id = payload.get("bank_id")
        query = (payload.get("query") or "").lower()
        entries = self.repo.list_entries(bank_id) if bank_id else [e for b in self.repo.list_banks() for e in self.repo.list_entries(b["id"])]
        if query:
            entries = [e for e in entries if query in e["source_term"].lower() or query in e["target_term"].lower()]
        limit = int(payload.get("limit", 50))
        return {"items": entries[:limit], "total": len(entries)}

    def _invalidate_memory(self, terms) -> int:
        """术语库增删改后，只让 source_text 命中这些术语的句对失效。

        旧实现把整张记忆表标 stale，加一条无关术语就会让所有历史句对不可召回；
        这里改为按术语命中（ASCII 按词边界、CJK 按子串）精准失效，返回受影响条数。
        """
        try:
            return int(self.tm.invalidate_by_terms(terms) or 0)
        except Exception:  # noqa: BLE001 - 失效失败不影响术语写入
            return 0

    def glossary_add(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        entry = self.glossary.add_entry(payload.get("bank_id", "personal-default"), payload.get("entry") or payload)
        return {"ok": True, "entry": entry,
                "memory_invalidated": self._invalidate_memory([entry.get("source_term", "")])}

    def glossary_remove(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        entry_id = payload["entry_id"]
        e = self.repo.get_entry(entry_id)
        if not e:
            raise err("LAA-4003")
        e["deleted_at"] = utc_now()
        self.repo.save_entry(e)
        return {"removed": entry_id, "memory_invalidated": self._invalidate_memory([e.get("source_term", "")])}

    def glossary_update(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """编辑已有词条：按 entry_id 就地更新，保留语言对/来源/标签，version+1。"""
        patch = payload.get("entry") or payload
        entry_id = payload.get("entry_id") or patch.get("id")
        if not entry_id:
            raise err("LAA-1002", message="缺少 entry_id")
        e = self.repo.get_entry(entry_id)
        if not e:
            raise err("LAA-4003")
        bank = self.repo.get_bank(e["bank_id"]) if self.repo is not None else None
        scope = (bank or {}).get("scope", "personal")
        if (bank and bank.get("readonly")) or scope in ("builtin", "official", "community", "team"):
            raise err("LAA-4004", message="只读术语库不可编辑")
        if "source_term" in patch:
            e["source_term"] = patch["source_term"]
        if "target_term" in patch:
            e["target_term"] = patch["target_term"]
        for k in ("domain", "match_mode", "part_of_speech", "definition"):
            if patch.get(k) is not None:
                e[k] = patch[k]
        if "forced" in patch and patch["forced"] is not None:
            e["forced"] = int(patch["forced"])
        if "case_sensitive" in patch and patch["case_sensitive"] is not None:
            e["case_sensitive"] = int(patch["case_sensitive"])
        if "scene_variants" in patch and patch["scene_variants"] is not None:
            e["scene_variants"] = dict(patch["scene_variants"])
        if not e.get("source_term") or not e.get("target_term"):
            raise err("LAA-1002", message="术语必须填写源词与译词")
        old_term = str((self.repo.get_entry(entry_id) or {}).get("source_term") or "")
        e["version"] = int(e.get("version", 1)) + 1
        self.repo.save_entry(e)
        self._invalidate_memory([old_term, e.get("source_term", "")])
        return self.repo.get_entry(entry_id)

    def glossary_promote(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        entry = self.glossary.promote_to_personal(payload["entry_id"])
        self._invalidate_memory([entry.get("source_term", "")])
        return entry

    def glossary_export(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.glossary.export_package(payload.get("bank_id", "personal-default"))

    def glossary_import(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        pkg = payload.get("package") or {}
        result = dict(self.glossary.import_package(pkg, payload.get("mode", "merge"),
                                                   payload.get("target_bank_id", "personal-default")))
        if result.get("inserted") or result.get("updated"):
            terms = [str(e.get("source_term") or "") for e in (pkg.get("entries") or [])
                     if isinstance(e, dict)]
            result["memory_invalidated"] = self._invalidate_memory(terms)
        return result

    def glossary_package_list(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"items": self.repo.list_banks()}

    def glossary_bank_create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """新建一个用户自定义词库（scope=personal，可编辑，readonly=0）。"""
        name = (payload.get("name") or "").strip()
        if not name:
            raise err("LAA-1002", message="词库名称必填")
        for b in self.repo.list_banks():
            if (b.get("name") or "").strip().lower() == name.lower():
                raise err("LAA-4011", message="词库名称已存在")
        bank_id = "bank-" + new_id()
        bank = {
            "id": bank_id,
            "scope": "personal",
            "name": name,
            "src_lang": (payload.get("src_lang") or "").strip() or "*",
            "tgt_lang": (payload.get("tgt_lang") or "").strip() or "*",
            "domain": (payload.get("domain") or "").strip() or "general",
            "readonly": 0,
            "version": 1,
            "entry_count": 0,
            "owner": "local",
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        self.repo.save_bank(bank)
        return {"ok": True, "bank": self.repo.get_bank(bank_id)}

    def glossary_discover(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """兼容旧入口：扫描当前任务并返回待处理候选。"""
        return self.term_scan(payload)

    def glossary_discover_accept(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        items = []
        for cid in payload.get("ids", []) or []:
            items.append(self.term_accept({"id": cid, "target_term": (payload.get("target_map") or {}).get(cid, "")}))
        return {"accepted": [i.get("candidate", {}).get("id") for i in items]}

    def glossary_discover_reject(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.term_ignore({"ids": payload.get("ids", [])})

    # ---------- term discovery（候选译词闭环：列表 / 采纳 / 忽略） ----------
    def _known_term_set(self) -> set:
        known = set()
        for bank in self.repo.list_banks():
            for entry in self.repo.list_entries(bank["id"]):
                term = (entry.get("source_term") or "").strip().lower()
                if term:
                    known.add(term)
        return known

    def term_scan(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """从当前任务的原文与逐词对齐里抽取候选术语，落库并返回待处理列表。

        只做规则抽取（缩写 / 驼峰 / 下划线 / 定义式 / 高频中文词），不调用模型，零成本。
        """
        from ..domain.glossary.discovery import TermExtractor, _COMMON_STOP

        task_id = (payload.get("task_id") or "").strip()
        if not task_id:
            raise err("LAA-1002", message="缺少字段 task_id")
        task = self.repo.get_task(task_id)
        if not task:
            raise err("LAA-3006")
        tgt_lang = task.get("tgt_lang") or ""
        # 记下这条翻译当时实际使用的术语库（场景解析结果），采纳时默认写回同一库。
        # 真实链路写入的是嵌套结构 resolved_scene.scene.bank_ids；顶层 bank_ids 仅作旧数据兼容。
        resolved = task.get("resolved_scene") or {}
        scene_meta = resolved.get("scene") if isinstance(resolved.get("scene"), dict) else {}
        scene_meta = scene_meta or {}
        bank_ids = [str(b) for b in (scene_meta.get("bank_ids") or resolved.get("bank_ids") or []) if b]
        # 场景未限定术语库时保持为空：采纳前必须让用户显式选库，不静默落到默认库
        default_bank = bank_ids[0] if bank_ids else ""
        known = self._known_term_set()
        extractor = TermExtractor()
        grouped: Dict[str, Dict[str, Any]] = {}

        for seg in self.repo.list_segments(task_id):
            src = seg.get("text") or ""
            if not src.strip():
                continue
            version = self.repo.latest_version(seg["id"]) or {}
            aligned: Dict[str, str] = {}
            for word in version.get("words") or []:
                if not isinstance(word, dict):
                    continue
                key = (word.get("src") or "").strip().lower()
                val = (word.get("dst") or word.get("target") or "").strip()
                if key and val:
                    aligned.setdefault(key, val)
            for mention in extractor.extract(src):
                norm = mention.normalized
                if len(norm) < 2 or norm in _COMMON_STOP or norm in known:
                    continue
                slot = grouped.setdefault(norm, {
                    "surface": mention.surface,
                    "occurrences": 0,
                    "target": "",
                    "context": "",
                    "segment_id": seg["id"],
                    "kinds": set(),
                })
                slot["occurrences"] += 1
                slot["kinds"].add(mention.kind)
                if not slot["context"]:
                    slot["context"] = src.strip()[:180]
                if not slot["target"] and aligned.get(norm):
                    slot["target"] = aligned[norm]

        now = utc_now()
        for norm, slot in grouped.items():
            strong = bool(slot["kinds"] & {"acronym", "camel", "snake", "definition", "proper"})
            confidence = min(0.98, 0.5 + min(0.3, 0.06 * slot["occurrences"])
                             + (0.12 if slot["target"] else 0) + (0.06 if strong else 0))
            self.repo.upsert_term_candidate({
                "id": "cand-" + new_id(),
                "normalized": norm,
                "source_term": slot["surface"],
                "target_term": slot["target"] or None,
                "lang": task.get("detected_lang") or task.get("src_lang") or "",
                "target_lang": tgt_lang,
                "task_id": task_id,
                "segment_id": slot["segment_id"],
                "bank_id": default_bank,
                "context": slot["context"],
                "occurrences": slot["occurrences"],
                "confidence": round(confidence, 3),
                "status": "pending",
                "evidence": [],
                "created_at": now,
                "updated_at": now,
            })

        trimmed = self._enforce_term_limits()
        auto = self._maybe_auto_review(task_id)
        return {
            "scanned": len(grouped),
            "trimmed": trimmed,
            "items": self._candidate_views("pending", task_id),
            "counts": self.repo.count_term_candidates(task_id),
            **({"auto_review": auto} if auto else {}),
        }

    def _candidate_views(self, status: str, task_id: str = "") -> List[Dict[str, Any]]:
        """候选列表按任务过滤：避免不同任务的候选混在一张表里。"""
        items = self.repo.list_term_candidates(status)
        if task_id:
            items = [c for c in items if str(c.get("task_id") or "") == task_id]
        return [self._term_view(c) for c in items]

    @staticmethod
    def _term_view(cand: Dict[str, Any]) -> Dict[str, Any]:
        """给候选补上质量分层与推荐理由，前端据此排序/批量采纳。"""
        conf = float(cand.get("confidence") or 0)
        quality = "high" if conf >= 0.8 else "medium" if conf >= 0.65 else "low"
        reasons: List[str] = []
        if (cand.get("target_term") or "").strip():
            reasons.append("aligned")
        if int(cand.get("occurrences") or 0) >= 3:
            reasons.append("repeated")
        src = (cand.get("source_term") or "").strip()
        if len(src) >= 2 and src.isascii() and src.isalpha() and src.isupper():
            reasons.append("acronym")
        return {**cand, "bank_id": cand.get("bank_id") or "", "quality": quality, "reasons": reasons}

    def term_list(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        status = (payload.get("status") or "pending").strip() or "pending"
        task_id = (payload.get("task_id") or "").strip()
        return {
            "items": self._candidate_views(status, task_id),
            "counts": self.repo.count_term_candidates(task_id or None),
        }

    def term_accept_bulk(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """批量采纳：只处理当前任务「待处理 + 已有译词 + 置信度达标」的候选。

        task_id 是必填的隔离键：没有它就无法判断候选属于哪个任务，
        宁可报错也不能把别的任务的候选一起写进个人术语库。
        """
        task_id = (payload.get("task_id") or "").strip()
        if not task_id:
            raise err("LAA-1002", message="批量采纳必须指定 task_id")
        threshold = float(payload.get("min_confidence") or 0.8)
        wanted = {str(i) for i in (payload.get("ids") or [])}
        override_bank = (payload.get("bank_id") or "").strip()
        # 只读库提前过滤：内置/官方库写不进去，没必要逐条触发异常
        writable = {b["id"] for b in self.repo.list_banks()
                    if not b.get("readonly") and b.get("scope", "personal") == "personal"}
        accepted: List[str] = []
        skipped: List[str] = []
        needs_bank: List[str] = []
        failed: List[Dict[str, str]] = []
        for cand in self.repo.list_term_candidates("pending", task_id=task_id):
            if wanted and cand["id"] not in wanted:
                continue
            if not (cand.get("target_term") or "").strip():
                skipped.append(cand["id"])
                continue
            if float(cand.get("confidence") or 0) < threshold:
                skipped.append(cand["id"])
                continue
            bank_id = override_bank or str(cand.get("bank_id") or "").strip()
            if not bank_id:
                # 当时没有关联术语库：让用户先选，绝不静默落到默认库（不重复计入 skipped）
                needs_bank.append(cand["id"])
                continue
            if bank_id not in writable:
                failed.append({"id": cand["id"],
                               "error": f"目标术语库 {bank_id} 只读或不存在，请改选其它库"})
                continue
            # 逐条独立处理：单条坏数据不影响其余候选
            try:
                self.term_accept({"id": cand["id"], "task_id": task_id, "bank_id": bank_id})
            except Exception as e:  # noqa: BLE001 - 单条失败要如实上报，不整批中止
                failed.append({"id": cand["id"],
                               "error": getattr(e, "message", None) or str(e) or "采纳失败"})
                continue
            accepted.append(cand["id"])
        return {
            "accepted": accepted,
            "skipped": skipped,
            "needs_bank": needs_bank,
            "failed": failed,
            "accepted_count": len(accepted),
            "failed_count": len(failed),
            "bank_id": override_bank,
            "items": self._candidate_views("pending", task_id),
            "counts": self.repo.count_term_candidates(task_id),
        }

    def term_accept(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        cand_id = (payload.get("id") or "").strip()
        cand = self.repo.get_term_candidate(cand_id)
        if not cand:
            raise err("LAA-1002", message="候选术语不存在")
        task_id = (payload.get("task_id") or "").strip()
        if task_id and str(cand.get("task_id") or "") != task_id:
            raise err("LAA-1002", message="候选术语不属于当前任务")
        target = (payload.get("target_term") or cand.get("target_term") or "").strip()
        if not target:
            raise err("LAA-1002", message="采纳前请填写译词")
        # 写入目标：显式选择 > 翻译时实际使用的库；都没有就要求用户选，不静默兜底
        bank_id = (payload.get("bank_id") or cand.get("bank_id") or "").strip()
        if not bank_id:
            raise err("LAA-1002", message="该候选未关联术语库，请先选择目标库")
        bank = next((b for b in self.repo.list_banks() if b["id"] == bank_id), None)
        if bank is None:
            raise err("LAA-1002", message=f"目标术语库 {bank_id} 不存在，请重新选择")
        same = next((e for e in self.repo.list_entries(bank_id)
                     if (e.get("source_term") or "").strip().lower()
                     == cand["source_term"].strip().lower()), None)
        entry_input = {
            "source_term": cand["source_term"],
            "target_term": target,
            "origin": "discovered",
            "confidence": cand.get("confidence") or 0.8,
        }
        if same:
            entry_input["id"] = same["id"]  # 同库已有同源词条：直接更新译词，不产生重复
        entry = self.glossary.add_entry(bank_id, entry_input)
        updated = self.repo.update_term_candidate(cand_id, {
            "status": "accepted", "target_term": target, "updated_at": utc_now(),
        })
        self._invalidate_memory([cand["source_term"]])
        return {
            "ok": True,
            "entry": entry,
            "candidate": updated,
            "trimmed": self._enforce_term_limits(),
            "counts": self.repo.count_term_candidates(task_id or None),
        }

    def term_ignore(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ids = payload.get("ids") or ([payload["id"]] if payload.get("id") else [])
        done = []
        task_id = (payload.get("task_id") or "").strip()
        for cand_id in ids:
            cand = self.repo.get_term_candidate(str(cand_id))
            if not cand:
                continue
            if task_id and str(cand.get("task_id") or "") != task_id:
                continue
            upd = self.repo.update_term_candidate(str(cand_id), {
                "status": "ignored", "updated_at": utc_now(),
            })
            if upd:
                done.append(upd["id"])
        return {"ignored": done, "trimmed": self._enforce_term_limits(),
                "counts": self.repo.count_term_candidates(task_id or None)}

    # ---------- term auto review ----------
    AUTO_REVIEW_BATCH_KEY = "term.auto_review.last_batch"

    def _auto_review_available(self) -> Dict[str, Any]:
        """自动审批依赖真实模型：离线/未配置时必须明确不可用，不能静默跑规则。"""
        try:
            pid = self.gateway.router.default_id
            provider = self.gateway.router.get(pid)
        except Exception as e:  # noqa: BLE001 - 配置缺失按不可用处理
            return {"available": False, "reason": getattr(e, "message", None) or "未配置翻译模型"}
        if pid == "fake" or getattr(provider, "provider_id", "") == "fake":
            return {"available": False, "reason": "当前使用离线演示引擎，未配置真实模型"}
        if not getattr(provider, "api_key", None):
            return {"available": False, "reason": f"供应商 {pid} 未配置密钥"}
        if not getattr(provider, "base_url", "") or not getattr(provider, "model", ""):
            return {"available": False, "reason": f"供应商 {pid} 配置不完整"}
        return {"available": True, "reason": "", "provider_id": pid}

    def term_auto_review_status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        task_id = str(payload.get("task_id") or "").strip() or None
        settings = self.settings_get()
        cfg = settings.get("term_auto_review") or {}
        avail = self._auto_review_available()
        return {
            "enabled": bool(cfg.get("enabled")),
            "threshold": int(cfg.get("threshold") or 0),
            "allow_manual": bool(cfg.get("allow_manual")),
            "available": avail["available"],
            "reason": avail["reason"],
            "pending": int(self.repo.count_term_candidates(task_id).get("pending", 0)),
            "last_batch": self.repo.get_config(self.AUTO_REVIEW_BATCH_KEY, {}) or {},
        }

    def term_auto_review(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        task_id = str(payload.get("task_id") or "").strip() or None
        avail = self._auto_review_available()
        if not avail["available"]:
            raise err("LAA-1002", message=f"自动审批不可用：{avail['reason']}")
        return self._run_term_auto_review(task_id, "manual")

    def _run_term_auto_review(self, task_id: Optional[str], trigger: str) -> Dict[str, Any]:
        """按规则批量裁决待处理候选：高置信且有译词→采纳；低置信/单次无译词→忽略。

        规则是确定性的；但仍要求真实模型可用——离线演示下不提供自动审批。
        """
        writable = {b["id"] for b in self.repo.list_banks()
                    if not b.get("readonly") and b.get("scope", "personal") == "personal"}
        candidates = self.repo.list_term_candidates("pending")
        if task_id:
            candidates = [c for c in candidates if str(c.get("task_id") or "") == task_id]
        accepted: List[str] = []
        ignored: List[str] = []
        failed: List[Dict[str, str]] = []
        needs_bank: List[Dict[str, str]] = []
        items: List[Dict[str, Any]] = []
        skipped = 0
        for cand in candidates:
            target = (cand.get("target_term") or "").strip()
            conf = float(cand.get("confidence") or 0)
            bank_id = str(cand.get("bank_id") or "").strip()
            occurrences = int(cand.get("occurrences") or 0)
            if target and conf >= 0.8 and not bank_id:
                # 高置信但不知道写哪个库：显式回报，保持待处理，交人工指定
                needs_bank.append({"id": cand["id"], "source_term": cand.get("source_term") or "",
                                   "reason": "未指定目标术语库"})
                continue
            if target and conf >= 0.8 and bank_id:
                if bank_id not in writable:
                    failed.append({"id": cand["id"], "source_term": cand.get("source_term") or "",
                                   "reason": f"目标术语库 {bank_id} 只读或不存在"})
                    continue
                try:
                    existing = next((e for e in self.repo.list_entries(bank_id)
                                     if not e.get("deleted_at")
                                     and (e.get("source_term") or "").strip().lower()
                                     == str(cand.get("source_term") or "").strip().lower()), None)
                    res = self.term_accept({"id": cand["id"],
                                            "task_id": cand.get("task_id") or None,
                                            "bank_id": bank_id})
                    entry = res.get("entry") or {}
                    items.append({
                        "candidate_id": cand["id"], "source_term": cand.get("source_term") or "",
                        "bank_id": bank_id, "entry_id": entry.get("id") or "",
                        "created": existing is None,
                        "prev_entry": existing or {},
                    })
                    accepted.append(cand["id"])
                except Exception as e:  # noqa: BLE001 - 单条失败如实上报
                    failed.append({"id": cand["id"], "source_term": cand.get("source_term") or "",
                                   "reason": getattr(e, "message", None) or str(e) or "采纳失败"})
                continue
            if conf < 0.65 or (not target and occurrences <= 1):
                upd = self.repo.update_term_candidate(cand["id"], {
                    "status": "ignored", "updated_at": utc_now(),
                })
                if upd:
                    ignored.append(cand["id"])
                else:
                    failed.append({"id": cand["id"], "source_term": cand.get("source_term") or "",
                                   "reason": "候选不存在或已被处理"})
                continue
            skipped += 1  # 证据不足：保持待处理，交人工判断
        batch_id = ""
        if items or ignored:
            # 采纳与忽略都要记入批次，撤回时才能一起恢复
            batch_id = "arb-" + new_id()
            self.repo.set_config(self.AUTO_REVIEW_BATCH_KEY, {
                "id": batch_id, "task_id": task_id or "", "trigger": trigger,
                "created_at": utc_now(), "counts": {
                    "accepted": len(accepted), "ignored": len(ignored), "failed": len(failed),
                },
                "items": items, "ignored": ignored,
            })
        return {
            "trigger": trigger, "task_id": task_id or "",
            "processed": len(accepted) + len(ignored) + len(failed) + len(needs_bank),
            "accepted_count": len(accepted), "ignored_count": len(ignored),
            "failed_count": len(failed), "skipped": skipped,
            "accepted": accepted, "ignored": ignored, "failed": failed,
            "needs_bank": needs_bank, "needs_bank_count": len(needs_bank),
            "batch_id": batch_id,
            "counts": self.repo.count_term_candidates(task_id),
            "trimmed": self._enforce_term_limits(),
        }

    def term_auto_review_undo(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """撤回上一轮自动审批：恢复本轮采纳与忽略的候选，并撤销本轮新建/改写的词条。"""
        batch = self.repo.get_config(self.AUTO_REVIEW_BATCH_KEY, {}) or {}
        wanted = str(payload.get("batch_id") or "").strip()
        if not batch or (wanted and batch.get("id") != wanted):
            raise err("LAA-1002", message="没有可撤回的自动审批批次")
        restored = 0
        restored_ignored = 0
        for item in reversed(batch.get("items") or []):
            try:
                entry_id = str(item.get("entry_id") or "")
                if entry_id:
                    if item.get("created"):
                        self.repo.delete_entry(entry_id, hard=True)
                    elif item.get("prev_entry"):
                        self.repo.save_entry(dict(item["prev_entry"]))
                if self.repo.update_term_candidate(str(item.get("candidate_id") or ""), {
                    "status": "pending", "updated_at": utc_now(),
                }):
                    restored += 1
            except Exception:  # noqa: BLE001 - 单条撤回失败不影响其余条目
                continue
        for cand_id in batch.get("ignored") or []:
            try:
                if self.repo.update_term_candidate(str(cand_id), {
                    "status": "pending", "updated_at": utc_now(),
                }):
                    restored_ignored += 1
            except Exception:  # noqa: BLE001 - 单条撤回失败不影响其余条目
                continue
        self.repo.set_config(self.AUTO_REVIEW_BATCH_KEY, {})
        task_id = str(batch.get("task_id") or "").strip() or None
        return {"restored": restored, "restored_ignored": restored_ignored,
                "counts": self.repo.count_term_candidates(task_id),
                "trimmed": self._enforce_term_limits()}

    # ---------- settings / candidate limits ----------
    DEFAULT_SETTINGS: Dict[str, Any] = {
        "term_candidate_limits": {"pending": 200, "accepted": 100, "ignored": 100},
        "term_candidate_cleanup": "auto",  # auto=超上限自动删最老；manual=只手动清理
        "memory_limit": 500,               # 0 = 无上限
        "term_auto_review": {"enabled": False, "threshold": 20, "allow_manual": True},
        # 长文本：上限不是“只能翻这么多”，超限前一律分批处理
        "long_text": {"max_chars": 200000, "batch_chars": 2000, "batch_segments": 8,
                      "retries": 2, "throttle_ms": 120},
        # 用量：调用历史的保留策略与统计口径（只影响 calls 表，不动 usage 账单账本）
        "usage": {"calls_retention": 2000, "calls_unlimited": False,
                  "calls_max_age_days": 0, "stats_enabled": True,
                  "stats_include_offline": True},
    }

    @staticmethod
    def _normalize_settings(raw: Any) -> Dict[str, Any]:
        raw = raw if isinstance(raw, dict) else {}
        limits_raw = raw.get("term_candidate_limits")
        limits_raw = limits_raw if isinstance(limits_raw, dict) else {}
        limits: Dict[str, int] = {}
        for name, default in Application.DEFAULT_SETTINGS["term_candidate_limits"].items():
            value = limits_raw.get(name, default)
            try:
                iv = int(value)
            except (TypeError, ValueError):
                raise err("LAA-1002", message=f"候选上限 {name} 必须是整数")
            if iv < 0 or iv > 100000:
                raise err("LAA-1002", message=f"候选上限 {name} 需在 0–100000 之间（0 表示无上限）")
            limits[name] = iv
        cleanup = str(raw.get("term_candidate_cleanup") or "auto")
        if cleanup not in ("auto", "manual"):
            raise err("LAA-1002", message="候选清理策略只能是 auto 或 manual")
        try:
            memory_limit = int(raw.get("memory_limit", Application.DEFAULT_SETTINGS["memory_limit"]))
        except (TypeError, ValueError):
            raise err("LAA-1002", message="翻译记忆上限必须是整数")
        if memory_limit < 0 or memory_limit > 1000000:
            raise err("LAA-1002", message="翻译记忆上限需在 0–1000000 之间（0 表示无上限）")
        review_raw = raw.get("term_auto_review")
        review_raw = review_raw if isinstance(review_raw, dict) else {}
        defaults = Application.DEFAULT_SETTINGS["term_auto_review"]
        try:
            threshold = int(review_raw.get("threshold", defaults["threshold"]))
        except (TypeError, ValueError):
            raise err("LAA-1002", message="自动审批阈值必须是整数")
        if threshold < 1 or threshold > 100000:
            raise err("LAA-1002", message="自动审批阈值需在 1–100000 之间")
        long_raw = raw.get("long_text")
        long_raw = long_raw if isinstance(long_raw, dict) else {}
        long_defaults = Application.DEFAULT_SETTINGS["long_text"]
        long_text: Dict[str, int] = {}
        bounds = {
            "max_chars": (1000, 5_000_000, "长文本上限"),
            "batch_chars": (200, 20000, "每批字符数"),
            "batch_segments": (1, 50, "每批片段数"),
            "retries": (0, 5, "失败重试次数"),
            "throttle_ms": (0, 5000, "批次间隔(毫秒)"),
        }
        for name, (lo, hi, label) in bounds.items():
            try:
                iv = int(long_raw.get(name, long_defaults[name]))
            except (TypeError, ValueError):
                raise err("LAA-1002", message=f"{label}必须是整数")
            if iv < lo or iv > hi:
                raise err("LAA-1002", message=f"{label}需在 {lo}–{hi} 之间")
            long_text[name] = iv
        usage_raw = raw.get("usage")
        usage_raw = usage_raw if isinstance(usage_raw, dict) else {}
        usage_defaults = Application.DEFAULT_SETTINGS["usage"]
        try:
            calls_retention = int(usage_raw.get("calls_retention", usage_defaults["calls_retention"]))
        except (TypeError, ValueError):
            raise err("LAA-1002", message="调用历史保留条数必须是整数")
        if calls_retention < 100 or calls_retention > 200000:
            raise err("LAA-1002", message="调用历史保留条数需在 100–200000 之间；无上限请打开对应开关")
        try:
            calls_max_age_days = int(usage_raw.get("calls_max_age_days", usage_defaults["calls_max_age_days"]))
        except (TypeError, ValueError):
            raise err("LAA-1002", message="清理天数必须是整数")
        if calls_max_age_days not in (0, 30, 90):
            raise err("LAA-1002", message="清理天数只支持 0（不按天数清理）/ 30 / 90")
        return {
            "term_candidate_limits": limits,
            "term_candidate_cleanup": cleanup,
            "memory_limit": memory_limit,
            "term_auto_review": {
                "enabled": bool(review_raw.get("enabled", defaults["enabled"])),
                "threshold": threshold,
                "allow_manual": bool(review_raw.get("allow_manual", defaults["allow_manual"])),
            },
            "long_text": long_text,
            "usage": {
                "calls_retention": calls_retention,
                "calls_unlimited": bool(usage_raw.get("calls_unlimited", usage_defaults["calls_unlimited"])),
                "calls_max_age_days": calls_max_age_days,
                "stats_enabled": bool(usage_raw.get("stats_enabled", usage_defaults["stats_enabled"])),
                "stats_include_offline": bool(usage_raw.get(
                    "stats_include_offline", usage_defaults["stats_include_offline"])),
            },
        }

    def settings_get(self) -> Dict[str, Any]:
        return self._normalize_settings(self.repo.get_config("app.settings", {}) or {})

    def settings_save(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raw = payload.get("settings") if isinstance(payload.get("settings"), dict) else payload
        settings = self._normalize_settings(raw)
        self.repo.set_config("app.settings", settings)
        trimmed_terms = self._enforce_term_limits(settings)
        removed_memory = self.tm.enforce_limit(int(settings["memory_limit"]))
        auto = self._maybe_auto_review(None, settings)
        return {"settings": settings, "removed": {"term_candidates": trimmed_terms,
                                                  "memory": removed_memory},
                **({"auto_review": auto} if auto else {})}

    def _maybe_auto_review(self, task_id: Optional[str],
                           settings: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """开启且待处理数达到阈值时自动执行一次；不可用/未达标时返回 None。"""
        settings = settings or self.settings_get()
        cfg = settings.get("term_auto_review") or {}
        if not cfg.get("enabled"):
            return None
        pending = int(self.repo.count_term_candidates(task_id).get("pending", 0))
        if pending < int(cfg.get("threshold") or 0):
            return None
        avail = self._auto_review_available()
        if not avail["available"]:
            return {"trigger": "auto", "available": False, "reason": avail["reason"],
                    "processed": 0, "accepted_count": 0, "ignored_count": 0, "failed_count": 0,
                    "needs_bank": [], "needs_bank_count": 0,
                    "skipped": 0, "counts": self.repo.count_term_candidates(task_id)}
        return {**self._run_term_auto_review(task_id, "auto"), "available": True}

    def _enforce_term_limits(self, settings: Optional[Dict[str, Any]] = None) -> int:
        settings = settings or self.settings_get()
        if settings.get("term_candidate_cleanup") != "auto":
            return 0
        limits = settings.get("term_candidate_limits") or {}
        total = 0
        for status in ("pending", "accepted", "ignored"):
            limit = int(limits.get(status) or 0)
            if limit > 0:
                total += int(self.repo.trim_term_candidates(status, limit))
        return total

    def term_clear(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        status = str(payload.get("status") or "all")
        if status not in ("pending", "accepted", "ignored", "all"):
            raise err("LAA-1002", message="未知的候选栏目")
        task_id = str(payload.get("task_id") or "").strip() or None
        removed = self.repo.delete_term_candidates(None if status == "all" else status, task_id)
        return {"removed": int(removed), "counts": self.repo.count_term_candidates(task_id)}

    # ---------- provider ----------
    def _provider_view(self, p: Dict[str, Any]) -> Dict[str, Any]:
        """供应商视图：附带白名单校验结果，旧库非法地址在用户确认前标记 blocked。"""
        from ..infra.providers.openai_compat import is_blocked_profile, is_official_base_url

        pid = p["id"]
        handle = p.get("secret_handle") or f"key:{pid}"
        key_present = bool(self.secrets and self.secrets.get(handle))
        cfg = p.get("config_json") or {}
        return {
            "id": pid, "name": p["name"], "kind": p["kind"], "base_url": p["base_url"],
            "model": p["model"], "enabled": bool(p.get("enabled", 1)), "default": bool(p.get("is_default", 0)),
            "configured": key_present, "preset": pid if pid in ("deepseek", "openai", "claude") else "",
            "custom_endpoint": bool(cfg.get("custom_endpoint")),
            "official": is_official_base_url(pid, str(p.get("base_url") or "")),
            "blocked": is_blocked_profile(p),
        }

    def provider_list(self) -> List[Dict[str, Any]]:
        return [self._provider_view(p) for p in self.repo.list_providers()]

    def provider_test(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # 允许对「已保存供应商」或「未保存的表单临时配置」做连通性测试
        from ..infra.providers.openai_compat import (
            OpenAICompatProvider,
            PROVIDER_PRESETS,
            base_url_host,
            base_url_scheme,
            is_blocked_profile,
            is_official_base_url,
        )
        pid = payload.get("provider_id") or payload.get("id") or payload.get("kind") or "openai"
        base_url = str(payload.get("base_url") or "").strip()
        model = payload.get("model")
        api_key = payload.get("api_key")
        allow_custom = bool(payload.get("allow_custom_endpoint", 0))
        saved = next((p for p in self.repo.list_providers() if p["id"] == pid), None)
        saved_custom = bool(((saved or {}).get("config_json") or {}).get("custom_endpoint"))
        if base_url:
            host = base_url_host(base_url)
            scheme = base_url_scheme(base_url)
            if not host or scheme not in ("http", "https"):
                raise err("LAA-2003", message="base_url 非法：需要 http(s)://主机/路径")
            if not is_official_base_url(pid, base_url):
                same_saved = bool(saved) and base_url.rstrip("/") == str(saved.get("base_url") or "").rstrip("/")
                if not (allow_custom or (saved_custom and same_saved and not is_blocked_profile(saved))):
                    raise err("LAA-2003",
                              message=f"base_url 主机 {host} 不在官方白名单内；如确需自定义/中转地址，"
                                      f"请在设置中勾选「允许自定义端点」并保存")
        if not base_url or not model or not api_key:
            # 回退到已保存的配置
            if saved is None:
                raise err("LAA-2003", message=f"未配置供应商 {pid}（缺少 base_url/model/api_key）")
            if is_blocked_profile(saved):
                raise err("LAA-2003",
                          message="该供应商保存的 base_url 未通过白名单校验，"
                                  "请先在设置中确认自定义端点或改回官方域名")
            base_url = saved.get("base_url")
            model = saved.get("model")
            handle = saved.get("secret_handle") or f"key:{pid}"
            api_key = self.secrets.get(handle) if self.secrets else None
        preset = PROVIDER_PRESETS.get(pid, {})
        prov = OpenAICompatProvider(provider_id=pid, name=preset.get("name", pid),
                                    base_url=base_url, model=model, api_key=api_key, timeout_s=20.0)
        return prov.health()

    def _provider_from_profile(self, prof: Dict[str, Any]):
        from ..infra.providers.openai_compat import OpenAICompatProvider
        cfg = prof.get("config_json") or {}
        handle = prof.get("secret_handle") or f"key:{prof['id']}"
        api_key = self.secrets.get(handle) if self.secrets else None
        return OpenAICompatProvider(
            provider_id=prof["id"], name=prof.get("name") or cfg.get("name", prof["id"]),
            base_url=prof.get("base_url") or cfg.get("base_url", ""),
            model=prof.get("model") or cfg.get("model", ""), api_key=api_key)

    def reload_providers(self) -> None:
        from ..infra.providers.fake import FakeProvider
        from ..infra.providers.gateway import ProviderGateway, ProviderRouter
        from ..infra.providers.openai_compat import is_blocked_profile

        profiles = self.repo.list_providers()
        providers = [FakeProvider()]
        for prof in profiles:
            if prof["id"] == "fake" or is_blocked_profile(prof):
                # 未经用户确认的非法地址不进入路由，避免被"盲调"
                continue
            try:
                providers.append(self._provider_from_profile(prof))
            except Exception:
                pass
        default = next((p["id"] for p in profiles if p.get("is_default")), "fake")
        if default not in {x.provider_id for x in providers}:
            default = "fake"
        # 保留 on_usage 回调
        on_usage = self.gateway.on_usage
        self.gateway.router = ProviderRouter(providers, default_id=default)
        self.gateway.on_usage = on_usage

    def provider_upsert(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """写入口同样锁死 base_url：只接受官方域名，自定义/中转需显式开关并落库标记。"""
        from ..infra.providers.openai_compat import (
            PROVIDER_PRESETS,
            base_url_host,
            base_url_scheme,
            is_official_base_url,
        )
        profile = payload.get("profile") or {}
        pid = profile.get("id") or payload.get("provider_id") or profile.get("kind") or "openai"
        if pid == "fake":
            raise err("LAA-1002", message="内置离线引擎不可编辑")
        preset = PROVIDER_PRESETS.get(pid, PROVIDER_PRESETS.get("openai"))
        base_url = str(profile.get("base_url") or payload.get("base_url") or preset["base_url"]).strip().rstrip("/")
        allow_custom = bool(profile.get("allow_custom_endpoint", payload.get("allow_custom_endpoint", 0)))
        existing = next((p for p in self.repo.list_providers() if p["id"] == pid), None)
        saved_url = str((existing or {}).get("base_url") or "").rstrip("/")
        saved_custom = bool(((existing or {}).get("config_json") or {}).get("custom_endpoint"))
        host = base_url_host(base_url)
        scheme = base_url_scheme(base_url)
        if not host or scheme not in ("http", "https"):
            raise err("LAA-2003", message="base_url 非法：需要 http(s)://主机/路径")
        official = is_official_base_url(pid, base_url)
        if not official and not allow_custom and not (saved_custom and base_url == saved_url):
            raise err("LAA-2003",
                      message=f"base_url 主机 {host} 不在官方白名单内；如确需自定义/中转地址，"
                              f"请勾选「允许自定义端点」后保存")
        want_default = bool(profile.get("is_default", payload.get("default", 0)))
        rec = {
            "id": pid, "name": profile.get("name") or payload.get("name") or preset["name"],
            "kind": profile.get("kind", pid),
            "base_url": base_url,
            "model": profile.get("model") or payload.get("model") or preset["model"],
            "enabled": int(profile.get("enabled", payload.get("enabled", True))),
            "is_default": int(want_default),
            "secret_handle": profile.get("secret_handle", f"key:{pid}"),
            "custom_endpoint": 0 if official else 1,
        }
        api_key = payload.get("api_key") or profile.get("api_key")
        if api_key and self.secrets is not None:
            self.secrets.set(f"key:{pid}", api_key)
        if want_default:
            for p in self.repo.list_providers():
                if p["id"] != pid and p.get("is_default"):
                    p2 = dict(p)
                    p2["is_default"] = 0
                    self.repo.save_provider(p2)
        self.repo.save_provider(rec)
        self.reload_providers()
        return {"saved": pid, "default": want_default, "custom_endpoint": bool(rec["custom_endpoint"])}

    def provider_delete(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        pid = payload.get("provider_id") or payload.get("id")
        if pid == "fake":
            raise err("LAA-1002", message="内置离线引擎不可删除")
        if self.repo is not None and hasattr(self.repo, "delete_provider"):
            self.repo.delete_provider(pid)
        if self.secrets is not None:
            self.secrets.delete(f"key:{pid}")
        self.reload_providers()
        return {"deleted": pid}

    # ---------- cost / memory ----------
    def cost_summary(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self.cost.summary(group_by=payload.get("group_by", "provider"))

    def usage_summary(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """账单总览：总金额/token/调用次数 + 按供应商 / 按天分组。"""
        return {
            "totals": self.cost.totals(),
            "by_provider": self.cost.summary("provider"),
            "by_day": self.cost.summary("day"),
        }

    def usage_list(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """账单明细：按时间倒序分页，可选按供应商过滤。"""
        limit = int(payload.get("limit") or 50)
        offset = int(payload.get("offset") or 0)
        provider = payload.get("provider") or None
        return self.cost.list_usage(min(limit, 200), max(offset, 0), provider)

    # ---------- 翻译历史 / 调用历史 ----------
    def history_list(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """工作台侧栏：按时间倒序分页返回最近的翻译任务摘要。"""
        limit = max(1, min(int(payload.get("limit") or 30), 200))
        offset = max(0, int(payload.get("offset") or 0))
        if not hasattr(self.repo, "list_tasks_page"):
            return {"items": [], "total": 0}
        return self.repo.list_tasks_page(limit, offset)

    def calls_list(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """设置 → 调用历史：模型调用列表（提示词预览只给用户原始输入，不含完整提示词）。"""
        limit = max(1, min(int(payload.get("limit") or 20), 200))
        offset = max(0, int(payload.get("offset") or 0))
        task_id = payload.get("task_id") or None
        if not hasattr(self.repo, "list_calls"):
            return {"items": [], "total": 0}
        res = self.repo.list_calls(limit, offset, task_id)
        items = []
        for c in res.get("items", []):
            items.append({
                "id": c.get("id"), "task_id": c.get("task_id") or "",
                "provider": c.get("provider") or "", "model": c.get("model") or "",
                "purpose": c.get("purpose") or "",
                "user_input": (c.get("user_input") or "")[:400],
                "input_tokens": int(c.get("input_tokens") or 0),
                "output_tokens": int(c.get("output_tokens") or 0),
                "amount": float(c.get("amount") or 0.0),
                "latency_ms": int(c.get("latency_ms") or 0),
                "created_at": c.get("created_at") or "",
                "response_preview": (c.get("response") or "")[:300],
            })
        return {"items": items, "total": int(res.get("total") or 0)}

    def call_get(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """设置 → 调用历史详情：完整提示词 messages + 回复 + 花费。"""
        call_id = payload.get("call_id") or payload.get("id")
        if not call_id:
            raise err("LAA-1002", message="缺少 call_id")
        call = self.repo.get_call(call_id) if hasattr(self.repo, "get_call") else None
        if not call:
            raise err("LAA-3005", message="该调用记录不存在")
        messages = call.get("prompt") or []
        if isinstance(messages, str):
            try:
                messages = json.loads(messages)
            except (json.JSONDecodeError, TypeError):
                messages = []
        if not isinstance(messages, list):
            messages = []
        return {
            "id": call.get("id"), "task_id": call.get("task_id") or "",
            "provider": call.get("provider") or "", "model": call.get("model") or "",
            "purpose": call.get("purpose") or "",
            "user_input": call.get("user_input") or "",
            "prompt": {"messages": [
                {"role": str(m.get("role") or ""), "content": str(m.get("content") or "")}
                for m in messages if isinstance(m, dict)
            ]},
            "response": call.get("response") or "",
            "response_preview": (call.get("response") or "")[:300],
            "input_tokens": int(call.get("input_tokens") or 0),
            "output_tokens": int(call.get("output_tokens") or 0),
            "amount": float(call.get("amount") or 0.0),
            "latency_ms": int(call.get("latency_ms") or 0),
            "created_at": call.get("created_at") or "",
        }

    # ---------- 用量：统计与调用历史保留策略 ----------
    def usage_stats(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """统计概览：只读 usage 账本，不受调用历史裁剪影响。"""
        cfg = self.settings_get()["usage"]
        exclude = [] if cfg["stats_include_offline"] else ["fake"]
        repo = self.repo
        totals = repo.usage_totals(exclude) if hasattr(repo, "usage_totals") else {"calls": 0, "input_tokens": 0, "output_tokens": 0, "amount": 0.0}
        by_day = repo.sum_usage("day", exclude) if hasattr(repo, "sum_usage") else []
        by_purpose = repo.sum_usage("purpose", exclude) if hasattr(repo, "sum_usage") else []
        by_provider = repo.sum_usage("provider") if hasattr(repo, "sum_usage") else []
        rng = repo.usage_range() if hasattr(repo, "usage_range") else {"first_at": None, "last_at": None}
        days = sorted(({
            "day": str(r.get("k") or ""),
            "calls": int(r.get("n") or 0),
            "input_tokens": int(r.get("input_tokens") or 0),
            "output_tokens": int(r.get("output_tokens") or 0),
            "amount": float(r.get("amount") or 0.0),
        } for r in by_day), key=lambda d: d["day"])
        return {
            "enabled": bool(cfg["stats_enabled"]),
            "include_offline": bool(cfg["stats_include_offline"]),
            "totals": {
                "calls": int(totals.get("calls") or 0),
                "input_tokens": int(totals.get("input_tokens") or 0),
                "output_tokens": int(totals.get("output_tokens") or 0),
                "amount": float(totals.get("amount") or 0.0),
            },
            "by_day": days,
            "by_purpose": [{"purpose": str(r.get("k") or ""), "calls": int(r.get("n") or 0),
                            "input_tokens": int(r.get("input_tokens") or 0),
                            "output_tokens": int(r.get("output_tokens") or 0),
                            "amount": float(r.get("amount") or 0.0)}
                           for r in by_purpose],
            "by_provider": [{"provider": str(r.get("k") or ""), "calls": int(r.get("n") or 0),
                             "amount": float(r.get("amount") or 0.0)} for r in by_provider],
            "range": rng,
        }

    def _usage_calls_status(self) -> Dict[str, Any]:
        cfg = self.settings_get()["usage"]
        count = int(self.repo.count_calls()) if hasattr(self.repo, "count_calls") else 0
        limit = 0 if cfg["calls_unlimited"] else int(cfg["calls_retention"])
        return {
            "count": count,
            "limit": limit,
            "unlimited": bool(cfg["calls_unlimited"]),
            "over_limit": bool(limit > 0 and count > limit),
            "suggested": 2000,
            "settings": cfg,
        }

    def usage_calls_status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._usage_calls_status()

    def usage_settings_save(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """用户在用量设置里主动保存时才按保留条数裁剪；升级后的超限只提示不删。"""
        current = self.settings_get()
        incoming = payload.get("usage") if isinstance(payload.get("usage"), dict) else payload
        merged = {**current, "usage": {**current["usage"], **(incoming or {})}}
        settings = self._normalize_settings(merged)
        self.repo.set_config("app.settings", settings)
        cfg = settings["usage"]
        trimmed = 0
        if not cfg["calls_unlimited"] and hasattr(self.repo, "trim_calls"):
            trimmed = int(self.repo.trim_calls(int(cfg["calls_retention"])) or 0)
        return {"settings": settings, "removed": {"calls": trimmed},
                "calls": self._usage_calls_status()}

    def usage_calls_cleanup(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """按天数清理调用历史；账单聚合（usage 表）完全不动。

        days=0 表示不按天数清理：必须原样传 0，且一条都不删。
        """
        cfg = self.settings_get()["usage"]
        raw_days = payload.get("days", cfg["calls_max_age_days"])
        try:
            days = int(raw_days)
        except (TypeError, ValueError):
            days = 0
        if days == 0:
            return {"removed": 0, "days": 0, "cutoff": None,
                    "calls": self._usage_calls_status()}
        if days not in (30, 90):
            raise err("LAA-1002", message="按天数清理只支持 30 天或 90 天")
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="milliseconds")
        removed = int(self.repo.delete_calls_before(cutoff)) if hasattr(self.repo, "delete_calls_before") else 0
        return {"removed": removed, "days": days, "cutoff": cutoff,
                "calls": self._usage_calls_status()}

    def usage_calls_clear(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """清空调用历史；返回清空后的账单总额，证明聚合没有被一起清掉。"""
        removed = int(self.repo.clear_calls()) if hasattr(self.repo, "clear_calls") else 0
        return {"removed": removed, "billing": self.usage_summary({}), "calls": self._usage_calls_status()}

    # ---------- 皮肤 ----------
    def skin_list(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._require_skin()
        return self.skin.list()

    def skin_active(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._require_skin()
        return self.skin.active()

    def skin_select(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._require_skin()
        return self.skin.select(str(payload.get("id") or payload.get("skin_id") or ""))

    def skin_import(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._require_skin()
        return self.skin.import_package(str(payload.get("filename") or ""),
                                        str(payload.get("data") or ""))

    def skin_export(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._require_skin()
        return self.skin.export_package(str(payload.get("id") or payload.get("skin_id") or ""))

    def skin_delete(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._require_skin()
        return self.skin.delete(str(payload.get("id") or payload.get("skin_id") or ""))

    def _require_skin(self) -> None:
        if self.skin is None:
            raise err("LAA-9001", message="皮肤服务未启用")

    def memory_lookup(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        hits = self.tm.lookup(payload["source_text"], payload.get("src_lang", "en"), payload.get("tgt_lang", "zh-Hans"),
                              payload.get("domain", "general"))
        return [h.to_dict() for h in hits]

    def memory_list(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """翻译记忆管理：按语言对/关键词过滤并分页，默认隐藏已失效条目。"""
        query = str(payload.get("query") or "").strip().lower()
        lang_pair = str(payload.get("lang_pair") or "").strip()
        include_stale = bool(payload.get("include_stale"))
        try:
            limit = max(1, min(500, int(payload.get("limit") or 50)))
        except (TypeError, ValueError):
            limit = 50
        try:
            offset = max(0, int(payload.get("offset") or 0))
        except (TypeError, ValueError):
            offset = 0
        rows = []
        all_rows = self.repo.list_tm() or []
        stale_total = sum(1 for e in all_rows if int(e.get("stale") or 0))
        for e in all_rows:
            if e.get("stale") and not include_stale:
                continue
            if lang_pair and e.get("lang_pair") != lang_pair:
                continue
            if query and query not in str(e.get("source_text", "")).lower() \
                    and query not in str(e.get("target_text", "")).lower():
                continue
            rows.append({
                "entry_id": e.get("id", ""),
                "source_text": e.get("source_text", ""),
                "target_text": e.get("target_text", ""),
                "lang_pair": e.get("lang_pair", ""),
                "domain": e.get("domain", "general"),
                "approved": bool(e.get("approved")),
                "quality": float(e.get("quality") or 0.0),
                "stale": bool(e.get("stale")),
                "use_count": int(e.get("use_count") or 0),
                "last_used_at": e.get("last_used_at") or "",
                "created_at": e.get("created_at") or "",
            })
        rows.sort(key=lambda r: (r["stale"], -r["use_count"], r["entry_id"]))
        return {"items": rows[offset:offset + limit], "total": len(rows),
                "limit": limit, "offset": offset, "stale_total": stale_total,
                "pairs": sorted({r["lang_pair"] for r in rows if r["lang_pair"]})}

    def memory_restore(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """确认恢复一条因术语变更而失效的记忆（清 stale 标记）。"""
        entry_id = str(payload.get("entry_id") or "").strip()
        if not entry_id:
            raise err("LAA-1002", message="缺少字段 entry_id")
        return {"entry_id": entry_id, "restored": bool(self.tm.restore(entry_id))}

    def memory_add(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """把当前译文手动加入翻译记忆（结果区「加入记忆」）。"""
        task_id = str(payload.get("task_id") or "").strip()
        segment_id = str(payload.get("segment_id") or "").strip()
        task = self.repo.get_task(task_id) if task_id else None
        if not task:
            raise err("LAA-3006")
        seg = self.repo.get_segment(segment_id) if segment_id else None
        if not seg or str(seg.get("task_id") or "") != task_id:
            raise err("LAA-3005", message="分段不存在")
        version = self.repo.latest_version(segment_id)
        if not version:
            raise err("LAA-1002", message="该分段尚无译文，无法加入记忆")
        channel = str(version.get("source_channel") or "").lower()
        if channel in ("offline", "fake"):
            raise err("LAA-1002", message="离线或演示译文不写入翻译记忆")
        src = str(seg.get("text") or "").strip()
        tgt = str(version.get("target_text") or "").strip()
        if not src or not tgt or src == tgt:
            raise err("LAA-1002", message="句对内容为空，无法加入记忆")
        entry = self.tm.store(
            src, tgt, task.get("src_lang") or "auto", task.get("tgt_lang") or "",
            domain=task.get("domain") or "general", approved=True,
            scene_profile_id=task.get("scene_profile_id"), skip_if_exists=True,
        )
        removed = self.tm.enforce_limit(int(self.settings_get()["memory_limit"]))
        return {"entry_id": entry.id, "entry": entry.to_dict(), "removed": removed}

    def memory_delete(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        entry_id = str(payload.get("entry_id") or "").strip()
        if not entry_id:
            raise err("LAA-1002", message="缺少字段 entry_id")
        return {"entry_id": entry_id, "deleted": bool(self.repo.delete_tm(entry_id))}

    # ---------- misc ----------
    def app_info(self) -> Dict[str, Any]:
        from laa_core import __version__
        return {"version": __version__, "providers": self.repo.list_providers(),
                "capabilities": self.capabilities.list()["items"], "storage": "local"}

    def capability_list(self, group: Optional[str] = None) -> Dict[str, Any]:
        return self.capabilities.list(group)

    def message_keys(self) -> Dict[str, str]:
        return self.capabilities.message_keys

    def diagnostics_export(self) -> Dict[str, Any]:
        from laa_core import __version__
        md5 = hashlib.sha256(json.dumps({"tasks": self.repo.list_tasks()}, sort_keys=True,
                                        default=str).encode()).hexdigest()
        return {"version": __version__, "tasks": len(self.repo.list_tasks()),
                "checksum": md5[:16]}

    def community_list(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"items": []}

    def community_add(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"accepted": True, "source": payload.get("url")}

    def community_sync(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"synced": 0}

    def community_remove(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"removed": payload.get("url")}