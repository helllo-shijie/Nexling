"""V4 修复的回归用例：离线保留标注、auto 目标语言、TM 写入策略。"""
from __future__ import annotations

import pytest

from laa_core.domain.tm.service import TranslationMemoryService
from laa_core.shared.errors import LaaError


def _latest(app, tid: str, idx: int = 0) -> dict:
    seg = app.repo.list_segments(tid)[idx]
    return app.repo.latest_version(seg["id"])


def test_offline_echo_is_not_marked_as_source_kept(run, app):
    tid, _ = run("这是整段中文源文，离线演示不应标注为保留。", target_lang="en")
    segs = app.snapshot(tid)["segments"]
    kinds = {k for seg in segs for sp in seg["spans"] for k in sp["kinds"]}
    assert "source_lang_kept" not in kinds


def test_auto_target_reaches_prompt_as_concrete_language(run, app):
    tid, _ = run("The compiler optimizes the loop.", target_lang="auto")
    task = app.repo.get_task(tid)
    assert task["tgt_lang"] == "zh-Hans"
    items = app.repo.list_calls(limit=10)["items"]
    assert items
    prompts = " ".join(str(i.get("prompt") or "") for i in items)
    assert "目标语言 auto" not in prompts
    assert "zh-Hans" in prompts


def test_translation_does_not_auto_write_memory(run, app):
    tid, _ = run("Offline demo text must not pollute memory.", target_lang="zh-Hans")
    assert app.repo.list_tm() == []


def test_manual_memory_add_and_remove(run, app):
    """翻译记忆改为手动：翻译完成不入库，点「加入记忆」才写，撤回可删掉该条。"""
    tid, _ = run("Manual memory add writes an approved sentence pair.", target_lang="zh-Hans")
    seg = app.repo.list_segments(tid)[0]
    version = app.repo.latest_version(seg["id"])
    # 翻译完成后默认不入库
    assert app.repo.list_tm() == []
    # 离线/fake 译文拒绝入库
    with pytest.raises(LaaError) as exc:
        app.memory_add({"task_id": tid, "segment_id": seg["id"]})
    assert exc.value.code == "LAA-1002"
    # 模拟真实在线译文后手动加入
    app.repo.save_version({**version, "id": version["id"] + "-online", "source_channel": "online"})
    res = app.memory_add({"task_id": tid, "segment_id": seg["id"]})
    rows = app.repo.list_tm()
    assert len(rows) == 1
    assert rows[0]["approved"] is True
    assert res["entry_id"] == rows[0]["id"]
    assert app.memory_delete({"entry_id": res["entry_id"]})["deleted"] is True
    assert app.repo.list_tm() == []


def test_tm_lookup_skips_unapproved_drafts():
    class _Mem:
        def __init__(self):
            self.rows = []

        def find_tm_exact(self, h, lp):
            return [e for e in self.rows if e["source_hash"] == h and e["lang_pair"] == lp]

        def list_tm(self):
            return list(self.rows)

        def upsert_tm(self, e):
            self.rows.append(e)

    repo = _Mem()
    svc = TranslationMemoryService(repo)
    svc.store("draft only", "草稿", "en", "zh-Hans", approved=False)
    assert svc.lookup("draft only", "en", "zh-Hans") == []
    assert svc.lookup("draft only", "en", "zh-Hans", include_drafts=True)


def test_snapshot_exposes_version_id(run, app):
    tid, _ = run("Snapshot must expose the current version id.", target_lang="zh-Hans")
    segs = app.snapshot(tid)["segments"]
    assert segs and segs[0]["version_id"]
    assert app.repo.get_version(segs[0]["version_id"]) is not None


def test_legacy_laa_migrates_to_localappdata(tmp_path, monkeypatch):
    import sqlite3

    import desktop

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.delenv("NEXLING_HOME", raising=False)
    legacy = tmp_path / "install" / ".laa"
    legacy.mkdir(parents=True)
    # 用真实 SQLite 库验证复制后仍可打开（不是占位字面量）
    src = sqlite3.connect(legacy / "laa.sqlite3")
    src.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY, note TEXT)")
    src.execute("INSERT INTO probe (note) VALUES ('legacy-row')")
    src.commit()
    src.close()
    (legacy / "secrets.json").write_text("{}")
    monkeypatch.setattr(desktop, "_legacy_data_dir", lambda: str(legacy))

    got = desktop._data_dir()
    new = tmp_path / "local" / "NexLing"
    assert got == str(new)
    copied = sqlite3.connect(new / "laa.sqlite3")
    assert copied.execute("SELECT note FROM probe").fetchone()[0] == "legacy-row"
    copied.close()
    assert (new / "secrets.json").exists()
    # 旧目录只读，不删除原数据
    assert (legacy / "laa.sqlite3").exists()
