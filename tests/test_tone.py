"""语气自动识别测试：一次模型调用同时产出译文与原文语气片段（span + 中文字段标签）。"""
from __future__ import annotations

import time

from laa_core.app.bootstrap import Bootstrap
from laa_core.app.pipeline import norm_tones
from laa_core.shared.types import TaskStatus

SRC = "You really did a great job this time."


class _ToneProvider:
    """返回同一份译文 + 指定语气片段的桩供应商（顶替 fake）。"""

    provider_id = "fake"
    kind = "translate"

    def __init__(self, tones):
        self.tones = tones

    def translate(self, plan, segments):
        out = []
        for seg in segments:
            sid = seg["id"] if isinstance(seg, dict) else seg.id
            out.append({"segment_id": sid, "target_text": "你这次真是干得漂亮。", "tones": self.tones})
        return {"segments": out, "emotions": []}

    def capabilities(self):
        return {"input": ["text"], "output": ["text"], "source_channel": "online"}

    def health(self):
        return {"ok": True}


def _app(tmp_path, tones):
    app = Bootstrap(data_dir=str(tmp_path)).build()
    app.gateway.router._providers["fake"] = _ToneProvider(tones)
    return app


def _run(app, text=SRC):
    tid = app.start_translation({"text": text, "target_lang": "zh-Hans", "mode": "fluent"})["task_id"]
    task = None
    for _ in range(500):
        task = app.repo.get_task(tid)
        if task["status"] in (TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value):
            break
        time.sleep(0.01)
    return tid, task


def test_tone_detected_in_same_call(tmp_path):
    """语气标注与译文来自同一次模型调用，落在原文正确区间上。"""
    app = _app(tmp_path, [{"start": 32, "end": 36, "label": "讽刺"}])
    tid, task = _run(app)
    assert task["status"] == TaskStatus.SUCCEEDED.value, task
    seg = app.snapshot(tid)["segments"][0]
    assert seg["target_text"] == "你这次真是干得漂亮。"
    assert seg["tones"] == [{"span": [32, 36], "label": "讽刺"}]
    assert seg["source_text"][32:36] == "time"


def test_no_tone_means_no_annotation(tmp_path):
    """无特殊语气时不给任何标注。"""
    app = _app(tmp_path, [])
    tid, task = _run(app, text="The meeting starts at nine.")
    assert task["status"] == TaskStatus.SUCCEEDED.value, task
    assert app.snapshot(tid)["segments"][0]["tones"] == []


def test_tones_persist_across_rebuild(tmp_path):
    app = _app(tmp_path, [{"start": 4, "end": 10, "label": "强调"}])
    tid, _ = _run(app)
    again = Bootstrap(data_dir=str(tmp_path)).build()
    seg = again.snapshot(tid)["segments"][0]
    assert seg["tones"] == [{"span": [4, 10], "label": "强调"}]


def test_norm_tones_tolerates_forms_and_drops_invalid():
    src = "Please stop right now!"
    # span 形式
    assert norm_tones([{"span": [7, 11], "label": "警告"}], src) == [{"span": [7, 11], "label": "警告"}]
    # text 片段形式（按子串定位）
    assert norm_tones([{"text": "right now", "label": "催促"}], src) == [{"span": [12, 21], "label": "催促"}]
    # 越界裁剪
    assert norm_tones([{"start": 5, "end": 999, "label": "愤怒"}], src) == [{"span": [5, len(src)], "label": "愤怒"}]
    # 非法/空标签/空区间/重叠片段被丢弃
    assert norm_tones([{"start": -3, "end": -1, "label": "愤怒"}], src) == []
    assert norm_tones([{"start": 1, "end": 3, "label": "  "}], src) == []
    assert norm_tones([{"start": 3, "end": 3, "label": "愤怒"}], src) == []
    assert norm_tones([{"start": 0, "end": 6, "label": "A"}, {"start": 3, "end": 9, "label": "B"}], src) == [
        {"span": [0, 6], "label": "A"}
    ]
    # 非列表 / 垃圾输入
    assert norm_tones(None, src) == []
    assert norm_tones([{"label": "讽刺"}], src) == []


def test_prompt_asks_for_tones_and_tone_preservation():
    """提示词要求：识别原文语气（方括号标签风格）、无语气不标注、译文保留语气。"""
    from laa_core.domain.scene.service import PromptComposer
    from laa_core.shared.dto import TranslateRequest

    plan = PromptComposer().compose(TranslateRequest(text="a sample sentence", target_lang="zh-Hans"),
                                    None, "", "fluent")
    prompt = plan.messages[0]["content"]
    assert '"tones"' in prompt
    assert "语气识别" in prompt
    assert "没有明显语气时 tones 输出空数组" in prompt
    assert "保留原文语气" in prompt
    assert "2~4 个汉字" in prompt
    for example in ("how old", "怎么老是你"):
        assert example not in prompt.lower()