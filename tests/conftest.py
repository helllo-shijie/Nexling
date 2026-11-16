"""Shared fixtures for the LAA test suite."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from laa_core.app.bootstrap import Bootstrap  # noqa: E402


@pytest.fixture()
def app():
    return Bootstrap(use_memory=True).build()


@pytest.fixture()
def run(app):
    """Start a translation with FakeProvider and wait for terminal status."""
    def _run(text="The compiler optimizes the loop. Neural network handles garbage collection.",
             target_lang="zh-Hans", domain="tech"):
        info = app.start_translation({"text": text, "target_lang": target_lang, "domain": domain}, trace_id="t")
        import time
        from laa_core.shared.types import TaskStatus
        tid = info["task_id"]
        for _ in range(400):
            t = app.repo.get_task(tid)
            if t["status"] in (TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value):
                break
            time.sleep(0.01)
        return tid, t
    return _run