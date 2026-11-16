"""启动实测：双击 → 启动窗 / 主窗 / 可输入（首次冷启动与温启分开）。

用法（在 v5 根目录）：
    C:\\Python314\\python.exe tools\\measure_startup.py --runs 3
    C:\\Python314\\python.exe tools\\measure_startup.py --mode cold --runs 1

口径：
- 双击时刻 = 脚本调用 Popen 之前的墙钟（含进程创建开销，几十毫秒，各版本一致）。
- 启动窗 = launcher.log 里 "splash shown" 的绝对时间戳（毫秒）。
- 主窗   = startup.log 里 "main window shown" 的 epoch。
- 可输入 = startup.log 里 "input ready" 的 epoch。
冷启动用全新数据目录（含全新 WebView2 profile）；温启复用同一目录的第二次及以后。
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "dist" / "NexLing" / "NexLing.exe"
HOME = ROOT / ".measure_home"
LOGS = ("launcher.log", "startup.log")
# 行格式：`  6904.5 ms  epoch=1794711397.471  wall=10:56:37  input ready`
STARTUP_RE = re.compile(r"^\s*([\d.]+) ms\s+epoch=([\d.]+)\s+wall=\S+\s+(.+)$")


def _truncate_logs(home: Path) -> None:
    for name in LOGS:
        for path in (home / name, home / ".laa" / name):
            if path.exists():
                path.unlink()


def _read_epochs(home: Path) -> dict[str, float]:
    """返回里程碑 → 绝对 epoch（秒）。"""
    marks: dict[str, float] = {}
    launcher = home / ".laa" / "launcher.log"
    if launcher.exists():
        for line in launcher.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.split(" ", 1)
            if len(parts) != 2 or not parts[0].isdigit():
                continue
            epoch, msg = int(parts[0]) / 1000, parts[1].strip()
            if msg == "splash shown":
                marks["splash"] = epoch
    startup = home / ".laa" / "startup.log"
    if startup.exists():
        for line in startup.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = STARTUP_RE.match(line)
            if not m:
                continue
            epoch, msg = float(m.group(2)), m.group(3).strip()
            if msg.startswith("main window shown"):
                marks["window"] = epoch
            elif msg == "input ready":
                marks["input"] = epoch
    return marks


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
    """只杀本次启动的进程树，不碰用户自己开着的窗口。"""
    if pid > 0:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)


def run_once(home: Path) -> dict[str, float] | None:
    home.mkdir(parents=True, exist_ok=True)
    _truncate_logs(home)
    for flag in (".shown", ".ready"):
        (home / ".laa" / flag).unlink(missing_ok=True)

    env = {**os.environ, "NEXLING_HOME": str(home)}
    t0 = time.time()
    proc = subprocess.Popen([str(EXE)], env=env)
    deadline = t0 + 90
    try:
        while time.time() < deadline:
            if (home / ".laa" / ".ready").exists():
                break
            if proc.poll() is not None and proc.returncode not in (0, None):
                break
            time.sleep(0.02)
        time.sleep(0.3)  # 让日志落盘
    finally:
        app_pid = _read_app_pid(home)
        proc.terminate()
        _kill_tree(proc.pid)
        _kill_tree(app_pid)
        time.sleep(0.6)

    marks = _read_epochs(home)
    if "splash" not in marks or "window" not in marks or "input" not in marks:
        print(f"  缺少里程碑：{sorted(marks)}", file=sys.stderr)
        return None
    return {k: round((v - t0) * 1000) for k, v in marks.items()}


def summarise(label: str, rows: list[dict[str, float]]) -> None:
    if not rows:
        print(f"{label}: 无有效样本")
        return
    print(f"{label}（{len(rows)} 次）")
    for key, name in (("splash", "启动窗"), ("window", "主窗"), ("input", "可输入")):
        vals = [r[key] for r in rows]
        print(f"  {name:<4} 中位 {statistics.median(vals):.0f} ms   区间 {min(vals)}–{max(vals)} ms")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--mode", choices=("cold", "warm", "both"), default="both")
    ap.add_argument("--home", default=str(HOME))
    ap.add_argument("--fresh", action="store_true", help="忽略 --home，用临时目录")
    args = ap.parse_args()

    if not EXE.exists():
        print(f"找不到 {EXE}，先运行 tools/build_release.py", file=sys.stderr)
        return 2

    home = Path(args.home)
    results: dict[str, list[dict[str, float]]] = {"cold": [], "warm": []}
    if args.fresh:
        shutil.rmtree(home, ignore_errors=True)

    for i in range(args.runs):
        if args.mode in ("cold", "both"):
            shutil.rmtree(home, ignore_errors=True)
            row = run_once(home)
            if row:
                results["cold"].append(row)
                print(f"冷启动 #{i + 1}: {row}")
        if args.mode in ("warm", "both"):
            if not (home / ".laa").exists():
                run_once(home)  # 先跑一次把 profile 养热，不计入温启样本
            row = run_once(home)
            if row:
                results["warm"].append(row)
                print(f"温启 #{i + 1}: {row}")

    print()
    if results["cold"]:
        summarise("首次冷启动（全新数据目录与 WebView2 profile）", results["cold"])
    if results["warm"]:
        summarise("温启（复用数据目录与 profile）", results["warm"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
