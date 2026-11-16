"""术语库 CRUD 接口测试（search/add/update/remove + 只读保护）。"""
from __future__ import annotations

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from laa_core.app.bootstrap import Bootstrap


@pytest.fixture()
def persisted_app(tmp_path):
    app = Bootstrap(data_dir=str(tmp_path)).build()
    yield app
    app.repo.db.close()
    try:
        shutil.rmtree(str(tmp_path), ignore_errors=True)
    except OSError:
        pass


def test_banks_seeded_with_builtin_readonly(persisted_app):
    app = persisted_app
    banks = {b["id"]: b for b in app.repo.list_banks()}
    assert "builtin-default" in banks and "personal-default" in banks
    assert banks["builtin-default"]["readonly"] == 1
    assert banks["personal-default"]["readonly"] == 0
    assert len(app.repo.list_entries("builtin-default")) >= 15


def test_add_update_remove_roundtrip(persisted_app):
    app = persisted_app
    r = app.glossary_add({"bank_id": "personal-default",
                          "entry": {"source_term": "deadline", "target_term": "截止日期"}})
    eid = r["entry"]["id"]
    assert r["ok"] is True

    upd = app.glossary_update({"entry_id": eid,
                               "entry": {"target_term": "最终期限", "domain": "tech", "forced": True}})
    assert upd["target_term"] == "最终期限"
    assert upd["domain"] == "tech"
    assert upd["forced"] == 1
    assert upd["version"] == 2

    items = app.glossary_search({"bank_id": "personal-default", "query": "deadline"})["items"]
    assert [e["source_term"] for e in items] == ["deadline"]
    assert items[0]["target_term"] == "最终期限"

    app.glossary_remove({"entry_id": eid})
    after = app.glossary_search({"bank_id": "personal-default", "query": "deadline"})["items"]
    assert after == []


def test_update_builtin_rejected(persisted_app):
    app = persisted_app
    builtin = app.repo.list_entries("builtin-default")
    with pytest.raises(Exception):
        app.glossary_update({"entry_id": builtin[0]["id"], "entry": {"target_term": "改"}})


def test_add_empty_term_rejected(persisted_app):
    app = persisted_app
    with pytest.raises(Exception):
        app.glossary_add({"entry": {"source_term": "", "target_term": "x"}})


def test_import_package_preserves_fields(persisted_app):
    app = persisted_app
    r = app.glossary_import({"package": {"entries": [
        {"source_term": "batch", "target_term": "批量", "domain": "tech", "forced": True},
        {"source_term": "epoch", "target_term": "轮次", "part_of_speech": "n", "definition": "训练轮数"},
    ]}, "mode": "merge"})
    assert r["inserted"] == 2
    items = app.glossary_search({"bank_id": "personal-default"})["items"]
    batch = next(e for e in items if e["source_term"] == "batch")
    assert batch["target_term"] == "批量"
    assert batch["domain"] == "tech"
    assert batch["forced"] == 1
    epoch = next(e for e in items if e["source_term"] == "epoch")
    assert epoch["part_of_speech"] == "n"
    assert epoch["definition"] == "训练轮数"


def test_import_merge_and_append_modes(persisted_app):
    app = persisted_app
    app.glossary_import({"package": {"entries": [{"source_term": "x", "target_term": "甲"}]}})
    r = app.glossary_import({"package": {"entries": [{"source_term": "x", "target_term": "乙"}]}, "mode": "merge"})
    assert r["updated"] == 1
    items = app.glossary_search({"bank_id": "personal-default", "query": "x"})["items"]
    assert items[0]["target_term"] == "乙"
    r2 = app.glossary_import({"package": {"entries": [{"source_term": "x", "target_term": "丙"}]}, "mode": "append"})
    assert r2["skipped"] == 1
    items = app.glossary_search({"bank_id": "personal-default", "query": "x"})["items"]
    assert items[0]["target_term"] == "乙"  # append 不覆盖


def test_create_bank(persisted_app):
    app = persisted_app
    r = app.glossary_bank_create({"name": "我的术语"})
    assert r["ok"] is True
    b = r["bank"]
    assert b["scope"] == "personal"
    assert b["readonly"] == 0
    assert b["name"] == "我的术语"
    assert b["src_lang"] == "*" and b["tgt_lang"] == "*"
    assert b["id"] in [x["id"] for x in app.repo.list_banks()]
    with pytest.raises(Exception):
        app.glossary_bank_create({"name": "我的术语"})
    with pytest.raises(Exception):
        app.glossary_bank_create({"name": "   "})


def test_scene_variant_roundtrip(persisted_app):
    app = persisted_app
    r = app.glossary_add({"bank_id": "personal-default", "entry": {
        "source_term": "deadline", "target_term": "截止日期",
        "scene_variants": {"business-formal": "交付期限", "casual-chat": "最后期限"}}})
    eid = r["entry"]["id"]
    e = app.repo.get_entry(eid)
    assert e["scene_variants"] == {"business-formal": "交付期限", "casual-chat": "最后期限"}
    # update 覆盖 scene_variants
    app.glossary_update({"entry_id": eid, "entry": {"scene_variants": {"business-formal": "截止时限"}}})
    e2 = app.repo.get_entry(eid)
    assert e2["scene_variants"] == {"business-formal": "截止时限"}


def test_scene_variant_match(persisted_app):
    app = persisted_app
    app.glossary_add({"bank_id": "personal-default", "entry": {
        "source_term": "deadline", "target_term": "截止日期",
        "scene_variants": {"business-formal": "交付期限"}}})
    hits = app.glossary.match("Please confirm the deadline.", "en", "zh-Hans")
    assert any(h.target_term == "截止日期" for h in hits)
    hits_biz = app.glossary.match("Please confirm the deadline.", "en", "zh-Hans", scene_id="business-formal")
    assert any(h.target_term == "交付期限" for h in hits_biz)
    # 无覆盖的场景仍用默认译词
    hits_casual = app.glossary.match("Please confirm the deadline.", "en", "zh-Hans", scene_id="casual-chat")
    assert any(h.target_term == "截止日期" for h in hits_casual)