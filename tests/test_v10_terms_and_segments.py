"""V10：长文本术语一致性、模型分句、候选译法气泡与状态机收尾。"""
from __future__ import annotations

import threading
import time

from laa_core.app.bootstrap import Bootstrap
from laa_core.domain.text.service import Segmenter, segment_text
from laa_core.infra.providers.gateway import ProviderGateway, ProviderRouter
from laa_core.shared.types import TaskStatus


def _wait(app, tid: str, limit: int = 600) -> dict:
    for _ in range(limit):
        task = app.repo.get_task(tid)
        if task["status"] in (TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value,
                              TaskStatus.CANCELLED.value, TaskStatus.PAUSED.value):
            return task
        time.sleep(0.01)
    return app.repo.get_task(tid)


def _fast(app, **overrides) -> None:
    cfg = {"max_chars": 200000, "batch_chars": 400, "batch_segments": 1,
           "retries": 0, "throttle_ms": 0}
    cfg.update(overrides)
    app.settings_save({"long_text": cfg})


# ---------------------------------------------------------------- 术语一致性
def test_batch_terms_are_recorded_and_lock_later_batches(app, monkeypatch):
    _fast(app)
    app.gateway.translate = lambda plan, segments: {
        "segments": [
            {"segment_id": s.id, "target_text": "译 GraphQL API",
             "terms": [{"source": "GraphQL", "target": "GraphQL API"},
                       {"source": "对不上号的词", "target": "瞎填"}]}
            for s in segments
        ],
        "emotions": [],
        "provider_id": "fake", "source_channel": "offline", "model": "fake",
    }
    seen_locked: list = []
    orig_compose = app.scene.compose

    def spy(req, scene, glossary_block, mode, segments=None, locked_terms=""):
        plan = orig_compose(req, scene, glossary_block, mode, segments, locked_terms=locked_terms)
        seen_locked.append((locked_terms, plan.messages[-1]["content"]))
        return plan

    monkeypatch.setattr(app.scene, "compose", spy)
    text = "第一段讲 GraphQL。\n\n第二段也讲 GraphQL。"
    info = app.start_translation({"text": text, "target_lang": "en"}, trace_id="t")
    tid = info["task_id"]
    assert _wait(app, tid)["status"] == TaskStatus.SUCCEEDED.value

    terms = {t["source_term"]: t for t in app.snapshot(tid)["terms"]}
    assert terms["GraphQL"]["target_term"] == "GraphQL API"
    assert terms["GraphQL"]["origin"] == "model"
    assert "对不上号的词" not in terms, "对不上原文的术语不得写入"
    assert all(t["target_term"] in "译 GraphQL API" for t in terms.values()), "译法必须能在译文中找到"

    assert len(seen_locked) >= 2
    assert seen_locked[0][0] == "", "首批还没有已定译法"
    assert "GraphQL => GraphQL API" in seen_locked[1][0], "后续批次必须带上已定译法"
    assert "已定译法" in seen_locked[1][1] and "GraphQL => GraphQL API" in seen_locked[1][1]


def test_task_term_priority_is_user_glossary_model(app):
    tid = "task-priority"
    app.repo.save_task({
        "id": tid, "source_text": "cache", "src_lang": "en", "tgt_lang": "zh-Hans",
        "status": TaskStatus.SUCCEEDED.value, "segment_count": 0, "created_at": "",
        "resolved_scene": {}, "domain": "general", "mode": "fluent",
    })
    app.repo.upsert_task_term({"task_id": tid, "source_term": "cache", "target_term": "缓存",
                               "origin": "model", "updated_at": "1"})
    app.repo.upsert_task_term({"task_id": tid, "source_term": "cache", "target_term": "高速缓存",
                               "origin": "glossary", "updated_at": "2"})
    assert app.repo.list_task_terms(tid)[0]["target_term"] == "高速缓存"

    app.repo.upsert_task_term({"task_id": tid, "source_term": "cache", "target_term": "缓存区",
                               "origin": "user", "updated_at": "3"})
    app.repo.upsert_task_term({"task_id": tid, "source_term": "cache", "target_term": "模型改回",
                               "origin": "model", "updated_at": "4"})
    app.repo.upsert_task_term({"task_id": tid, "source_term": "cache", "target_term": "术语库改回",
                               "origin": "glossary", "updated_at": "5"})
    rows = app.repo.list_task_terms(tid)
    assert len(rows) == 1 and rows[0]["target_term"] == "缓存区"
    assert rows[0]["origin"] == "user"


