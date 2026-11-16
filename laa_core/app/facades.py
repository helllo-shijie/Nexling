"""Application facades: adapt domain services into orchestrator-friendly interfaces.

This is the single place that smooths over module-specific class splits (e.g. scene =
SceneProfileService + PromptComposer + ModeController) so the orchestrator stays stable.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..shared.types import TranslateMode


class TextFacade:
    def __init__(self, mod):
        self.segment_text = mod.segment_text
        self.detect_language = mod.detect_language
        self.normalize_text = mod.normalize_text
        self.estimate_tokens = mod.estimate_tokens


class RiskFacade:
    def __init__(self, engine, scorer=None, router=None, policy=None):
        self._engine = engine
        self._scorer = scorer
        self._router = router
        self._policy = policy

    def assess(self, text, segments, domain="general"):
        if hasattr(self._engine, "assess"):
            return self._engine.assess(text, segments, domain)
        return self._engine(text, segments, domain)

    def explain(self, assessment):
        if hasattr(self._engine, "explain"):
            return self._engine.explain(assessment)
        return assessment.tier

    def route(self, score, policy=None):
        if self._router is not None:
            return self._router.route(score, policy or self._policy)
        return {"routing": "auto_finalize", "auto_export_allowed": True}


class SceneFacade:
    def __init__(self, profile_service, composer=None, mode_controller=None):
        self._profiles = profile_service
        self._composer = composer
        self._mode = mode_controller

    def resolve(self, ref):
        return self._profiles.resolve(ref)

    def get(self, scene_id):
        return self._profiles.get(scene_id)

    def list(self):
        return self._profiles.list()

    def resolve_mode(self, task_mode, resolved_scene):
        mode = task_mode or getattr(resolved_scene, "mode", None) or "fluent"
        if self._mode is not None:
            return self._mode.resolve(mode, None) if getattr(self._mode, "resolve", None) else mode
        return mode

    def compose(self, req, scene, glossary_block, mode, segments=None, locked_terms=""):
        if self._composer is not None:
            return self._composer.compose(req, scene, glossary_block, mode, segments,
                                          locked_terms=locked_terms)
        from ..shared.dto import PromptPlan
        return PromptPlan(template_id="default", template_version="1", messages=[], mode=mode or "fluent",
                          scene_profile_id=getattr(scene, "id", None), scene_version=getattr(scene, "version", 1),
                          glossary_terms=[], fingerprint="")

    def ensure_marker(self, text):
        if self._mode is not None and hasattr(self._mode, "ensure_marker"):
            return self._mode.ensure_marker(text)
        return text

    def save_from_dict(self, d):
        return self._profiles.save_from_dict(d)

    def set_default(self, scene_id):
        return self._profiles.set_default(scene_id)

    def delete(self, scene_id):
        return self._profiles.delete(scene_id)

    def duplicate(self, scene_id, new_name):
        return self._profiles.duplicate(scene_id, new_name)


class GlossaryFacade:
    def __init__(self, service, resolver=None):
        self._srv = service
        self._resolver = resolver

    def match(self, text, src, tgt, bank_ids=None, scene_id=None):
        return self._srv.match(text, src, tgt, bank_ids, "L0", scene_id)

    def prompt_block(self, hits):
        return "\n".join(f"{h.source_term} => {h.target_term}" for h in hits)

    def bindings_for(self, hits):
        return []

    def current_bank_version(self):
        if hasattr(self._srv, "current_bank_version"):
            return self._srv.current_bank_version()
        return None

    def add_entry(self, bank_id, entry):
        return self._srv.add_entry(bank_id, entry)

    def promote_to_personal(self, entry_id):
        return self._srv.promote_to_personal(entry_id)

    def export_package(self, bank_id):
        return self._srv.export_package(bank_id)

    def import_package(self, pkg, mode="merge", target_bank_id="personal-default"):
        return self._srv.import_package(pkg, mode, target_bank_id)

    def conflicts(self, text, src, tgt):
        return self._srv.conflicts(text, src, tgt)


class EmotionFacade:
    def __init__(self, parser, aligner=None):
        self._parser = parser
        self._aligner = aligner

    def parse(self, raw, segments):
        items = self._parser.parse(raw, segments)
        if self._aligner is not None:
            targets = {}
            items = self._aligner.align(items, segments, targets)
        return items


class QAFacade:
    def __init__(self, qa_service, estimator, planner=None, parser=None, applier=None):
        self._qa = qa_service
        self._est = estimator
        self._planner = planner
        self._parser = parser
        self._applier = applier

    def check(self, seg, draft, ctx):
        return self._qa.check(seg, draft, ctx)

    def estimate(self, report, signals):
        return self._est.estimate(report, signals)

    def apply_fixes(self, task_id, segments, drafts, qa_reports, hits, risk):
        if self._planner is None or self._applier is None:
            return {}
        out = {}
        plan = self._planner.plan(list(qa_reports.values()), segments, drafts, hits, risk)
        for item in plan.get("items", []):
            sid = item.get("segment_id")
            applied = self._applier.apply(drafts.get(sid, ""), item)
            out[sid] = {"applied": applied.get("applied", False), "new_text": applied.get("new_text", drafts.get(sid, ""))}
        return out


class CostFacade:
    def __init__(self, service):
        self._srv = service

    def summary(self, group_by="provider"):
        return self._srv.summary(group_by)

    def totals(self):
        return self._srv.totals()

    def list_usage(self, limit=50, offset=0, provider=None):
        return self._srv.list_usage(limit, offset, provider)

    def record(self, *args, **kwargs):
        return self._srv.record(*args, **kwargs)

    def estimate(self, input_tokens, output_tokens, provider="deepseek"):
        return self._srv.estimate(input_tokens, output_tokens, provider)

    def task_total(self, task_id):
        total = 0.0
        for r in self._srv.repo.sum_usage("task_id") or []:
            if str(r.get("k", r.get("task_id", ""))) == str(task_id):
                total += float(r.get("amount", 0.0) or 0.0)
        return round(total, 6)