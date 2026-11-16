"""V1 新增能力的回归测试：情感概率、候选译法、中文保留、目标语言自动。"""
from __future__ import annotations

import time

from laa_core.app.pipeline import (
    build_kept_spans,
    build_variant_spans,
    drop_overlaps,
    norm_sentiment,
    norm_variants,
)
from laa_core.shared.types import TaskStatus


def _wait(app, tid: str, timeout: float = 6.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = app.repo.get_task(tid)
        if task["status"] in (
            TaskStatus.SUCCEEDED.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
        ):
            return task
        time.sleep(0.01)
    return app.repo.get_task(tid)


def test_sentiment_probabilities_are_normalized():
    out = norm_sentiment({"positive": 0.7, "negative": 0.1, "neutral": 0.2})
    assert out is not None
    assert abs(out["positive"] + out["negative"] + out["neutral"] - 1.0) < 0.002
    assert out["needs_review"] is False
    assert out["threshold"] == 0.6


def test_sentiment_accepts_percentages_and_labels():
    pct = norm_sentiment({"积极": 70, "消极": 10, "中性": 20})
    assert pct is not None and abs(pct["positive"] - 0.7) < 0.01

    labeled = norm_sentiment([
        {"label": "positive", "score": 0.3},
        {"label": "negative", "score": 0.3},
        {"label": "neutral", "score": 0.4},
    ])
    assert labeled is not None and labeled["needs_review"] is True


def test_sentiment_invalid_returns_none():
    assert norm_sentiment(None) is None
    assert norm_sentiment({"positive": 0, "negative": 0, "neutral": 0}) is None
    assert norm_sentiment({"positive": "high"}) is None


def test_variants_are_located_in_target_text():
    target = "调度器采用指数退避重试失败的 Pod。"
    raw = [{"text": "指数退避", "options": ["指数级退避", "逐步拉长间隔"]}]
    found = norm_variants(raw, target)
    assert found and target[found[0]["span"][0]:found[0]["span"][1]] == "指数退避"

    spans = build_variant_spans("s1", found)
    assert len(spans) == 1
    kinds = spans[0].kinds
    assert "alternate_translation" in kinds
    labels = [v["label"] for v in spans[0].variants]
    assert "指数级退避" in labels


def test_variants_missing_text_are_dropped():
    assert norm_variants([{"text": "不存在的片段", "options": ["x"]}], "目标译文") == []
    assert norm_variants([{"text": "目标", "options": ["目标"]}], "目标译文") == []


def test_kept_spans_only_when_target_is_not_chinese():
    """中文保留：译为非中文时，原样出现在译文里的中文片段才加下划线。"""
    src = "升级后 术语库联动 更稳定，NexLing 1.0 已发布。"
    # 译成英文但保留了「术语库联动」这几个中文字
    tgt = "After the upgrade, NexLing terms 术语库联动 became more stable."
    kept = build_kept_spans("s1", src, tgt, "en")
    texts = {s.text for s in kept}
    assert "术语库联动" in texts
    # 译成中文时整段是中文，不标注
    assert build_kept_spans("s1", src, "新版本 NexLing 支持术语库联动。", "zh-Hans") == []
    # 离线回显（译文==原文）不算保留，避免假阳性
    assert build_kept_spans("s1", src, src, "en") == []
    assert build_kept_spans("s1", src, "NexLing supports glossary binding.", "en") == []


def test_drop_overlaps_keeps_priority_order():
    from laa_core.shared import AnnotatedSpan

    kept = [AnnotatedSpan(id="k1", text="术语库联动", span=[0, 5], kinds=["source_lang_kept"]),
            AnnotatedSpan(id="k2", text="很重要", span=[5, 8], kinds=["source_lang_kept"])]
    taken = [AnnotatedSpan(id="t1", text="术", span=[0, 1], kinds=["terminology_applied"])]
    remaining = drop_overlaps(kept, taken)
    ids = {s.id for s in remaining}
    assert ids == {"k2"}


def test_view_carries_sentiment_and_persists(app):
    info = app.start_translation({"text": "The deployment failed again. Please check the logs.",
                                  "target_lang": "zh-Hans"}, trace_id="t")
    tid = info["task_id"]
    _wait(app, tid)
    seg = app.snapshot(tid)["segments"][0]
    assert seg["sentiment"] is not None
    assert abs(sum(seg["sentiment"][k] for k in ("positive", "negative", "neutral")) - 1.0) < 0.002


def test_pick_variant_rebuilds_version(app):
    info = app.start_translation({"text": "The compiler optimizes the loop.", "target_lang": "zh-Hans"},
                                 trace_id="t")
    tid = info["task_id"]
    _wait(app, tid)
    seg_id = app.repo.list_segments(tid)[0]["id"]
    version = app.repo.latest_version(seg_id)
    target = version["target_text"]
    head = target[:2]
    span = [0, 2]
    inject = dict(version)
    inject["id"] = "ver-variant"
    inject["spans"] = [{
        "id": f"{seg_id}-var-0", "text": head, "span": span,
        "kinds": ["alternate_translation"], "term_ref": None,
        "variants": [
            {"id": f"{seg_id}-v0-0", "label": head, "text": head},
            {"id": f"{seg_id}-v0-1", "label": "另一种说法", "text": "另一种说法"},
        ],
        "confidence": None, "fix_ref": None, "note": "可替换译法",
    }]
    app.repo.save_version(inject)

    view = app.pick_variant({"task_id": tid, "segment_id": seg_id, "span": span, "choice": "另一种说法"})
    assert view["target_text"].startswith("另一种说法")
    assert view["target_text"].endswith(target[2:])
    assert any("alternate_translation" in s["kinds"] for s in view["spans"])

    latest = app.repo.latest_version(seg_id)
    assert latest["target_text"] == view["target_text"]
    assert latest["origin"] == "variant_pick"


def test_target_language_auto(app):
    en = app.start_translation({"text": "Hello world, this is a short sentence.", "target_lang": "auto"},
                               trace_id="t")
    _wait(app, en["task_id"])
    assert app.repo.get_task(en["task_id"])["tgt_lang"] == "zh-Hans"

    zh = app.start_translation({"text": "这是一段很短的中文句子。", "target_lang": "auto"}, trace_id="t")
    _wait(app, zh["task_id"])
    assert app.repo.get_task(zh["task_id"])["tgt_lang"] == "en"
