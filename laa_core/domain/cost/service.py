"""Cost ledger: pricing, estimation, recording, and aggregation (spec §6.18).

Prices are CNY per 1M tokens (documented, may be placeholder values). Amounts
are reported in USD using 1 USD ≈ 7.2 CNY. No network, no model.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from laa_core.shared import CostEstimate, err, new_id, utc_now

USD_PER_CNY = 7.2

PRICE_TABLE = {
    "version": "2026.11.1",
    "deepseek": {"in": 0.5, "out": 1.5},
    "openai": {"in": 8.0, "out": 30.0},
}

VALID_PURPOSES = ("draft", "qa", "fix", "segment")


class CostService:
    """Estimate and record token usage via a duck-typed repo."""

    def __init__(self, repo) -> None:
        self.repo = repo

    def price(self, provider: str) -> Dict[str, float]:
        key = (provider or "deepseek").lower()
        return PRICE_TABLE.get(key, PRICE_TABLE["deepseek"])

    def estimate(self, input_tokens: int, output_tokens: int,
                 provider: str = "deepseek") -> CostEstimate:
        p = self.price(provider)
        cny = (int(input_tokens) * p["in"] + int(output_tokens) * p["out"]) / 1_000_000.0
        usd = cny / USD_PER_CNY
        return CostEstimate(
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            segments=1,
            calls=1,
            amount=round(usd, 6),
            currency="USD",
            assumptions=[
                f"{provider} 定价 in={p['in']} out={p['out']} 元/百万 token",
                f"1 USD ≈ {USD_PER_CNY} CNY",
                f"价格表版本 {PRICE_TABLE['version']}",
            ],
        )

    def record(self, task_id: str, segment_id: str, provider: str, model: str,
               purpose: str, input_tokens: int, output_tokens: int,
               latency_ms: int) -> None:
        if purpose not in VALID_PURPOSES:
            raise err("LAA-1002", f"非法用途 purpose={purpose}，仅支持 {VALID_PURPOSES}")
        est = self.estimate(input_tokens, output_tokens, provider)
        entry = {
            "id": new_id(),
            "task_id": task_id,
            "segment_id": segment_id,
            "provider": provider,
            "model": model,
            "purpose": purpose,
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "latency_ms": int(latency_ms),
            "amount": est.amount,
            "currency": "USD",
            "created_at": utc_now(),
        }
        self.repo.append_usage(entry)

    def summary(self, group_by: str = "provider") -> List[Dict[str, Any]]:
        return list(self.repo.sum_usage(group_by) or [])

    def totals(self) -> Dict[str, Any]:
        return self.repo.usage_totals()

    def list_usage(self, limit: int = 50, offset: int = 0, provider: Optional[str] = None) -> Dict[str, Any]:
        return self.repo.list_usage(limit, offset, provider)

    def budget_left(self, task_id: str, limit) -> Dict[str, Any]:
        spent = 0.0
        for r in self.repo.sum_usage("task") or []:
            key = r.get("task") if "task" in r else r.get("task_id")
            if str(key) == str(task_id):
                amount = r.get("amount", r.get("total", r.get("cost", 0.0)))
                spent += float(amount or 0.0)
        limit_f = float(limit)
        remaining = limit_f - spent
        return {
            "task_id": task_id,
            "limit": limit_f,
            "spent": round(spent, 6),
            "remaining": round(remaining, 6),
        }


if __name__ == "__main__":  # pragma: no cover - smoke test
    class _Mem:
        def __init__(self):
            self.rows = []

        def append_usage(self, e):
            self.rows.append(e)

        def sum_usage(self, group_by):
            return []

    svc = CostService(_Mem())
    print(svc.estimate(1000, 2000).to_dict())