def test_set_task_term_replaces_known_translation_without_model_call(app):
    tid = "task-rewrite"
    app.repo.save_task({"id": tid, "source_text": "缓存很快。\n\n缓存很稳。", "src_lang": "zh-Hans",
                        "tgt_lang": "en", "status": TaskStatus.SUCCEEDED.value, "segment_count": 2,
                        "created_at": "", "mode": "fluent", "domain": "general", "resolved_scene": {}})
    for i, text in enumerate(("缓存很快。", "缓存很稳。")):
        sid = f"seg-{i}"
        app.repo.save_segment({"id": sid, "task_id": tid, "idx": i, "text": text,
                               "span": [0, len(text)], "lang": "zh-Hans", "token_estimate": 1,
                               "status": "done"})
        app.repo.save_version({"id": f"v-{i}", "segment_id": sid, "parent_version_id": None,
                               "target_text": "The cache is fast." if i == 0 else "The cache is stable.",
                               "origin": "draft", "provider": "fake", "model": "fake",
                               "prompt_fingerprint": "", "routing_at_creation": "",
                               "source_channel": "offline", "spans": [], "words": [], "tones": [],
                               "sentiment": {}, "emotions": [], "created_at": ""})
    app.repo.upsert_task_term({"task_id": tid, "source_term": "缓存", "target_term": "cache",
                               "origin": "model", "updated_at": "1"})

    res = app.set_task_term({"task_id": tid, "source_term": "缓存", "target_term": "buffer"})
    assert res["rewritten"] == 2 and res["affected"] == 2
    assert res["queued"] is False, "已知译法可直接替换，不应再花一次模型调用"
    assert res["segment_ids"] == []
    for i in range(2):
        target = app.repo.latest_version(f"seg-{i}")["target_text"]
        assert "buffer" in target and "cache" not in target
    assert app.repo.get_task(tid)["status"] == TaskStatus.SUCCEEDED.value


def test_set_task_term_rewrites_when_new_target_is_substring_of_old(app):
    """旧译法比新译法长（server-side cache → cache）时不能被“子串已存在”误判为无需改动。"""
    tid = "task-substring"
    app.repo.save_task({"id": tid, "source_text": "缓存很快。", "src_lang": "zh-Hans",
                        "tgt_lang": "en", "status": TaskStatus.SUCCEEDED.value, "segment_count": 1,
                        "created_at": "", "mode": "fluent", "domain": "general", "resolved_scene": {}})
    app.repo.save_segment({"id": "seg-s", "task_id": tid, "idx": 0, "text": "缓存很快。",
                           "span": [0, 5], "lang": "zh-Hans", "token_estimate": 1, "status": "done"})
    app.repo.save_version({"id": "v-s", "segment_id": "seg-s", "parent_version_id": None,
                           "target_text": "The server-side cache is fast.", "origin": "draft",
                           "provider": "fake", "model": "fake", "prompt_fingerprint": "",
                           "routing_at_creation": "", "source_channel": "offline", "spans": [],
                           "words": [], "tones": [], "sentiment": {}, "emotions": [], "created_at": ""})
    app.repo.upsert_task_term({"task_id": tid, "source_term": "缓存",
                               "target_term": "server-side cache", "origin": "model", "updated_at": "1"})

    res = app.set_task_term({"task_id": tid, "source_term": "缓存", "target_term": "cache"})
    assert res["affected"] == 1 and res["rewritten"] == 1 and res["queued"] is False
    assert res["matched"] == 1 and res["already"] == 0
    assert app.repo.latest_version("seg-s")["target_text"] == "The cache is fast."


