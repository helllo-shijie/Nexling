"""桌面程序入口：双击 → 立即开窗（内联启动页）→ 后台起本地服务 → 载入工作台。

性能目标：窗口先出现，后端按需初始化。启动里程碑写入 `<数据目录>/startup.log`，便于实测冷启动。
数据默认落盘到 `%LOCALAPPDATA%/NexLing`（旧版便携目录 `.laa` 首次启动自动迁移）。
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time

# 进程内最早的时间基准（模块导入即计时）
_T0 = time.perf_counter()

# 单实例锁句柄：必须持有到进程退出（局部变量会被回收，锁随之释放）
_INSTANCE_LOCK = None

# WebView2 使用持久化配置目录：避免每次启动重建临时 profile，同时保住界面本地设置
_PRIVATE_MODE = False


def _storage_path() -> str:
    path = os.path.join(_data_dir(), "webview")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return ""
    return path


def _error_page(message: str) -> str:
    """后端初始化失败时的兜底页面：把原因直接显示在窗口里，而不是静默卡住。"""
    import html as _html

    log_path = os.path.join(_data_dir(), "startup.log")
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>NexLing · 启动失败</title>
<style>
  html,body{{height:100%;margin:0;background:#f7f8fa;color:#1b2430;
    font-family:"Segoe UI","Microsoft YaHei",sans-serif}}
  .wrap{{max-width:640px;margin:0 auto;padding:64px 24px}}
  h1{{font-size:20px;font-weight:600;margin:0 0 6px}}
  p{{font-size:13px;color:#5b6675;line-height:1.7;margin:0 0 14px}}
  pre{{background:#fff;border:1px solid #e3e7ee;border-radius:8px;padding:12px 14px;
    font-size:12px;color:#8a3529;white-space:pre-wrap;word-break:break-all}}
  code{{font-size:12px;color:#3b5c8f}}
</style></head>
<body><div class="wrap">
  <h1>本地引擎未能启动</h1>
  <p>NexLing 的后端进程初始化失败，界面暂时不可用。下面是错误信息：</p>
  <pre>{_html.escape(message)}</pre>
  <p>完整启动日志：<code>{_html.escape(log_path)}</code><br>
     可先关闭本窗口，再重新双击 NexLing 重试；若持续失败，请把日志内容反馈给开发者。</p>
</div></body></html>"""


def _run_splash() -> int:
    """独立进程的启动窗：在 WebView2 初始化完成前立即给用户反馈。

    只依赖 tkinter（标准库），进程启动约 0.2s；检测到主窗口出现后自动关闭。
    """
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("NexLing 启动中")
    root.overrideredirect(True)
    root.configure(bg="#f7f8fa")
    w, h = 380, 200
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2 - 40}")
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass

    tk.Label(root, text="NexLing", bg="#f7f8fa", fg="#1b2430",
             font=("Segoe UI Semibold", 20)).pack(pady=(52, 2))
    tk.Label(root, text="技术翻译工作台", bg="#f7f8fa", fg="#7a8699",
             font=("Segoe UI", 10)).pack()
    bar = ttk.Progressbar(root, mode="indeterminate", length=160)
    bar.pack(pady=20)
    bar.start(12)
    tk.Label(root, text="正在启动本地引擎…", bg="#f7f8fa", fg="#9aa4b3",
             font=("Segoe UI", 9)).pack()

    import ctypes

    user32 = ctypes.windll.user32
    deadline = time.time() + 45

    def watch() -> None:
        if user32.FindWindowW(None, "NexLing 技术翻译工作台") or time.time() > deadline:
            root.destroy()
            return
        root.after(100, watch)

    root.after(100, watch)
    root.mainloop()
    return 0


def _spawn_splash() -> None:
    """开发态启动窗（tkinter）；发布包由原生启动器直接画窗，不再走这里。"""
    try:
        exe = sys.executable
        if not getattr(sys, "frozen", False):
            candidate = exe.replace("python.exe", "pythonw.exe")
            if os.path.isfile(candidate):
                exe = candidate
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        args = [exe, "--splash"] if getattr(sys, "frozen", False) else [
            exe, os.path.abspath(__file__), "--splash",
        ]
        subprocess.Popen(args, creationflags=flags, close_fds=True)
    except OSError:
        pass


