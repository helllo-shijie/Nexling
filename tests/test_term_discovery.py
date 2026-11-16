"""术语发现闭环（候选列表 + 采纳 / 忽略 + 写入术语库）的接口测试。"""
from __future__ import annotations

import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from laa_core.app.bootstrap import Bootstrap
from laa_core.shared.types import TaskStatus

SOURCE = ("gRPC uses HTTP2 transport, while the RPC layer retries failed calls. "
          "Another RPC note: gRPC keeps retrying.")


@pytest.fixture()
def persisted_app(tmp_path):
    app = Bootstrap(data_dir=str(tmp_path)).build()
    yield app
    app.repo.db.close()
    try:
        shutil.rmtree(str(tmp_path), ignore_errors=True)
    except OSError:
        pass


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


def test_scan_persists_candidates_and_merges_on_rescan(persisted_app):
    app = persisted_app
    tid = _translate(app)
    first = app.term_scan({"task_id": tid})
    assert first["scanned"] >= 1
    pending = first["items"]
    assert pending and all(c["status"] == "pending" for c in pending)
    norms = {c["normalized"] for c in pending}
    assert "grpc" in norms

    grpc = next(c for c in pending if c["normalized"] == "grpc")
    first_occ = grpc["occurrences"]
    assert grpc["context"]
    assert grpc["confidence"] >= 0.5

    again = app.term_scan({"task_id": tid})
    merged = next(c for c in again["items"] if c["normalized"] == "grpc")
    assert merged["id"] == grpc["id"], "重复扫描应合并同一条候选，而不是新增"
    assert merged["occurrences"] == first_occ, "同一任务重复扫描不应虚增出现次数"

    tid2 = _translate(app)
    third = app.term_scan({"task_id": tid2})
    other = next(c for c in third["items"] if c["normalized"] == "grpc")
    assert other["id"] != grpc["id"], "不同任务应各自保留候选，不能互相覆盖或抢走"
    assert other["task_id"] == tid2
    # 原任务的候选不受影响
    again1 = app.term_list({"status": "pending", "task_id": tid})["items"]
    assert next(c for c in again1 if c["normalized"] == "grpc")["id"] == grpc["id"]


def test_candidates_carry_quality_and_reasons(persisted_app):
    app = persisted_app
    tid = _translate(app)
    items = app.term_scan({"task_id": tid})["items"]
    assert items
    for c in items:
        assert c["quality"] in ("high", "medium", "low")
        assert isinstance(c["reasons"], list)
    # 列表按质量降序（置信度）排列，前端直接展示即可
    confidences = [c["confidence"] for c in items]
    assert confidences == sorted(confidences, reverse=True)


def test_accept_bulk_only_takes_high_quality_with_target(persisted_app):
    app = persisted_app
    tid = _translate(app)
    items = app.term_scan({"task_id": tid})["items"]
    cand = next(c for c in items if c["normalized"] == "grpc")
    app.repo.update_term_candidate(cand["id"], {
        "confidence": 0.9, "target_term": "gRPC 框架", "updated_at": "",
    })
    low = next(c for c in app.term_list({"status": "pending"})["items"]
               if c["normalized"] != "grpc")
    app.repo.update_term_candidate(low["id"], {
        "confidence": 0.55, "target_term": None, "updated_at": "",
    })

    out = app.term_accept_bulk({"min_confidence": 0.8, "task_id": tid,
                                "bank_id": "personal-default"})
    assert cand["id"] in out["accepted"]
    assert low["id"] in out["skipped"]
    assert out["counts"]["accepted"] >= 1


def test_accept_writes_glossary_entry_and_leaves_pending(persisted_app):
    app = persisted_app
    tid = _translate(app)
    items = app.term_scan({"task_id": tid})["items"]
    cand = next(c for c in items if c["normalized"] == "grpc")

    res = app.term_accept({"id": cand["id"], "target_term": "远程过程调用框架",
                           "bank_id": "personal-default"})
    assert res["ok"] is True
    assert res["candidate"]["status"] == "accepted"
    assert res["candidate"]["target_term"] == "远程过程调用框架"

    entries = app.repo.list_entries("personal-default")
    assert any(e["source_term"].lower() == cand["source_term"].lower()
               and e["target_term"] == "远程过程调用框架" for e in entries)

    # 已采纳的词不再回到待处理，也不会被再次扫描“复活”
    app.term_scan({"task_id": tid})
    pendings = app.term_list({"status": "pending"})["items"]
    assert all(c["normalized"] != "grpc" for c in pendings)
    file = app.term_list({"status": "accepted"})["items"]
    assert any(c["normalized"] == "grpc" for c in file)


def test_ignore_is_terminal_and_not_removed(persisted_app):
    app = persisted_app
    tid = _translate(app)
    items = app.term_scan({"task_id": tid})["items"]
    cand = next(c for c in items if c["normalized"] == "http2")

    out = app.term_ignore({"ids": [cand["id"]]})
    assert out["ignored"] == [cand["id"]]
    assert app.repo.get_term_candidate(cand["id"])["status"] == "ignored"

    app.term_scan({"task_id": tid})
    pendings = app.term_list({"status": "pending"})["items"]
    assert all(c["normalized"] != "http2" for c in pendings)
    assert out["counts"]["ignored"] >= 1


def test_accept_requires_target_term(persisted_app):
    app = persisted_app
    tid = _translate(app)
    # 造一条没有建议译法的候选，直接采纳应报错
    app.repo.upsert_term_candidate({
        "id": "cand-manual", "normalized": "zzz-term", "source_term": "zzz-term",
        "target_term": None, "lang": "en", "target_lang": "zh-Hans",
        "task_id": tid, "segment_id": "", "context": "", "occurrences": 1,
        "confidence": 0.6, "status": "pending", "evidence": [],
        "created_at": "", "updated_at": "",
    })
    with pytest.raises(Exception) as exc:
        app.term_accept({"id": "cand-manual"})
    assert "译词" in getattr(exc.value, "message", str(exc.value))


def test_command_router_exposes_term_commands(persisted_app):
    from laa_core.bridge.command import CommandRouter

    router = CommandRouter(persisted_app)
    tid = _translate(persisted_app)
    out = router.dispatch("term.scan", {"task_id": tid})
    assert out["scanned"] >= 1
    listed = router.dispatch("term.list", {"status": "pending"})
    assert isinstance(listed["items"], list)
