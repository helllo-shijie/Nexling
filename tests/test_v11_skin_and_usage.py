# -*- coding: utf-8 -*-
"""V11：皮肤包（声明式变量 / 导入导出 / 删除）与用量（统计 / 保留 / 清理）。"""
from __future__ import annotations

import base64
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from pathlib import Path

from laa_core.app.bootstrap import Bootstrap
from laa_core.domain.skin.service import COLOR_KEYS, SHADOW_KEYS, SkinService


def _night_vars() -> dict:
    """以 night 示例包为完整的深色基线，避免用同一个颜色填满所有语义键。"""
    path = Path(__file__).resolve().parent.parent / "skins" / "night.nxlskin"
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read("skin.json").decode("utf-8"))["vars"]


FULL_DARK = _night_vars()


def _manifest(**overrides):
    data = {
        "format": "nexling.skin",
        "version": 1,
        "id": "demo-skin",
        "name": "演示皮肤",
        "mode": "light",
        "vars": {"--accent": "#2a6f86", "--accent-hover": "#1f5b6f"},
        "effects": {"glass": "off"},
        "background": None,
    }
    data.update(overrides)
    return data


def _zip(files: dict) -> str:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _png() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture()
def app():
    return Bootstrap(use_memory=True).build()


def test_builtin_skins_listed_and_default_not_deletable(app):
    listing = app.skin_list({})
    ids = [item["id"] for item in listing["items"]]
    assert ids[:2] == ["default", "mint"]
    assert all(item["builtin"] for item in listing["items"][:2])
    active = app.skin_active({})
    assert active["id"] == "default" and active["builtin"] is True
    assert active["vars"] == {}
    assert active["mode"] == "light"
    with pytest.raises(Exception) as exc:
        app.skin_delete({"id": "default"})
    assert "内置" in exc.value.message


def test_mint_builtin_has_complete_light_palette(app):
    view = app.skin_select({"id": "mint"})
    assert view["mode"] == "light" and view["builtin"] is True
    for key in ("--bg", "--surface", "--accent", "--emotion-positive-bg",
                "--confidence-high-bg", "--sent-pos-bg", "--scrollbar-thumb"):
        assert key in view["vars"]
    assert app.settings_get()["usage"]["calls_retention"] == 2000


def test_import_light_package_and_export_without_screenshot(app):
    data = _zip({
        "skin.json": json.dumps(_manifest()),
        "screenshot.png": b"not-an-image-but-never-read",
    })
    res = app.skin_import({"filename": "demo.nxlskin", "data": data})
    assert res["skin"]["id"] == "demo-skin" and res["updated"] is False
    assert res["skin"]["builtin"] is False

    view = app.skin_select({"id": "demo-skin"})
    assert view["vars"]["--accent"] == "#2a6f86"
    assert view["background"] is None

    exported = app.skin_export({"id": "demo-skin"})
    assert exported["filename"] == "demo-skin.nxlskin"
    payload = base64.b64decode(exported["data"])
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        assert "screenshot.png" not in names
        assert "skin.json" in names
        saved = json.loads(archive.read("skin.json").decode("utf-8"))
        assert saved["id"] == "demo-skin"


def test_same_id_import_updates_in_place(app):
    first = _zip({"skin.json": json.dumps(_manifest(name="旧名字"))})
    app.skin_import({"filename": "a.nxlskin", "data": first})
    second = _zip({"skin.json": json.dumps(_manifest(name="新名字"))})
    res = app.skin_import({"filename": "b.nxlskin", "data": second})
    assert res["updated"] is True
    items = [i for i in app.skin_list({})["items"] if i["id"] == "demo-skin"]
    assert len(items) == 1 and items[0]["name"] == "新名字"


def test_background_is_stored_and_exported_but_screenshot_is_not(app):
    data = _zip({
        "skin.json": json.dumps(_manifest(
            id="with-bg",
            background={"file": "background.png", "scrim": "high"},
        )),
        "background.png": _png(),
        "screenshot.png": b"ignored",
    })
    app.skin_import({"filename": "bg.nxlskin", "data": data})
    view = app.skin_select({"id": "with-bg"})
    assert view["background"]["scrim"] == "high"
    assert view["background"]["data_url"].startswith("data:image/png;base64,")

    with zipfile.ZipFile(io.BytesIO(base64.b64decode(app.skin_export({"id": "with-bg"})["data"]))) as archive:
        assert "background.png" in archive.namelist()
        assert "screenshot.png" not in archive.namelist()