def test_set_task_term_reports_honestly_when_untouched(app):
    """术语没出现在片段里时如实返回 matched=0，不假装统一成功。"""
    tid = "task-miss"
    app.repo.save_task({"id": tid, "source_text": "别的词。", "src_lang": "zh-Hans",
                        "tgt_lang": "en", "status": TaskStatus.SUCCEEDED.value, "segment_count": 1,
                        "created_at": "", "mode": "fluent", "domain": "general", "resolved_scene": {}})
    app.repo.save_segment({"id": "seg-m", "task_id": tid, "idx": 0, "text": "别的词。",
                           "span": [0, 4], "lang": "zh-Hans", "token_estimate": 1, "status": "done"})
    app.repo.save_version({"id": "v-m", "segment_id": "seg-m", "parent_version_id": None,
                           "target_text": "Something else.", "origin": "draft", "provider": "fake",
                           "model": "fake", "prompt_fingerprint": "", "routing_at_creation": "",
                           "source_channel": "offline", "spans": [], "words": [], "tones": [],
                           "sentiment": {}, "emotions": [], "created_at": ""})
    res = app.set_task_term({"task_id": tid, "source_term": "缓存", "target_term": "cache"})
    assert res["affected"] == 0 and res["rewritten"] == 0 and res["queued"] is False
    assert res["matched"] == 0
    assert app.repo.latest_version("seg-m")["target_text"] == "Something else."


def test_term_hit_uses_word_boundary_for_ascii():
    from laa_core.shared.terms import replace_term, term_hit

    assert term_hit("The cache is warm.", "cache")
    assert not term_hit("The cachegate is warm.", "cache")
    assert not term_hit("Caching helps.", "cache")
    assert replace_term("server-side cache", "cache", "buffer") == ("server-side buffer", 1)
    assert replace_term("cachegate cache", "cache", "buffer") == ("cachegate buffer", 1)
    assert term_hit("高速缓存命中", "缓存") and not term_hit("别的词", "缓存")


def test_set_task_term_retranslates_only_affected_segments(app):
    _fast(app)
    text = "GraphQL 很快。\n\nGraphQL 很慢。"
    info = app.start_translation({"text": text, "target_lang": "zh-Hans"}, trace_id="t")
    tid = info["task_id"]
    _wait(app, tid)
    snap = app.snapshot(tid)
    segs = snap["segments"]
    assert len(segs) == 2

    # 两个片段都含 GraphQL；让其中一个已使用目标译法，另一个未使用，模拟译法漂移
    for i, seg in enumerate(segs):
        version = app.repo.latest_version(seg["segment_id"])
        version["target_text"] = ("GraphQL 图查询语言 很快" if i == 0 else "GraphQL 很慢")
        app.repo.save_version(version)

    res = app.set_task_term({"task_id": tid, "source_term": "GraphQL",
                             "target_term": "GraphQL 图查询语言"}, trace_id="t")
    assert res["affected"] == 1 and res["queued"] is True
    assert res["segment_ids"] == [seg["segment_id"]]
    assert res["term"]["origin"] == "user"
    task = _wait(app, tid)
    assert task["status"] == TaskStatus.SUCCEEDED.value
    assert {t["source_term"]: t["origin"] for t in app.snapshot(tid)["terms"]}["GraphQL"] == "user"


# ---------------------------------------------------------------- 模型分句
def _gateway_with(provider):
    return ProviderGateway(ProviderRouter([provider], default_id="stub"))


