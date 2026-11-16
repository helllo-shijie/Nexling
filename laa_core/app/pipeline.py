"""Translation orchestrator: the staged S0→S6 pipeline with checkpointing & cancellation."""
from __future__ import annotations

import json
import re
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterator, List, Optional

from ..domain.text.service import plan_batches

from ..shared import (
    AnnotatedSpan,
    ConfidenceResult,
    EmotionAnnotation,
    QAReport,
    RiskAssessment,
    SegmentView,
    TextSegment,
    TranslateRequest,
    UiEvent,
    new_id,
    utc_now,
    err,
)
from ..shared.events import Topic
from ..shared.clock import CancellationToken
from ..shared.types import TaskStatus, TranslateMode

EventSink = Callable[[str, Dict[str, Any]], None]

_CJK_TARGETS = ("zh", "ja", "ko")

# 情感概率低于该阈值时，界面提示人工复核
SENTIMENT_REVIEW_THRESHOLD = 0.6

_SENTIMENT_KEYS = ("positive", "negative", "neutral")
_SENTIMENT_ALIASES = {
    "positive": ("positive", "pos", "积极", "正面"),
    "negative": ("negative", "neg", "消极", "负面"),
    "neutral": ("neutral", "neu", "中性", "中立"),
}


def _no_space_lang(tgt_lang: str) -> bool:
    return (tgt_lang or "").lower().startswith(_CJK_TARGETS)


def norm_sentiment(raw: Any, threshold: float = SENTIMENT_REVIEW_THRESHOLD) -> Optional[Dict[str, Any]]:
    """归一化模型返回的情感概率分布。

    容忍 {"positive":0.7,...}、{"积极":70,...}、[{"label":"positive","score":0.7}] 等写法；
    百分比自动换算为 0~1 并归一化到总和 1；无法解析时返回 None（界面不显示概率条）。
    """
    values: Dict[str, Optional[float]] = {k: None for k in _SENTIMENT_KEYS}
    if isinstance(raw, dict):
        src = raw.get("probabilities") if isinstance(raw.get("probabilities"), dict) else raw
        for canon in _SENTIMENT_KEYS:
            for alias in _SENTIMENT_ALIASES[canon]:
                if alias in src:
                    try:
                        values[canon] = float(src[alias])
                    except (TypeError, ValueError):
                        values[canon] = None
                    break
    elif isinstance(raw, list):
        for it in raw:
            if not isinstance(it, dict):
                continue
            label = str(it.get("label") or it.get("emotion") or "").strip().lower()
            score = it.get("score", it.get("value"))
            for canon in _SENTIMENT_KEYS:
                if label in _SENTIMENT_ALIASES[canon] or label == canon:
                    try:
                        values[canon] = float(score)
                    except (TypeError, ValueError):
                        values[canon] = None
    if any(v is None for v in values.values()):
        return None
    nums = [max(0.0, float(values[k] or 0.0)) for k in _SENTIMENT_KEYS]
    if max(nums) <= 0:
        return None
    if max(nums) > 1.0:
        nums = [n / 100.0 for n in nums]
    total = sum(nums)
    if total <= 0:
        return None
    probs = [min(1.0, n / total) for n in nums]
    out = {k: round(p, 3) for k, p in zip(_SENTIMENT_KEYS, probs)}
    # 四舍五入后补回误差，保证三项相加为 1
    out["neutral"] = round(max(0.0, min(1.0, out["neutral"] + round(1.0 - sum(out.values()), 3))), 3)
    out["threshold"] = threshold
    out["needs_review"] = max(out[k] for k in _SENTIMENT_KEYS) < threshold
    return out


def _skip_ws(text: str, i: int) -> int:
    while i < len(text) and text[i].isspace():
        i += 1
    return i


def norm_sentences(raw: Any, source_text: str, target_text: str) -> List[Dict[str, Any]]:
    """归一化模型分句＋句子级情感。

    每条必须同时给出 source 与 text：source 需与原文按顺序连续对齐，text 需与译文按顺序连续对齐，
    两段拼接后不得吞字或重复。只需一条对不齐，该段整段降级为段落级（不产生任何行内标注），
    避免把错误区间画到正文上。模型分句本身来自原文，因此这里也校验了“分句结果与原文可对齐”。
    """
    if not isinstance(raw, list):
        return []
    src = source_text or ""
    tgt = target_text or ""
    out: List[Dict[str, Any]] = []
    sc = 0
    tc = 0
    for it in raw:
        if not isinstance(it, dict):
            return []
        sent = str(it.get("text") or it.get("sentence") or "").strip()
        sent_src = str(it.get("source") or it.get("source_text") or "").strip()
        if not sent or not sent_src:
            return []
        probs = norm_sentiment(it.get("sentiment"))
        if not probs:
            return []
        sc = _skip_ws(src, sc)
        if not src.startswith(sent_src, sc):
            return []
        tc = _skip_ws(tgt, tc)
        if not tgt.startswith(sent, tc):
            return []
        start = tc
        end = tc + len(sent)
        sc += len(sent_src)
        tc = end
        label = max(_SENTIMENT_KEYS, key=lambda k: probs[k])
        out.append({
            "span": [start, end], "text": sent, "source": sent_src,
            "positive": probs["positive"], "negative": probs["negative"], "neutral": probs["neutral"],
            "label": label, "needs_review": bool(probs.get("needs_review")),
        })
        if len(out) >= 40:
            break
    if not out:
        return []
    if src[_skip_ws(src, sc):].strip() or tgt[_skip_ws(tgt, tc):].strip():
        return []
    # 标点误用产生的二字碎片（如“很。”“到你”）不单独成句：整段降级为段落级，
    # 避免在正文上画出四五个碎句标注。
    if len(out) > 1 and any(len(o["source"].strip()) < 3 for o in out):
        return []
    return out