def test_import_rejects_unknown_field_and_bad_values(app):
    cases = [
        _manifest(extra_field=1),
        _manifest(vars={"--unknown-token": "#fff"}),
        _manifest(vars={"--accent": "javascript:alert(1)"}),
        _manifest(vars={"--radius": "999px"}),
        _manifest(vars={"--shadow": "url(http://x/y.png)"}),
        _manifest(effects={"glass": "maybe"}),
        _manifest(id="default"),
        _manifest(id="Bad ID"),
        _manifest(mode="dark", vars={"--bg": "#000000"}),
        _manifest(mode="sepia"),
    ]
    for manifest in cases:
        with pytest.raises(Exception):
            app.skin_import({"filename": "x.nxlskin", "data": _zip({"skin.json": json.dumps(manifest)})})


def test_import_rejects_low_contrast_palette(app):
    manifest = _manifest(vars={"--text": "#dddddd", "--surface": "#ffffff"})
    with pytest.raises(Exception) as exc:
        app.skin_import({"filename": "x.nxlskin", "data": _zip({"skin.json": json.dumps(manifest)})})
    assert "对比度" in exc.value.message


def test_import_rejects_oversize_and_bad_zip(app):
    big = _zip({"skin.json": json.dumps(_manifest()), "pad.bin": b"0" * (5 * 1024 * 1024 + 10)})
    with pytest.raises(Exception) as exc:
        app.skin_import({"filename": "big.nxlskin", "data": big})
    assert "5 MB" in exc.value.message
    with pytest.raises(Exception):
        app.skin_import({"filename": "x.nxlskin", "data": "bm90IGEgemlw"})


def test_dark_package_requires_complete_vars_then_applies(app):
    manifest = _manifest(id="night-demo", mode="dark", vars=FULL_DARK)
    app.skin_import({"filename": "n.nxlskin", "data": _zip({"skin.json": json.dumps(manifest)})})
    view = app.skin_select({"id": "night-demo"})
    assert view["mode"] == "dark"
    assert set(COLOR_KEYS) <= set(view["vars"])


def test_delete_external_skin_and_fall_back_to_default(app):
    data = _zip({"skin.json": json.dumps(_manifest(id="temp-skin"))})
    app.skin_import({"filename": "t.nxlskin", "data": data})
    app.skin_select({"id": "temp-skin"})
    res = app.skin_delete({"id": "temp-skin"})
    assert res["deleted"] == "temp-skin" and res["active"] == "default"
    assert app.skin_active({})["id"] == "default"
    assert "temp-skin" not in [i["id"] for i in app.skin_list({})["items"]]


def test_sample_packages_are_valid():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "skins"
    app = Bootstrap(use_memory=True).build()
    for name in ("liquid-glass", "night", "warm-contrast"):
        path = root / f"{name}.nxlskin"
        assert path.is_file(), path
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        res = app.skin_import({"filename": path.name, "data": data})
        assert res["skin"]["id"] == name
    assert app.skin_select({"id": "liquid-glass"})["effects"]["glass"] == "on"


# ---------- 用量 ----------

def _seed_calls(app, count: int):
    now = datetime.now(timezone.utc)
    for i in range(count):
        created = (now - timedelta(days=i % 120)).isoformat(timespec="milliseconds")
        app.repo.append_call({
            "id": f"call-{i:04d}", "created_at": created, "provider": "deepseek",
            "model": "m", "purpose": "draft", "cost": 0.001, "latency_ms": 10,
            "prompt": "p", "response": "r", "input_tokens": 1, "output_tokens": 1,
            "task_id": "t1",
        })


def _seed_usage(app, count: int):
    now = datetime.now(timezone.utc)
    for i in range(count):
        app.repo.append_usage({
            "id": f"usage-{i}", "created_at": (now - timedelta(days=i)).isoformat(timespec="milliseconds"),
            "provider": "deepseek", "model": "m", "purpose": "draft",
            "input_tokens": 10, "output_tokens": 5, "amount": 0.01,
        })


def test_usage_defaults_and_status_do_not_trim(app):
    _seed_calls(app, 120)
    status = app.usage_calls_status({})
    assert status["count"] == 120 and status["limit"] == 2000 and status["over_limit"] is False
    saved = app.settings_save({"usage": {"calls_retention": 100}})
    assert saved["settings"]["usage"]["calls_retention"] == 100
    # 只是普通设置保存：不裁剪，等用户主动保存用量设置
    assert app.repo.count_calls() == 120
    assert app.usage_calls_status({})["over_limit"] is True


def test_usage_settings_save_trims_only_calls_and_keeps_billing(app):
    _seed_calls(app, 120)
    _seed_usage(app, 3)
    before = app.usage_summary({})["totals"]
    res = app.usage_settings_save({"usage": {"calls_retention": 100, "calls_unlimited": False}})
    assert res["removed"]["calls"] == 20
    assert app.repo.count_calls() == 100
    assert app.usage_summary({})["totals"] == before
    assert app.usage_stats({})["totals"]["amount"] == pytest.approx(before["amount"])
    assert res["settings"]["usage"]["calls_retention"] == 100