class _SplitStub:
    provider_id = "stub"
    model = "stub"
    kind = "translate"

    def __init__(self, sentences):
        self._sentences = sentences

    def split_sentences(self, text, lang=""):
        return {"sentences": self._sentences, "usage": {"input_tokens": 1, "output_tokens": 1}}

    def capabilities(self):
        return {"source_channel": "online", "input": ["text"], "output": ["text"]}

    def health(self):
        return {"ok": True}


def test_model_sentences_are_used_when_they_join_back_to_source():
    calls: list = []
    gw = _gateway_with(_SplitStub(["你好呀。", "很高兴遇见你。"]))
    gw.on_usage = lambda *a: calls.append(a)
    text = "你好呀。很高兴遇见你。"
    assert gw.split_sentences(text) == ["你好呀。", "很高兴遇见你。"]
    assert calls and calls[0][2] == "segment"


def test_model_sentences_misaligned_fall_back_to_local_split():
    bogus = _gateway_with(_SplitStub(["你好呀。很高兴。", "遇见你。"]))
    text = "你好呀。很高兴遇见你。"
    out = bogus.split_sentences(text)
    assert "".join(out) == text, "降级分句仍必须逐字覆盖原文"
    assert out != ["你好呀。很高兴。", "遇见你。"]


def test_weird_punctuation_forms_readable_sentences_locally():
    text = "你好呀。很。高兴遇。到你"
    segs = segment_text(text)
    assert "".join(s.text for s in segs) == text
    local = Segmenter().split(text)[0].text
    assert local == text, "短段落整体成段，不按句号硬切"

    long_text = ("你好呀。很。高兴遇。到你 " * 60).strip()
    segs = segment_text(long_text)
    assert "".join(s.text for s in segs) == long_text
    for s in segs:
        assert len(s.text) <= 500


def test_local_split_keeps_abbreviations_and_decimals_intact():
    from laa_core.domain.text.service import _merge_tiny_spans, _sentence_spans

    text = "We use e.g. this case. Pi is 3.14 exactly. Dr. Smith agrees."
    spans = _merge_tiny_spans(_sentence_spans(text), text)
    parts = [text[s:e].strip() for s, e in spans]
    assert "".join(text[s:e] for s, e in spans) == text
    assert any("e.g. this case." in p for p in parts), "e.g. 内部不得断开"
    assert not any(p in ("e.", "g.") for p in parts)
    assert any("3.14" in p for p in parts), "小数点不得当作句末"
    assert any(p.startswith("Dr. Smith") for p in parts), "Dr. 不得拆开"


def test_forced_split_avoids_abbreviation_boundaries():
    # 一整句没有句号，只能强制切分；e.g. 会落在 500 字附近
    text = ("This sentence has no period and mentions e.g. an example "
            "inside it with more words to make it longer ") * 16
    segs = segment_text(text)
    assert "".join(s.text for s in segs) == text
    assert all(len(s.text) <= 500 for s in segs)
    cuts = {s.span[1] for s in segs[:-1]}
    for idx in [i for i in range(len(text)) if text.startswith("e.g.", i)]:
        assert not any(idx < cut < idx + 4 for cut in cuts), "强制切分不得落进 e.g. 内部"
    assert not any(text[:cut].endswith(("e.", "g.")) for cut in cuts)


