"""Provider gateway: routing, retry, budget hook (§6.15/M14)."""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from ...shared.dto import PromptPlan
from ...shared.errors import LaaError, err
from ...ports import ProviderPort
from .fake import FakeProvider
from .openai_compat import OpenAICompatProvider


class ProviderRouter:
    def __init__(self, providers: List[ProviderPort], default_id: Optional[str] = None):
        self._providers = {p.provider_id: p for p in providers}
        self.default_id = default_id or (providers[0].provider_id if providers else "fake")

    def get(self, provider_id: Optional[str] = None) -> ProviderPort:
        pid = provider_id or self.default_id
        p = self._providers.get(pid)
        if p is None:
            raise err("LAA-2003", message=f"未配置供应商 {pid}")
        return p

    def list(self) -> List[Dict[str, Any]]:
        return [
            {"provider_id": p.provider_id, "kind": getattr(p, "kind", "translate"),
             "capabilities": p.capabilities(), "default": p.provider_id == self.default_id}
            for p in self._providers.values()
        ]

    def set_default(self, provider_id: str) -> None:
        if provider_id not in self._providers:
            raise err("LAA-2003", message=f"供应商不存在 {provider_id}")
        self.default_id = provider_id


class ProviderGateway:
    def __init__(self, router: ProviderRouter, max_retries: int = 2, retry_backoff_s: float = 0.6,
                 on_usage=None, on_call=None):
        self.router = router
        self.max_retries = max_retries
        self.retry_backoff_s = retry_backoff_s
        self.on_usage = on_usage  # callable(provider_id, model, purpose, in_tok, out_tok, latency_ms)
        self.on_call = on_call    # callable(provider_id, model, purpose, messages, response_text, usage, latency_ms)

    def _log_call(self, provider, purpose: str, messages, response_text, usage: dict, latency: int) -> None:
        if not self.on_call:
            return
        try:
            self.on_call(provider.provider_id, getattr(provider, "model", "n/a"), purpose,
                         messages, response_text, usage, latency)
        except Exception:  # noqa: BLE001 - 日志失败不影响翻译主流程
            pass

    @staticmethod
    def _response_text(result: Dict[str, Any]) -> str:
        content = result.get("content")
        if content is None:
            content = {k: v for k, v in result.items() if k in ("segments", "emotions")}
        return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)

    def translate(self, plan: PromptPlan, segments: list, provider_id: Optional[str] = None) -> Dict[str, Any]:
        provider = self.router.get(provider_id)
        last_err: Optional[LaaError] = None
        for attempt in range(self.max_retries + 1):
            t0 = time.time()
            try:
                result = provider.translate(plan, segments)
                latency = int((time.time() - t0) * 1000)
                usage = result.get("usage", {})
                if self.on_usage:
                    self.on_usage(provider.provider_id, getattr(provider, "model", "n/a"), "draft",
                                  usage.get("input_tokens", 0), usage.get("output_tokens", 0), latency)
                content = result.get("content")
                response_text = self._response_text(result)
                self._log_call(provider, "draft", plan.messages, response_text, usage, latency)
                result.setdefault("provider_id", provider.provider_id)
                result.setdefault("model", getattr(provider, "model", "n/a"))
                result.setdefault("source_channel", provider.capabilities().get("source_channel", "online"))
                return result
            except LaaError as e:
                last_err = e
                if not e.is_retryable():
                    raise
                time.sleep(self.retry_backoff_s * (attempt + 1))
            except Exception as e:  # unexpected: treat as provider unavailable
                last_err = err("LAA-8004", message=str(e))
                time.sleep(self.retry_backoff_s * (attempt + 1))
        raise last_err or err("LAA-8004", message="provider failed")

    def split_sentences(self, text: str, provider_id: Optional[str] = None) -> List[str]:
        """模型分句（超长段落切分用）；离线/失败时返回本地兜底分句。"""
        provider = self.router.get(provider_id)
        if hasattr(provider, "split_sentences"):
            t0 = time.time()
            try:
                result = provider.split_sentences(text)
                usage = result.get("usage") or {}
                if self.on_usage:
                    self.on_usage(provider.provider_id, getattr(provider, "model", "n/a"), "segment",
                                  usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                                  int((time.time() - t0) * 1000))
                self._log_call(provider, "segment", [{"role": "user", "content": text}],
                               json.dumps(result.get("sentences"), ensure_ascii=False),
                               usage, int((time.time() - t0) * 1000))
                sents = result.get("sentences")
                if isinstance(sents, list) and sents and "".join(sents) == text:
                    return sents
            except Exception:  # noqa: BLE001 - 分句失败必须退回本地，不影响翻译主流程
                pass
        from ...domain.text.service import _merge_tiny_spans, _sentence_spans
        spans = _merge_tiny_spans(_sentence_spans(text), text)
        return [text[s:e] for s, e in spans]

    def complete(self, messages: List[Dict[str, str]], provider_id: Optional[str] = None, purpose: str = "qa",
                 **kw) -> Dict[str, Any]:
        provider = self.router.get(provider_id)
        t0 = time.time()
        result = provider.complete(messages, **kw)
        latency = int((time.time() - t0) * 1000)
        usage = result.get("usage") or {}
        content = result.get("content")
        response_text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        self._log_call(provider, purpose, messages, response_text, usage, latency)
        return result

    def health(self, provider_id: Optional[str] = None) -> Dict[str, Any]:
        try:
            return self.router.get(provider_id).health()
        except LaaError as e:
            return {"ok": False, "detail": e.message}


def build_gateway_from_config(profiles: List[dict], secrets) -> "ProviderGateway":
    """Assemble providers from stored profiles + secret handles."""
    providers: List[ProviderPort] = []
    has_fake = False
    for prof in profiles:
        pid = prof["id"]
        if pid == "fake":
            providers.append(FakeProvider())
            has_fake = True
            continue
        preset = prof.get("config_json", {})
        api_key = secrets.get(prof.get("secret_handle")) if prof.get("secret_handle") else secrets.get(f"key:{pid}")
        providers.append(OpenAICompatProvider(
            provider_id=pid, name=prof.get("name") or preset.get("name", pid),
            base_url=prof.get("base_url") or preset.get("base_url", ""),
            model=prof.get("model") or preset.get("model", ""),
            api_key=api_key,
        ))
    if not has_fake:
        providers.append(FakeProvider())
    default = next((p["id"] for p in profiles if p.get("is_default")), None)
    router = ProviderRouter(providers, default_id=default)
    return ProviderGateway(router)