def test_usage_unlimited_keeps_everything(app):
    _seed_calls(app, 130)
    res = app.usage_settings_save({"usage": {"calls_retention": 100, "calls_unlimited": True}})
    assert res["removed"]["calls"] == 0
    assert app.repo.count_calls() == 130
    assert app.usage_calls_status({})["unlimited"] is True


def test_usage_cleanup_by_days_keeps_usage_totals(app):
    _seed_calls(app, 120)
    _seed_usage(app, 5)
    before = app.usage_summary({})["totals"]
    res = app.usage_calls_cleanup({"days": 30})
    assert res["removed"] > 0
    assert app.repo.count_calls() == 120 - res["removed"]
    assert app.usage_summary({})["totals"] == before
    with pytest.raises(Exception):
        app.usage_calls_cleanup({"days": 7})


def test_usage_clear_history_keeps_billing_and_stats(app):
    _seed_calls(app, 40)
    _seed_usage(app, 4)
    before = app.usage_summary({})["totals"]
    stats_before = app.usage_stats({})["totals"]
    res = app.usage_calls_clear({})
    assert res["removed"] == 40
    assert app.repo.count_calls() == 0
    assert res["billing"]["totals"] == before
    assert app.usage_stats({})["totals"] == stats_before


def test_usage_stats_trend_and_offline_filter(app):
    _seed_usage(app, 3)
    app.repo.append_usage({
        "id": "fake-1", "created_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "provider": "fake", "model": "offline", "purpose": "draft",
        "input_tokens": 0, "output_tokens": 0, "amount": 0.0,
    })
    with_offline = app.usage_stats({})
    assert with_offline["totals"]["calls"] == 4
    assert len(with_offline["by_day"]) >= 1
    app.usage_settings_save({"usage": {"stats_include_offline": False}})
    without_offline = app.usage_stats({})
    assert without_offline["totals"]["calls"] == 3
    assert without_offline["include_offline"] is False


def test_usage_settings_validation(app):
    for bad in ({"calls_retention": 10}, {"calls_retention": "x"},
                {"calls_max_age_days": 7}):
        with pytest.raises(Exception):
            app.usage_settings_save({"usage": bad})


def test_contrast_cannot_be_bypassed_with_hsl_or_transparent(app):
    """hsl() 1:1 与 transparent 前景都必须被拒绝，不能因解析失败而跳过检查。"""
    same_hsl = {**FULL_DARK,
                "--text": "hsl(210 20% 18%)",
                "--surface": "hsl(210, 20%, 18%)",
                "--bg": "hsl(210deg 20% 18%)"}
    with pytest.raises(Exception) as exc:
        app.skin_import({"filename": "x.nxlskin", "data": _zip(
            {"skin.json": json.dumps(_manifest(mode="dark", vars=same_hsl))})})
    assert "对比度" in exc.value.message

    transparent = _manifest(mode="dark", vars={**FULL_DARK, "--text": "transparent"})
    with pytest.raises(Exception) as exc:
        app.skin_import({"filename": "y.nxlskin", "data": _zip(
            {"skin.json": json.dumps(transparent)})})
    assert "透明" in exc.value.message

    for bad in ("hsl(210, 20%)", "oklch(0.7 0.1 200)", "rgba(10, 20, 30, 0.5, 2)"):
        with pytest.raises(Exception):
            app.skin_import({"filename": "z.nxlskin", "data": _zip(
                {"skin.json": json.dumps(_manifest(vars={"--accent": bad}))})})


def test_partial_vars_are_merged_with_light_baseline(app):
    """复核用例：单键/部分变量也必须合并内置基线后检查全部组件配对。"""
    cases = [
        {"--text": "transparent"},
        {"--text": "rgba(0,0,0,0)"},
        {"--bg": "#0f141b", "--surface": "#0f141b"},
        {"--text": "#ffffff"},
        # 组件级配对：输入/按钮背景、代码块、提示条、状态徽标、主按钮悬停、当前导航项
        {"--surface-2": "#1b2430"},
        {"--code-bg": "#1b2430"},
        {"--toast-bg": "#ffffff"},
        {"--success-bg": "#1f7a4d"},   # 与浅色基线 success-fg 同色
        {"--warn-bg": "#8a6120"},
        {"--danger-bg": "#a3422f"},
        {"--risk-bg": "#a4443f"},
        {"--accent-hover": "#ffffff"},
        {"--accent-soft": "#1b2430"},
        # 语义文字与低置信度底色
        {"--negative": "#ffffff"},
        {"--danger-fg": "#ffffff"},
        {"--low-bg": "#1b2430"},
        # 第四轮复核：情绪底色、句子情感底色、页面渐变色
        {"--emotion-positive-bg": "#2f7a5c"},
        {"--emotion-urgent-bg": "#b06a2c"},
        {"--emotion-apology-bg": "#6b5b95"},
        {"--emotion-emphasis-bg": "#3b5c8f"},
        {"--emotion-humor-bg": "#3f7f8c"},
        {"--sent-pos-bg": "rgba(27, 36, 48, 0.95)"},
        {"--sent-neg-bg": "rgba(27, 36, 48, 0.95)"},
        {"--bg-tint": "#1b2430"},
    ]
    for index, vars_map in enumerate(cases):
        with pytest.raises(Exception):
            app.skin_import({"filename": f"partial-{index}.nxlskin", "data": _zip(
                {"skin.json": json.dumps(_manifest(id=f"partial-{index}", vars=vars_map))})})


