"""Atomic JSON file store (for scene profile / glossary pack cache, small files)."""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Optional

from ...shared.errors import err


class JsonFileStore:
    def __init__(self, path: str, default: Any = None):
        self.path = path
        self._lock = threading.RLock()
        parent = os.path.dirname(os.path.abspath(path))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        if not os.path.exists(path):
            self.write(default if default is not None else {})

    def read(self) -> Any:
        with self._lock:
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                raise err("LAA-7003", message=f"json store corrupted: {e}")

    def write(self, data: Any) -> None:
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)