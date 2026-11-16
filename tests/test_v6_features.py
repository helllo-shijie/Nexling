"""V6 新增三件的回归测试：导出保存路径、候选术语归属、拖入翻译（前端另测）。

这里只覆盖后端/桌面侧：
- 导出对话框按格式给过滤器、缺扩展名补全、记住上次目录；
- 候选继承翻译时实际使用的术语库，未关联时批量采纳不静默落默认库。
"""
from __future__ import annotations

import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import desktop
from laa_core.app.bootstrap import Bootstrap
from laa_core.shared.types import TaskStatus

SOURCE = ("gRPC uses HTTP2 transport, while the RPC layer retries failed calls. "
          "Another RPC note: gRPC keeps retrying.")


@pytest.fixture()
def persisted_app(tmp_path):
    app = Bootstrap(data_dir=str(tmp_path)).build()
    yield app
    app.repo.db.close()
    shutil.rmtree(str(tmp_path), ignore_errors=True)


def _translate(app, text=SOURCE, target="zh-Hans"):
    info = app.start_translation({"text": text, "target_lang": target, "mode": "literal"},
                                 trace_id="t")
    tid = info["task_id"]
    for _ in range(300):
        task = app.repo.get_task(tid)
        if task["status"] in (TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value,
                              TaskStatus.CANCELLED.value):
            break
        time.sleep(0.01)
    return tid


# ---------- 导出：三种格式 + 记住上次目录 ----------

def test_export_file_types_cover_three_formats():
    assert "JSON" in desktop._export_file_types("a.json")[0]
    assert "Markdown" in desktop._export_file_types("a.md")[0]
    assert "文本" in desktop._export_file_types("a.txt")[0]
    assert desktop._export_file_types("a.bin") == ("所有文件 (*.*)",)


def test_ensure_extension_fills_missing_suffix():
    assert desktop._ensure_extension("/tmp/out", "doc.md").endswith("out.md")
    # 扩展名与导出格式不一致时按格式校正（V7）
    assert desktop._ensure_extension("/tmp/out.txt", "doc.md") == "/tmp/out.md"
    assert desktop._ensure_extension("/tmp/out.md", "doc.md") == "/tmp/out.md"
    assert desktop._ensure_extension("/tmp/out", "doc") == "/tmp/out"


def test_last_save_dir_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXLING_HOME", str(tmp_path))
    chosen = tmp_path / "exports"
    chosen.mkdir()
    desktop._save_last_save_dir(str(chosen))
    assert desktop._load_last_save_dir() == str(chosen)
    # 目录被删掉后不应再把无效路径塞回对话框
    shutil.rmtree(str(chosen))
    assert desktop._load_last_save_dir() == ""


# ---------- 候选术语：写入目标归属 ----------

def test_scan_records_bank_used_by_translation(persisted_app):
    app = persisted_app
    tid = _translate(app)
    app.repo.update_task(tid, {"resolved_scene": {"bank_ids": ["personal-default"]}})

    items = app.term_scan({"task_id": tid})["items"]
    assert items
    assert all(c["bank_id"] == "personal-default" for c in items), \
        "候选必须记住翻译时实际使用的术语库，而不是硬编码默认库"

    cand = next(c for c in items if c["normalized"] == "grpc")
    app.repo.update_term_candidate(cand["id"], {
        "confidence": 0.9, "target_term": "gRPC 框架", "updated_at": "",
    })
    out = app.term_accept_bulk({"min_confidence": 0.8, "task_id": tid})
    assert cand["id"] in out["accepted"], "未手动选库时应按候选归属写入"
    entries = app.repo.list_entries("personal-default")
    assert any(e["source_term"].lower() == "grpc" for e in entries)


def test_bulk_accept_without_bank_requires_explicit_target(persisted_app):
    app = persisted_app
    tid = _translate(app)
    # 内置场景 bank_ids 为空：翻译当时没有关联任何术语库
    items = app.term_scan({"task_id": tid})["items"]
    assert items and all(c["bank_id"] == "" for c in items)
    cand = next(c for c in items if c["normalized"] == "grpc")
    app.repo.update_term_candidate(cand["id"], {
        "confidence": 0.9, "target_term": "gRPC 框架", "updated_at": "",
    })

    out = app.term_accept_bulk({"min_confidence": 0.8, "task_id": tid})
    assert cand["id"] in out["needs_bank"]
    assert cand["id"] not in out["accepted"]
    assert app.repo.get_term_candidate(cand["id"])["status"] == "pending", \
        "没有目标库时不能静默写入任何默认库"

    # 用户显式选库后同一批候选可以正常采纳
    picked = app.term_accept_bulk({"min_confidence": 0.8, "task_id": tid,
                                   "bank_id": "personal-default"})
    assert cand["id"] in picked["accepted"]
    assert not picked["needs_bank"]


def test_single_accept_without_bank_is_rejected(persisted_app):
    app = persisted_app
    tid = _translate(app)
    cand = next(c for c in app.term_scan({"task_id": tid})["items"]
                if c["normalized"] == "grpc")
    app.repo.update_term_candidate(cand["id"], {"target_term": "gRPC 框架", "updated_at": ""})

    with pytest.raises(Exception) as exc:
        app.term_accept({"id": cand["id"], "task_id": tid})
    assert "选择目标库" in getattr(exc.value, "message", str(exc.value))
