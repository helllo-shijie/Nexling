"""ULID: locally-sortable, unique identifier (Crockford base32, 26 chars)."""
from __future__ import annotations

import os
import time
from typing import Optional

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode(b: bytes) -> str:
    # b: 16 bytes -> 26 chars base32 (128 bits -> 26 chars, last char uses 3 bits)
    out: list[str] = []
    bit_buf = 0
    bit_len = 0
    for byte in b:
        bit_buf = (bit_buf << 8) | byte
        bit_len += 8
        while bit_len >= 5:
            bit_len -= 5
            out.append(_CROCKFORD[(bit_buf >> bit_len) & 0x1F])
    if bit_len > 0:
        out.append(_CROCKFORD[(bit_buf << (5 - bit_len)) & 0x1F])
    return "".join(out)


class Ulid:
    """A ULID string. ``Ulid.new()`` returns a new identifier."""

    __slots__ = ("value",)

    def __init__(self, value: str):
        self.value = value

    @classmethod
    def new(cls, timestamp_ms: Optional[int] = None) -> "Ulid":
        ts = int(timestamp_ms if timestamp_ms is not None else time.time() * 1000)
        ts_bytes = ts.to_bytes(6, "big")
        rand = os.urandom(10)
        return cls(_encode(ts_bytes + rand))

    @classmethod
    def from_hash(cls, seed: str) -> "Ulid":
        """Deterministically derive a ULID from a string (for pack record ids)."""
        import hashlib

        digest = hashlib.sha256(seed.encode("utf-8")).digest()[:16]
        return cls(_encode(digest))

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"Ulid({self.value!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Ulid) and other.value == self.value

    def __hash__(self) -> int:
        return hash(self.value)


def new_id() -> str:
    return str(Ulid.new())


def id_from(seed: str) -> str:
    return str(Ulid.from_hash(seed))