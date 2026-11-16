"""V10 长文本：分层切分 / 分批 / 进度 / 取消 / 重试 / 重启恢复 / 上限与成本估算。"""
from __future__ import annotations

import time

import pytest

from laa_core.app.bootstrap import Bootstrap
from laa_core.domain.text.service import plan_batches, segment_text
from laa_core.shared.types import TaskStatus


def _wait(app, tid: str, limit: int = 600) -> dict:
    for _ in range(limit):
        task = app.repo.get_task(tid)
        if task["status"] in (TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value,
                              TaskStatus.CANCELLED.value):
            return task
        time.sleep(0.01)
    return app.repo.get_task(tid)


def _paragraphs(n: int, tail: str = "Compilers and caches matter here.") -> str:
    return "\n\n".join(f"Paragraph {i} talks about latency. {tail}" for i in range(n))


def _fast_batches(app, **overrides) -> None:
    cfg = {"max_chars": 200000, "batch_chars": 200, "batch_segments": 1,
           "retries": 0, "throttle_ms": 0}
    cfg.update(overrides)
    app.settings_save({"long_text": cfg})


# ---------------------------------------------------------------- 切分
def test_paragraph_first_keeps_short_paragraphs_whole():
    text = "First paragraph stays whole.\n\nSecond paragraph also stays whole."
    segs = segment_text(text)
    assert [s.text for s in segs] == ["First paragraph stays whole.", "Second paragraph also stays whole."]
    assert all(not s.forced for s in segs)


def test_long_paragraph_splits_on_sentence_boundaries():
    text = "Alpha beta gamma delta. " * 40
    segs = segment_text(text)
    assert len(segs) > 1
    for s in segs:
        assert len(s.text) <= 500
        assert s.text.rstrip().endswith("."), "切分不能停在句子中段"
        assert not s.forced
        assert text[s.span[0]:s.span[1]] == s.text, "span 必须与原文一致"


def test_oversized_sentence_is_forced_split_and_marked():
    text = "A" * 1200
    segs = segment_text(text)
    assert len(segs) == 3
    assert all(s.forced for s in segs), "单句超限要标记为强制切分"
    assert all(len(s.text) <= 500 for s in segs)
    assert "".join(s.text for s in segs) == text


# ---------------------------------------------------------------- 分批
def test_plan_batches_respects_limits_and_keeps_order():
    segs = segment_text("Sentence one is here. Sentence two is here. " * 30)
    batches = plan_batches(segs, max_chars=600, max_segments=3)
    assert len(batches) > 1
    for batch in batches:
        assert len(batch) <= 3
        assert sum(len(s.text) for s in batch) <= 600 or len(batch) == 1
    assert [s for b in batches for s in b] == segs


# ---------------------------------------------------------------- 进度
def test_progress_matches_actual_done(app, run):
    _fast_batches(app)
    text = _paragraphs(12)
    tid, task = run(text)
    assert task["status"] == TaskStatus.SUCCEEDED.value
    snap = app.snapshot(tid)
    prog = snap["progress"]
    assert prog["total"] == len(snap["segments"]) == 12
    assert prog["done"] == prog["total"]
    assert prog["failed"] == 0 and prog["remaining"] == 0
    assert prog["batch_total"] >= 12, "每批 1 段时应至少 12 批"
    assert prog["calls"] >= prog["batch_total"], "真实调用数应回填到进度"
    assert all(s["target_text"] for s in snap["segments"])


def test_progress_events_are_incremental(app):
    _fast_batches(app)
    text = _paragraphs(5)
    info = app.start_translation({"text": text, "target_lang": "zh-Hans"})
    tid = info["task_id"]
    seen_done: list = []
    for _ in range(400):
        events = app.buffer.replay(tid, 0)["events"]
        done = [e["payload"].get("done", 0) for e in events
                if e["topic"] == "task.progress" and "done" in e.get("payload", {})]
        seen_done = done
        if app.repo.get_task(tid)["status"] == TaskStatus.SUCCEEDED.value:
            break
        time.sleep(0.01)
    assert seen_done, "应有任务级进度事件"
    assert seen_done == sorted(seen_done), "进度必须单调递增"
    assert max(seen_done) == 5


