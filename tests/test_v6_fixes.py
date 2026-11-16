"""V6 回归：base_url 写入口白名单、候选跨任务隔离、记忆精准失效、token 不落页面。"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from laa_core.app.bootstrap import Bootstrap
from laa_core.shared.errors import LaaError


@pytest.fixture()
def db_app(tmp_path):
    app = Bootstrap(data_dir=str(tmp_path)).build()
    yield app
    try:
        shutil.rmtree(str(tmp_path), ignore_errors=True)
    except OSError:
        pass


def _online_versions(app, tid: str) -> None:
    """把整段译文标成在线渠道，模拟真实在线译文场景。"""
    for seg in app.repo.list_segments(tid):
        v = app.repo.latest_version(seg["id"])
        app.repo.save_version({**v, "id": v["id"] + "-online", "source_channel": "online"})


def _serve(app, token: str, static_dir=None):
    from laa_core.bridge.http_server import serve

    srv = serve(app, host="127.0.0.1", port=0, static_dir=static_dir, token=token)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def _call(url: str, data=None, headers=None):
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


# ---------- 阻断 1：base_url 写入口也锁死 ----------
def test_provider_upsert_rejects_unknown_domain(db_app):
    with pytest.raises(LaaError) as exc:
        db_app.provider_upsert({"profile": {"id": "deepseek", "base_url": "https://evil.example/v1",
                                            "model": "deepseek-chat"}, "api_key": "k"})
    assert exc.value.code == "LAA-2003"
    assert all(p["id"] != "deepseek" for p in db_app.provider_list())

    # 先 upsert（被拒）再 test 同地址：同样不能放行
    with pytest.raises(LaaError) as test_exc:
        db_app.provider_test({"provider_id": "deepseek", "base_url": "https://evil.example/v1",
                              "model": "deepseek-chat", "api_key": "k"})
    assert test_exc.value.code == "LAA-2003"


def test_provider_upsert_accepts_official_domain(db_app):
    res = db_app.provider_upsert({"profile": {
        "id": "deepseek", "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat", "is_default": True,
    }, "api_key": "sk-test"})
    assert res["saved"] == "deepseek"
    assert res["custom_endpoint"] is False
    row = next(p for p in db_app.provider_list() if p["id"] == "deepseek")
    assert row["official"] is True and row["blocked"] is False
    assert "deepseek" in db_app.gateway.router._providers


def test_custom_endpoint_requires_explicit_flag_and_is_stored(db_app):
    with pytest.raises(LaaError) as exc:
        db_app.provider_upsert({"profile": {"id": "relay", "base_url": "https://relay.example/v1",
                                            "model": "m"}, "api_key": "k"})
    assert exc.value.code == "LAA-2003"

    res = db_app.provider_upsert({"profile": {
        "id": "relay", "base_url": "https://relay.example/v1", "model": "m",
        "allow_custom_endpoint": True,
    }, "api_key": "k"})
    assert res["custom_endpoint"] is True
    row = next(p for p in db_app.provider_list() if p["id"] == "relay")
    assert row["custom_endpoint"] is True and row["blocked"] is False
    assert "relay" in db_app.gateway.router._providers


def test_legacy_illegal_provider_is_blocked_until_confirmed(tmp_path):
    first = Bootstrap(data_dir=str(tmp_path)).build()
    first.repo.save_provider({
        "id": "deepseek", "kind": "deepseek", "name": "DeepSeek",
        "base_url": "https://evil.example/v1", "model": "deepseek-chat",
        "enabled": 1, "is_default": 1, "secret_handle": "key:deepseek",
    })

    # 重启（旧库）后：非法地址被识别、不进入路由、盲调被拒
    app = Bootstrap(data_dir=str(tmp_path)).build()
    row = next(p for p in app.provider_list() if p["id"] == "deepseek")
    assert row["blocked"] is True
    assert "deepseek" not in app.gateway.router._providers
    with pytest.raises(LaaError) as exc:
        app.provider_test({"provider_id": "deepseek"})
    assert exc.value.code == "LAA-2003"

    # 用户显式确认后：落库 custom_endpoint，恢复路由
    app.provider_upsert({"profile": {
        "id": "deepseek", "base_url": "https://evil.example/v1", "model": "deepseek-chat",
        "is_default": True, "allow_custom_endpoint": True,
    }})
    row = next(p for p in app.provider_list() if p["id"] == "deepseek")
    assert row["blocked"] is False and row["custom_endpoint"] is True
    assert "deepseek" in app.gateway.router._providers

    # 确认标记落盘：再次重启后依然可用
    again = Bootstrap(data_dir=str(tmp_path)).build()
    assert "deepseek" in again.gateway.router._providers


# ---------- 阻断 2：批量采纳按 task_id 隔离 ----------
def test_bulk_accept_is_scoped_to_current_task(run, app):
    tid_a, _ = run("The compiler optimizes the loop. Neural network handles garbage collection.")
    tid_b, _ = run("The compiler optimizes the loop. Neural network handles garbage collection.")
    a_items = app.term_scan({"task_id": tid_a})["items"]
    b_items = app.term_scan({"task_id": tid_b})["items"]
    assert a_items and b_items
    assert {c["id"] for c in a_items}.isdisjoint({c["id"] for c in b_items})

    for cand in a_items:
        app.repo.update_term_candidate(cand["id"], {
            "confidence": 0.95, "target_term": "A 任务译词", "updated_at": "",
        })
    for cand in b_items:
        app.repo.update_term_candidate(cand["id"], {
            "confidence": 0.95, "target_term": "B 任务译词", "updated_at": "",
        })

    out = app.term_accept_bulk({"task_id": tid_a, "min_confidence": 0.0,
                                "bank_id": "personal-default"})
    accepted = set(out["accepted"])
    assert accepted and accepted <= {c["id"] for c in a_items}
    assert accepted.isdisjoint({c["id"] for c in b_items})

    # B 的候选原样保留（pending，未被写进个人术语库）
    b_ids = {c["id"] for c in b_items}
    assert all(app.repo.get_term_candidate(cid)["status"] == "pending" for cid in b_ids)
    assert app.term_list({"status": "pending", "task_id": tid_b})["items"]

    # 缺少 task_id 时拒绝，避免"没带隔离键就全表采纳"
    with pytest.raises(LaaError) as exc:
        app.term_accept_bulk({"min_confidence": 0.0})
    assert exc.value.code == "LAA-1002"


def test_term_counts_are_scoped_per_task(run, app):
    tid_a, _ = run("The compiler optimizes the loop. Neural network handles garbage collection.")
    tid_b, _ = run("The compiler optimizes the loop. Neural network handles garbage collection.")
    app.term_scan({"task_id": tid_a})
    app.term_scan({"task_id": tid_b})
    counts_a = app.term_list({"status": "pending", "task_id": tid_a})["counts"]
    counts_all = app.repo.count_term_candidates()
    assert 0 < counts_a["pending"] < counts_all["pending"]


# ---------- 严重 3：记忆失效精准化 + 可恢复 ----------
MEM_A = "The compiler optimizes the loop."
MEM_B = "Neural network handles garbage collection."


def _seed_memory(app):
    app.tm.store(MEM_A, "编译器优化循环。", "en", "zh-Hans", approved=True)
    app.tm.store(MEM_B, "神经网络处理垃圾回收。", "en", "zh-Hans", approved=True)


def test_unrelated_glossary_term_keeps_memory(app):
    _seed_memory(app)
    app.glossary_add({"bank_id": "personal-default", "entry": {
        "source_term": "Kubernetes", "target_term": "K8s",
    }})
    rows = app.repo.list_tm()
    assert len(rows) == 2
    assert all(int(r["stale"]) == 0 for r in rows)
    assert len(app.tm.lookup(MEM_A, "en", "zh-Hans")) == 1
    assert len(app.tm.lookup(MEM_B, "en", "zh-Hans")) == 1


def test_related_glossary_term_invalidates_only_matching_memory(app):
    _seed_memory(app)
    res = app.glossary_add({"bank_id": "personal-default", "entry": {
        "source_term": "compiler", "target_term": "编译器",
    }})
    assert res["memory_invalidated"] == 1
    stale = [r for r in app.repo.list_tm() if int(r["stale"])]
    assert len(stale) == 1 and stale[0]["source_text"] == MEM_A
    assert len(app.tm.lookup(MEM_A, "en", "zh-Hans")) == 0
    assert len(app.tm.lookup(MEM_B, "en", "zh-Hans")) == 1


def test_memory_restore_clears_stale(app):
    _seed_memory(app)
    app.glossary_add({"bank_id": "personal-default", "entry": {
        "source_term": "compiler", "target_term": "编译器",
    }})
    entry_id = next(r["id"] for r in app.repo.list_tm() if int(r["stale"]) == 1)
    assert app.memory_restore({"entry_id": entry_id})["restored"] is True
    row = next(r for r in app.repo.list_tm() if r["id"] == entry_id)
    assert int(row["stale"]) == 0
    assert len(app.tm.lookup(MEM_A, "en", "zh-Hans")) == 1


def test_glossary_change_marks_memory_stale_until_manual_restore(run, app):
    tid, _ = run(MEM_A + "\n\n" + MEM_B)
    _online_versions(app, tid)
    segs = app.repo.list_segments(tid)
    for seg in segs:
        app.memory_add({"task_id": tid, "segment_id": seg["id"]})
    assert len(app.repo.list_tm()) == 2
    assert all(int(r["stale"]) == 0 for r in app.repo.list_tm())

    app.glossary_add({"bank_id": "personal-default", "entry": {
        "source_term": "compiler", "target_term": "编译器",
    }})
    assert any(int(r["stale"]) == 1 for r in app.repo.list_tm())

    # 术语变更只标记 stale，不自动清理：手动恢复后才重新可用
    assert any(int(r["stale"]) == 1 for r in app.repo.list_tm())
    assert len(app.repo.list_tm()) == 2

    for row in [r for r in app.repo.list_tm() if int(r["stale"]) == 1]:
        app.memory_restore({"entry_id": row["id"]})
    assert all(int(r["stale"]) == 0 for r in app.repo.list_tm())
    assert len(app.tm.lookup(MEM_A, "en", "zh-Hans")) == 1


# ---------- 阻断 4：token 只走原生桥 ----------
def test_token_is_required_for_data_endpoints(app):
    srv, port = _serve(app, "secret-token")
    base = f"http://127.0.0.1:{port}"
    try:
        status, _ = _call(f"{base}/api/invoke", {"cmd": "app.info", "payload": {}},
                          {"Content-Type": "application/json"})
        assert status == 403
        status, _ = _call(f"{base}/api/events?task_id=&from_seq=0")
        assert status == 403
        status, body = _call(f"{base}/api/invoke", {"cmd": "app.info", "payload": {}},
                             {"Content-Type": "application/json", "X-NexLing-Token": "secret-token"})
        assert status == 200 and json.loads(body)["ok"] is True
    finally:
        srv.shutdown()
        srv.server_close()


def test_pages_and_static_assets_never_contain_token(app, tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><html><head></head><body></body></html>",
                                         encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('boot');", encoding="utf-8")
    (assets / "app.css").write_text("body{color:#000}", encoding="utf-8")
    srv, port = _serve(app, "leak-me", static_dir=str(tmp_path))
    base = f"http://127.0.0.1:{port}"
    try:
        for path in ("/", "/index.html", "/assets/app.js", "/assets/app.css"):
            status, body = _call(f"{base}{path}")
            assert status == 200, path
            assert b"leak-me" not in body, path
            assert b"nexling-token" not in body, path
        status, body = _call(f"{base}/__mark?name=probe")
        assert status == 403
        assert b"leak-me" not in body
    finally:
        srv.shutdown()
        srv.server_close()


def test_mark_requires_origin_and_token(app):
    srv, port = _serve(app, "t")
    base = f"http://127.0.0.1:{port}"
    try:
        status, _ = _call(f"{base}/__mark?name=x", headers={"Origin": "http://evil.example"})
        assert status == 403
        # 同源但无 token：同样拒绝（不能凭同源伪造启动日志）
        status, _ = _call(f"{base}/__mark?name=x", headers={"Origin": base})
        assert status == 403
        status, _ = _call(f"{base}/__mark?name=x",
                          headers={"Origin": base, "X-NexLing-Token": "t"})
        assert status == 200
    finally:
        srv.shutdown()
        srv.server_close()
