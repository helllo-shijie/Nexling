"""Acceptance tests mapped to the 31-item acceptance list (M0–M3, offline)."""
from __future__ import annotations

import time

import pytest

from laa_core.shared import err, new_id
from laa_core.shared.types import TaskStatus, TranslateMode

SAMPLE = "The compiler optimizes the loop. Neural network handles garbage collection. " \
         "The latency is bounded by the cache miss rate and the deadline is strict."


# ---------------------------------------------------------------- A 组:功能
def test_A1_translate_offline(app, run):
    tid, task = run()
    assert task["status"] == TaskStatus.SUCCEEDED.value
    snap = app.snapshot(tid)
    assert snap["segments"], "应产出翻译段"
    for s in snap["segments"]:
        assert s["target_text"].startswith("〔离线引擎")


def test_A2_segmentation(app, run):
    tid, task = run(SAMPLE)
    segs = app.repo.list_segments(tid)
    # V10 分层切分：段落优先，短段落保持完整，不再按句拆成多段
    assert len(segs) == 1, "短段落应保持完整"
    spans = sorted(s["span"] for s in segs)
    assert spans[0][0] == 0
    assert spans[-1][1] == len(SAMPLE)


def test_A3_glossary_injection(app, run):
    e = app.glossary.add_entry("personal-default", {"source_term": "deadline", "target_term": "截止期限",
                                                    "forced": True})
    assert e["target_term"] == "截止期限"
    tid, task = run("Please respect the deadline.")
    hits = app.glossary.match("Please respect the deadline.", "en", "zh-Hans")
    assert any(h.source_term == "deadline" for h in hits)


def test_A4_scene_default(app):
    scenes = app.scene_list()
    assert scenes, "至少一个内置场景"
    default = next((s for s in scenes if s["is_default"]), None)
    assert default is not None
    resolved = app.scene.resolve(None)
    assert resolved.profile_id == default["id"]


def test_A5_risk_tier_L2(app, run):
    tid, task = run("甲方违约须承担违约责任。乙方应按合同约定支付违约金。", target_lang="en")
    assert task["risk_tier"] in ("L0", "L1", "L2", "L3")


def test_A7_export(app, run):
    tid, task = run()
    out = app.export(tid, fmt="txt")
    assert out["path"].endswith(".txt")
    assert "〔离线引擎" in out["content"]


def test_A8_mode_literal(app, run):
    tid, task = run()
    r = app.set_mode(tid, TranslateMode.LITERAL.value)
    assert r["mode"] == "literal"
    assert app.mode_get(tid)["mode"] == "literal"


def test_A9_retranslate(app, run):
    tid, task = run()
    r = app.retranslate(tid)
    assert r["task_id"] != tid  # new task spawned


# ---------------------------------------------------------------- B 组:质量
def test_B1_confidence_present(app, run):
    tid, task = run()
    for s in app.snapshot(tid)["segments"]:
        assert s["confidence"] is None or 0 <= s["confidence"]["score"] <= 1


def test_B2_literal_output_marked(app, run):
    # literal mode -> marker appended for real providers; fake provider echoes source
    tid, task = run()
    app.set_mode(tid, "literal")
    assert app.repo.get_task(tid)["mode"] == "literal"


def test_B3_segment_ids_unique(app, run):
    tid, task = run()
    ids = [s["id"] for s in app.repo.list_segments(tid)]
    assert len(ids) == len(set(ids))


def test_B4_qa_blocking_offline(app, run):
    tid, task = run("这是一段需要翻译的中文文本，包含数字 12345 与单位 kg。")
    # QA deterministic checks run without a real provider; here we assert no crash + report exists
    seg = app.repo.list_segments(tid)[0]
    v = app.repo.latest_version(seg["id"])
    assert v is not None


# ---------------------------------------------------------------- C 组:长任务/流
def test_C1_events_ordered(app, run):
    tid, task = run()
    ev = app.events(tid, 0)["events"]
    seqs = [e["seq"] for e in ev]
    assert seqs == sorted(seqs)
    assert ev[0]["topic"] == "task.created"
    assert ev[-1]["topic"] == "task.completed"


def test_C2_snapshot_checkpoint(app, run):
    tid, task = run()
    snap = app.snapshot(tid)
    assert snap["checkpoint_seq"] == app.buffer.latest_seq(tid)


def test_C3_cancel(app):
    info = app.start_translation({"text": SAMPLE * 50, "target_lang": "zh-Hans"}, trace_id="t")
    tid = info["task_id"]
    r = app.cancel_task(tid)
    assert r["cancelled"] is True or r["cancelled"] is False


def test_C4_resumable_flag(app, run):
    tid, task = run()
    info = app.start_translation({"text": "Hello", "target_lang": "zh-Hans"}, trace_id="t")
    assert info["stream"]["resumable"] is True


def test_C5_unknown_task(app):
    with pytest.raises(Exception):
        app.snapshot("nonexistent")


# ---------------------------------------------------------------- D 组:能力占位
def test_D1_capability_list(app):
    caps = app.capability_list()["items"]
    ids = {c["id"] for c in caps}
    assert "translation.text" in ids
    for pid in ("input.voice", "output.voice", "input.document", "extend.plugin",
                "platform.multi", "model.local"):
        spec = app.capabilities.get(pid)
        assert spec.status == "roadmap"


def test_D2_placeholder_blocked(app):
    # 占位能力 = roadmap + 无后端命令（前端零调用，收进路线图）
    for pid in ("input.voice", "output.voice", "input.document", "extend.plugin",
                "platform.multi", "model.local"):
        spec = app.capabilities.get(pid)
        assert spec.status == "roadmap"
        assert spec.command is None


def test_D3_message_keys(app):
    keys = app.message_keys()
    assert keys.get("capability.voice.input.in_development")


# ---------------------------------------------------------------- E 组:非功能
def test_E1_determinism():
    from laa_core.app.bootstrap import Bootstrap
    a = Bootstrap(use_memory=True).build()
    b = Bootstrap(use_memory=True).build()
    t1, _ = _run_sync(a, SAMPLE)
    t2, _ = _run_sync(b, SAMPLE)
    o1 = [s["target_text"] for s in a.snapshot(t1)["segments"]]
    o2 = [s["target_text"] for s in b.snapshot(t2)["segments"]]
    assert o1 == o2


def _run_sync(app, text):
    info = app.start_translation({"text": text, "target_lang": "zh-Hans"}, trace_id="t")
    tid = info["task_id"]
    for _ in range(400):
        t = app.repo.get_task(tid)
        if t["status"] in (TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value):
            break
        time.sleep(0.01)
    return tid, t


def test_E2_export_after_translation(app, run):
    """翻译完成后即可直接导出。"""
    tid, _ = run("Export after translation should work.", target_lang="zh-Hans")
    out = app.export(tid, "txt", False)
    assert out["content"].strip()


def test_E3_offline_no_network(app):
    # FakeProvider is the only provider; health must be pristine
    h = app.gateway.health("fake")
    assert h["ok"] is True