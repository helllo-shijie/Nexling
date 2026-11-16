"""V2：导出格式与整段覆写。"""
from __future__ import annotations

import json

import pytest

from laa_core.shared.errors import LaaError


def test_export_txt(app, run):
    tid, task = run()
    assert task["status"] == "succeeded"
    out = app.export(tid, "txt", False)
    assert out["path"].endswith(".txt")
    assert out["content"].strip()


def test_export_markdown_bilingual(app, run):
    tid, _ = run()
    out = app.export(tid, "md", False)
    assert out["path"].endswith(".md")
    assert "**原文**" in out["content"]
    assert "**译文**" in out["content"]


def test_export_json_metadata(app, run):
    tid, _ = run()
    out = app.export(tid, "json", True)
    data = json.loads(out["content"])
    assert data["task_id"] == tid
    assert data["segments"]
    assert "sentiment" in data["segments"][0]
    assert "target" in data["segments"][0]


def test_override_target_saves_new_version(app, run):
    tid, _ = run()
    seg = app.repo.list_segments(tid)[0]
    view = app.override_target({
        "task_id": tid,
        "segment_id": seg["id"],
        "target_text": "人工覆写后的译文。",
        "origin": "tm_apply",
    })
    assert view["segment_id"] == seg["id"]
    assert view["target_text"] == "人工覆写后的译文。"
    versions = app.repo.list_versions(seg["id"])
    assert versions[-1]["origin"] == "tm_apply"
    assert versions[-1]["target_text"] == "人工覆写后的译文。"


def test_override_rejects_empty(app, run):
    tid, _ = run()
    seg = app.repo.list_segments(tid)[0]
    with pytest.raises(LaaError):
        app.override_target({"task_id": tid, "segment_id": seg["id"], "target_text": "   "})
