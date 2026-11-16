"""scene.ai 对话式场景助理的单元测试（离线 fake gateway，不联网）。"""
from laa_core.shared.errors import LaaError


def test_scene_ai_norm_bad_enum_falls_back(app):
    norm = app._norm_scene_ai_profile(
        {"name": "法务", "register": "weird", "descriptors": ["严谨"]},
        {"name": "旧", "description": "dd", "register": "informal", "mode_default": "literal",
         "descriptors": ["a"], "do": ["x"], "dont": ["y"], "labels": ["z"]},
    )
    assert norm["name"] == "法务"
    assert norm["register"] == "informal"  # 非法枚举回退现值
    assert norm["mode_default"] == "literal"  # 缺失保留现值
    assert norm["descriptors"] == ["严谨"]  # AI 给非空覆盖
    assert norm["do"] == ["x"]              # AI 未给保留现值
    assert norm["dont"] == ["y"]
    assert norm["labels"] == ["z"]


def test_scene_ai_norm_accepts_string_lines(app):
    norm = app._norm_scene_ai_profile(
        {"do": "保留术语\n保留编号", "dont": ""},
        {},
    )
    assert norm["do"] == ["保留术语", "保留编号"]
    assert norm["register"] == "semiformal"
    assert norm["mode_default"] == "fluent"


def test_scene_ai_empty_message_rejected(app):
    try:
        app.scene_ai({"message": "   "})
        raise AssertionError("应当抛出 LAA-1002")
    except LaaError as e:
        assert e.code == "LAA-1002"


def test_scene_ai_fake_shape(app):
    r = app.scene_ai({"message": "做一个法律合同场景", "scene_profile": {"name": "法务"}})
    assert isinstance(r, dict)
    assert "reply" in r
    assert "scene_profile" in r
    assert r["scene_profile"]["name"] == "法务"  # fake 无真实内容，回退现值