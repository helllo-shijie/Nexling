"""回归：单实例锁、真实 SQLite 关键路径、导出格式白名单、拒绝慢连接。"""
from __future__ import annotations

import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from laa_core.app.bootstrap import Bootstrap
from laa_core.bridge import http_server
from laa_core.shared.errors import LaaError
from laa_core.shared.types import TaskStatus

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT = "The compiler optimizes the loop.\n\nNeural network handles garbage collection."
TERMINAL = (TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value)


@pytest.fixture()
def file_app(tmp_path):
    """真实 SQLite 文件（不使用内存库）：覆盖迁移、落盘与导出路径。"""
    app = Bootstrap(data_dir=str(tmp_path)).build()
    yield app


def _wait(app, tid: str) -> dict:
    for _ in range(600):
        task = app.repo.get_task(tid)
        if task["status"] in TERMINAL:
            return task
        time.sleep(0.01)
    raise AssertionError(f"翻译任务未在预期时间内结束：{tid}")


def _translate(app) -> str:
    info = app.start_translation({"text": TEXT, "target_lang": "zh-Hans", "domain": "tech"},
                                 trace_id="reg")
    tid = info["task_id"]
    _wait(app, tid)
    return tid


def test_export_rejects_unknown_format(file_app):
    app = file_app
    tid = _translate(app)
    with pytest.raises(LaaError) as exc:
        app.export(tid, "pdf")
    assert exc.value.code == "LAA-3011"
    assert "导出格式不支持" in (exc.value.message or "")
    # 白名单内格式仍然正常
    assert app.export(tid, "txt")["path"].endswith(".txt")
    assert app.export(tid, "md")["path"].endswith(".md")
    assert app.export(tid, "json")["path"].endswith(".json")


# ---------- 真实 SQLite：候选默认库来自翻译时的场景 ----------
def test_candidate_default_bank_on_real_sqlite(file_app, tmp_path):
    app = file_app
    scene = app.scene_manage({"action": "create", "scene_profile": {
        "name": "真实库场景", "description": "reg", "register": "formal",
        "mode_default": "fluent", "bank_ids": ["personal-default"],
    }})
    info = app.start_translation({"text": TEXT, "target_lang": "zh-Hans",
                                  "scene_profile_id": scene["id"]}, trace_id="reg")
    tid = info["task_id"]
    _wait(app, tid)

    assert os.path.isfile(tmp_path / "laa.sqlite3")
    items = app.term_scan({"task_id": tid})["items"]
    assert items and {c["bank_id"] for c in items} == {"personal-default"}

    # 重新打开同一数据目录：候选确实落盘（不是内存库假绿）
    reopened = Bootstrap(data_dir=str(tmp_path)).build()
    persisted = reopened.term_list({"status": "pending", "task_id": tid})["items"]
    assert {c["bank_id"] for c in persisted} == {"personal-default"}


# ---------- 真实 SQLite：术语候选唯一索引迁移 ----------
def test_term_candidate_index_migration_on_real_sqlite(tmp_path):
    db_path = tmp_path / "laa.sqlite3"
    Bootstrap(data_dir=str(tmp_path)).build()

    # 模拟旧库：唯一索引只有 (normalized, target_lang)
    conn = sqlite3.connect(db_path)
    conn.execute("DROP INDEX IF EXISTS idx_term_cand_key")
    conn.execute("CREATE UNIQUE INDEX idx_term_cand_key ON term_candidates(normalized, target_lang)")
    conn.commit()
    conn.close()

    Bootstrap(data_dir=str(tmp_path)).build()  # 启动即迁移

    conn = sqlite3.connect(db_path)
    cols = [row[2] for row in conn.execute("PRAGMA index_info(idx_term_cand_key)").fetchall()]
    conn.close()
    assert cols == ["normalized", "target_lang", "task_id"]


# ---------- 单实例：两个进程同时启动只有一个拿到锁 ----------
def test_only_one_instance_acquires_lock(tmp_path):
    script = (
        "import time, desktop\n"
        "ok = desktop._acquire_instance_lock()\n"
        "print('LOCK' if ok else 'BUSY', flush=True)\n"
        "time.sleep(3 if ok else 0)\n"
    )
    env = {**os.environ, "NEXLING_HOME": str(tmp_path)}
    procs = [subprocess.Popen([sys.executable, "-c", script], cwd=ROOT, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for _ in range(2)]
    try:
        outs = [p.communicate(timeout=30)[0].strip() for p in procs]
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
    assert sorted(outs) == ["BUSY", "LOCK"], outs


def test_live_control_file_is_not_removed_without_lock(tmp_path, monkeypatch):
    import desktop

    monkeypatch.setenv("NEXLING_HOME", str(tmp_path))
    data_dir = desktop._data_dir()
    os.makedirs(data_dir, exist_ok=True)
    # 端口连不通，但 PID 活着（本进程）：非锁持有者不得删除控制文件
    with open(desktop._control_path(), "w", encoding="utf-8") as fh:
        fh.write(f"1 {os.getpid()}")
    assert desktop._activate_existing(allow_cleanup=False) is False
    assert os.path.exists(desktop._control_path())


# ---------- 拒绝慢连接：读请求体有超时，不挂住线程 ----------
def test_drain_body_has_read_timeout(app, monkeypatch):
    monkeypatch.setattr(http_server, "DRAIN_TIMEOUT_SECONDS", 0.3)
    srv = http_server.serve(app, host="127.0.0.1", port=0, token="t")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        # 声明 1000 字节请求体，只发开头就停住：不设超时服务端会一直等
        sock.sendall(
            b"POST /api/invoke HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\nX-NexLing-Token: wrong\r\n"
            b"Content-Length: 1000\r\nConnection: close\r\n\r\n{\"cmd\":"
        )
        started = time.perf_counter()
        data = sock.recv(4096)
        elapsed = time.perf_counter() - started
        sock.close()
        assert b"403" in data
        assert elapsed < 5.0, f"拒绝慢连接耗时过长：{elapsed:.1f}s"
    finally:
        srv.shutdown()
        srv.server_close()
