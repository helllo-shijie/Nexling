"""临时副本真实启动自检：确认窗口可输入，且页面已通过原生桥拿到 token。

只读启动日志里的里程碑，不修改发布包；结束后清理临时目录与残余进程。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dist" / "NexLing"


def _read_app_pid(home: Path) -> int:
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


def main() -> int:
    tmp = ROOT / ".tmp_launch_check"
    shutil.rmtree(tmp, ignore_errors=True)
    home = tmp / "home"
    home.mkdir(parents=True)
    pkg = tmp / "pkg"
    shutil.copytree(OUT, pkg)
    env = {**os.environ, "NEXLING_HOME": str(home)}
    started = time.time()
    proc = subprocess.Popen([str(pkg / "NexLing.exe")], env=env)
    ready = home / ".laa" / ".ready"
    try:
        while time.time() - started < 90:
            if ready.exists():
                break
            time.sleep(0.25)
        time.sleep(1.0)
        log = (home / ".laa" / "startup.log").read_text(encoding="utf-8", errors="ignore")
        marks = [line.strip() for line in log.splitlines() if line.strip()]
        ok_ready = ready.exists()
        ok_bridge = "bridge_ready" in log
        print(f"可输入: {ok_ready}  原生桥 token 握手: {ok_bridge}  用时 {time.time() - started:.1f}s")
        print("日志尾部：")
        print("\n".join(marks[-8:]))
        return 0 if ok_ready and ok_bridge else 1
    finally:
        app_pid = _read_app_pid(home)
        proc.terminate()
        _kill_tree(proc.pid)
        _kill_tree(app_pid)
        time.sleep(2)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
