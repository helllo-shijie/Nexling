"""V5 回归：TM 策略、本地桥安全、记忆命中回填、迁移标记。"""
from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request

import pytest

from laa_core.infra.persistence.database import Database, LaaRepository, Migrator


def test_tm_skip_if_exists_updates_changed_translation(run, app):
    app.tm.store("Same source sentence here.", "旧译法", "en", "zh-Hans", approved=True, skip_if_exists=True)
    app.tm.store("Same source sentence here.", "新译法", "en", "zh-Hans", approved=True, skip_if_exists=True)
    rows = app.repo.list_tm()
    assert len(rows) == 1
    assert rows[0]["target_text"] == "新译法"
    hits = app.tm.lookup("Same source sentence here.", "en", "zh-Hans")
    assert hits and hits[0].target_text == "新译法"


def test_glossary_change_invalidates_memory(run, app):
    app.tm.store("Cache invalidation is hard.", "缓存失效很难。", "en", "zh-Hans", approved=True)
    bank = "personal-default"
    app.glossary_add({"bank_id": bank, "entry": {
        "source_term": "cache", "target_term": "高速缓存", "lang": "en", "target_lang": "zh-Hans",
    }})
    rows = app.repo.list_tm()
    assert rows and int(rows[0]["stale"]) == 1


def test_segment_view_exposes_tm_hits_and_apply_counts_use(run, app):
    text = "The compiler optimizes the loop."
    tid, _ = run(text, target_lang="zh-Hans")
    seg = app.repo.list_segments(tid)[0]
    entry = app.tm.store(text, "编译器会优化该循环。", "en", "zh-Hans", approved=True)
    views = app._segment_views(tid)
    hits = views[0]["tm_hits"]
    assert hits and hits[0]["entry_id"] == entry.id

    app.override_target({
        "task_id": tid, "segment_id": seg["id"], "target_text": hits[0]["target_text"],
        "origin": "tm_apply", "tm_entry_id": hits[0]["entry_id"],
    })
    row = next(e for e in app.repo.list_tm() if e["id"] == entry.id)
    assert int(row["use_count"]) == 1
    assert row["last_used_at"]


def test_term_candidates_are_task_scoped_and_cover_pascal_case(app, run):
    tid_a, _ = run("The ZephyrCore runtime warms up quickly; Nimbus stores the shards.",
                   target_lang="zh-Hans")
    tid_b, _ = run("Another task mentions GraphQL and QuasarLite plan.", target_lang="zh-Hans")
    app.term_scan({"task_id": tid_a})
    app.term_scan({"task_id": tid_b})

    items_a = app.term_list({"status": "pending", "task_id": tid_a})["items"]
    terms_a = {c["source_term"] for c in items_a}
    assert "ZephyrCore" in terms_a  # PascalCase
    assert "Nimbus" in terms_a      # 句中普通专名
    assert all(c["task_id"] == tid_a for c in items_a)
    terms_b = {c["source_term"] for c in app.term_list({"status": "pending", "task_id": tid_b})["items"]}
    assert "QuasarLite" in terms_b
    assert "ZephyrCore" not in terms_b

    # 同一术语出现在第三个任务：两边都要各自看得到，候选不能互相「抢走」
    tid_c, _ = run("ZephyrCore shows up again in a different task.", target_lang="zh-Hans")
    app.term_scan({"task_id": tid_c})
    terms_c = {c["source_term"] for c in app.term_list({"status": "pending", "task_id": tid_c})["items"]}
    assert "ZephyrCore" in terms_c
    still_a = {c["source_term"] for c in app.term_list({"status": "pending", "task_id": tid_a})["items"]}
    assert "ZephyrCore" in still_a


# ---- 本地桥安全 ----

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


def test_bridge_rejects_cross_origin_and_missing_token(app):
    srv, port = _serve(app, "secret-token")
    base = f"http://127.0.0.1:{port}"
    try:
        status, _ = _call(f"{base}/health")
        assert status == 200

        status, _ = _call(f"{base}/api/invoke",
                          {"cmd": "app.info", "payload": {}},
                          {"Content-Type": "application/json", "Origin": "http://evil.example"})
        assert status == 403

        status, _ = _call(f"{base}/api/invoke",
                          {"cmd": "app.info", "payload": {}},
                          {"Content-Type": "application/json", "Origin": base})
        assert status == 403  # 同源但缺少一次性 token

        status, body = _call(f"{base}/api/invoke",
                             {"cmd": "app.info", "payload": {}},
                             {"Content-Type": "application/json", "Origin": base,
                              "X-NexLing-Token": "secret-token"})
        assert status == 200 and json.loads(body)["ok"] is True

        status, _ = _call(f"{base}/api/events?task_id=&from_seq=0",
                          headers={"Origin": base})
        assert status == 403
    finally:
        srv.shutdown()
        srv.server_close()


