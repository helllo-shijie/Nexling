"""翻译历史（工作台侧栏）与调用历史（设置 → 调用历史）后端测试。"""
from __future__ import annotations

import time

import pytest

from laa_core.app.bootstrap import Bootstrap
from laa_core.shared.errors import LaaError
from laa_core.shared.types import TaskStatus


def _wait(app, tid):
    task = None
    for _ in range(500):
        task = app.repo.get_task(tid)
        if task["status"] in (TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value):
            break
        time.sleep(0.01)
    return task


def test_history_list_returns_recent_tasks(app, run):
    tid, task = run()
    hist = app.history_list({"limit": 10, "offset": 0})
    assert hist["total"] >= 1
    first = hist["items"][0]
    assert first["task_id"] == tid
    assert first["status"] == TaskStatus.SUCCEEDED.value
    assert first["mode"] in ("fluent", "literal")
    assert first["source_text"]
    assert "created_at" in first and first["segment_count"] >= 1


def test_history_snapshot_still_loads(app, run):
    tid, _ = run()
    snap = app.snapshot(tid)
    assert snap["task"]["id"] == tid
    assert len(snap["segments"]) >= 1
    assert snap["segments"][0]["target_text"]


def test_calls_logged_with_prompt_response_and_cost(app, run):
    text = "The compiler optimizes the loop."
    run(text=text)
    res = app.calls_list({"limit": 10})
    assert res["total"] >= 1
    item = res["items"][0]
    assert item["purpose"] == "draft"
    assert item["provider"] == "fake"
    assert item["user_input"] == text
    assert item["response_preview"]
    assert item["input_tokens"] >= 0 and item["output_tokens"] >= 0
    assert item["amount"] >= 0.0
    assert item["created_at"]

    detail = app.call_get({"call_id": item["id"]})
    roles = [m["role"] for m in detail["prompt"]["messages"]]
    assert "system" in roles and "user" in roles
    user_msg = next(m["content"] for m in detail["prompt"]["messages"] if m["role"] == "user")
    assert text in user_msg  # 完整提示词里含用户输入
    assert detail["user_input"] == text
    assert detail["response"]
    assert detail["amount"] == item["amount"]


def test_call_get_unknown_id_raises(app):
    with pytest.raises(LaaError) as ei:
        app.call_get({"call_id": "not-a-real-call"})
    assert ei.value.code == "LAA-3005"


def test_call_get_requires_id(app):
    with pytest.raises(LaaError) as ei:
        app.call_get({})
    assert ei.value.code == "LAA-1002"


def test_complete_calls_are_logged_too(app):
    app.gateway.complete([{"role": "user", "content": "ping"}])
    res = app.calls_list({"limit": 5})
    assert res["total"] >= 1
    assert res["items"][0]["purpose"] == "qa"
    detail = app.call_get({"call_id": res["items"][0]["id"]})
    assert detail["prompt"]["messages"][0]["content"] == "ping"


def test_calls_and_history_persist_in_sqlite(tmp_path):
    app = Bootstrap(data_dir=str(tmp_path)).build()
    info = app.start_translation({"text": "Persisted call check.", "target_lang": "zh-Hans"})
    tid = info["task_id"]
    assert _wait(app, tid)["status"] == TaskStatus.SUCCEEDED.value

    calls = app.calls_list({"limit": 5})
    assert calls["total"] >= 1

    again = Bootstrap(data_dir=str(tmp_path)).build()
    assert again.calls_list({"limit": 5})["total"] >= 1
    hist = again.history_list({"limit": 5})
    assert hist["items"][0]["task_id"] == tid
    detail = again.call_get({"call_id": again.calls_list({"limit": 5})["items"][0]["id"]})
    assert detail["prompt"]["messages"]
    assert detail["user_input"] == "Persisted call check."