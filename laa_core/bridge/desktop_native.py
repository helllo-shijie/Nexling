"""桌面原生能力桥接钩子（desktop.py 注册，bridge 命令分发到这里）。

避免在 laa_core 里直接 import pywebview/desktop，保持核心与桌面层的解耦。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

# desktop.py 的 main() 会注册一个 save_dialog 实现
_save_handler: Optional[Callable[[str, str, bool], Dict[str, Any]]] = None


def register_save_handler(fn: Callable[[str, str, bool], Dict[str, Any]]) -> None:
    """由 desktop.py 调用：注册「另存为」处理器。"""
    global _save_handler
    _save_handler = fn


def save_dialog(suggested_name: str, content: str, base64_encoded: bool = False) -> Dict[str, Any]:
    """弹出系统保存对话框并写入文件（由前端 file.save_dialog 命令触发）。

    返回：
      {"unsupported": True}          - 非桌面模式（run.py serve / 浏览器），前端应降级
      {"saved": True, "path": "..."} - 保存成功
      {"saved": False, "cancelled": True} - 用户取消
      {"saved": False, "error": "..."}    - 失败
    """
    if _save_handler is None:
        return {"unsupported": True}
    try:
        return _save_handler(suggested_name, content, bool(base64_encoded))
    except Exception as e:
        return {"saved": False, "error": str(e)}