def test_both_baselines_pass_and_dark_baseline_is_used():
    from laa_core.domain.skin.service import _check_contrast

    _check_contrast({}, "light")
    _check_contrast({}, "dark")
    # 深色基线配上浅色底：深色正文看不清，必须拒绝
    with pytest.raises(Exception):
        _check_contrast({"--bg": "#ffffff", "--surface": "#ffffff"}, "dark")


def test_valid_hsl_dark_palette_imports_and_transparent_non_text_allowed(app):
    palette = {**FULL_DARK,
               "--text": "hsl(210, 30%, 96%)",
               "--surface": "hsla(210, 30%, 12%, 0.95)",
               "--bg": "hsl(210deg 30% 8%)",
               "--text-secondary": "hsl(210 20% 80%)",
               "--text-muted": "hsl(210 15% 66%)",
               "--on-accent": "hsl(210 40% 8%)",
               "--accent": "hsl(210 70% 62%)",
               "--scrollbar-track": "transparent"}
    app.skin_import({"filename": "hsl.nxlskin", "data": _zip(
        {"skin.json": json.dumps(_manifest(id="hsl-night", mode="dark", vars=palette))})})
    view = app.skin_select({"id": "hsl-night"})
    assert view["mode"] == "dark"
    assert view["vars"]["--text"] == "hsl(210, 30%, 96%)"


def test_usage_cleanup_with_zero_days_never_deletes(app):
    _seed_calls(app, 10)
    before = app.repo.count_calls()
    res = app.usage_calls_cleanup({"days": 0})
    assert res["removed"] == 0 and res["days"] == 0 and res["cutoff"] is None
    assert app.repo.count_calls() == before
    # 不传 days 且配置为 0：同样不删
    res2 = app.usage_calls_cleanup({})
    assert res2["removed"] == 0 and app.repo.count_calls() == before


def test_startup_skin_mode_decodes_json_config(tmp_path, monkeypatch):
    """启动期直接读 SQLite：config.value 是 JSON 编码的字符串，必须解码后再识别深色。"""
    import sqlite3

    import desktop

    home = tmp_path / "home"
    data = home / ".laa"
    (data / "skins" / "night").mkdir(parents=True)
    con = sqlite3.connect(data / "laa.sqlite3")
    con.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    con.execute("INSERT INTO config VALUES (?, ?)", ("app.skin.active", json.dumps("night")))
    con.commit()
    con.close()
    (data / "skins" / "night" / "skin.json").write_text(
        json.dumps({"mode": "dark"}), encoding="utf-8")

    monkeypatch.setenv("NEXLING_HOME", str(home))
    assert desktop._skin_mode_from_disk() == "dark"


def test_save_dialog_forwards_base64_flag():
    """皮肤包导出按字节写入：file.save_dialog 必须把 base64_encoded 传到桌面层。"""
    from laa_core.bridge import desktop_native

    calls = []

    def fake(name, content, is_base64):
        calls.append((name, content, is_base64))
        return {"saved": True, "path": "x"}

    desktop_native.register_save_handler(fake)
    try:
        assert desktop_native.save_dialog("night.nxlskin", "QUJD", True)["saved"] is True
        assert calls[-1] == ("night.nxlskin", "QUJD", True)
        assert desktop_native.save_dialog("billing.json", "{}")["saved"] is True
        assert calls[-1][2] is False
    finally:
        desktop_native.register_save_handler(None)


def test_skin_service_constants_cover_v11_css():
    assert "--sent-pos-bg" in COLOR_KEYS
    assert "--confidence-low-fg" in COLOR_KEYS
    assert "--scrollbar-thumb" in COLOR_KEYS
    assert "--shadow-lg" in SHADOW_KEYS
    assert SkinService.__name__ == "SkinService"