def strip_sentences(sentiment: Any) -> Dict[str, Any]:
    """文本被改写后丢弃句子级情感：区间已失效，保留会指向错误的句子。"""
    if not isinstance(sentiment, dict):
        return {}
    return {k: v for k, v in sentiment.items() if k != "sentences"}


def norm_variants(raw: Any, target_text: str) -> List[Dict[str, Any]]:
    """归一化候选译法：[{text, span:[s,e], options:[...]}]。

    容忍 options/alternatives 两种键名与字符串/对象两种元素；text 必须能在译文中定位。
    """
    if not isinstance(raw, list):
        return []
    n = len(target_text or "")
    out: List[Dict[str, Any]] = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        text = str(it.get("text") or it.get("current") or "").strip()
        if not text or text not in (target_text or ""):
            continue
        options: List[str] = []
        for o in (it.get("options") or it.get("alternatives") or []):
            v = o.get("text") if isinstance(o, dict) else o
            v = str(v or "").strip()
            if v and v != text and v not in options:
                options.append(v)
        if not options:
            continue
        start: Optional[int] = None
        end: Optional[int] = None
        span = it.get("span")
        if isinstance(span, (list, tuple)) and len(span) >= 2:
            try:
                s, e = int(span[0]), int(span[1])
            except (TypeError, ValueError):
                s = e = -1
            if 0 <= s < e <= n and target_text[s:e] == text:
                start, end = s, e
        if start is None:
            pos = target_text.find(text)
            if pos < 0:
                continue
            start, end = pos, pos + len(text)
        out.append({"text": text, "span": [start, end], "options": options[:4]})
        if len(out) >= 6:
            break
    return out


def build_variant_spans(segment_id: str, variants: List[Dict[str, Any]]) -> List[AnnotatedSpan]:
    """把候选译法转成带 variants 的 span（区间在译文内），供气泡展示与点选。"""
    spans: List[AnnotatedSpan] = []
    for k, v in enumerate(variants):
        text = str(v.get("text") or "")
        span = v.get("span") or []
        if not text or len(span) != 2:
            continue
        variants_list = [{"id": f"{segment_id}-v{k}-0", "label": text, "text": text, "source": "model"}]
        for j, opt in enumerate(v.get("options") or []):
            variants_list.append({"id": f"{segment_id}-v{k}-{j + 1}", "label": str(opt), "text": str(opt), "source": "model"})
        spans.append(AnnotatedSpan(
            id=f"{segment_id}-var-{k}", text=text, span=[int(span[0]), int(span[1])],
            kinds=["alternate_translation"], variants=variants_list, note="可替换译法",
        ))
    return spans


_CHINESE_RUN = re.compile(r"[\u3400-\u9fff]{2,}")
# 离线演示引擎的回显前缀：〔离线演示…〕原文：<整段源文>
_OFFLINE_ECHO = re.compile(r"^\s*〔[^〕]*〕\s*原文[:：]\s*")


def build_kept_spans(segment_id: str, source_text: str, target_text: str, tgt_lang: str,
                     channel: str = "") -> List[AnnotatedSpan]:
    """中文保留标注：译为非中文时，原文里原样保留的中文片段在译文中加细下划线。

    译成中文时整段本来都是中文，不做标注；离线演示（channel=offline）或译文只是回显原文时
    同样不标注，避免把「没翻译」误报成「刻意保留」。
    """
    if (tgt_lang or "").lower().startswith("zh"):
        return []
    if (channel or "").lower() == "offline":
        return []
    if not (source_text or "") or not (target_text or ""):
        return []
    if source_text.strip() == target_text.strip():
        return []
    echo = _OFFLINE_ECHO.sub("", target_text or "").strip()
    if echo == (source_text or "").strip():
        return []
    spans: List[AnnotatedSpan] = []
    cursor = 0
    seen = set()
    for m in _CHINESE_RUN.finditer(source_text or ""):
        run = m.group(0)
        pos = target_text.find(run, cursor)
        if pos < 0:
            pos = target_text.find(run)
        if pos < 0 or run in seen:
            continue
        seen.add(run)
        spans.append(AnnotatedSpan(
            id=f"{segment_id}-kept-{len(spans)}", text=run, span=[pos, pos + len(run)],
            kinds=["source_lang_kept"], note="原文中文保留",
        ))
        cursor = pos + len(run)
        if len(spans) >= 8:
            break
    return spans


