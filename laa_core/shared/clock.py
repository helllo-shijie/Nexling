"""Clock (real + fake), cancellation token, and contextvars-based trace."""
from __future__ import annotations

import contextvars
import datetime
import threading
from dataclasses import dataclass, field
from typing import Optional

from .errors import err


def utc_now() -> str:
    """ISO-8601 UTC with millisecond precision."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


class Clock:
    def now(self) -> str:
        return utc_now()

    def now_ms(self) -> int:
        return int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)


class FakeClock(Clock):
    def __init__(self, start_ms: int = 1_700_000_000_000):
        self._ms = start_ms
        self._lock = threading.Lock()

    def advance(self, ms: int) -> None:
        with self._lock:
            self._ms += ms

    def set(self, ms: int) -> None:
        with self._lock:
            self._ms = ms

    def now_ms(self) -> int:
        with self._lock:
            return self._ms

    def now(self) -> str:
        ms = self.now_ms()
        dt = datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.timezone.utc)
        return dt.isoformat(timespec="milliseconds")


class CancellationToken:
    def __init__(self) -> None:
        self._flag = threading.Event()
        self.reason: Optional[str] = None

    def cancel(self, reason: str = "cancelled") -> None:
        self.reason = reason
        self._flag.set()

    def is_cancelled(self) -> bool:
        return self._flag.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise err("LAA-3005", reason=self.reason or "cancelled")


_trace_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("trace_id", default=None)
_task_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("task_id", default=None)
_segment_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("segment_id", default=None)


class TraceContext:
    """Stores trace/task/segment association without threading it through every call."""

    def __init__(self, trace_id: str, task_id: Optional[str] = None, segment_id: Optional[str] = None):
        self.trace_id = trace_id
        self.task_id = task_id
        self.segment_id = segment_id
        self._resets: list = []

    def __enter__(self) -> "TraceContext":
        self._resets.append((_trace_var, _trace_var.set(self.trace_id)))
        self._resets.append((_task_var, _task_var.set(self.task_id)))
        self._resets.append((_segment_var, _segment_var.set(self.segment_id)))
        return self

    def __exit__(self, *exc) -> None:
        for var, token in self._resets:
            var.reset(token)
        self._resets = []

    def child(self, segment_id: Optional[str] = None) -> "TraceContext":
        return TraceContext(self.trace_id, self.task_id, segment_id or self.segment_id)

    @staticmethod
    def current_trace() -> Optional[str]:
        return _trace_var.get()

    @staticmethod
    def current_task() -> Optional[str]:
        return _task_var.get()

    @staticmethod
    def current_segment() -> Optional[str]:
        return _segment_var.get()


@dataclass
class Span:
    """Half-open character interval [start, end) on source or target text."""

    start: int
    end: int

    def to_list(self) -> list:
        return [self.start, self.end]

    @classmethod
    def from_list(cls, v) -> "Span":
        return cls(int(v[0]), int(v[1]))


@dataclass
class Score:
    value: float = 0.0


@dataclass
class Paginated:
    items: list = field(default_factory=list)
    total: int = 0
    cursor: Optional[str] = None

    def to_dict(self) -> dict:
        return {"items": self.items, "total": self.total, "cursor": self.cursor}