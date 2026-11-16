"""Composition root: assemble every service and return a ready Application."""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, Optional

from ..shared import ServiceContainer, TraceContext
from ..shared.clock import utc_now
from ..shared.ids import new_id
from ..ports import ProviderPort
from ..domain.text.service import detect_language, estimate_tokens, normalize_text, segment_text
from ..domain.scene.service import ModeController, PromptComposer, SceneProfileService
from ..domain.emotion.parser import EmotionAligner, EmotionAnnotationParser
from ..domain.glossary.service import GlossaryService, PersonalGlossaryExporter
from ..domain.risk.engine import RiskEngine, RiskPolicy, RiskRouter, RiskScorer
from ..domain.qa.service import ConfidenceEstimator, QAService
from ..domain.qa.fix import FixApplier, FixParser, QAFixPlanner
from ..domain.tm.service import TranslationMemoryService
from ..domain.cost.service import CostService
from ..infra.persistence.database import LaaRepository, _open_db
from ..infra.persistence.repository import InMemoryRepository
from ..infra.persistence.secrets import SecretStore
from ..infra.providers.gateway import ProviderGateway, ProviderRouter
from ..infra.providers.fake import FakeProvider
from ..infra.providers.openai_compat import OpenAICompatProvider
from ..domain.skin.service import SkinService
from .facades import (
    CostFacade,
    EmotionFacade,
    GlossaryFacade,
    QAFacade,
    RiskFacade,
    SceneFacade,
    TextFacade,
)
from .capability import CapabilityGate, CapabilityRegistry
from .pipeline import TranslationOrchestrator
from .services import Application


class Bootstrap:
    def __init__(self, data_dir: str = "", use_memory: bool = False, base_url: str = ""):
        self.data_dir = data_dir or os.path.join(os.getcwd(), ".laa")
        self.use_memory = use_memory
        self.base_url = base_url

    def build(self) -> Application:
        os.makedirs(self.data_dir, exist_ok=True)
        if self.use_memory:
            repo = InMemoryRepository()
            secrets: Optional[SecretStore] = None
        else:
            db = _open_db(os.path.join(self.data_dir, "laa.sqlite3"))
            repo = LaaRepository(db)
            secrets = SecretStore(os.path.join(self.data_dir, "secrets.json"))

        # domain services
        text = TextFacade(__import__("laa_core.domain.text.service", fromlist=["x"]))
        scene_svc = SceneProfileService(repo)
        scene = SceneFacade(scene_svc, PromptComposer(), ModeController())
        glossary = GlossaryFacade(GlossaryService(repo))
        emotion = EmotionFacade(EmotionAnnotationParser(), EmotionAligner())
        risk = RiskFacade(RiskEngine(), RiskScorer(), RiskRouter(), RiskPolicy())
        qa = QAFacade(QAService(), ConfidenceEstimator(), QAFixPlanner(), FixParser(), FixApplier())
        tm = TranslationMemoryService(repo)
        cost_svc = CostService(repo)
        cost = CostFacade(cost_svc)

        # provider gateway
        gateway = self._build_gateway(repo, secrets, cost_svc)
        capabilities = CapabilityRegistry()
        gate = CapabilityGate(capabilities)

        orchestrator = TranslationOrchestrator(
            repo, text, glossary, risk, scene, qa, emotion, tm, cost, gateway,
        )
        # 内存库用于测试：皮肤包写入临时目录，避免污染仓库
        skin_root = tempfile.mkdtemp(prefix="nexling-skin-") if self.use_memory else self.data_dir
        skin = SkinService(repo, skin_root)
        app = Application(
            repo, orchestrator, gateway, capabilities, gate,
            scene=scene, glossary=glossary, qa=qa, risk=risk,
            tm=tm, cost=cost, emotion=emotion, text=text,
            secrets=secrets, skin=skin,
        )
        # 上次进程异常退出时留下的运行中任务：标记 paused，可重试续传
        app.recover_tasks()
        return app

    def _build_gateway(self, repo, secrets, cost_svc) -> ProviderGateway:
        from ..infra.providers.openai_compat import is_blocked_profile

        providers: list = [FakeProvider()]
        profiles = repo.list_providers() if hasattr(repo, "list_providers") else []
        for prof in profiles:
            if prof.get("id") == "fake" or is_blocked_profile(prof):
                # 旧库里未经确认的非法 base_url：不加载进路由（用户确认前禁用）
                continue
            cfg = prof.get("config_json") or {}
            api_key = None
            if secrets is not None:
                handle = prof.get("secret_handle") or f"key:{prof.get('id')}"
                api_key = secrets.get(handle)
            providers.append(OpenAICompatProvider(
                provider_id=prof["id"], name=prof.get("name") or cfg.get("name", prof["id"]),
                base_url=prof.get("base_url") or cfg.get("base_url", ""),
                model=prof.get("model") or cfg.get("model", ""), api_key=api_key,
            ))
        default_ok = next((p.get("id") for p in profiles if p.get("is_default")), None)
        default_id = default_ok if default_ok in {p.provider_id for p in providers} else "fake"
        router = ProviderRouter(providers, default_id=default_id)
        gateway = ProviderGateway(router)

        def on_usage(provider_id, model, purpose, in_tok, out_tok, latency_ms):
            try:
                task_id = TraceContext.current_task() or ""
                cost_svc.record(task_id, "", provider_id, model, purpose, in_tok, out_tok, latency_ms)
            except Exception:
                pass

        gateway.on_usage = on_usage

        def on_call(provider_id, model, purpose, messages, response_text, usage, latency_ms):
            """调用历史：记录提示词 / 回复 / token / 花费，供「设置 → 调用历史」查看。"""
            try:
                if not hasattr(repo, "append_call"):
                    return
                task_id = TraceContext.current_task() or ""
                user_input = ""
                if task_id:
                    task = repo.get_task(task_id)
                    if task:
                        user_input = task.get("source_text") or ""
                in_tok = int((usage or {}).get("input_tokens", 0) or 0)
                out_tok = int((usage or {}).get("output_tokens", 0) or 0)
                amount = 0.0
                try:
                    amount = float(cost_svc.estimate(in_tok, out_tok, provider_id).amount)
                except Exception:
                    pass
                repo.append_call({
                    "id": new_id(), "task_id": task_id, "segment_id": "",
                    "provider": provider_id, "model": model or "", "purpose": purpose or "draft",
                    "user_input": user_input,
                    "prompt": json.dumps(messages or [], ensure_ascii=False),
                    "response": str(response_text or "")[:20000],
                    "input_tokens": in_tok, "output_tokens": out_tok,
                    "amount": amount, "latency_ms": int(latency_ms or 0),
                    "created_at": utc_now(),
                })
            except Exception:
                pass

        gateway.on_call = on_call
        return gateway