def _legacy_data_dir() -> str:
    """旧版便携数据目录（<安装目录>\\.laa）：仅用于兼容读取，不再写入。"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
        if os.path.basename(base).lower() == "app":
            base = os.path.dirname(base)
        return os.path.join(base, ".laa")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), ".laa")


def _data_dir() -> str:
    """数据目录：默认 %LOCALAPPDATA%\\NexLing，与安装目录分离（避免包内落库）。

    兼容策略：旧 <安装目录>\\.laa 若存在，首次启动把数据库/密钥复制到新目录（只读旧目录，不删）；
    NEXLING_HOME 仍可显式覆盖（测试与便携场景）。
    """
    home = os.environ.get("NEXLING_HOME")
    if home:
        return os.path.join(home, ".laa")
    legacy = _legacy_data_dir()
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    current = os.path.join(base, "NexLing")
    if os.path.isdir(legacy) and not os.path.exists(os.path.join(current, "laa.sqlite3")):
        try:
            os.makedirs(current, exist_ok=True)
            for name in ("laa.sqlite3", "laa.sqlite3-wal", "laa.sqlite3-shm", "secrets.json"):
                src = os.path.join(legacy, name)
                dst = os.path.join(current, name)
                if os.path.isfile(src) and not os.path.exists(dst):
                    shutil.copy2(src, dst)
        except OSError:
            return legacy
    return current


def _ready_flag() -> str:
    return os.path.join(_data_dir(), ".ready")


def _shown_flag() -> str:
    """主窗已显示（骨架可见）：启动器据此收起启动窗，比「可输入」更早。"""
    return os.path.join(_data_dir(), ".shown")


def _touch_ready() -> None:
    try:
        os.makedirs(_data_dir(), exist_ok=True)
        with open(_ready_flag(), "w", encoding="utf-8") as fh:
            fh.write("ready\n")
    except OSError:
        pass


def _touch_shown() -> None:
    try:
        os.makedirs(_data_dir(), exist_ok=True)
        with open(_shown_flag(), "w", encoding="utf-8") as fh:
            fh.write("shown\n")
    except OSError:
        pass


def _log(message: str) -> None:
    """启动里程碑：相对耗时（毫秒）写入 <数据目录>/startup.log，供冷启动实测。

    日志只写相对时间与里程碑，不写构建机绝对路径。
    """
    try:
        os.makedirs(_data_dir(), exist_ok=True)
        line = (f"{(time.perf_counter() - _T0) * 1000:8.1f} ms  epoch={time.time():.3f}  "
                f"wall={time.strftime('%H:%M:%S')}  {message}\n")
        with open(os.path.join(_data_dir(), "startup.log"), "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass


def _last_save_dir_path() -> str:
    return os.path.join(_data_dir(), "last_save_dir.txt")


def _load_last_save_dir() -> str:
    """上次导出所用的目录；目录已不存在时回退空串（交给系统默认位置）。"""
    try:
        with open(_last_save_dir_path(), encoding="utf-8") as fh:
            path = fh.read().strip()
    except OSError:
        return ""
    return path if path and os.path.isdir(path) else ""


def _save_last_save_dir(path: str) -> None:
    if not path:
        return
    try:
        os.makedirs(_data_dir(), exist_ok=True)
        with open(_last_save_dir_path(), "w", encoding="utf-8") as fh:
            fh.write(path)
    except OSError:
        pass


def _export_file_types(name: str) -> tuple:
    """导出对话框的文件类型过滤：按 .json / .md / .txt 给出对应格式。"""
    ext = os.path.splitext(str(name or ""))[1].lower()
    return {
        ".json": ("JSON 文件 (*.json)", "所有文件 (*.*)"),
        ".md": ("Markdown 文件 (*.md)", "所有文件 (*.*)"),
        ".txt": ("文本文件 (*.txt)", "所有文件 (*.*)"),
        ".nxlskin": ("NexLing 皮肤包 (*.nxlskin)", "所有文件 (*.*)"),
    }.get(ext, ("所有文件 (*.*)",))


def _ensure_extension(target: str, name: str) -> str:
    """按导出格式校正扩展名。

    - 没写后缀：补上建议后缀；
    - 写了别的后缀（如导出 JSON 却填 a.txt）：改成正确后缀，避免内容与扩展名不符。
    """
    fmt_ext = os.path.splitext(str(name or ""))[1].lower()
    target = str(target or "")
    if not fmt_ext:
        return target
    current = os.path.splitext(target)[1].lower()
    if current == fmt_ext:
        return target
    base = target[: len(target) - len(current)] if current else target
    return base + fmt_ext


def _default_save_dir() -> str:
    """首次导出时的起始目录：优先用户「文档」，不存在则交给系统默认。"""
    home = os.path.expanduser("~")
    for name in ("Documents", "文档"):
        path = os.path.join(home, name)
        if os.path.isdir(path):
            return path
    return ""


def _skin_mode_from_disk() -> str:
    """启动时读取当前皮肤明暗，决定窗口底色与原生标题栏（避免深色皮肤下白色闪屏）。"""
    try:
        import json
        import sqlite3

        path = os.path.join(_data_dir(), "laa.sqlite3")
        if not os.path.isfile(path):
            return "light"
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
        try:
            row = con.execute("SELECT value FROM config WHERE key = ?", ("app.skin.active",)).fetchone()
        finally:
            con.close()
        raw = str((row or ("",))[0] or "")
        # config.value 由仓储层按 JSON 编码写入（字符串会带引号），这里必须解码后再用。
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            decoded = raw
        skin_id = str(decoded if isinstance(decoded, str) else raw).strip()
        if skin_id in ("default", "mint"):
            return "light"
        manifest_path = os.path.join(_data_dir(), "skins", skin_id, "skin.json")
        if os.path.isfile(manifest_path):
            with open(manifest_path, encoding="utf-8") as fh:
                return "dark" if (json.load(fh) or {}).get("mode") == "dark" else "light"
    except Exception:  # noqa: BLE001 - 读不到就按浅色处理
        pass
    return "light"


# 标题栏深色目标值：窗口句柄可能晚于后端初始化才创建，需要后台重试直到写成功。
_TITLEBAR = {"wanted": False, "thread": None, "applied": None}
_TITLEBAR_RETRY_SECONDS = 20.0


def _apply_titlebar_dark(enabled: bool) -> bool:
    """仅 Windows：让原生标题栏跟随深色皮肤（DWM 深浅色），浅色保持系统默认外观。

    不做自绘标题栏；返回是否真正写入成功（句柄未就绪 / 旧系统 / 非 Windows 返回 False）。
    """
    if os.name != "nt":
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, "NexLing 技术翻译工作台")
        if not hwnd:
            return False
        value = ctypes.c_int(1 if enabled else 0)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE（新/旧 build）
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
            if result == 0:
                return True
    except Exception:  # noqa: BLE001 - 标题栏跟随失败不影响功能
        return False
    return False


def _titlebar_retry() -> None:
    """句柄就绪前反复尝试；每次读当前目标值，避免切换皮肤后仍写旧值。"""
    deadline = time.time() + _TITLEBAR_RETRY_SECONDS
    while time.time() < deadline:
        wanted = bool(_TITLEBAR["wanted"])
        if _apply_titlebar_dark(wanted):
            _TITLEBAR["applied"] = wanted
            return
        time.sleep(0.15)
    _log(f"titlebar dark apply failed after {_TITLEBAR_RETRY_SECONDS:.0f}s "
         f"(enabled={_TITLEBAR['wanted']})")


def _set_titlebar_dark(enabled: bool) -> None:
    """立即尝试应用，失败则起后台重试线程（等窗口/句柄创建后再写 DWM 属性）。"""
    enabled = bool(enabled)
    _TITLEBAR["wanted"] = enabled
    if _apply_titlebar_dark(enabled):
        _TITLEBAR["applied"] = enabled
        return
    thread = _TITLEBAR["thread"]
    if thread is None or not thread.is_alive():
        thread = threading.Thread(target=_titlebar_retry, daemon=True)
        _TITLEBAR["thread"] = thread
        thread.start()


def _free_port(preferred: int = 8787) -> int:
    for port in (preferred, *range(12000, 12100)):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            s.close()
            return port
        except OSError:
            s.close()
    raise RuntimeError("no free local port")


def _find_static_dir() -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(base, "webui", "dist"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "webui", "dist"),
    ]
    for c in candidates:
        if os.path.isdir(os.path.join(c, "assets")) or os.path.isfile(os.path.join(c, "index.html")):
            return c
    return ""


def _control_path() -> str:
    return os.path.join(_data_dir(), ".control")


def _clear_control() -> None:
    try:
        os.remove(_control_path())
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    """控制文件里的 PID 是否仍存活；用于跳过异常退出留下的陈旧端口。"""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_control() -> tuple:
    """读 `.control`：格式为 "port pid"（旧版只有 port）。"""
    try:
        with open(_control_path(), encoding="utf-8") as fh:
            parts = (fh.read() or "").split()
    except OSError:
        return 0, 0
    port = pid = 0
    if parts:
        try:
            port = int(parts[0])
        except ValueError:
            port = 0
    if len(parts) > 1:
        try:
            pid = int(parts[1])
        except ValueError:
            pid = 0
    return port, pid


def _activate_existing(allow_cleanup: bool = True) -> bool:
    """已有实例在跑：把激活请求发过去并返回 True（本次不再开新窗口）。

    存活判断不靠连接超时：是否已有实例由独占锁（命名互斥体/锁文件）决定，
    这里只负责把窗口唤到前面。``allow_cleanup`` 仅在确认自己已持有实例锁时为真——
    否则删除控制文件会让两个实例同时启动并共用同一个 SQLite。
    """
    port, pid = _read_control()
    if pid and not _pid_alive(pid):
        if allow_cleanup:
            _log("stale .control (pid gone) removed")
            _clear_control()
        return False
    if port <= 0:
        if allow_cleanup:
            _clear_control()
        return False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4) as sock:
            sock.sendall(b"activate\n")
            sock.settimeout(0.4)
            reply = sock.recv(64)
        if reply.startswith(b"NEXLING"):
            return True
        if allow_cleanup:
            _clear_control()
        return False
    except OSError:
        if allow_cleanup:
            _log("stale .control (connect failed) removed")
            _clear_control()
        return False


def _instance_lock_name() -> str:
    """按数据目录生成互斥体名：不同 NEXLING_HOME 的实例互不影响。"""
    import hashlib

    key = hashlib.sha1(os.path.abspath(_data_dir()).lower().encode("utf-8")).hexdigest()[:12]
    return f"Local\\NexLing.{key}"


def _acquire_instance_lock() -> bool:
    """独占实例锁：True=本次是唯一实例（锁持有到进程退出），False=已有实例在跑。

    不依赖任何超时推断存活：Windows 用命名互斥体（句柄随进程销毁），
    其它平台用 O_EXCL 锁文件 + PID 校验。返回 False 时调用方只能激活已有实例
    然后退出，绝不能再清控制文件或另起一个后端（否则两个实例共用一个 SQLite）。
    """
    global _INSTANCE_LOCK
    if _INSTANCE_LOCK is not None:
        return True
    os.makedirs(_data_dir(), exist_ok=True)
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        handle = kernel32.CreateMutexW(None, wintypes.BOOL(True), _instance_lock_name())
        if not handle:
            _log("instance mutex create failed")
            return False
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False
        _INSTANCE_LOCK = handle
        return True
    lock_path = os.path.join(_data_dir(), ".instance.lock")
    for attempt in range(2):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            # 锁文件存在：PID 已不在（上次异常退出）时清掉重试一次，否则视为已有实例
            try:
                with open(lock_path, encoding="ascii") as fh:
                    pid = int((fh.read() or "0").strip() or 0)
            except (OSError, ValueError):
                pid = 0
            if attempt == 0 and not _pid_alive(pid):
                try:
                    os.remove(lock_path)
                except OSError:
                    return False
                continue
            return False
        except OSError:
            return False
        try:
            os.write(fd, str(os.getpid()).encode("ascii"))
        except OSError:
            pass
        _INSTANCE_LOCK = fd
        return True
    return False


def _start_control_server(on_activate) -> socket.socket | None:
    """单实例唤醒通道：端口写入 <数据目录>/.control，退出时删除。"""
    try:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(4)
        os.makedirs(_data_dir(), exist_ok=True)
        with open(_control_path(), "w", encoding="utf-8") as fh:
            # 端口 + 当前 PID：下次启动可先判断进程是否还在，直接跳过陈旧端口
            fh.write(f"{srv.getsockname()[1]} {os.getpid()}")
    except OSError as exc:
        _log(f"control server failed: {exc!r}")
        return None

    def loop() -> None:
        while True:
            try:
                conn, _addr = srv.accept()
            except OSError:
                return
            try:
                data = conn.recv(64)
                if data.startswith(b"activate"):
                    conn.sendall(b"NEXLING 1.11.0\n")
                    on_activate()
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    threading.Thread(target=loop, daemon=True).start()
    return srv


def main() -> int:
    if "--splash" in sys.argv:
        return _run_splash()

    # 先起启动窗（独立进程），再加载 WebView：窗口出现不受后端与 WebView2 初始化影响
    # 由原生启动器拉起时，启动窗已由启动器绘制，这里不再重复弹窗
    _log("module start")
    # 单实例：先抢独占锁。抢到才允许清理陈旧控制文件、启动后端；
    # 抢不到说明已有实例活着，只能激活它后退出，绝不因一次连接超时就清控制文件。
    if not _acquire_instance_lock():
        for _ in range(12):
            if _activate_existing(allow_cleanup=False):
                _log("activated existing instance")
                return 0
            time.sleep(0.25)
        _log("instance lock held by another process but not reachable")
        return 0
    if _activate_existing():
        # 升级场景：旧版本实例仍在跑（没有互斥体），把窗口唤到前面后退出
        _log("activated legacy instance")
        return 0
    if os.environ.get("NEXLING_LAUNCHED") != "1" and not getattr(sys, "frozen", False):
        _spawn_splash()
    _log("splash spawned")

    import webview

    # 本机自动化验收用：设置 NEXLING_DEBUG_PORT 才打开 WebView2 调试端口，默认关闭。
    debug_port = os.environ.get("NEXLING_DEBUG_PORT")
    if debug_port:
        try:
            webview.settings["REMOTE_DEBUGGING_PORT"] = int(debug_port)
            _log(f"remote debugging enabled: {debug_port}")
        except (TypeError, ValueError):
            pass

    _log("webview imported")

    host = "127.0.0.1"
    port = _free_port()
    url = f"http://{host}:{port}/"

    try:
        os.remove(_ready_flag())
    except OSError:
        pass
    try:
        os.remove(_shown_flag())
    except OSError:
        pass

    # 本地桥一次性 token：只经 pywebview 原生桥（js_api）交给页面，
    # 不写入 HTTP 响应/页面源码，其它本地进程从 GET / 或静态资源里读不到。
    import secrets

    bridge_token = secrets.token_urlsafe(32)

    class _BridgeApi:
        """暴露给页面的原生桥。除 token 外不提供其它能力。"""

        def get_bridge_token(self) -> str:
            return bridge_token

    # 窗口先建但保持隐藏：骨架一画出来就显示主窗（可输入略晚于此，两者分开计量）。
    # 期间由原生启动器（或 dev 下的 tkinter 启动窗）提供品牌反馈，避免白屏。
    window = webview.create_window(
        "NexLing 技术翻译工作台",
        url=url,
        width=1120, height=780, min_size=(920, 620),
        background_color="#12161c" if _skin_mode_from_disk() == "dark" else "#f7f8fa",
        confirm_close=True,
        hidden=True,
        js_api=_BridgeApi(),
    )
    _log("window created")

    revealed = threading.Event()
    reveal_lock = threading.Lock()

    def reveal(reason: str, error_html: str | None = None) -> None:
        """显示主窗口并通知启动器关闭启动窗（幂等）。"""
        with reveal_lock:
            if revealed.is_set():
                return
            revealed.set()
            if error_html is not None:
                try:
                    window.load_html(error_html)
                except Exception as exc:  # noqa: BLE001
                    _log(f"error page failed: {exc!r}")
            try:
                window.show()
            except Exception as exc:  # noqa: BLE001
                _log(f"window show failed: {exc!r}")
            # 隐藏窗口上写 DWM 属性可能被系统丢弃：显示后再写一次，确保深色标题栏生效。
            _set_titlebar_dark(bool(_TITLEBAR["wanted"]))
            _touch_shown()
            _log(f"main window shown ({reason})")

    def on_mark(name: str) -> None:
        _log(name)
        # 骨架（index.html 内联样式）解析完成即可显示主窗；「可输入」另外立里程碑，
        # 让启动器在骨架可见时收起启动窗，而不是等到 React 全部就绪。
        if name.endswith("html_parsed"):
            reveal("skeleton ready")
        elif "workbench_input_ready" in name:
            _touch_ready()
            _log("input ready")

    def _ev(name: str):
        def _handler(*_args, **_kwargs):
            _log(f"event: {name}")
            if name == "loaded":
                # 兜底：页面加载完成而前端里程碑没到（例如脚本异常），也把骨架露出来
                reveal("page loaded")
        return _handler

    try:
        window.events.shown += _ev("shown")
        window.events.loaded += _ev("loaded")
    except (AttributeError, TypeError):
        pass

    def activate_window() -> None:
        """第二次双击：把已有窗口唤到前面（不新开窗口）。"""
        _log("activate requested")
        reveal("second launch")
        try:
            window.restore()
        except Exception:  # noqa: BLE001
            pass
        try:
            window.show()
        except Exception:  # noqa: BLE001
            pass

    control = _start_control_server(activate_window)

    state = {"server": None, "error": None}
    ready = threading.Event()

    def prepare() -> None:
        """与 WebView2 初始化并行：后端在独立线程里先建好，窗口就绪后直接加载工作台。"""
        try:
            from laa_core.app.bootstrap import Bootstrap
            from laa_core.bridge.http_server import serve
            from laa_core.bridge.desktop_native import register_save_handler

            static_dir = _find_static_dir() or None
            app = Bootstrap(data_dir=_data_dir()).build()
            _log("backend initialized (background)")
            # 深色皮肤下原生标题栏跟随变深；切换皮肤时即时更新（浅色恢复系统默认）
            try:
                app.skin.on_mode_change = lambda mode: _set_titlebar_dark(mode == "dark")
                _set_titlebar_dark(app.skin.active_mode() == "dark")
            except Exception:  # noqa: BLE001 - 标题栏属增强项
                pass

            server = serve(app, host=host, port=port, static_dir=static_dir, on_mark=on_mark,
                           token=bridge_token)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            state["server"] = server
            _log("http server ready (background)")

            def _save_handler(suggested_name: str, content: str, is_base64: bool = False) -> dict:
                """导出：系统保存对话框选目录+文件名，并记住上次目录。

                路径由用户在对话框里决定，前端不再固定写入位置；取消/写失败都如实回传。
                皮肤包等二进制导出走 base64，按字节写入。
                """
                name = os.path.basename(str(suggested_name or "export.json"))
                last_dir = _load_last_save_dir() or _default_save_dir()
                try:
                    paths = window.create_file_dialog(
                        webview.FileDialog.SAVE,
                        directory=last_dir or "",
                        save_filename=name,
                        file_types=_export_file_types(name),
                    )
                except Exception as exc:  # noqa: BLE001 - 对话框失败不能把后端线程带走
                    return {"saved": False, "error": str(exc)}
                if not paths:
                    return {"saved": False, "cancelled": True}
                target = str(paths[0]) if isinstance(paths, (list, tuple)) else str(paths)
                target = _ensure_extension(target, name)
                try:
                    if is_base64:
                        import base64

                        with open(target, "wb") as fh:
                            fh.write(base64.b64decode(content))
                    else:
                        with open(target, "w", encoding="utf-8", newline="\n") as fh:
                            fh.write(content if isinstance(content, str) else str(content))
                except (OSError, ValueError) as exc:
                    return {"saved": False, "error": str(exc)}
                _save_last_save_dir(os.path.dirname(target))
                return {"saved": True, "path": target}

            register_save_handler(_save_handler)
        except Exception as exc:  # noqa: BLE001 - 记录后由 boot 兜底
            state["error"] = exc
            _log(f"backend init failed: {exc!r}")
        finally:
            ready.set()

    # WebView2 初始化（通常最慢的一段）与后端初始化并行
    threading.Thread(target=prepare, daemon=True).start()
    _log("backend init thread started")

    def boot() -> None:
        """GUI 事件循环已就绪：后端失败给错误页，页面报里程碑后显示窗口。"""
        _log("gui loop ready")
        try:
            ready.wait(timeout=30)
            if state["error"] is not None:
                _log(f"boot aborted: {state['error']!r}")
                reveal("backend error", _error_page(repr(state["error"])))
                return
            if not revealed.wait(timeout=20):
                _log("reveal timeout, showing window anyway")
                reveal("timeout")
        except Exception as exc:  # noqa: BLE001 - boot 自身异常也必须留下痕迹
            _log(f"boot crashed: {exc!r}")

    _log("start() called")
    try:
        webview.start(boot, private_mode=_PRIVATE_MODE, storage_path=_storage_path())
    except Exception as exc:  # noqa: BLE001 - 启动失败必须留痕，而不是静默退出
        import traceback

        _log(f"start() crashed: {exc!r}\n{traceback.format_exc()}")
        raise
    finally:
        _log("start() returned")
        if control is not None:
            try:
                control.close()
            except OSError:
                pass
        try:
            os.remove(_control_path())
        except OSError:
            pass
    server = state.get("server")
    if server is not None:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
