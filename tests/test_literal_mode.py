"""直译模式（逐词义项对译 + 点词选义）测试：使用桩 provider，不联网。"""
from __future__ import annotations

import time

from laa_core.app.bootstrap import Bootstrap
from laa_core.shared.errors import LaaError
from laa_core.shared.types import TaskStatus


class _WordProvider:
    """返回逐词直译结果的桩供应商（顶替 fake）。"""

    kind = "translate"

    def __init__(self, words=None, provider_id="fake"):
        self.provider_id = provider_id
        self.words = words if words is not None else [
            {"src": "report", "target": "报告", "alternatives": ["报道", "报告书"]},
            {"src": "deadline", "target": "截止", "alternatives": ["期限", "最后期限"]},
            {"src": "Friday", "target": "星期五", "alternatives": ["礼拜五"]},
        ]

    def translate(self, plan, segments):
        out = []
        for seg in segments:
            sid = seg["id"] if isinstance(seg, dict) else seg.id
            out.append({
                "segment_id": sid,
                "target_text": " ".join(w["target"] for w in self.words),
                "words": self.words,
            })
        return {"segments": out, "emotions": []}

    def capabilities(self):
        return {"input": ["text"], "output": ["text"], "source_channel": "online"}

    def health(self):
        return {"ok": True}


def _make_app(tmp_path, provider_id="fake"):
    app = Bootstrap(data_dir=str(tmp_path)).build()
    app.gateway.router._providers[provider_id] = _WordProvider(provider_id=provider_id)
    if provider_id != "fake":
        app.gateway.router.default_id = provider_id
    return app


def _translate(app, text="The report deadline is Friday.", mode="literal", target_lang="zh-Hans"):
    info = app.start_translation({"text": text, "target_lang": target_lang, "mode": mode})
    tid = info["task_id"]
    task = None
    for _ in range(500):
        task = app.repo.get_task(tid)
        if task["status"] in (TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value):
            break
        time.sleep(0.01)
    return tid, task


def test_literal_words_and_marker(tmp_path):
    app = _make_app(tmp_path)
    tid, task = _translate(app)
    assert task["status"] == TaskStatus.SUCCEEDED.value, task
    seg = app.snapshot(tid)["segments"][0]
    assert seg["mode"] == "literal"
    # 中文目标：逐词相连 + 段末标识
    assert seg["target_text"] == "报告截止星期五 [AI TRANSLATED]"
    assert [w["target"] for w in seg["words"]] == ["报告", "截止", "星期五"]
    assert seg["words"][1]["alternatives"] == ["期限", "最后期限"]
    # 每个词都有一个 literal_word span，且 variants 含默认义项 + 其他义项
    lw = [s for s in seg["spans"] if "literal_word" in s["kinds"]]
    assert len(lw) == 3
    assert [v["label"] for v in lw[1]["variants"]] == ["截止", "期限", "最后期限"]
    assert lw[0]["span"] == [0, 2]


def test_literal_pick_word_rebuilds_sentence(tmp_path):
    app = _make_app(tmp_path)
    tid, _ = _translate(app)
    seg_id = app.snapshot(tid)["segments"][0]["segment_id"]
    view = app.pick_word({"task_id": tid, "segment_id": seg_id, "word_index": 1, "choice": "最后期限"})
    assert view["target_text"] == "报告最后期限星期五 [AI TRANSLATED]"
    assert view["words"][1]["target"] == "最后期限"
    # 新版本已持久化，快照读到的是选择后的结果
    seg = app.snapshot(tid)["segments"][0]
    assert seg["target_text"] == "报告最后期限星期五 [AI TRANSLATED]"
    versions = app.repo.list_versions(seg_id)
    assert versions[-1]["origin"] == "literal_pick"
    assert versions[-1]["parent_version_id"] == versions[0]["id"]


def test_literal_pick_rejects_unknown_choice(tmp_path):
    app = _make_app(tmp_path)
    tid, _ = _translate(app)
    seg_id = app.snapshot(tid)["segments"][0]["segment_id"]
    try:
        app.pick_word({"task_id": tid, "segment_id": seg_id, "word_index": 0, "choice": "不存在的义项"})
        raise AssertionError("应当抛出 LAA-1002")
    except LaaError as e:
        assert e.code == "LAA-1002"


