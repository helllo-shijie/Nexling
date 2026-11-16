"""V8 回归：审计移除后的旧库兼容、手动翻译记忆、候选清理与设置上限。"""
import sqlite3

import pytest

from laa_core.infra.persistence.database import Database, LaaRepository, Migrator
from laa_core.shared.errors import LaaError


def _cand(i: int, status: str = "pending", task_id: str = "t1", created: str = "") -> dict:
    stamp = created or f"2026-01-01T00:00:{i:02d}+00:00"
    return {
        "id": f"c{i}", "task_id": task_id, "bank_id": "", "source_term": f"Term{i}",
        "normalized": f"term{i}", "target_lang": "zh-Hans", "target_term": "",
        "context": "", "occurrences": 1, "confidence": 0.6, "quality": "medium",
        "status": status, "created_at": stamp, "updated_at": stamp,
    }


def test_old_database_with_audit_table_opens(tmp_path):
    """V7 旧库带 audit 表、tm 无 created_at：V8 打开要平滑迁移且不报错。"""
    path = str(tmp_path / "old.sqlite3")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO schema_meta VALUES('migrations','migrations_v5')")
    conn.execute(
        "CREATE TABLE tm (id TEXT PRIMARY KEY, source_hash TEXT NOT NULL, source_text TEXT NOT NULL,"
        " target_text TEXT NOT NULL, lang_pair TEXT NOT NULL, domain TEXT NOT NULL DEFAULT 'general',"
        " scene_profile_id TEXT, approved INTEGER NOT NULL DEFAULT 0, quality REAL NOT NULL DEFAULT 0.8,"
        " glossary_version INTEGER NOT NULL DEFAULT 0, prompt_fingerprint TEXT NOT NULL DEFAULT '',"
        " stale INTEGER NOT NULL DEFAULT 0, use_count INTEGER NOT NULL DEFAULT 0,"
        " last_used_at TEXT NOT NULL DEFAULT '')"
    )
    conn.execute("CREATE TABLE audit (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT, ts TEXT, hash TEXT)")
    conn.execute("INSERT INTO audit(id, ts, hash) VALUES('a1','2026-01-01','h1')")
    conn.commit()
    conn.close()

    db = Database(path)
    Migrator(db).migrate()
    repo = LaaRepository(db)

    cols = {r["name"] for r in db.conn().execute("PRAGMA table_info(tm)").fetchall()}
    assert "created_at" in cols
    assert repo.list_tm() == []
    repo.upsert_tm({"id": "m1", "source_hash": "h", "source_text": "a", "target_text": "b",
                    "lang_pair": "en|zh-Hans"})
    assert len(repo.list_tm()) == 1
    # 旧表保留但不参与业务，不影响打开与读写
    names = {r["name"] for r in db.conn().execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "audit" in names
    db.close()


def test_settings_defaults_and_validation(app):
    settings = app.settings_get()
    assert settings["term_candidate_cleanup"] == "auto"
    assert settings["term_candidate_limits"] == {"pending": 200, "accepted": 100, "ignored": 100}
    assert settings["memory_limit"] == 500

    saved = app.settings_save({"settings": {
        "term_candidate_limits": {"pending": 0, "accepted": 5, "ignored": 3},
        "term_candidate_cleanup": "manual",
        "memory_limit": 0,
    }})
    assert saved["settings"]["term_candidate_limits"]["pending"] == 0
    assert app.settings_get()["term_candidate_cleanup"] == "manual"

    with pytest.raises(LaaError):
        app.settings_save({"settings": {"term_candidate_cleanup": "weird"}})
    with pytest.raises(LaaError):
        app.settings_save({"settings": {"memory_limit": -1}})
    with pytest.raises(LaaError):
        app.settings_save({"settings": {"term_candidate_limits": {"pending": "x"}}})


def test_candidate_limit_trims_oldest_and_clear_by_column(app):
    for i in range(1, 5):
        app.repo.upsert_term_candidate(_cand(i))
    app.repo.upsert_term_candidate(_cand(5, status="accepted"))
    app.repo.upsert_term_candidate(_cand(6, status="ignored"))
    app.repo.upsert_term_candidate(_cand(7, status="pending", task_id="t2"))

    res = app.settings_save({"settings": {"term_candidate_limits": {
        "pending": 2, "accepted": 0, "ignored": 0,
    }}})
    assert res["removed"]["term_candidates"] == 3
    pending = [c["id"] for c in app.repo.list_term_candidates("pending", limit=10)]
    assert set(pending) == {"c4", "c7"}

    cleared = app.term_clear({"status": "accepted", "task_id": "t1"})
    assert cleared["removed"] == 1
    assert app.repo.count_term_candidates("t1")["accepted"] == 0

    assert app.term_clear({"status": "pending", "task_id": "t1"})["removed"] == 1
    assert app.repo.count_term_candidates("t1")["pending"] == 0
    assert app.repo.count_term_candidates("t2")["pending"] == 1

    assert app.term_clear({"status": "all", "task_id": "t2"})["removed"] == 1
    assert app.repo.count_term_candidates("t2")["pending"] == 0

    with pytest.raises(LaaError):
        app.term_clear({"status": "bogus"})


def test_memory_limit_trims_oldest_and_unlimited(app):
    for i in range(3):
        app.tm.store(f"source {i}", f"target {i}", "en", "zh-Hans", approved=True)
    assert len(app.repo.list_tm()) == 3

    res = app.settings_save({"settings": {"memory_limit": 2}})
    assert res["removed"]["memory"] == 1
    remaining = [r["source_text"] for r in app.repo.list_tm()]
    assert remaining == ["source 1", "source 2"]

    app.settings_save({"settings": {"memory_limit": 0}})
    app.tm.store("source 3", "target 3", "en", "zh-Hans", approved=True)
    assert len(app.repo.list_tm()) == 3
