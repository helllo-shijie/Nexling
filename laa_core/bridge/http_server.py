"""Stdlib HTTP bridge: POST /api/invoke, GET /api/events, GET /health, static files."""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from ..shared import err, new_id
from .command import CommandRouter, err_response

# 请求体上限：正常翻译文本上限 200,000 字符，16 MiB 足够覆盖媒体引用与批量命令
MAX_BODY_BYTES = 16 * 1024 * 1024
# 拒绝请求时读取请求体的超时：慢连接不能无限占住处理线程
DRAIN_TIMEOUT_SECONDS = 3.0

_MIME = {
    ".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
    ".woff2": "font/woff2", ".map": "application/json",
}


def make_handler(app, router: CommandRouter, static_dir: Optional[str] = None, on_mark=None,
                 token: str = ""):
    """本地桥：只服务 127.0.0.1 上的同源页面。

    安全边界：
    - 带 Origin 的请求必须与自身监听地址完全一致（本机任意网页不能跨源调用）；
    - 业务接口要求页面携带启动时生成的一次性 token（防止其它本地进程盲调）。
      token 只经 pywebview 原生桥（js_api）下发给页面，绝不出现在任何 HTTP 响应里，
      所以 `GET /`、静态资源、index.html 源码都读不到它；
    - CORS 不再返回 ``*``，只对允许的 Origin 回显。
    """
    class Handler(BaseHTTPRequestHandler):
        server_version = "NexLing/1.0"

        def _request_origin(self) -> str:
            return (self.headers.get("Origin") or "").strip()

        def _allowed_origins(self) -> set:
            try:
                port = int(self.server.server_address[1])
            except (AttributeError, IndexError, TypeError, ValueError):
                return set()
            return {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

        def _origin_ok(self) -> bool:
            origin = self._request_origin()
            return not origin or origin in self._allowed_origins()

        def _token_ok(self) -> bool:
            # 空 token 一律拒绝（失败关闭）：服务端始终应有一个启动时生成的 token
            if not token:
                return False
            return (self.headers.get("X-NexLing-Token") or "") == token

        def _content_length(self) -> int:
            try:
                return max(0, int(self.headers.get("Content-Length") or 0))
            except (TypeError, ValueError):
                return 0

        def _drain_body(self) -> None:
            """拒绝请求前把请求体读空，避免客户端还在写就被 RST（Windows 10053）。

            读取设超时：慢连接/半开连接不能无限占住工作线程。
            """
            remaining = self._content_length()
            if remaining <= 0:
                return
            if remaining > MAX_BODY_BYTES:
                # 超限请求不读，直接声明关闭连接，避免为坏请求分配大缓冲
                self.close_connection = True
                return
            try:
                self.connection.settimeout(DRAIN_TIMEOUT_SECONDS)
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 65536))
                    if not chunk:
                        break
                    remaining -= len(chunk)
            except (OSError, ValueError):
                self.close_connection = True
            finally:
                try:
                    self.connection.settimeout(None)
                except OSError:
                    pass

        def _reject(self, code: int, body: Any) -> None:
            self._drain_body()
            self._json(code, body)

        def _guard(self) -> bool:
            """跨源/无 token 的调用一律拒绝；返回 False 时响应已发出。"""
            if not self._origin_ok():
                self._reject(403, err_response(err("LAA-1001", message="origin not allowed")))
                return False
            if not self._token_ok():
                self._reject(403, err_response(err("LAA-1001", message="invalid bridge token")))
                return False
            return True

        def _cors(self) -> None:
            origin = self._request_origin()
            if origin and self._origin_ok():
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-NexLing-Token")

        def _json(self, code: int, body: Any) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self._cors()
            self.end_headers()
            try:
                self.wfile.write(data)
            except OSError:
                # 客户端已断开（例如拒绝慢连接后）：响应写不出去无需再抛
                self.close_connection = True

        def do_OPTIONS(self) -> None:  # noqa: N802
            if not self._origin_ok():
                self.send_response(403)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            if not self._origin_ok():
                self._reject(403, err_response(err("LAA-1001", message="origin not allowed")))
                return
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._json(200, {"ok": True, "status": "up"})
                return
            if parsed.path == "/api/events":
                if not self._guard():
                    return
                qs = parse_qs(parsed.query)
                task_id = (qs.get("task_id") or [""])[0]
                from_seq = int((qs.get("from_seq") or ["0"])[0])
                try:
                    data = app.events(task_id, from_seq)
                    self._json(200, data)
                except BaseException as e:  # noqa: BLE001
                    self._json(200, err_response(e))
                return
            if parsed.path == "/__mark":
                # 启动里程碑：只写一行日志、不返回业务数据，但仍要求 token——
                # 否则本机任意进程都能伪造启动日志（日志注入）。
                if not self._token_ok():
                    self._reject(403, err_response(err("LAA-1001", message="invalid bridge token")))
                    return
                qs = parse_qs(parsed.query)
                raw_name = (qs.get("name") or [""])[0]
                # 只保留可打印字符并截断，避免换行/控制字符注入 startup.log
                name = "".join(ch for ch in raw_name if ch.isprintable())[:80]
                if name and on_mark is not None:
                    try:
                        on_mark(f"frontend: {name}")
                    except Exception:  # noqa: BLE001 - 里程碑失败不影响业务
                        pass
                self._json(200, {"ok": True})
                return
            if static_dir:
                if parsed.path in ("/", "/index.html"):
                    self._serve_file(os.path.join(static_dir, "index.html"))
                    return
                self._serve_static(parsed.path)
                return
            self._json(404, err_response(err("LAA-1001", message="not found")))

        def do_POST(self) -> None:  # noqa: N802
            if not self._origin_ok():
                self._reject(403, err_response(err("LAA-1001", message="origin not allowed")))
                return
            parsed = urlparse(self.path)
            if parsed.path != "/api/invoke":
                self._reject(404, err_response(err("LAA-1001", message="not found")))
                return
            if not self._guard():
                return
            length = self._content_length()
            if length > MAX_BODY_BYTES:
                self.close_connection = True
                self._json(413, err_response(err("LAA-1002", message="请求体超过上限")))
                return
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                self._json(400, err_response(err("LAA-1002", message="非法 JSON")))
                return
            cmd = body.get("cmd", "")
            payload = body.get("payload", {}) or {}
            trace_id = body.get("trace_id") or body.get("request_id") or new_id()
            try:
                data = router.dispatch(cmd, payload, trace_id)
                self._json(200, {"ok": True, "data": data, "trace_id": trace_id})
            except BaseException as e:  # noqa: BLE001
                self._json(200, {"ok": False, "error": err_response(e)["error"], "trace_id": trace_id})

        def _serve_static(self, path: str) -> None:
            rel = path.lstrip("/") or "index.html"
            root = os.path.abspath(static_dir)
            fp = os.path.normpath(os.path.join(root, rel))
            # commonpath 而非 startswith：避免同前缀兄弟目录被读取
            try:
                inside = os.path.commonpath([os.path.abspath(fp), root]) == root
            except ValueError:
                inside = False
            if not inside:
                self._json(403, err_response(err("LAA-1001", message="forbidden")))
                return
            if os.path.isdir(fp):
                fp = os.path.join(fp, "index.html")
            self._serve_file(fp)

        def _serve_file(self, fp: str) -> None:
            if not os.path.isfile(fp):
                self._json(404, err_response(err("LAA-1001", message="not found")))
                return
            ext = os.path.splitext(fp)[1]
            ctype = _MIME.get(ext, "application/octet-stream")
            with open(fp, "rb") as fh:
                data = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self._cors()
            if os.path.basename(fp).lower() == "index.html":
                self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):  # silence default logging
            pass

    return Handler


def serve(app, host: str = "127.0.0.1", port: int = 8787, static_dir: Optional[str] = None,
          on_mark=None, token: str = "") -> ThreadingHTTPServer:
    """启动本地桥。

    ``token`` 为空时自动生成随机 token 并挂在 ``server.bridge_token`` 上：
    HTTP 层永远失败关闭，调用方（桌面原生桥 / CLI 终端）负责把 token 交给使用者。
    """
    if not token:
        import secrets

        token = secrets.token_urlsafe(32)
    router = CommandRouter(app)
    handler = make_handler(app, router, static_dir, on_mark, token)
    server = ThreadingHTTPServer((host, port), handler)
    server.bridge_token = token
    return server