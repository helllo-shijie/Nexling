"""V7 回归：候选默认库真实链路、CLI 边界、批量采纳容错、启动/HTTP 稳定性。"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from laa_core.bridge.http_server import MAX_BODY_BYTES, serve
from laa_core.shared.errors import LaaError

SEG_A = "The compiler optimizes the loop."
SEG_B = "Neural network handles garbage collection."
TEXT = SEG_A + "\n\n" + SEG_B


def _serve(app, token: str, static_dir=None, on_mark=None):
    srv = serve(app, host="127.0.0.1", port=0, static_dir=static_dir, on_mark=on_mark, token=token)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def _call(url: str, data=None, headers=None, timeout=5):
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


# ---------- 严重 1：候选默认库来自真实翻译链路 ----------
def test_candidates_default_bank_from_real_pipeline(run, app):
    tid, _ = run(TEXT)
    task = app.repo.get_task(tid)
    # 风险信息不得被场景解析覆盖
    assert task["resolved_scene"]["risk"]["tier"]
    # 内置场景没有绑定术语库：候选保持空目标库，采纳时必须让用户显式选择
    assert task["resolved_scene"]["scene"]["bank_ids"] == []
    items = app.term_scan({"task_id": tid})["items"]
    assert items and {c["bank_id"] for c in items} == {""}
    with pytest.raises(LaaError):
        app.term_accept({"id": items[0]["id"], "target_term": "候选译词"})


def test_scene_limited_bank_is_recorded_on_candidates(app):
    scene = app.scene_manage({"action": "create", "scene_profile": {
        "name": "强约束术语场景", "description": "测试用",
        "register": "formal", "mode_default": "fluent",
        "bank_ids": ["personal-default"],
    }})
    info = app.start_translation({"text": TEXT, "target_lang": "zh-Hans",
                                  "scene_profile_id": scene["id"]})
    tid = info["task_id"]
    from laa_core.shared.types import TaskStatus

    for _ in range(400):
        task = app.repo.get_task(tid)
        if task["status"] in (TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value,
                              TaskStatus.CANCELLED.value):
            break
        time.sleep(0.01)
    assert task["resolved_scene"]["scene"]["bank_ids"] == ["personal-default"]
    items = app.term_scan({"task_id": tid})["items"]
    assert items and {c["bank_id"] for c in items} == {"personal-default"}


# ---------- 严重 2：CLI 模式 token 与 host 边界 ----------
class _FakeServer:
    def __init__(self):
        self.kwargs = None

    def serve_forever(self):
        return None


def _cli_args(**kw):
    base = {"host": "127.0.0.1", "port": 8787, "static": "", "allow_remote": False,
            "data": None, "memory": True}
    base.update(kw)
    return argparse.Namespace(**base)


def test_cli_rejects_external_host_without_explicit_flag(monkeypatch, capsys):
    import cli

    monkeypatch.setattr(cli, "serve", lambda *a, **k: _FakeServer())
    assert cli.cmd_serve(_cli_args(host="0.0.0.0")) == 2
    err = capsys.readouterr().err
    assert "--allow-remote" in err
    assert cli.cmd_serve(_cli_args(host="192.168.1.10")) == 2


def test_cli_always_generates_bridge_token(monkeypatch, capsys):
    import cli

    fake = _FakeServer()

    def _fake_serve(*args, **kwargs):
        fake.kwargs = kwargs
        return fake

    monkeypatch.setattr(cli, "serve", _fake_serve)
    assert cli.cmd_serve(_cli_args()) == 0
    assert fake.kwargs["host"] == "127.0.0.1"
    assert len(fake.kwargs["token"]) >= 20
    assert "bridge token:" in capsys.readouterr().out

    # 显式风险开关：允许但必须警告
    assert cli.cmd_serve(_cli_args(host="0.0.0.0", allow_remote=True)) == 0
    assert "警告" in capsys.readouterr().err
    assert fake.kwargs["token"]


def test_bridge_fails_closed_when_token_empty(app):
    srv, port = _serve(app, "")
    base = f"http://127.0.0.1:{port}"
    try:
        assert srv.bridge_token
        status, _ = _call(f"{base}/api/invoke", {"cmd": "app.info", "payload": {}},
                          {"Content-Type": "application/json"})
        assert status == 403
        status, _ = _call(f"{base}/api/invoke", {"cmd": "app.info", "payload": {}},
                          {"Content-Type": "application/json",
                           "X-NexLing-Token": srv.bridge_token})
        assert status == 200
    finally:
        srv.shutdown()
        srv.server_close()


# ---------- 一般 1：陈旧 .control 不再阻塞启动 ----------
def test_stale_control_file_does_not_block_startup(tmp_path, monkeypatch):
    import desktop

    monkeypatch.setenv("NEXLING_HOME", str(tmp_path))
    data_dir = desktop._data_dir()
    os.makedirs(data_dir, exist_ok=True)

    # 端口 + 已不存在的 PID：应立刻判定陈旧并清理，不发起连接
    with open(desktop._control_path(), "w", encoding="utf-8") as fh:
        fh.write("47654 999999")
    started = time.perf_counter()
    assert desktop._activate_existing() is False
    elapsed = time.perf_counter() - started
    assert elapsed < 0.2, f"stale .control 仍在阻塞启动：{elapsed * 1000:.0f} ms"
    assert not os.path.exists(desktop._control_path())

    # 只有端口、指不到活进程：连接失败后同样清理
    with open(desktop._control_path(), "w", encoding="utf-8") as fh:
        fh.write("1")
    started = time.perf_counter()
    assert desktop._activate_existing() is False
    assert time.perf_counter() - started < 0.6
    assert not os.path.exists(desktop._control_path())


# ---------- 一般 2：403 拒绝也读完请求体，连接不抖 ----------
def test_rejected_requests_do_not_break_connection(app):
    srv, port = _serve(app, "only-token")
    base = f"http://127.0.0.1:{port}"
    try:
        for i in range(30):
            status, _ = _call(f"{base}/api/invoke",
                              {"cmd": "translation.start", "payload": {"text": "x" * 5000}},
                              {"Content-Type": "application/json",
                               "X-NexLing-Token": f"wrong-{i}"})
            assert status == 403, i
    finally:
        srv.shutdown()
        srv.server_close()


def test_oversized_body_is_rejected_without_reading(app):
    srv, port = _serve(app, "t")
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        request = (
            "POST /api/invoke HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            "Content-Type: application/json\r\nX-NexLing-Token: t\r\n"
            f"Content-Length: {MAX_BODY_BYTES + 1}\r\nConnection: close\r\n\r\n"
        ).encode("ascii")
        sock.sendall(request)
        data = sock.recv(4096)
        sock.close()
        assert b"413" in data
    finally:
        srv.shutdown()
        srv.server_close()


# ---------- 一般 3：批量采纳逐条独立处理 ----------
def test_bulk_accept_survives_bad_candidates(run, app):
    tid, _ = run("The HTTP API uses TLS, JSON and XML. GPU and CPU run the SQL compiler.")
    items = app.term_scan({"task_id": tid})["items"]
    assert len(items) >= 3
    for cand in items:
        app.repo.update_term_candidate(cand["id"], {
            "confidence": 0.95, "target_term": "译词-" + cand["source_term"],
            "bank_id": "personal-default", "updated_at": "",
        })
    bad_bank, need_bank, readonly = items[0]["id"], items[1]["id"], items[2]["id"]
    app.repo.update_term_candidate(bad_bank, {"bank_id": "no-such-bank"})
    app.repo.update_term_candidate(need_bank, {"bank_id": ""})
    app.repo.update_term_candidate(readonly, {"bank_id": "builtin-default"})

    # 不传统一 bank_id：让每条候选按自己记录的目标库处理（个人库 / 坏库 / 空库 / 只读库）
    out = app.term_accept_bulk({"task_id": tid, "min_confidence": 0.8})
    failed_ids = {f["id"] for f in out["failed"]}
    assert bad_bank in failed_ids
    assert readonly in failed_ids
    assert need_bank in out["needs_bank"]
    assert need_bank not in out["skipped"]  # 不重复计数
    assert out["failed_count"] == len(out["failed"])
    assert out["accepted_count"] == len(out["accepted"])
    # 坏数据不阻断其余候选
    expected = {c["id"] for c in items} - failed_ids - set(out["needs_bank"])
    assert set(out["accepted"]) == expected


# ---------- 一般 4：导出扩展名按格式校正 ----------
def test_export_extension_matches_format():
    import desktop

    assert desktop._ensure_extension("/tmp/report", "report.md") == "/tmp/report.md"
    assert desktop._ensure_extension("/tmp/report.txt", "report.md") == "/tmp/report.md"
    assert desktop._ensure_extension("/tmp/report.md", "report.md") == "/tmp/report.md"
    assert desktop._ensure_extension("/tmp/report.MD", "report.md") == "/tmp/report.MD"
    assert desktop._ensure_extension("/tmp/data.txt", "data.json") == "/tmp/data.json"


# ---------- 其他清理：路径校验 / 日志注入 ----------
def test_static_path_traversal_into_sibling_is_rejected(app, tmp_path):
    root = tmp_path / "static"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    sibling = tmp_path / "static-evil"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("TOP-SECRET", encoding="utf-8")

    srv, port = _serve(app, "t", static_dir=str(root))
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("GET", "/../static-evil/secret.txt")
        res = conn.getresponse()
        body = res.read()
        conn.close()
        assert res.status == 403
        assert b"TOP-SECRET" not in body
    finally:
        srv.shutdown()
        srv.server_close()


def test_mark_sanitizes_log_injection(app):
    marks = []
    srv, port = _serve(app, "t", on_mark=marks.append)
    base = f"http://127.0.0.1:{port}"
    try:
        # 无 token：伪造里程碑一律拒绝，也不产生日志
        status, _ = _call(f"{base}/__mark?name=evil%0Aforged%0Dline")
        assert status == 403
        assert marks == []
        # 带 token：仍然过滤换行/控制字符
        status, _ = _call(f"{base}/__mark?name=evil%0Aforged%0Dline",
                          headers={"X-NexLing-Token": "t"})
        assert status == 200
        assert marks == ["frontend: evilforgedline"]
    finally:
        srv.shutdown()
        srv.server_close()