# ---------------------------------------------------------------- 候选译法气泡
def test_pick_word_keeps_each_option_distinct():
    app = Bootstrap(use_memory=True).build()
    tid, sid = "task-pick", "seg-pick"
    app.repo.save_task({"id": tid, "source_text": "bank", "src_lang": "en", "tgt_lang": "zh-Hans",
                        "status": TaskStatus.SUCCEEDED.value, "segment_count": 1, "created_at": "",
                        "mode": "literal", "domain": "general", "resolved_scene": {}})
    app.repo.save_segment({"id": sid, "task_id": tid, "idx": 0, "text": "bank",
                           "span": [0, 4], "lang": "en", "token_estimate": 1, "status": "done"})
    words = [{"src": "bank", "target": "银行", "alternatives": ["河岸", "库"]}]
    app.repo.save_version({"id": "v1", "segment_id": sid, "parent_version_id": None,
                           "target_text": "银行", "origin": "draft", "provider": "fake",
                           "model": "fake", "prompt_fingerprint": "", "routing_at_creation": "",
                           "source_channel": "offline", "spans": [], "words": words,
                           "tones": [], "sentiment": {}, "emotions": [], "created_at": ""})

    for choice in ("河岸", "库", "银行", "河岸"):
        app.pick_word({"task_id": tid, "segment_id": sid, "word_index": 0, "choice": choice})
        current = app.repo.latest_version(sid)["words"][0]
        options = [current["target"]] + list(current["alternatives"])
        assert len(options) == len(set(options)), "选项不能重复"
        assert set(options) == {"银行", "河岸", "库"}, "每项必须保留自己的译文"
        assert current["target"] == choice, "选中只标记当前采用项"
        assert current["recommended"] == "银行", "推荐标记必须始终留在最初的推荐项上"
        assert current["options"] == ["银行", "河岸", "库"], "候选顺序不得随选中重排"


# ---------------------------------------------------------------- 状态机
def test_cancel_before_first_batch_marks_segments_cancelled_and_retryable(app, monkeypatch):
    _fast(app)
    entered, release = threading.Event(), threading.Event()
    orig_assess = app.risk.assess

    def blocked(*args, **kwargs):
        entered.set()
        release.wait(3)
        return orig_assess(*args, **kwargs)

    monkeypatch.setattr(app.risk, "assess", blocked)
    info = app.start_translation({"text": "第一段。\n\n第二段。\n\n第三段。", "target_lang": "en"})
    tid = info["task_id"]
    assert entered.wait(3), "预检应已开始"
    app.cancel_task(tid)
    release.set()
    task = _wait(app, tid)
    assert task["status"] == TaskStatus.CANCELLED.value

    snap = app.snapshot(tid)
    prog = snap["progress"]
    assert prog["done"] == 0
    assert prog["cancelled"] == prog["total"] > 0, "未开始的片段应有明确取消状态"
    assert all(s["status"] == "cancelled" for s in snap["segments"])

    res = app.retry_translation({"task_id": tid})
    assert res["queued"] is True, "预检取消后应能重试"
    assert _wait(app, tid)["status"] == TaskStatus.SUCCEEDED.value


def test_paused_with_all_segments_done_finalizes_without_new_calls(app):
    _fast(app)
    info = app.start_translation({"text": "第一段。\n\n第二段。", "target_lang": "en"})
    tid = info["task_id"]
    assert _wait(app, tid)["status"] == TaskStatus.SUCCEEDED.value
    calls_before = app.snapshot(tid)["progress"]["calls"]

    app.repo.update_task(tid, {"status": TaskStatus.PAUSED.value, "completed_at": None})
    res = app.retry_translation({"task_id": tid})
    assert res["finalized"] is True and res["queued"] is False
    task = app.repo.get_task(tid)
    assert task["status"] == TaskStatus.SUCCEEDED.value and task["completed_at"]
    assert app.snapshot(tid)["progress"]["calls"] == calls_before, "收尾不应产生新调用"


def test_recover_finalizes_running_task_when_all_segments_done(app):
    _fast(app)
    info = app.start_translation({"text": "第一段。\n\n第二段。", "target_lang": "en"})
    tid = info["task_id"]
    assert _wait(app, tid)["status"] == TaskStatus.SUCCEEDED.value
    # 模拟异常退出：片段已全部完成，但任务仍停在运行态
    app.repo.update_task(tid, {"status": TaskStatus.RUNNING.value, "completed_at": None})
    app.recover_tasks()
    task = app.repo.get_task(tid)
    assert task["status"] == TaskStatus.SUCCEEDED.value and task["completed_at"]
