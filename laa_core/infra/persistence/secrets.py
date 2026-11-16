"""Secret storage via Windows DPAPI (CryptProtectData) with a documented fallback.

Secrets are never written to config as plaintext; callers receive a handle string
that references a protected blob stored under the data directory.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from typing import Optional

from ...shared.errors import err

_LocalFree = ctypes.windll.kernel32.LocalFree  # type: ignore


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob_to_bytes(blob: _DATA_BLOB) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def _dpapi_protect(data: bytes, description: str = "laa-secret") -> bytes:
    local = wintypes.HANDLE(ctypes.c_size_t(0).value)
    in_blob = _DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
    out_blob = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(  # type: ignore
        ctypes.byref(in_blob), ctypes.c_wchar_p(description), None, None, None, 0, ctypes.byref(out_blob)
    )
    if not ok:
        raise err("LAA-2002", message="DPAPI protect failed")
    try:
        return _blob_to_bytes(out_blob)
    finally:
        if out_blob.pbData:
            _LocalFree(ctypes.cast(out_blob.pbData, wintypes.HLOCAL))


def _dpapi_unprotect(data: bytes) -> bytes:
    in_blob = _DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
    out_blob = _DATA_BLOB()
    desc = wintypes.LPWSTR()
    ok = ctypes.windll.crypt32.CryptUnprotectData(  # type: ignore
        ctypes.byref(in_blob), ctypes.byref(desc), None, None, None, 0, ctypes.byref(out_blob)
    )
    if not ok:
        raise err("LAA-2002", message="DPAPI unprotect failed")
    try:
        return _blob_to_bytes(out_blob)
    finally:
        if out_blob.pbData:
            _LocalFree(ctypes.cast(out_blob.pbData, wintypes.HLOCAL))


class SecretStore:
    def __init__(self, path: str, use_dpapi: bool = True):
        self.path = path
        self.use_dpapi = use_dpapi and os.name == "nt"
        self._cache: dict = {}
        parent = os.path.dirname(os.path.abspath(path))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._cache = {}

    def _persist(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def set(self, handle: str, secret: str) -> str:
        payload = _dpapi_protect(secret.encode("utf-8")) if self.use_dpapi else secret.encode("utf-8")
        record = {"scheme": "dpapi" if self.use_dpapi else "base64", "blob": base64.b64encode(payload).decode("ascii")}
        self._cache[handle] = record
        self._persist()
        return handle

    def get(self, handle: Optional[str]) -> Optional[str]:
        if not handle or handle not in self._cache:
            return None
        record = self._cache[handle]
        raw = base64.b64decode(record["blob"])
        try:
            data = _dpapi_unprotect(raw) if record.get("scheme") == "dpapi" else raw
        except Exception:
            data = raw
        return data.decode("utf-8")

    def delete(self, handle: str) -> None:
        self._cache.pop(handle, None)
        self._persist()

    def is_available(self) -> bool:
        return self.use_dpapi