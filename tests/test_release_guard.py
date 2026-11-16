"""发布包守卫：dist 目录里不得混入运行时数据、密钥、构建残留。

打包流程见 tools/build_release.py —— 组装完 dist\\NexLing 后会调用本文件，
守卫不通过则打包失败（避免手工测试遗漏）。
"""
from pathlib import Path

import pytest

DIST = Path(__file__).resolve().parent.parent / "dist" / "NexLing"
FORBIDDEN_DIRS = {".laa", "build", "__pycache__", ".pytest_cache", "node_modules"}
FORBIDDEN_FILES = {"secrets.json", "NexLing.lnk"}
FORBIDDEN_SUFFIXES = (".sqlite3", ".db", ".wal", ".shm", ".log", ".pyc")
pytestmark = pytest.mark.skipif(not DIST.exists(), reason="尚未打包")


def _scan() -> list[str]:
    found: list[str] = []
    for p in DIST.rglob("*"):
        rel = str(p.relative_to(DIST))
        if p.is_dir():
            if p.name in FORBIDDEN_DIRS:
                found.append(rel + "/")
            continue
        if p.name in FORBIDDEN_FILES or p.suffix.lower() in FORBIDDEN_SUFFIXES:
            found.append(rel)
    return found


def test_release_dir_has_no_runtime_or_build_artifacts():
    found = _scan()
    assert found == [], f"发布目录含不该发布的内容: {found}"


def test_release_logs_have_no_absolute_build_paths():
    import re

    build_root = str(Path(__file__).resolve().parent.parent)
    offenders = []
    for p in DIST.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in (".log", ".txt"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if build_root in text or re.search(r"[A-Za-z]:\\\\", text):
            offenders.append(str(p.relative_to(DIST)))
    assert offenders == [], f"发布包里含构建机绝对路径: {offenders}"


def test_release_has_launcher_app_and_frontend():
    assert (DIST / "NexLing.exe").exists()
    assert (DIST / "app" / "NexLingApp.exe").exists()
    assert (DIST / "app" / "_internal" / "webui" / "dist" / "index.html").exists()


def test_release_ships_sample_skin_packs_without_bundling_into_defaults():
    """示例皮肤包随交付目录提供；不得混进内置皮肤目录。"""
    src = Path(__file__).resolve().parent.parent / "skins"
    packs = sorted(src.glob("*.nxlskin"))
    if not packs:
        pytest.skip("源码目录没有示例皮肤包")
    for pack in packs:
        assert (DIST / "skins" / pack.name).is_file(), pack.name
    assert not (DIST / "app" / "_internal" / "skins").exists()


def test_release_frontend_never_carries_bridge_token():
    """token 只经原生桥下发：构建产物里不应再出现旧的 meta 注入标记。"""
    web_dist = DIST / "app" / "_internal" / "webui" / "dist"
    offenders = []
    for p in web_dist.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in (".html", ".js", ".css"):
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        if "nexling-token" in text:
            offenders.append(str(p.relative_to(DIST)))
    assert offenders == [], f"前端产物里仍有 token 标记: {offenders}"