def test_bridge_never_leaks_token_into_pages_or_assets(app, tmp_path):
    """token 只走原生桥：从 GET / 与任何静态资源都读不到。"""
    (tmp_path / "index.html").write_text("<!doctype html><html><head></head><body></body></html>",
                                         encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('boot');", encoding="utf-8")
    srv, port = _serve(app, "inject-me", static_dir=str(tmp_path))
    base = f"http://127.0.0.1:{port}"
    try:
        for path in ("/", "/index.html", "/assets/app.js"):
            status, body = _call(f"{base}{path}")
            assert status == 200, path
            assert b"inject-me" not in body, path
            assert b"nexling-token" not in body, path
        # 里程碑接口要求 token：无 token 一律 403，响应里也不回显 token
        status, body = _call(f"{base}/__mark?name=probe")
        assert status == 403
        assert b"inject-me" not in body
    finally:
        srv.shutdown()
        srv.server_close()


def test_cross_origin_write_is_rejected_without_cors_headers(app):
    srv, port = _serve(app, "")
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/invoke",
            data=json.dumps({"cmd": "app.info", "payload": {}}).encode(),
            headers={"Content-Type": "application/json", "Origin": "http://evil.example"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code == 403
        assert exc.value.headers.get("Access-Control-Allow-Origin") is None
    finally:
        srv.shutdown()
        srv.server_close()


# ---- 迁移 ----

def test_migration_is_marked_and_validated(tmp_path):
    path = str(tmp_path / "v5.sqlite3")
    db = Database(path)
    Migrator(db).migrate()
    with db.tx() as conn:
        marker = conn.execute(
            "SELECT value FROM schema_meta WHERE key = ?", (Migrator.MARKER,)
        ).fetchone()
    assert marker is not None
    db.close()

    # 二次迁移不重复加列，也不报错
    db2 = Database(path)
    Migrator(db2).migrate()
    with db2.tx() as conn:
        version = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(versions)").fetchall()}
    assert version is not None
    assert {"spans", "words", "sentiment"} <= cols
    db2.close()


def test_migration_validates_real_legacy_database(tmp_path):
    path = str(tmp_path / "legacy.sqlite3")
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE versions (id TEXT PRIMARY KEY, segment_id TEXT, created_at TEXT)")
    raw.commit()
    raw.close()
    db = Database(path)
    Migrator(db).migrate()
    with db.tx() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(versions)").fetchall()}
    assert {"spans", "words", "tones", "sentiment", "emotions"} <= cols
    db.close()


def test_old_term_candidate_index_is_upgraded(tmp_path):
    """v4 的库里是两列唯一索引，升级后要能容纳同一术语在多个任务下的候选。"""
    path = str(tmp_path / "old_index.sqlite3")
    db = Database(path)
    Migrator(db).migrate()
    with db.tx() as conn:
        conn.execute("DROP INDEX IF EXISTS idx_term_cand_key")
        conn.execute(
            "CREATE UNIQUE INDEX idx_term_cand_key ON term_candidates(normalized, target_lang)"
        )
    db.close()

    db2 = Database(path)
    Migrator(db2).migrate()
    with db2.tx() as conn:
        cols = [r["name"] for r in conn.execute("PRAGMA index_info(idx_term_cand_key)").fetchall()]
    assert cols == ["normalized", "target_lang", "task_id"]
    repo = LaaRepository(db2)
    repo.upsert_term_candidate({
        "id": "c1", "source_term": "gRPC", "normalized": "grpc", "target_lang": "zh-Hans",
        "task_id": "t1", "occurrences": 1, "confidence": 0.7, "status": "pending",
        "evidence": [], "created_at": "", "updated_at": "",
    })
    repo.upsert_term_candidate({
        "id": "c2", "source_term": "gRPC", "normalized": "grpc", "target_lang": "zh-Hans",
        "task_id": "t2", "occurrences": 1, "confidence": 0.7, "status": "pending",
        "evidence": [], "created_at": "", "updated_at": "",
    })
    tasks = {c["task_id"] for c in repo.list_term_candidates()}
    assert {"t1", "t2"} <= tasks
    db2.close()
