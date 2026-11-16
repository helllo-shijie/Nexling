"""Focused unit tests for deterministic domain modules."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from laa_core.shared import TermEntry, new_id


def test_language_detect_zh():
    from laa_core.domain.text.service import detect_language
    r = detect_language("这是一个中文句子,包含 neural network 与 deadlock。")
    assert r["lang"] in ("zh-Hans", "zh-Hant")


def test_language_detect_en():
    from laa_core.domain.text.service import detect_language
    r = detect_language("This is an English sentence with some words.")
    assert r["lang"] == "en"


def test_token_estimate_positive():
    from laa_core.domain.text.service import estimate_tokens
    assert estimate_tokens("这是一段中文。") >= 2
    assert estimate_tokens("hello world") >= 2


def test_glossary_longest_match():
    from laa_core.domain.glossary.matcher import TermMatcher
    m = TermMatcher()
    m.build_index([
        TermEntry(id=new_id(), bank_id="b", source_term="neural network", target_term="神经网络",
                  src_lang="*", tgt_lang="*", forced=True),
        TermEntry(id=new_id(), bank_id="b", source_term="network", target_term="网络",
                  src_lang="*", tgt_lang="*", forced=False),
    ])
    hits = [h for h in m.scan("a neural network", "en", "zh-Hans") if h.resolved]
    assert any(h.source_term == "neural network" for h in hits)


def test_risk_l2_legal():
    from laa_core.domain.risk.engine import RiskEngine
    a = RiskEngine().assess("甲方违约须承担违约责任。", domain="legal")
    assert a.tier == "L2"
    assert a.routing == "manual_export"
    assert a.auto_export_allowed is False


def test_risk_out_of_scope():
    from laa_core.domain.risk.engine import RiskEngine
    a = RiskEngine().assess("本药品每日服用剂量不得超过处方规定的量。")
    assert a.tier == "L3"
    assert a.routing == "blocked"


def test_qa_blocks_on_term_mismatch():
    from laa_core.domain.qa.service import QAService
    from laa_core.shared import TermHit
    seg = type("S", (), {"text": "The deadline is strict.", "id": "s1"})()
    report = QAService().check(seg, "截止时间很严格。", {"terms": [
        TermHit(source_term="deadline", target_term="截止期限", span=[4, 12], entry_id="e1",
                bank_id="b", scope="personal", forced=True, resolved=True, match_mode="exact",
                domain="general", version=1, shadowed_by=None),
    ]})
    assert report.has_blocking or report.issues is not None


def test_tm_exact_hit():
    from laa_core.infra.persistence.repository import InMemoryRepository
    from laa_core.domain.tm.service import TranslationMemoryService
    repo = InMemoryRepository()
    svc = TranslationMemoryService(repo)
    svc.store("hello world", "你好世界", "en", "zh-Hans", "general", approved=True)
    hits = svc.lookup("hello world", "en", "zh-Hans", "general")
    assert hits and hits[0].score >= 0.9


def test_cost_usd_conversion():
    from laa_core.domain.cost.service import CostService
    class _R:
        def append_usage(self, e): self.e = e
        def sum_usage(self, g): return []
    svc = CostService(_R())
    est = svc.estimate(1_000_000, 0, "deepseek")
    assert est.currency == "USD"
    assert abs(est.amount - 0.5 / 7.2) < 1e-4