def test_fluent_mode_has_no_words(tmp_path):
    app = _make_app(tmp_path)
    tid, task = _translate(app, mode="fluent")
    assert task["status"] == TaskStatus.SUCCEEDED.value, task
    seg = app.snapshot(tid)["segments"][0]
    assert seg["mode"] == "fluent"
    assert seg["words"] == []
    assert not seg["target_text"].endswith("[AI TRANSLATED]")


def test_literal_spans_persist_across_rebuild(tmp_path):
    """SQLite 落盘后重建应用，逐词对齐与 span 仍能读到（刷新页面不丢）。"""
    app = _make_app(tmp_path)
    tid, _ = _translate(app)
    seg_id = app.snapshot(tid)["segments"][0]["segment_id"]
    app.pick_word({"task_id": tid, "segment_id": seg_id, "word_index": 0, "choice": "报道"})

    again = Bootstrap(data_dir=str(tmp_path)).build()
    seg = again.snapshot(tid)["segments"][0]
    assert seg["target_text"] == "报道截止星期五 [AI TRANSLATED]"
    assert [w["target"] for w in seg["words"]] == ["报道", "截止", "星期五"]
    assert any("literal_word" in s["kinds"] for s in seg["spans"])


# ---------- 推荐的是“逐词义项”，不是整句/习语意译 ----------

def test_literal_prompt_asks_for_word_sense_not_phrase():
    """直译提示词必须要求逐词本义/推荐词义，且不得内置具体例句（防照抄）。"""
    from laa_core.domain.scene.service import PromptComposer
    from laa_core.shared.dto import TranslateRequest

    plan = PromptComposer().compose(TranslateRequest(text="a sample sentence", target_lang="zh-Hans"),
                                    None, "", "literal")
    prompt = plan.messages[0]["content"]
    assert "推荐义项" in prompt
    assert "最贴切" in prompt
    assert "孤立时的字典本义" in prompt
    assert "习语" in prompt
    assert "极短词组" in prompt
    assert "按顺序拼接" in prompt or "依序拼接" in prompt
    # 约束里不放具体示例句，避免模型照抄某个例句
    lowered = prompt.lower()
    for example in ("how old", "怎么老是你", "多少 岁 是 你"):
        assert example not in lowered


def test_literal_rejects_phrase_level_alignment(tmp_path):
    """模型把整句当一个“词”输出时，不展示逐词视图，退化为整句直译 + 标识。"""
    app = Bootstrap(data_dir=str(tmp_path)).build()
    app.gateway.router._providers["fake"] = _WordProvider(words=[
        {"src": "how old are you", "target": "整句意译的习语", "alternatives": []},
    ])
    tid, task = _translate(app, text="how old are you and your brother today")
    assert task["status"] == TaskStatus.SUCCEEDED.value, task
    seg = app.snapshot(tid)["segments"][0]
    assert seg["words"] == []
    assert seg["target_text"].endswith("[AI TRANSLATED]")
    assert not any("literal_word" in s["kinds"] for s in seg["spans"])


def test_literal_qa_length_not_flagged_as_blocking():
    """直译稿天然比原文短（英文→中文），不能按流畅稿的长度区间判为高严重度问题。"""
    from laa_core.domain.qa.service import LengthRatioCheck

    src = "The report deadline is Friday."
    literal = LengthRatioCheck({"source": src, "target": "报告截止星期五", "mode": "literal"})
    assert literal == []
    fluent = LengthRatioCheck({"source": src, "target": "报告截止星期五", "mode": "fluent"})
    assert fluent and fluent[0].severity == "medium"


def test_literal_mode_skips_fix_stage(tmp_path, monkeypatch):
    """直译模式不进入“修复”阶段：修复会把逐词稿改写成流畅稿。"""
    app = Bootstrap(data_dir=str(tmp_path)).build()
    app.gateway.router._providers["stub"] = _WordProvider(provider_id="stub")
    app.gateway.router.default_id = "stub"
    calls = []
    monkeypatch.setattr(app.qa, "apply_fixes", lambda *a, **k: calls.append(1) or {})
    # 源文带数字而译词不含数字 → 触发 high 级问题；流畅模式会进入修复，直译模式不应进入
    tid, task = _translate(app, text="There are 42 items in the box.")
    assert task["status"] == TaskStatus.SUCCEEDED.value, task
    assert calls == []
    assert app.snapshot(tid)["segments"][0]["mode"] == "literal"