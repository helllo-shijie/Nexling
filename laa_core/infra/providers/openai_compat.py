"""OpenAI-compatible chat provider (DeepSeek, OpenAI, DeepL-x, etc.) via stdlib urllib.

Only vendor-agnostic HTTP lives here; no third-party SDK. Errors map to LAA-8xxx.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from ...shared.dto import PromptPlan
from ...shared.errors import err


class OpenAICompatProvider:
    kind = "translate"

    def __init__(self, provider_id: str, name: str, base_url: str, model: str, api_key: Optional[str] = None,
                 temperature: float = 0.2, timeout_s: float = 90.0):
        self.provider_id = provider_id
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.timeout_s = timeout_s

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.api_key:
            raise err("LAA-2003", message=f"{self.name} 未配置密钥")
        url = self.base_url + "/chat/completions"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            code = e.code
            if code in (401, 403):
                raise err("LAA-8001", message=f"{self.name} {code}")
            if code == 429:
                raise err("LAA-8002", message=f"{self.name} 限流")
            if code in (400, 422):
                raise err("LAA-8005", message=f"{self.name} 内容拦截或参数错误 {code}")
            raise err("LAA-8004", message=f"{self.name} HTTP {code}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise err("LAA-8003", message=f"{self.name} 超时/不可达: {e}")

    def _completion(self, messages: List[Dict[str, str]], response_format: str = "json_object",
                    max_tokens: int = 2048) -> Dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": response_format},
        }
        raw = self._post(payload)
        try:
            content = raw["choices"][0]["message"]["content"]
            usage = raw.get("usage", {})
        except (KeyError, IndexError, TypeError):
            raise err("LAA-8006", message="结构化输出不合规")
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            raise err("LAA-8005", message="输出不是合法 JSON")
        return {"content": parsed, "usage": {
            "input_tokens": int(usage.get("prompt_tokens", 0)),
            "output_tokens": int(usage.get("completion_tokens", 0)),
        }}

    def split_sentences(self, text: str, lang: str = "") -> Dict[str, Any]:
        """由模型按语义分句；返回的句子拼接后必须与原文逐字一致，否则调用方降级。"""
        messages = [
            {"role": "system", "content":
                "你是分句器。把用户给出的原文按语义切成完整句子，只输出 JSON：{\"sentences\":[\"...\"]}。"
                "要求：1) 每句必须从原文原样连续复制，不得改写、增删任何字符或标点；"
                "2) 所有句子按顺序拼接后必须与原文完全一致；3) 按语义成句，不要机械按每个句号切割，"
                "标点误用、残句、语气词碎片要合并成完整一句；没有标点的长句也要切分。"},
            {"role": "user", "content": text},
        ]
        result = self._completion(messages, max_tokens=min(4096, max(256, len(text) // 2 + 128)))
        content = result["content"]
        sents = content.get("sentences") if isinstance(content, dict) else None
        if not isinstance(sents, list):
            raise err("LAA-8006", message="分句输出不是句子列表")
        out = [s for s in sents if isinstance(s, str) and s]
        if not out or "".join(out) != text:
            raise err("LAA-8006", message="模型分句与原文对不齐")
        return {"sentences": out, "usage": result.get("usage", {})}

    def translate(self, plan: PromptPlan, segments: list) -> Dict[str, Any]:
        result = self._completion(plan.messages, response_format="json_object", max_tokens=plan.max_output_tokens)
        content = result["content"]
        if not isinstance(content, dict):
            raise err("LAA-8006", message="翻译输出不是 JSON 对象")
        segs = content.get("segments")
        emotions = content.get("emotions", [])
        if not isinstance(segs, list):
            raise err("LAA-8006", message="segments 字段缺失或非列表")
        norm_segments = []
        for it in segs:
            if isinstance(it, dict) and "segment_id" in it and "target_text" in it:
                item = {"segment_id": str(it["segment_id"]), "target_text": str(it["target_text"])}
                words = it.get("words")
                if isinstance(words, list):
                    item["words"] = words  # 直译模式：逐词对齐，由 pipeline 归一化
                tones = it.get("tones")
                if isinstance(tones, list):
                    item["tones"] = tones  # 语气识别：原文片段 + 标签，由 pipeline 归一化
                # 情感概率与候选译法必须原样透传，否则真实 provider 下界面永远为空
                sentiment = it.get("sentiment")
                if isinstance(sentiment, (dict, list)):
                    item["sentiment"] = sentiment
                elif sentiment is not None:
                    raise err("LAA-8006", message="sentiment 字段类型不合规")
                sentences = it.get("sentences")
                if isinstance(sentences, list):
                    item["sentences"] = sentences  # 句子级情感：由 pipeline 校验定位后落库
                elif sentences is not None:
                    raise err("LAA-8006", message="sentences 字段类型不合规")
                variants = it.get("variants")
                if isinstance(variants, list):
                    item["variants"] = variants
                elif variants is not None:
                    raise err("LAA-8006", message="variants 字段类型不合规")
                terms = it.get("terms")
                if isinstance(terms, list):
                    item["terms"] = terms  # 本文术语→译法：由 pipeline 校验后落库
                elif terms is not None:
                    raise err("LAA-8006", message="terms 字段类型不合规")
                norm_segments.append(item)
            elif isinstance(it, str):
                # tolerate bare strings by matching order
                norm_segments.append({"segment_id": "", "target_text": it})
        if not isinstance(emotions, list):
            emotions = []
        result["segments"] = norm_segments
        result["emotions"] = emotions
        return result

    def complete(self, messages: List[Dict[str, str]], *, response_format: str = "json_object", max_tokens: int = 2048) -> Dict[str, Any]:
        return self._completion(messages, response_format=response_format, max_tokens=max_tokens)

    def health(self) -> Dict[str, Any]:
        t0 = time.time()
        try:
            self._post({"model": self.model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1})
            return {"ok": True, "latency_ms": int((time.time() - t0) * 1000), "detail": "ok"}
        except Exception as e:
            return {"ok": False, "latency_ms": int((time.time() - t0) * 1000), "detail": str(e)}

    def capabilities(self) -> Dict[str, Any]:
        return {"input": ["text"], "output": ["text"], "supports_stream": True, "source_channel": "online",
                "model": self.model}


PROVIDER_PRESETS = {
    "deepseek": {"name": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "openai": {"name": "OpenAI", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "claude": {"name": "Claude", "base_url": "https://api.anthropic.com/v1", "model": "claude-3-5-sonnet-latest"},
}

# 每个内置供应商自己的官方 API 域名。写入（provider.upsert）与连通测试
# （provider.test）都只认这些主机；自定义/中转地址必须显式开启 allow_custom_endpoint。
PRESET_HOSTS = {
    "deepseek": {"api.deepseek.com"},
    "openai": {"api.openai.com"},
    "claude": {"api.anthropic.com"},
}
OFFICIAL_HOSTS = set().union(*PRESET_HOSTS.values())


def base_url_host(base_url: str) -> str:
    from urllib.parse import urlparse

    try:
        return (urlparse(str(base_url or "").strip()).hostname or "").lower()
    except ValueError:
        return ""


def base_url_scheme(base_url: str) -> str:
    from urllib.parse import urlparse

    try:
        return (urlparse(str(base_url or "").strip()).scheme or "").lower()
    except ValueError:
        return ""


def is_official_base_url(provider_id: str, base_url: str) -> bool:
    """base_url 是否属于该供应商的官方域名（自定义 id 可命中任意官方主机）。"""
    host = base_url_host(base_url)
    if not host:
        return False
    if base_url_scheme(base_url) != "https":
        return False
    allowed = PRESET_HOSTS.get(provider_id) or OFFICIAL_HOSTS
    return host in allowed


def is_blocked_profile(profile: dict) -> bool:
    """旧库里未经确认的非法地址：未标记 custom_endpoint 且不在官方白名单内。"""
    cfg = profile.get("config_json")
    if isinstance(cfg, str):
        try:
            import json as _json

            cfg = _json.loads(cfg or "{}")
        except (TypeError, ValueError):
            cfg = {}
    if (cfg or {}).get("custom_endpoint"):
        return False
    return not is_official_base_url(str(profile.get("id") or ""), str(profile.get("base_url") or ""))