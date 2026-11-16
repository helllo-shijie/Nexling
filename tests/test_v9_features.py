"""V9：句子级情感与术语候选自动审批。"""
from __future__ import annotations

import pytest

from laa_core.app.pipeline import norm_sentences, strip_sentences


TARGET = "系统运行稳定。延迟有所下降，但峰值仍然偏高。"
SOURCE = "The system runs stably. Latency dropped but peaks remain high."


def test_sentences_are_located_and_normalized():
    raw = [
        {"source": "The system runs stably.", "text": "系统运行稳定。",
         "sentiment": {"positive": 0.8, "negative": 0.05, "neutral": 0.15}},
        {"source": "Latency dropped but peaks remain high.",
         "text": "延迟有所下降，但峰值仍然偏高。",
         "sentiment": {"positive": 0.2, "negative": 0.5, "neutral": 0.3}},
    ]
    out = norm_sentences(raw, SOURCE, TARGET)
    assert len(out) == 2
    assert out[0]["label"] == "positive"
    assert out[1]["label"] == "negative"
    assert TARGET[out[0]["span"][0]:out[0]["span"][1]] == "系统运行稳定。"
    assert abs(out[0]["positive"] + out[0]["negative"] + out[0]["neutral"] - 1.0) < 0.002


def test_sentences_unknown_text_is_dropped_not_guessed():
    raw = [
        {"source": "The system runs stably.", "text": "模型没有给出的句子",
         "sentiment": {"positive": 0.9, "negative": 0.05, "neutral": 0.05}},
        {"source": "Latency dropped but peaks remain high.",
         "text": "延迟有所下降，但峰值仍然偏高。",
         "sentiment": {"positive": 0.6, "negative": 0.2, "neutral": 0.2}},
    ]
    out = norm_sentences(raw, SOURCE, TARGET)
    assert out == [], "有一条对不上就整段降级，不猜测位置"


def test_sentences_probability_sum_is_normalized_not_dropped():
    raw = [{"source": "The system runs stably.", "text": "系统运行稳定。",
            "sentiment": {"positive": 8, "negative": 1, "neutral": 1}}]
    out = norm_sentences(raw, "The system runs stably.", "系统运行稳定。")
    assert len(out) == 1, "概率和不为 1 时应归一化，而不是丢弃"
    assert abs(out[0]["positive"] - 0.8) < 0.002
    assert abs(out[0]["negative"] - 0.1) < 0.002


def test_sentences_invalid_probabilities_are_dropped():
    assert norm_sentences(
        [{"source": SOURCE, "text": "系统运行稳定。", "sentiment": {"positive": "高"}}], SOURCE, TARGET) == []
    assert norm_sentences(None, SOURCE, TARGET) == []
    assert norm_sentences([{"source": SOURCE, "text": "系统运行稳定。"}], SOURCE, TARGET) == []


def test_sentences_without_source_are_not_guessed():
    raw = [{"text": "系统运行稳定。", "sentiment": {"positive": 0.5, "negative": 0.2, "neutral": 0.3}}]
    assert norm_sentences(raw, SOURCE, TARGET) == [], "缺少原文分句时无法对齐，整段降级"


def test_tiny_punctuation_fragments_fall_back_to_paragraph():
    source = "你好呀。很。高兴遇。到你"
    target = "Hello. Very. Glad to. Meet you"
    raw = [
        {"source": "你好呀。", "text": "Hello.", "sentiment": {"positive": 0.6, "negative": 0.1, "neutral": 0.3}},
        {"source": "很。", "text": "Very.", "sentiment": {"positive": 0.3, "negative": 0.2, "neutral": 0.5}},
        {"source": "高兴遇。", "text": "Glad to.", "sentiment": {"positive": 0.6, "negative": 0.1, "neutral": 0.3}},
        {"source": "到你", "text": "Meet you", "sentiment": {"positive": 0.5, "negative": 0.1, "neutral": 0.4}},
    ]
    assert norm_sentences(raw, source, target) == [], "碎句不单独成句，整段降级"


def test_strip_sentences_keeps_paragraph_level():
    sentiment = {"positive": 0.6, "negative": 0.2, "neutral": 0.2,
                 "sentences": [{"span": [0, 2], "text": "系统"}]}
    out = strip_sentences(sentiment)
    assert "sentences" not in out
    assert out["positive"] == 0.6
    assert strip_sentences(None) == {}


def test_offline_translation_has_no_inline_sentences(app, run):
    tid, task = run()
    assert task["status"] == "succeeded"
    views = app.snapshot(tid)["segments"]
    assert views
    for seg in views:
        sentiment = seg["sentiment"] or {}
        assert sentiment, "离线演示仍应保留段落级情感"
        assert "sentences" not in sentiment, "离线演示不得生成句子级行内标注"


def test_json_export_keeps_sentence_sentiment(app, run):
    import json

    tid, _ = run()
    seg = app.repo.list_segments(tid)[0]
    version = dict(app.repo.latest_version(seg["id"]))
    text = version["target_text"]
    sentence = {"span": [0, min(4, len(text))], "text": text[:min(4, len(text))],
                "positive": 0.7, "negative": 0.1, "neutral": 0.2, "label": "positive"}
    version.update({
        "id": "v9-sent-export",
        "sentiment": {**version["sentiment"], "sentences": [sentence]},
    })
    app.repo.save_version(version)
    payload = json.loads(app.export(tid, "json")["content"])
    assert payload["segments"][0]["sentiment"]["sentences"][0]["label"] == "positive"
    assert app.export(tid, "txt")["content"]