def drop_overlaps(candidates: List[AnnotatedSpan], taken: List[AnnotatedSpan]) -> List[AnnotatedSpan]:
    """丢弃与已占用区间重叠的候选 span，保证同一段文字只标注一次。"""
    def bounds(s: Any) -> Optional[tuple]:
        sp = s.get("span") if isinstance(s, dict) else getattr(s, "span", None)
        if isinstance(sp, (list, tuple)) and len(sp) >= 2:
            return int(sp[0]), int(sp[1])
        return None

    occupied = [b for b in (bounds(s) for s in taken) if b]
    out: List[AnnotatedSpan] = []
    for c in sorted(candidates, key=lambda s: (s.span[0], s.span[1])):
        cs, ce = c.span[0], c.span[1]
        if any(not (ce <= os_ or cs >= oe) for os_, oe in occupied):
            continue
        occupied.append((cs, ce))
        out.append(c)
    return out


def norm_literal_words(raw: Any, source_text: str = "") -> List[Dict[str, Any]]:
    """归一化模型返回的逐词对齐：[{src, target, alternatives:[...]}]。

    丢弃无 target 的条目；alternatives 去重且不含默认义项；保留原文顺序。
    另外做一层“是否真的逐词”的防护：若模型把整句/习语当成一个词（或词数远少于原文词数），
    逐词视图会误导用户，此时返回空列表让上层退化为整句直译。
    """
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        target = str(it.get("target") or "").strip()
        if not target:
            continue
        alts: List[str] = []
        for a in it.get("alternatives") or []:
            if isinstance(a, str):
                v = a.strip()
            elif isinstance(a, dict):
                v = str(a.get("label") or "").strip()
            else:
                v = ""
            if v and v != target and v not in alts:
                alts.append(v)
        out.append({"src": str(it.get("src") or "").strip(), "target": target, "alternatives": alts})
    src_words = [t for t in re.split(r"\s+", (source_text or "").strip()) if t]
    if src_words:
        # 原文多个词却只回一两个“词”，或单个词长达整句——都不是逐词义项
        if len(src_words) >= 4 and len(out) <= max(1, len(src_words) // 4):
            return []
        if any(len(w["target"]) > 60 for w in out):
            return []
    return out


def norm_tones(raw: Any, source_text: str) -> List[Dict[str, Any]]:
    """归一化语气识别结果：[{span:[s,e], label}]，区间相对本段原文。

    容忍三种写法：span=[s,e] / start+end / 直接给 text 片段（按子串定位）。
    非法区间、空标签、重叠片段都会被丢弃；没有明显语气时返回空列表。
    """
    if not isinstance(raw, list):
        return []
    n = len(source_text or "")
    out: List[Dict[str, Any]] = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        label = str(it.get("label") or it.get("tone") or "").strip()
        if not label:
            continue
        label = label[:12]
        start: Optional[int] = None
        end: Optional[int] = None
        span = it.get("span")
        if isinstance(span, (list, tuple)) and len(span) >= 2:
            try:
                start, end = int(span[0]), int(span[1])
            except (TypeError, ValueError):
                start = end = None
        if start is None:
            try:
                start, end = int(it.get("start")), int(it.get("end"))
            except (TypeError, ValueError):
                start = end = None
        if start is None:
            frag = str(it.get("text") or "").strip()
            if frag:
                pos = source_text.find(frag)
                if pos >= 0:
                    start, end = pos, pos + len(frag)
        if start is None or end is None:
            continue
        start = max(0, min(int(start), n))
        end = max(0, min(int(end), n))
        if end <= start:
            continue
        out.append({"span": [start, end], "label": label})
    out.sort(key=lambda t: t["span"][0])
    cleaned: List[Dict[str, Any]] = []
    for t in out:
        if cleaned and t["span"][0] < cleaned[-1]["span"][1]:
            continue  # 重叠片段只保留先出现的
        cleaned.append(t)
    return cleaned


def join_words(words: List[Dict[str, Any]], tgt_lang: str) -> str:
    """按目标语言习惯把逐词译文拼成整句（中文等无空格相连，其余空格分隔）。"""
    pieces = [str(w.get("target") or "") for w in words]
    return ("" if _no_space_lang(tgt_lang) else " ").join(pieces)


def build_literal_spans(words: List[Dict[str, Any]], target: str) -> List[AnnotatedSpan]:
    """为逐词译文生成 span（区间在 target 内），供透明化样式与点选使用。"""
    spans: List[AnnotatedSpan] = []
    cursor = 0
    for i, w in enumerate(words):
        piece = str(w.get("target") or "")
        if not piece:
            continue
        start = target.find(piece, cursor)
        if start < 0:
            start = target.find(piece)
        if start < 0:
            continue
        end = start + len(piece)
        variants = [{"id": f"w{i}-0", "label": piece, "source": "literal"}]
        for j, alt in enumerate(w.get("alternatives") or []):
            variants.append({"id": f"w{i}-{j + 1}", "label": alt, "source": "literal"})
        spans.append(AnnotatedSpan(
            id=f"lw-{i}-{start}", text=piece, span=[start, end],
            kinds=["literal_word"], variants=variants,
            note=str(w.get("src") or ""),
        ))
        cursor = end
    return spans


class TranslationOrchestrator:
    """Wires domain services into the translation pipeline. Domain services are injected."""

    def __init__(self, repo, text, glossary, risk, scene, qa, emotion, tm, cost, provider_gateway):
        self.repo = repo
        self.text = text
        self.glossary = glossary
        self.risk = risk
        self.scene = scene
        self.qa = qa
        self.emotion = emotion
        self.tm = tm
        self.cost = cost
        self.gateway = provider_gateway

    # ---- helpers ----
    def _emit(self, sink: Optional[EventSink], topic: str, payload: Dict[str, Any], task_id: str) -> None:
        if sink is not None:
            sink(topic, {"task_id": task_id, **payload})

    def _set_status(self, task_id: str, status: str, sink: Optional[EventSink]) -> None:
        self.repo.update_task(task_id, {"status": status})
        topic = {
            TaskStatus.PREPARING.value: Topic.TASK_PROGRESS,
            TaskStatus.RUNNING.value: Topic.TASK_PROGRESS,
            TaskStatus.FINALIZING.value: Topic.TASK_FINALIZING,
            TaskStatus.SUCCEEDED.value: Topic.TASK_COMPLETED,
            TaskStatus.FAILED.value: Topic.TASK_FAILED,
            TaskStatus.CANCELLED.value: Topic.TASK_CANCELLED,
        }.get(status, Topic.TASK_PROGRESS)
        self._emit(sink, topic, {"status": status}, task_id)

    def _split_source_sentences(self, text: str) -> List[str]:
        """超长段落交给模型按语义分句；离线或失败由网关退回本地兜底。"""
        return self.gateway.split_sentences(text)

    def _locked_terms_block(self, task_id: str, hits: Optional[List[Any]] = None) -> str:
        """已定译法约束：术语库命中优先于模型自报，用户指定优先于两者。"""
        glossary: Dict[str, str] = {}
        for hit in hits or []:
            src_term = getattr(hit, "source_term", "")
            tgt_term = getattr(hit, "target_term", "") or ""
            if src_term and tgt_term:
                glossary[src_term] = tgt_term
        lines: List[str] = []
        for r in self.repo.list_task_terms(task_id):
            source = r.get("source_term") or ""
            target = r.get("target_term") or ""
            if not source or not target:
                continue
            if r.get("origin") == "model" and source in glossary and glossary[source] != target:
                continue
            lines.append(f"{source} => {target}")
        return "\n".join(lines[:200])

    def _record_batch_terms(self, task_id: str, batch: List[TextSegment],
                            raw_terms: Dict[str, Any], drafts: Dict[str, str],
                            hits: List[Any]) -> None:
        """记录本批出现的“术语→实际译法”。

        只接受能对上号的数据：source 必须在该段原文中、target 必须在该段译文中；
        对不上的一律丢弃，不猜测。术语库命中优先于模型自报。
        """
        now = datetime.now(timezone.utc).isoformat()
        for seg in batch:
            target = drafts.get(seg.id) or ""
            for hit in hits:
                src_term = getattr(hit, "source_term", "")
                tgt_term = getattr(hit, "target_term", "") or ""
                if not src_term or not tgt_term:
                    continue
                if src_term in seg.text and tgt_term in target:
                    self.repo.upsert_task_term({
                        "task_id": task_id, "source_term": src_term, "target_term": tgt_term,
                        "term_id": getattr(hit, "term_id", ""), "origin": "glossary",
                        "segment_id": seg.id, "updated_at": now,
                    })
            for item in raw_terms.get(seg.id) or []:
                if not isinstance(item, dict):
                    continue
                src_term = str(item.get("source") or "").strip()
                tgt_term = str(item.get("target") or "").strip()
                if not src_term or not tgt_term or len(src_term) > 80 or len(tgt_term) > 120:
                    continue
                if src_term not in seg.text or tgt_term not in target:
                    continue
                self.repo.upsert_task_term({
                    "task_id": task_id, "source_term": src_term, "target_term": tgt_term,
                    "term_id": "", "origin": "model", "segment_id": seg.id, "updated_at": now,
                })

    def run(self, task_id: str, req: TranslateRequest, token: Optional[CancellationToken],
            sink: Optional[EventSink] = None, options: Optional[Dict[str, Any]] = None,
            only_segment_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        opts: Dict[str, Any] = {"batch_chars": 2000, "batch_segments": 8, "retries": 2, "throttle_ms": 120}
        if options:
            opts.update({k: v for k, v in options.items() if v is not None})
        task = self.repo.get_task(task_id)
        src = task["src_lang"] or req.source_lang or "auto"
        tgt = task["tgt_lang"]

        # S0 preflight（续传时复用已落库的片段，不重切、不覆盖已完成结果）
        self._set_status(task_id, TaskStatus.PREPARING.value, sink)
        if only_segment_ids is None:
            segments: List[TextSegment] = self.text.segment_text(
                task["source_text"], task.get("detected_lang") or "",
                sentence_splitter=self._split_source_sentences)
            detected = self.text.detect_language(task["source_text"], req.source_lang)
            if src == "auto":
                src = detected["lang"]
                self.repo.update_task(task_id, {"src_lang": src, "detected_lang": detected["lang"]})
            if (tgt or "").lower() == "auto":
                # 目标语言自动：中文原文译成英文，其余译成简体中文
                tgt = "en" if str(src).lower().startswith("zh") else "zh-Hans"
                self.repo.update_task(task_id, {"tgt_lang": tgt})
            # 提示词只能看到解析后的具体语言：auto 不能流进 compose
            try:
                req = replace(req, target_lang=tgt)
            except TypeError:
                req.target_lang = tgt  # type: ignore[misc]
            for seg in segments:
                seg.lang = src
                self.repo.save_segment({
                    "id": seg.id, "task_id": task_id, "idx": seg.index, "text": seg.text,
                    "span": seg.span, "lang": src, "token_estimate": seg.token_estimate,
                    "status": "pending", "forced": bool(seg.forced),
                })
            self.repo.update_task(task_id, {"segment_count": len(segments)})
        else:
            wanted = set(only_segment_ids)
            rows = self.repo.list_segments(task_id)
            segments = [TextSegment(
                id=r["id"], index=int(r.get("idx") or 0), text=r.get("text") or "",
                span=list(r.get("span") or [0, 0]), lang=r.get("lang") or "",
                token_estimate=int(r.get("token_estimate") or 0),
                status=r.get("status") or "pending", forced=bool(r.get("forced")),
            ) for r in rows]
            for r in rows:
                if r["id"] in wanted:
                    r["status"] = "pending"
                    self.repo.save_segment(r)
            try:
                req = replace(req, target_lang=tgt)
            except TypeError:
                req.target_lang = tgt  # type: ignore[misc]
        work: List[TextSegment] = [s for s in segments
                                   if only_segment_ids is None or s.id in set(only_segment_ids)]
        batches = plan_batches(work, int(opts["batch_chars"]), int(opts["batch_segments"]))
        self.repo.update_task(task_id, {"segment_count": len(segments), "batch_total": len(batches)})
        self._emit(sink, Topic.TASK_PROGRESS, {
            "phase": "preflight", "segment_count": len(segments), "batch_total": len(batches),
            "total": len(segments), "done": self._count_status(task_id, "done"),
            "failed": self._count_status(task_id, "failed"), "remaining": len(work),
        }, task_id)

        # risk assessment (domain = task.domain)
        risk_assessment: RiskAssessment = self.risk.assess(task["source_text"], segments, task.get("domain", "general"))
        risk_assessment.task_id = task_id
        resolved_meta = {**(task.get("resolved_scene") or {}), "risk": risk_assessment.to_dict()}
        self.repo.update_task(task_id, {
            "risk_tier": risk_assessment.tier,
            "routing": risk_assessment.routing,
            "resolved_scene": resolved_meta,
        })
        self._emit(sink, Topic.RISK_ASSESSED, {"tier": risk_assessment.tier, "routing": risk_assessment.routing,
                                               "reason": self.risk.explain(risk_assessment)}, task_id)
        token.raise_if_cancelled() if token else None

        # scene resolve + mode
        resolved_scene = self.scene.resolve(task.get("scene_profile_id"))
        mode = self.scene.resolve_mode(req.mode if req.mode else task.get("mode"), resolved_scene) \
            if hasattr(self.scene, "resolve_mode") else (req.mode or task.get("mode") or "fluent")
        self.repo.update_task(task_id, {"mode": mode, "resolved_scene": {**resolved_meta,
                                                                         "scene": resolved_scene.to_dict()}})
        self._emit(sink, Topic.SCENE_CHANGED, {"scene": resolved_scene.to_dict(), "mode": mode}, task_id)

        # glossary match + bind (deterministic, zero model)
        hits = self.glossary.match(task["source_text"], src, tgt, resolved_scene.bank_ids, resolved_scene.profile_id)
        if token and token.is_cancelled():
            token.raise_if_cancelled()
        bindings = self.glossary.bindings_for(hits) if hasattr(self.glossary, "bindings_for") else []
        term_block = self.glossary.prompt_block(hits) if hasattr(self.glossary, "prompt_block") else \
            "\n".join(f"{h.source_term} => {h.target_term}" for h in hits)

        # TM recall (deterministic)
        tm_hits = {}
        for seg in work:
            tm_hits[seg.id] = self.tm.lookup(seg.text, src, tgt, task.get("domain", "general"))
        self._emit(sink, Topic.TASK_PROGRESS, {"phase": "memory", "tm_hits": sum(len(v) for v in tm_hits.values())}, task_id)

        # S1 translate（分批：边翻边落库，批间节流）
        self._set_status(task_id, TaskStatus.RUNNING.value, sink)
        scene_obj = self.scene.get(resolved_scene.profile_id)
        total = len(segments)
        done_ids: set = set()
        failed_ids: set = set()
        failed_batches: List[Dict[str, Any]] = []
        emotions: List[EmotionAnnotation] = []
        drafts: Dict[str, str] = {}

        for bi, batch in enumerate(batches):
            if token is not None and token.is_cancelled():
                for s in work:
                    if s.id not in done_ids and s.id not in failed_ids:
                        self._set_segments_status(task_id, [s.id], "cancelled")
                self._emit(sink, Topic.TASK_PROGRESS,
                           self._progress_payload(task_id, total, len(batches), bi), task_id)
                token.raise_if_cancelled()
            plan = self.scene.compose(req, scene_obj, term_block, mode, batch,
                                      locked_terms=self._locked_terms_block(task_id, hits))
            plan.glossary_terms = hits
            self._emit(sink, Topic.TRANSLATION_DELTA,
                       {"phase": "translating", "batch": bi + 1, "batch_total": len(batches)}, task_id)
            try:
                raw = self._translate_with_retry(plan, batch, int(opts["retries"]), token)
            except Exception as e:  # noqa: BLE001 - 单批失败不拖垮整个任务
                failed_ids.update(s.id for s in batch)
                self._set_segments_status(task_id, [s.id for s in batch], "failed")
                failed_batches.append({
                    "index": bi + 1, "segment_ids": [s.id for s in batch],
                    "error": getattr(e, "message", "") or str(e) or "批次请求失败",
                })
                self.repo.update_task(task_id, {
                    "failed_batches": json.dumps(failed_batches, ensure_ascii=False)})
                self._emit(sink, Topic.TASK_PROGRESS,
                           self._progress_payload(task_id, total, len(batches), bi + 1), task_id)
                continue

            raw_segments = raw.get("segments", [])
            seg_by_id = {s.id: s for s in batch}
            raw_words_by_seg: Dict[str, Any] = {}
            raw_tones_by_seg: Dict[str, Any] = {}
            raw_sentiment_by_seg: Dict[str, Any] = {}
            raw_sentences_by_seg: Dict[str, Any] = {}
            raw_variants_by_seg: Dict[str, Any] = {}
            raw_terms_by_seg: Dict[str, Any] = {}
            unmatched = list(batch)
            for it in raw_segments:
                sid = it.get("segment_id") or ""
                seg = seg_by_id.get(sid)
                if seg is not None:
                    if seg in unmatched:
                        unmatched.remove(seg)
                elif unmatched:
                    # 模型未复述 id 时按顺序回退匹配
                    seg = unmatched.pop(0)
                else:
                    continue  # 多余分段，忽略
                drafts[seg.id] = it.get("target_text", "")
                if it.get("words") is not None:
                    raw_words_by_seg[seg.id] = it.get("words")
                if it.get("tones") is not None:
                    raw_tones_by_seg[seg.id] = it.get("tones")
                if it.get("sentiment") is not None:
                    raw_sentiment_by_seg[seg.id] = it.get("sentiment")
                if it.get("sentences") is not None:
                    raw_sentences_by_seg[seg.id] = it.get("sentences")
                if it.get("variants") is not None:
                    raw_variants_by_seg[seg.id] = it.get("variants")
                if it.get("terms") is not None:
                    raw_terms_by_seg[seg.id] = it.get("terms")
                self._emit(sink, Topic.SEGMENT_DRAFT, {"segment_id": seg.id, "target_text": drafts[seg.id]}, task_id)

            # 语气识别归一化（span 相对本段原文；无语气 → 空）
            tones_by_seg: Dict[str, List[Dict[str, Any]]] = {
                seg.id: norm_tones(raw_tones_by_seg.get(seg.id), seg.text) for seg in batch
            }
            self._emit(sink, Topic.TRANSLATION_DELTA,
                       {"phase": "tones", "count": sum(len(v) for v in tones_by_seg.values())}, task_id)

            # emotion parse + align
            emotions.extend(self.emotion.parse(raw.get("emotions"), batch))
            self._emit(sink, Topic.TRANSLATION_DELTA,
                       {"phase": "emotions", "count": sum(1 for e in emotions if e.segment_id in seg_by_id)},
                       task_id)

            # S2 QA + confidence + S2.5 fix（按批，避免一次处理全量）
            provider_is_fake = raw.get("provider_id") == "fake"
            qa_reports: Dict[str, QAReport] = {}
            confs: Dict[str, ConfidenceResult] = {}
            for seg in batch:
                if seg.id not in drafts:
                    drafts[seg.id] = ""
                report = self.qa.check(seg, drafts[seg.id], {
                    "source_lang": src, "target_lang": tgt, "mode": mode,
                    "hard_terms": [h for h in hits if h.forced],
                    "bindings": bindings,
                })
                qa_reports[seg.id] = report
                confs[seg.id] = self.qa.estimate(report, {})
                self._emit(sink, Topic.SEGMENT_QA, {"segment_id": seg.id, "report": report.to_dict(),
                                                    "confidence": confs[seg.id].to_dict()}, task_id)

            # S2.5 direct fix (only when issues + a real provider; keep deterministic with fake)
            # 直译模式不做“修复”：修复会把逐词稿改写成流畅稿，正是直译语义丢失的根源。
            has_fixable = any(r.has_blocking or any(i.severity in ("high", "medium") for i in r.issues)
                              for r in qa_reports.values())
            if has_fixable and not provider_is_fake and mode != TranslateMode.LITERAL.value:
                fix_results = self.qa.apply_fixes(task_id, batch, drafts, qa_reports, hits, risk_assessment)
                for seg, fixed in fix_results.items():
                    if fixed.get("applied"):
                        drafts[seg.id] = fixed["new_text"]
                        self._emit(sink, Topic.TRANSLATION_FIXED,
                                   {"segment_id": seg.id, "new_text": fixed["new_text"]}, task_id)

            # S3 build versions + SegmentView（逐批落库，界面边翻边出现）
            for seg in batch:
                words: List[Dict[str, Any]] = []
                if mode == TranslateMode.LITERAL.value:
                    words = norm_literal_words(raw_words_by_seg.get(seg.id), seg.text)
                target_text = join_words(words, tgt) if words else drafts[seg.id]
                if mode == TranslateMode.LITERAL.value:
                    target_text = self.scene.ensure_marker(target_text) if hasattr(self.scene, "ensure_marker") else target_text
                drafts[seg.id] = target_text  # 术语/翻译记忆写回用拼接后的直译文本
                literal_spans = build_literal_spans(words, target_text) if words else []
                annot_spans = self._annotate(seg, target_text, hits, confs.get(seg.id), emotions, mode)
                # 低置信 span 覆盖整段，只用于整段底色，不参与“区间占用”判断
                occupied = [s for s in annot_spans if "low_confidence" not in s.kinds]
                variant_spans: List[AnnotatedSpan] = []
                if mode != TranslateMode.LITERAL.value:
                    variants = norm_variants(raw_variants_by_seg.get(seg.id), target_text)
                    variant_spans = drop_overlaps(build_variant_spans(seg.id, variants), literal_spans + occupied)
                kept_spans = drop_overlaps(
                    build_kept_spans(seg.id, seg.text, target_text, tgt,
                                     str(raw.get("source_channel") or "")),
                    literal_spans + occupied + variant_spans,
                )
                sentiment = norm_sentiment(raw_sentiment_by_seg.get(seg.id))
                # 句子级情感只在真实模型给出且能原样定位时落库；离线/缺失一律不猜
                if sentiment:
                    sentences = norm_sentences(raw_sentences_by_seg.get(seg.id), seg.text, target_text)
                    if sentences:
                        sentiment["sentences"] = sentences
                spans = literal_spans + annot_spans + variant_spans + kept_spans
                seg_emotions = [e for e in emotions if e.segment_id == seg.id]
                version_id = new_id()
                self.repo.save_version({
                    "id": version_id, "segment_id": seg.id, "parent_version_id": None,
                    "target_text": target_text, "origin": "draft",
                    "provider": raw.get("provider_id", ""), "model": raw.get("model", ""),
                    "prompt_fingerprint": plan.fingerprint, "routing_at_creation": risk_assessment.routing,
                    "source_channel": raw.get("source_channel", "online"),
                    "confidence": confs[seg.id].score if seg.id in confs else None,
                    "spans": spans,
                    "words": words,
                    "tones": tones_by_seg.get(seg.id, []),
                    "sentiment": sentiment or {},
                    "emotions": [e.to_dict() for e in seg_emotions],
                    "created_at": utc_now(),
                })
                view = SegmentView(segment_id=seg.id, source_text=seg.text, target_text=target_text,
                                   spans=spans, words=words, tones=tones_by_seg.get(seg.id, []),
                                   confidence=confs.get(seg.id),
                                   emotions=seg_emotions,
                                   sentiment=sentiment,
                                   risk={"tier": risk_assessment.tier, "reason": self.risk.explain(risk_assessment)},
                                   mode=mode, channel=raw.get("source_channel", "online"),
                                   version_id=version_id)
                self._emit(sink, Topic.SEGMENT_VIEW, view.to_dict(), task_id)
                done_ids.add(seg.id)
            self._set_segments_status(task_id, [s.id for s in batch], "done")
            # 逐批记录“术语→实际译法”，供后续批次与整篇一致性约束使用
            self._record_batch_terms(task_id, batch, raw_terms_by_seg, drafts, hits)
            self._emit(sink, Topic.TASK_PROGRESS,
                       self._progress_payload(task_id, total, len(batches), bi + 1), task_id)
            if bi < len(batches) - 1 and int(opts["throttle_ms"]) > 0 and not provider_is_fake:
                time.sleep(int(opts["throttle_ms"]) / 1000.0)

        progress = self._progress_payload(task_id, total, len(batches), len(batches))

        # 有失败批次：明确失败、保留已完成结果，等待“重试失败片段”
        if failed_batches:
            message = (f"部分批次失败：{len(failed_batches)} 批 / {len(failed_ids)} 个片段；"
                       f"已完成 {progress['done']} 个，可重试失败片段")
            self.repo.update_task(task_id, {
                "status": TaskStatus.FAILED.value, "completed_at": utc_now(),
                "failed_batches": json.dumps(failed_batches, ensure_ascii=False),
                "cost_total": self.cost.task_total(task_id) if hasattr(self.cost, "task_total") else 0.0,
            })
            self._emit(sink, Topic.TASK_FAILED, {
                "status": TaskStatus.FAILED.value, "error": message, "code": "LAA-8004",
                "failed_batches": failed_batches, "progress": progress,
            }, task_id)
            return {"task_id": task_id, "segment_count": len(segments), "routing": risk_assessment.routing,
                    "done": progress["done"], "failed": progress["failed"],
                    "failed_batches": len(failed_batches)}

        self._set_status(task_id, TaskStatus.FINALIZING.value, sink)

        # S5/S6 archive: finalize
        # 翻译记忆改为手动写入（结果区「加入记忆」），流水线不再自动入库
        self.repo.update_task(task_id, {"status": TaskStatus.SUCCEEDED.value, "completed_at": utc_now(),
                                        "failed_batches": "[]",
                                        "cost_total": self.cost.task_total(task_id) if hasattr(self.cost, "task_total") else 0.0})
        self._emit(sink, Topic.TASK_COMPLETED, {"status": TaskStatus.SUCCEEDED.value, "progress": progress}, task_id)
        return {"task_id": task_id, "segment_count": len(segments), "routing": risk_assessment.routing,
                "done": progress["done"], "failed": 0, "failed_batches": 0}

    def _set_segments_status(self, task_id: str, segment_ids: List[str], status: str) -> None:
        wanted = set(segment_ids)
        for row in self.repo.list_segments(task_id):
            if row["id"] in wanted:
                row["status"] = status
                self.repo.save_segment(row)

    def _count_status(self, task_id: str, status: str) -> int:
        return sum(1 for r in self.repo.list_segments(task_id)
                   if (r.get("status") or "pending") == status)

    def _progress_payload(self, task_id: str, total: int, batch_total: int,
                          batch_done: int) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        for r in self.repo.list_segments(task_id):
            k = r.get("status") or "pending"
            counts[k] = counts.get(k, 0) + 1
        done = counts.get("done", 0)
        failed = counts.get("failed", 0)
        cancelled = counts.get("cancelled", 0)
        return {"phase": "batch", "total": total, "done": done, "failed": failed,
                "cancelled": cancelled, "remaining": max(0, total - done - failed - cancelled),
                "batch": batch_done, "batch_total": batch_total}

    def _translate_with_retry(self, plan, segments, retries: int, token) -> Dict[str, Any]:
        attempt = 0
        while True:
            if token is not None and token.is_cancelled():
                token.raise_if_cancelled()
            try:
                return self.gateway.translate(plan, segments)
            except Exception:
                if attempt >= retries:
                    raise
                attempt += 1
                time.sleep(min(1.5, 0.3 * attempt))

    def _annotate(self, seg: TextSegment, target: str, hits, conf, emotions, mode) -> List[AnnotatedSpan]:
        spans: List[AnnotatedSpan] = []
        # term hit spans in target
        for h in hits:
            if not h.target_term:
                continue
            start = target.find(h.target_term)
            if start >= 0:
                spans.append(AnnotatedSpan(id=new_id(), text=h.target_term, span=[start, start + len(h.target_term)],
                                           kinds=["terminology_applied"], term_ref=h.entry_id,
                                           variants=[{"label": h.target_term, "source": "glossary"}]))
        if conf is not None and conf.band == "low":
            spans.append(AnnotatedSpan(id=new_id(), text=target, span=[0, len(target)], kinds=["low_confidence"],
                                       confidence=conf.score))
        return spans