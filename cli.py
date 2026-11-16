"""NexLing command-line interface (serve / translate / seed)."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from laa_core.app.bootstrap import Bootstrap  # noqa: E402
from laa_core.bridge.http_server import serve  # noqa: E402
from laa_core.shared.types import TaskStatus  # noqa: E402

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _is_loopback(host: str) -> bool:
    return (host or "").strip().lower() in LOOPBACK_HOSTS


def _build(args) -> "Application":
    return Bootstrap(data_dir=args.data, use_memory=args.memory).build()


def cmd_serve(args) -> int:
    host = (args.host or "127.0.0.1").strip()
    if not _is_loopback(host):
        if not getattr(args, "allow_remote", False):
            print(f"拒绝启动：--host {host} 不是回环地址。\n"
                  "本服务没有 TLS 与账号体系，对外监听等于把完整 API 暴露给任何能访问该端口的人。\n"
                  "确需如此，请显式加 --allow-remote 并自行承担风险。", file=sys.stderr, flush=True)
            return 2
        print(f"警告：正在对外监听 {host}。任何能访问该端口的人都可调用完整 API"
              "（含模型配置与导出），请仅在受控网络中临时使用。", file=sys.stderr, flush=True)

    app = _build(args)
    static_dir = None
    if args.static and os.path.isdir(args.static):
        static_dir = os.path.abspath(args.static)
    # CLI 模式同样必须校验 token：没有"空 token 放行"的旁路
    token = secrets.token_urlsafe(32)
    server = serve(app, host=host, port=args.port, static_dir=static_dir, token=token)
    print(f"NexLing server listening on http://{host}:{args.port}  (static={static_dir})", flush=True)
    print(f"bridge token: {token}\n请在请求头携带 X-NexLing-Token: <token>", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def cmd_translate(args) -> int:
    app = _build(args)
    req = {
        "text": args.text, "target_lang": args.target, "source_lang": args.source or "auto",
        "mode": args.mode, "scene_profile_id": args.scene, "domain": args.domain,
    }
    info = app.start_translation(req, trace_id="cli")
    tid = info["task_id"]
    for _ in range(600):
        task = app.repo.get_task(tid)
        if task["status"] in (TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value):
            break
        time.sleep(0.05)
    snap = app.snapshot(tid)
    print(json.dumps(snap, ensure_ascii=False, indent=2))
    return 0 if task["status"] == TaskStatus.SUCCEEDED.value else 1


def cmd_seed(args) -> int:
    app = _build(args)
    print(f"Bootstrapped; banks={[b['id'] for b in app.repo.list_banks()]}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="nexling", description="NexLing 技术翻译工作台（命令行）")
    p.add_argument("--data", default=os.path.join(os.getcwd(), ".laa"), help="数据目录")
    p.add_argument("--memory", action="store_true", help="使用内存仓库(不落盘)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("serve", help="启动 HTTP 服务")
    s.add_argument("--host", default="127.0.0.1", help="监听地址，默认只允许回环地址")
    s.add_argument("--port", type=int, default=8787)
    s.add_argument("--static", default=os.path.join(os.getcwd(), "webui", "dist"), help="前端静态目录")
    s.add_argument("--allow-remote", action="store_true",
                   help="允许非回环地址监听（明确知道风险时才用，会打印警告）")
    s.set_defaults(func=cmd_serve)

    t = sub.add_parser("translate", help="一次性翻译")
    t.add_argument("--text", required=True)
    t.add_argument("--target", default="zh-Hans", help="目标语言；auto 表示按源语言自动决定")
    t.add_argument("--source", default="")
    t.add_argument("--mode", default="fluent", choices=["fluent", "literal"])
    t.add_argument("--scene", default="")
    t.add_argument("--domain", default="general")
    t.set_defaults(func=cmd_translate)

    d = sub.add_parser("seed", help="初始化数据仓库")
    d.set_defaults(func=cmd_seed)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())