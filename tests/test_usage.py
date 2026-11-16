"""账单功能（usage 总览 + 明细）单元测试。"""


def _seed(app):
    c = app.cost
    c.record("t1", "", "deepseek", "deepseek-chat", "draft", 1000, 2000, 50)
    c.record("t1", "", "openai", "gpt-4o-mini", "draft", 500, 100, 80)
    c.record("t2", "", "deepseek", "deepseek-chat", "qa", 300, 700, 40)


def test_usage_summary_totals_and_groups(app):
    _seed(app)
    s = app.usage_summary({})
    t = s["totals"]
    assert t["calls"] == 3
    assert t["input_tokens"] == 1800
    assert t["output_tokens"] == 2800
    assert t["amount"] > 0.0

    providers = {r["k"]: r for r in s["by_provider"]}
    assert set(providers) == {"deepseek", "openai"}
    assert providers["deepseek"]["n"] == 2

    days = {r["k"]: r for r in s["by_day"]}
    assert len(days) == 1  # 同一自然日


def test_usage_list_pagination_and_filter(app):
    _seed(app)
    lst = app.usage_list({"limit": 50})
    assert lst["total"] == 3
    assert len(lst["items"]) == 3
    # 按时间倒序：最后一条在最前
    assert lst["items"][0]["purpose"] == "qa"

    page = app.usage_list({"limit": 2, "offset": 0})
    assert page["total"] == 3
    assert len(page["items"]) == 2

    ds = app.usage_list({"provider": "deepseek"})
    assert ds["total"] == 2
    assert all(it["provider"] == "deepseek" for it in ds["items"])

    empty = app.usage_list({"provider": "claude"})
    assert empty["total"] == 0
    assert empty["items"] == []