# ---------------------------------------------------------------- 取消
def test_cancel_keeps_completed_segments_and_marks_rest(app):
    _fast_batches(app)
    orig = app.gateway.translate

    def slow(plan, segments):
        time.sleep(0.05)
        return orig(plan, segments)

    app.gateway.translate = slow
    text = _paragraphs(6)
    info = app.start_translation({"text": text, "target_lang": "zh-Hans"})
    tid = info["task_id"]
    for _ in range(300):
        events = app.buffer.replay(tid, 0)["events"]
        if any(e["topic"] == "segment.view" for e in events):
            break
        time.sleep(0.01)
    app.cancel_task(tid)
    task = _wait(app, tid)
    assert task["status"] == TaskStatus.CANCELLED.value
    snap = app.snapshot(tid)
    done = [s for s in snap["segments"] if s["version_id"]]
    assert done, "已完成的片段必须保留"
    assert len(done) < len(snap["segments"]), "应确有未完成片段"
    assert all(s["status"] in ("done", "cancelled") for s in snap["segments"])
    assert snap["progress"]["cancelled"] >= 1
    assert snap["progress"]["done"] == len(done)


# ---------------------------------------------------------------- 失败重试
def test_failed_batch_retry_does_not_rerun_done_segments(app, monkeypatch):
    _fast_batches(app)
    text = _paragraphs(4)
    orig = app.gateway.translate
    calls = {"n": 0}

    def flaky(plan, segments):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("batch boom")
        return orig(plan, segments)

    monkeypatch.setattr(app.gateway, "translate", flaky)
    info = app.start_translation({"text": text, "target_lang": "zh-Hans"})
    tid = info["task_id"]
    task = _wait(app, tid)
    assert task["status"] == TaskStatus.FAILED.value
    snap = app.snapshot(tid)
    prog = snap["progress"]
    assert prog["failed"] == 1 and prog["done"] == 3
    assert "batch boom" in str(task.get("failed_batches") or ""), "失败批次应落库"

    before = {s["segment_id"]: s["version_id"] for s in snap["segments"] if s["version_id"]}
    monkeypatch.setattr(app.gateway, "translate", orig)
    app.retry_translation({"task_id": tid})
    task2 = _wait(app, tid)
    assert task2["status"] == TaskStatus.SUCCEEDED.value
    snap2 = app.snapshot(tid)
    assert snap2["progress"]["done"] == 4 and snap2["progress"]["failed"] == 0
    after = {s["segment_id"]: s["version_id"] for s in snap2["segments"] if s["version_id"]}
    assert all(after[k] == v for k, v in before.items()), "已完成片段不应被重跑"


# ---------------------------------------------------------------- 重启恢复
def test_restart_marks_running_task_paused_and_can_resume(tmp_path):
    data_dir = str(tmp_path / "data")
    app = Bootstrap(data_dir=data_dir, use_memory=False).build()
    text = _paragraphs(2)
    info = app.start_translation({"text": text, "target_lang": "zh-Hans"})
    tid = info["task_id"]
    _wait(app, tid)
    # 模拟进程在第二段完成前崩溃
    segs = app.repo.list_segments(tid)
    crashed = segs[-1]
    crashed["status"] = "pending"
    app.repo.save_segment(crashed)
    app.repo.update_task(tid, {"status": TaskStatus.RUNNING.value})

    app2 = Bootstrap(data_dir=data_dir, use_memory=False).build()
    assert app2.repo.get_task(tid)["status"] == TaskStatus.PAUSED.value
    app2.retry_translation({"task_id": tid})
    task = _wait(app2, tid)
    assert task["status"] == TaskStatus.SUCCEEDED.value
    assert app2.snapshot(tid)["progress"]["done"] == 2


# ---------------------------------------------------------------- 上限与估算
def test_estimate_and_over_limit_message(app):
    est = app.estimate_translation({"text": "Hello world. " * 20})
    assert est["over_limit"] is False
    assert est["batches"] >= 1 and est["est_calls"] == est["batches"]

    app.settings_save({"long_text": {"max_chars": 1000, "batch_chars": 500,
                                     "batch_segments": 2, "retries": 1, "throttle_ms": 0}})
    big = "Word " * 300
    est2 = app.estimate_translation({"text": big})
    assert est2["over_limit"] is True and est2["max_chars"] == 1000
    with pytest.raises(Exception) as exc:
        app.start_translation({"text": big, "target_lang": "zh-Hans"})
    assert getattr(exc.value, "code", "") == "LAA-3002"
    assert "1000" in getattr(exc.value, "message", str(exc.value))


def test_long_text_settings_are_validated(app):
    with pytest.raises(Exception):
        app.settings_save({"long_text": {"max_chars": 10}})
    with pytest.raises(Exception):
        app.settings_save({"long_text": {"batch_segments": 0}})
    app.settings_save({"long_text": {"batch_segments": 4, "throttle_ms": 0}})
    assert app.settings_get()["long_text"]["batch_segments"] == 4
