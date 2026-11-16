"""一键打包发布目录（V4 起接入发布守卫）。

流程：PyInstaller 构建 → 组装 dist\\NexLing（原生启动器 + app）→ 清理运行时残留
→ 调用 tests/test_release_guard.py 校验。守卫失败则整个打包失败（不会留下"看起来能发"的包）。

用法：C:\\Python314\\python.exe tools\\build_release.py
前置：webui 已 `npm run build`。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
OUT = DIST / "NexLing"
APP = OUT / "app"
FORBIDDEN_SUFFIXES = {".sqlite3", ".db", ".wal", ".shm", ".log", ".pyc"}
FORBIDDEN_NAMES = {"secrets.json", "NexLing.lnk"}


def run(cmd: list[str], cwd: Path = ROOT) -> None:
    print(">", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd), check=True)


def clean_runtime(root: Path) -> list[str]:
    """清掉启动/调试期间生成的运行时数据，保证包体可分发。"""
    removed: list[str] = []
    if not root.exists():
        return removed
    for path in list(root.rglob("*")):
        if path.is_dir() and path.name in {".laa", "__pycache__", ".pytest_cache"}:
            shutil.rmtree(path, ignore_errors=True)
            removed.append(f"{path.relative_to(root)}/")
        elif path.is_file() and (path.name in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES):
            path.unlink(missing_ok=True)
            removed.append(str(path.relative_to(root)))
    return removed


def trim_internal(root: Path) -> list[str]:
    """裁掉运行时用不到的多架构/文档文件，减少首扫文件数与包体。

    注意：pywebview 会遍历 win-arm64 / win-x64 / win-x86 三个 runtimes 目录拼 Path，
    目录缺失会让它拿到 None 直接抛错——所以只删 DLL，保留空目录。
    """
    removed: list[str] = []
    internal = root / "app" / "_internal"
    drop_files = [
        internal / "webview" / "lib" / "runtimes" / "win-arm64" / "native" / "WebView2Loader.dll",
        internal / "webview" / "lib" / "runtimes" / "win-x86" / "native" / "WebView2Loader.dll",
        internal / "pythonnet" / "runtime" / "Python.Runtime.xml",
    ]
    for f in drop_files:
        if f.is_file():
            f.unlink(missing_ok=True)
            removed.append(str(f.relative_to(root)))
    return removed


def copy_sample_skins(root: Path) -> list[str]:
    """把随交付目录提供的示例皮肤包放到 exe 同级 skins/（不内置进默认列表）。"""
    src = ROOT / "skins"
    if not src.is_dir():
        return []
    dest = root / "skins"
    dest.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for pack in sorted(src.glob("*.nxlskin")):
        shutil.copy2(pack, dest / pack.name)
        copied.append(pack.name)
    return copied


def _app_alive() -> bool:
    """真实应用进程是否还在跑（启动器 NexLing.exe 会在主窗出现后立刻退出）。"""
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq NexLingApp.exe", "/NH"],
        capture_output=True,
        text=True,
        errors="ignore",
    )
    return "NexLingApp.exe" in (out.stdout or "")


def _read_app_pid(home) -> int:
    """从 <home>/.laa/.control 读本次启动的应用 PID（格式 "port pid"）。"""
    try:
        parts = (home / ".laa" / ".control").read_text(encoding="utf-8").split()
    except OSError:
        return 0
    try:
        return int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        return 0


def _kill_tree(pid: int) -> None:
    """只杀本次启动的进程树；不做全局 taskkill，避免误杀用户自己开的窗口。"""
    if pid > 0:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)


def smoke_launch(timeout: float = 90.0) -> bool:
    """在临时副本里真实启动一次，确认能走到「可输入」（写 .ready）——防止打包漏依赖。

    结束后只清理本次启动的进程树（PID 来自 .control），不按映像名全局杀，
    否则会连带杀掉用户自己开着的 NexLing / WebView2 窗口。
    """
    import os
    import time

    tmp = ROOT / ".smoke_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    home = tmp / "home"
    home.mkdir(parents=True)
    pkg = tmp / "pkg"
    shutil.copytree(OUT, pkg)
    env = {**os.environ, "NEXLING_HOME": str(home)}
    proc = subprocess.Popen([str(pkg / "NexLing.exe")], env=env)
    ready = home / ".laa" / ".ready"
    started = time.time()
    ok = False
    tail = ""
    try:
        deadline = started + timeout
        while time.time() < deadline:
            if ready.exists():
                ok = True
                print(f"启动自检通过：{time.time() - started:.1f}s 内进入可输入状态")
                break
            # 启动器 NexLing.exe 在 .shown 后即退出，不能拿它的退出当失败信号；
            # 这里以真正的应用进程 NexLingApp.exe 是否存活作为提前终止依据。
            # 前 20s 不给终止判断：拉起瞬间 tasklist 可能还没看到新进程。
            if time.time() - started > 20 and not _app_alive():
                break
            time.sleep(0.25)
    finally:
        log = home / ".laa" / "startup.log"
        if log.exists():
            tail = "\n".join(log.read_text(encoding="utf-8", errors="ignore").splitlines()[-8:])
        proc.terminate()
        _kill_tree(proc.pid)
        _kill_tree(_read_app_pid(home))
        time.sleep(2)
        shutil.rmtree(tmp, ignore_errors=True)
    if not ok:
        if tail:
            print("启动日志尾部：\n" + tail)
        print("启动自检失败：未在超时内进入可输入状态", file=sys.stderr)
    return ok


def main() -> int:
    if not (ROOT / "webui" / "dist" / "index.html").exists():
        print("缺少 webui/dist，先运行 npm run build", file=sys.stderr)
        return 2

    run([sys.executable, "-m", "PyInstaller", "NexLing.spec", "--noconfirm", "--clean"])

    built = DIST / "app"
    if not built.exists():
        print("PyInstaller 未产出 dist/app", file=sys.stderr)
        return 3
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    shutil.move(str(built), str(APP))

    run([
        "gcc", "-O2", "-municode", "-mwindows", "-o", str(OUT / "NexLing.exe"),
        str(ROOT / "tools" / "launcher.c"), "-lgdi32", "-luser32",
    ])

    removed = clean_runtime(OUT)
    if removed:
        print("已清理运行时残留：", ", ".join(removed[:10]), "…" if len(removed) > 10 else "")
    trimmed = trim_internal(OUT)
    if trimmed:
        print("已裁剪多余架构文件：", ", ".join(trimmed))
    samples = copy_sample_skins(OUT)
    if samples:
        print("已放入示例皮肤包：", ", ".join(samples))

    guard = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_release_guard.py", "-q"],
        cwd=str(ROOT),
    )
    if guard.returncode != 0:
        print("发布守卫未通过，打包失败", file=sys.stderr)
        return 4

    files = [p for p in OUT.rglob("*") if p.is_file()]
    size = sum(p.stat().st_size for p in files)
    print(f"完成：{OUT}  文件 {len(files)} 个，{size / 1024 / 1024:.1f} MiB")
    return 0 if smoke_launch() else 5


if __name__ == "__main__":
    raise SystemExit(main())
