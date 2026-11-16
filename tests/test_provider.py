"""Provider / API 接入链路测试（保存、密钥、动态刷新、连通测试）。"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from laa_core.app.bootstrap import Bootstrap


@pytest.fixture()
def persisted_app(tmp_path):
    app = Bootstrap(data_dir=str(tmp_path)).build()
    yield app
    try:
        shutil.rmtree(str(tmp_path), ignore_errors=True)
    except OSError:
        pass


def test_provider_upsert_persists_and_reloads(persisted_app):
    app = persisted_app
    r = app.provider_upsert({
        "profile": {"id": "deepseek", "kind": "deepseek", "name": "DeepSeek",
                    "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat",
                    "is_default": True},
        "api_key": "sk-test-123",
    })
    assert r["saved"] == "deepseek"
    lst = app.provider_list()
    deep = next(p for p in lst if p["id"] == "deepseek")
    assert deep["configured"] is True
    assert deep["default"] is True
    assert deep["base_url"] == "https://api.deepseek.com/v1"
    # 网关路由动态刷新后包含该供应商并设为默认
    assert "deepseek" in app.gateway.router._providers
    assert app.gateway.router.default_id == "deepseek"
    # 密钥经 SecretStore 加密封存可读
    assert app.secrets.get("key:deepseek") == "sk-test-123"


def test_provider_default_is_exclusive(persisted_app):
    app = persisted_app
    app.provider_upsert({"profile": {"id": "deepseek", "base_url": "https://api.deepseek.com/v1",
                                     "model": "m", "kind": "deepseek", "is_default": True}, "api_key": "k"})
    app.provider_upsert({"profile": {"id": "openai", "kind": "openai", "name": "OpenAI",
                                     "base_url": "https://api.openai.com/v1", "model": "m2", "is_default": True},
                         "api_key": "k2"})
    lst = app.provider_list()
    defaults = [p for p in lst if p["default"]]
    assert len(defaults) == 1
    assert defaults[0]["id"] == "openai"
    assert app.gateway.router.default_id == "openai"


def test_provider_test_unreachable_returns_false(persisted_app):
    app = persisted_app
    out = app.provider_test({"provider_id": "deepseek", "base_url": "http://127.0.0.1:1/v1",
                             "model": "deepseek-chat", "api_key": "sk-x",
                             "allow_custom_endpoint": True})
    assert out["ok"] is False  # 连通失败优雅返回，不抛异常


def test_provider_delete_removes(persisted_app):
    app = persisted_app
    app.provider_upsert({"profile": {"id": "openai", "kind": "openai", "name": "OpenAI",
                                     "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
                         "api_key": "sk-k"})
    r = app.provider_delete({"provider_id": "openai"})
    assert r["deleted"] == "openai"
    assert "openai" not in app.gateway.router._providers
    assert all(p["id"] != "openai" for p in app.provider_list())


def test_fake_engine_untouchable(persisted_app):
    app = persisted_app
    with pytest.raises(Exception):
        app.provider_upsert({"profile": {"id": "fake", "base_url": "", "model": ""}, "api_key": "x"})