def _seed(app, cid, source, target, conf, occurrences=2, bank="personal-default"):
    app.repo.upsert_term_candidate({
        "id": cid, "normalized": source.lower(), "source_term": source,
        "target_term": target, "lang": "en", "target_lang": "zh-Hans",
        "task_id": "", "segment_id": "", "context": "", "occurrences": occurrences,
        "confidence": conf, "status": "pending", "evidence": [], "bank_id": bank,
        "created_at": "", "updated_at": "",
    })


def test_auto_review_defaults_off_and_requires_real_model(app):
    settings = app.settings_get()
    assert settings["term_auto_review"] == {"enabled": False, "threshold": 20, "allow_manual": True}
    status = app.term_auto_review_status({})
    assert status["enabled"] is False
    assert status["available"] is False
    assert status["reason"]
    with pytest.raises(Exception) as exc:
        app.term_auto_review({})
    assert "不可用" in getattr(exc.value, "message", str(exc.value))


def test_settings_reject_invalid_auto_review_threshold(app):
    settings = app.settings_get()
    bad = {**settings, "term_auto_review": {"enabled": True, "threshold": 0, "allow_manual": True}}
    with pytest.raises(Exception):
        app.settings_save({"settings": bad})


def test_auto_review_accepts_skips_ignores_and_undoes(app, monkeypatch):
    monkeypatch.setattr(app, "_auto_review_available",
                        lambda: {"available": True, "reason": "", "provider_id": "stub"})
    _seed(app, "c-hi", "Rasterize", "栅格化", 0.92)
    _seed(app, "c-low", "Meh", None, 0.3, occurrences=1)
    _seed(app, "c-mid", "Maybe", "也许", 0.72)

    result = app.term_auto_review({})
    assert result["accepted_count"] == 1
    assert result["ignored_count"] == 1
    assert result["skipped"] == 1
    assert result["batch_id"]

    cands = {c["id"]: c for c in app.repo.list_term_candidates()}
    assert cands["c-hi"]["status"] == "accepted"
    assert cands["c-low"]["status"] == "ignored"
    assert cands["c-mid"]["status"] == "pending"
    entries = [e for e in app.repo.list_entries("personal-default")
               if (e.get("source_term") or "").lower() == "rasterize"]
    assert entries, "采纳应写入术语库"

    undo = app.term_auto_review_undo({"batch_id": result["batch_id"]})
    assert undo["restored"] == 1
    assert undo["restored_ignored"] == 1, "撤回也要恢复本轮被自动忽略的候选"
    cands = {c["id"]: c for c in app.repo.list_term_candidates()}
    assert cands["c-hi"]["status"] == "pending"
    assert cands["c-low"]["status"] == "pending"
    assert not [e for e in app.repo.list_entries("personal-default")
                if (e.get("source_term") or "").lower() == "rasterize"], "撤回应撤销本轮新建词条"


def test_auto_review_reports_high_confidence_without_bank(app, monkeypatch):
    monkeypatch.setattr(app, "_auto_review_available",
                        lambda: {"available": True, "reason": "", "provider_id": "stub"})
    _seed(app, "c-nobank", "Bleed", "出血", 0.95, bank="")

    result = app.term_auto_review({})
    assert result["needs_bank_count"] == 1
    assert result["needs_bank"][0]["id"] == "c-nobank"
    assert "术语库" in result["needs_bank"][0]["reason"]
    assert result["accepted_count"] == 0 and result["skipped"] == 0, "不能当成无事发生"
    cands = {c["id"]: c for c in app.repo.list_term_candidates()}
    assert cands["c-nobank"]["status"] == "pending", "未指定术语库的候选保持待处理"


def test_auto_review_ignored_only_batch_can_be_undone(app, monkeypatch):
    monkeypatch.setattr(app, "_auto_review_available",
                        lambda: {"available": True, "reason": "", "provider_id": "stub"})
    _seed(app, "c-low", "Meh", None, 0.2, occurrences=1)
    result = app.term_auto_review({})
    assert result["ignored_count"] == 1
    assert result["batch_id"], "只有忽略时也要能撤回"
    undo = app.term_auto_review_undo({"batch_id": result["batch_id"]})
    assert undo["restored_ignored"] == 1
    assert {c["id"]: c for c in app.repo.list_term_candidates()}["c-low"]["status"] == "pending"


def test_auto_review_runs_when_enabled_and_threshold_met(app, monkeypatch):
    monkeypatch.setattr(app, "_auto_review_available",
                        lambda: {"available": True, "reason": "", "provider_id": "stub"})
    _seed(app, "c-1", "Tokenizer", "分词器", 0.95, occurrences=3)
    settings = app.settings_get()
    saved = app.settings_save({"settings": {
        **settings,
        "term_auto_review": {"enabled": True, "threshold": 1, "allow_manual": True},
    }})
    auto = saved.get("auto_review") or {}
    assert auto.get("trigger") == "auto"
    assert auto.get("accepted_count") == 1
    status = app.term_auto_review_status({})
    assert status["last_batch"]["counts"]["accepted"] == 1
