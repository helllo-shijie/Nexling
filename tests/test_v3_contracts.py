"""V3 契约测试：真实 provider 字段透传、auto 语言识别、翻译记忆管理、HTTP 入口。"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

from laa_core.app.pipeline import norm_sentiment, norm_variants
from laa_core.bridge.http_server import serve
from laa_core.domain.text.service import LanguageDetector
from laa_core.infra.providers.openai_compat import OpenAICompatProvider
from laa_core.shared.dto import PromptPlan
from laa_core.shared.types import TaskStatus

ROOT = Path(__file__).resolve().parent.parent


# ---------- B1：真实 provider 必须透传 sentiment / variants ----------

def _provider(content: dict) -> OpenAICompatProvider:
    p = OpenAICompatProvider("deepseek", "DeepSeek", "https://api.example/v1", "m", api_key="k")

    def fake_post(payload):  # 不真的发网络请求
        return {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8}}

    p._post = fake_post
    return p


def _plan() -> PromptPlan:
    return PromptPlan(template_id="t", template_version="1", mode="fluent",
                      messages=[{"role": "user", "content": "translate"}],
                      scene_profile_id=None, scene_version=1)


def test_real_provider_preserves_sentiment_and_variants():
    content = {
        "segments": [{
            "segment_id": "s1",
            "target_text": "调度器采用指数退避重试失败的 Pod。",
            "sentiment": {"positive": 0.2, "negative": 0.3, "neutral": 0.5},
            "variants": [{"text": "指数退避", "options": ["指数级退避"]}],
        }],
        "emotions": [],
    }
    out = _provider(content).translate(_plan(), [])
    seg = out["segments"][0]
    assert seg["sentiment"] == content["segments"][0]["sentiment"]
    assert seg["variants"] == content["segments"][0]["variants"]
    # 下游归一化能把 provider 透传的字段变成界面要用的结构
    assert norm_sentiment(seg["sentiment"])["needs_review"] is True
    assert norm_variants(seg["variants"], seg["target_text"])[0]["options"] == ["指数级退避"]


def test_real_provider_rejects_malformed_sentiment():
    content = {"segments": [{"segment_id": "s1", "target_text": "x", "sentiment": "high"}],
               "emotions": []}
    with pytest.raises(Exception):
        _provider(content).translate(_plan(), [])


# ---------- S2：auto / 空 / None 都不算显式语言提示 ----------

def test_auto_hint_does_not_override_detection():
    det = LanguageDetector()
    assert det.detect("这是一段很短的中文句子。", "auto")["lang"] == "zh-Hans"
    assert det.detect("这是一段很短的中文句子。", "")["lang"] == "zh-Hans"
    assert det.detect("This is an English sentence.", None)["lang"] == "en"
    # 真正的显式提示仍然优先
    assert det.detect("This is an English sentence.", "ja")["method"] == "hint"


def test_explicit_auto_source_does_not_break_target_auto(app):
    info = app.start_translation({"text": "这是一段很短的中文句子。", "source_lang": "auto",
                                  "target_lang": "auto"}, trace_id="t")
    task = app.repo.get_task(info["task_id"])
    for _ in range(400):
        task = app.repo.get_task(info["task_id"])
        if task["status"] in (TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value):
            break
        threading.Event().wait(0.01)
    assert task["src_lang"] == "zh-Hans"
    assert task["tgt_lang"] == "en"


# ---------- 翻译记忆管理 ----------

def test_memory_list_filter_and_delete(app):
    entry = app.tm.store("The compiler optimizes the loop.", "编译器优化循环。", "en", "zh-Hans",
                         approved=True)
    out = app.memory_list({"query": "compiler"})
    assert out["total"] >= 1
    row = next(i for i in out["items"] if i["entry_id"] == entry.id)
    assert row["lang_pair"] == "en-zh-Hans"
    assert row["approved"] is True
    assert "en-zh-Hans" in out["pairs"]

    assert app.memory_list({"query": "compiler", "lang_pair": "ja-en"})["total"] == 0
    assert app.memory_delete({"entry_id": entry.id})["deleted"] is True
    assert app.memory_delete({"entry_id": entry.id})["deleted"] is False
    assert all(i["entry_id"] != entry.id for i in app.memory_list({})["items"])


def test_memory_delete_requires_entry_id(app):
    with pytest.raises(Exception):
        app.memory_delete({})


# ---------- HTTP 桥：命令真的可达 ----------

@pytest.fixture()
def http_base(app):
    server = serve(app, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    yield f"http://{host}:{port}", server.bridge_token
    server.shutdown()


def _invoke(base, cmd: str, payload: dict) -> dict:
    url, token = base
    req = urllib.request.Request(
        url + "/api/invoke",
        data=json.dumps({"cmd": cmd, "payload": payload}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-NexLing-Token": token}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_http_auto_language_and_memory_commands(http_base, app):
    body = _invoke(http_base, "translation.start",
                   {"text": "这是一段很短的中文句子。", "source_lang": "auto", "target_lang": "auto"})
    assert body["ok"] is True
    tid = body["data"]["task_id"]
    for _ in range(600):
        task = app.repo.get_task(tid)
        if task["status"] in (TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value):
            break
        threading.Event().wait(0.01)
    assert task["src_lang"] == "zh-Hans"
    assert task["tgt_lang"] == "en"

    listed = _invoke(http_base, "memory.list", {"limit": 5})
    assert listed["ok"] is True and "items" in listed["data"]


# ---------- CLI：--target auto 不再固定落到中文 ----------

def test_cli_target_auto_uses_detected_source(tmp_path):
    proc = subprocess.run(
        [sys.executable, "run.py", "--data", str(tmp_path / ".laa"), "translate",
         "--text", "这是一段很短的中文句子。", "--target", "auto"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    snap = json.loads(proc.stdout)
    assert snap["task"]["tgt_lang"] == "en"
    assert snap["task"]["src_lang"] == "zh-Hans"
