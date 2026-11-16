"""对比度配对的结构性校验：配对必须由样式派生，而不是手工清单。

这些用例的作用是保证「样式里新增未配对的配色组合」会直接让测试失败，
而不是等复核时才发现漏配。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import derive_contrast_pairs as derive_pairs  # noqa: E402

from laa_core.domain.skin.service import (  # noqa: E402
    DARK_BASELINE,
    LIGHT_BASELINE,
    contrast_pairs,
)

# 第四轮复核对点名的 11 组配对；派生结果必须包含它们。
REQUIRED_PAIRS = {
    ("--text", "--risk-bg"),
    ("--negative", "--risk-bg"),
    ("--positive", "--emotion-positive-bg"),
    ("--urgent", "--emotion-urgent-bg"),
    ("--apology", "--emotion-apology-bg"),
    ("--emphasis", "--emotion-emphasis-bg"),
    ("--humor", "--emotion-humor-bg"),
    ("--text", "--sent-pos-bg"),
    ("--text", "--sent-neg-bg"),
    ("--accent", "--bg-tint"),
    ("--positive", "--success-bg"),
}


def _derive():
    return derive_pairs.derive(derive_pairs.load_styles())


def test_artifact_matches_styles():
    derived, _used = _derive()
    problems = derive_pairs.compare(derived, derive_pairs.load_artifact())
    assert not problems, (
        "contrast_pairs.json 与样式不一致，请运行 python tools/derive_contrast_pairs.py：\n"
        + "\n".join(problems))


def test_every_style_color_variable_is_paired():
    derived, used = _derive()
    problems = derive_pairs.uncovered(derived, used)
    assert not problems, "样式里有颜色变量没有被任何配对覆盖：\n" + "\n".join(problems)


def test_required_review_pairs_are_derived():
    derived, _used = _derive()
    missing = sorted(REQUIRED_PAIRS - set(derived))
    assert not missing, "缺少复核点名的配对：" + ", ".join(f"{fg}/{bg}" for fg, bg in missing)


def test_artifact_matches_runtime_loader():
    saved = {(item["fg"], item["bg"], float(item["min"]))
             for item in derive_pairs.load_artifact()}
    assert set(contrast_pairs()) == saved


def test_pair_keys_exist_in_both_baselines():
    missing = []
    for fg, bg, _minimum in contrast_pairs():
        for key in (fg, bg):
            if key not in LIGHT_BASELINE:
                missing.append(f"浅色基线缺少 {key}（{fg}/{bg}）")
            if key not in DARK_BASELINE:
                missing.append(f"深色基线缺少 {key}（{fg}/{bg}）")
    assert not missing, "\n".join(sorted(set(missing)))


def test_whitelist_is_specific_and_reasoned(monkeypatch):
    whitelisted = set(derive_pairs.WHITELIST)
    for pair, reason in derive_pairs.WHITELIST.items():
        fg, bg = pair
        assert fg.startswith("--") and bg.startswith("--"), f"白名单必须是具体配对：{pair}"
        assert "*" not in fg and "*" not in bg, f"白名单不允许整变量豁免：{pair}"
        assert len(reason.strip()) >= 6, f"白名单缺少理由：{pair}"
    # 白名单不能是僵尸条目：去掉白名单后这些配对必须真的会从样式里派生出来。
    monkeypatch.setattr(derive_pairs, "WHITELIST", {})
    raw, _used = _derive()
    stale = sorted(whitelisted - set(raw))
    assert not stale, "白名单里存在样式已不产生的配对：" + ", ".join(
        f"{fg}/{bg}" for fg, bg in stale)


def test_adding_unpaired_color_in_styles_is_caught():
    styles = derive_pairs.load_styles()
    styles["global.css"] += (
        "\n.contrast-probe { color: var(--warn-strong); background: var(--success-bg); }\n")
    derived, _used = derive_pairs.derive(styles)
    assert ("--warn-strong", "--success-bg") in derived

    problems = derive_pairs.compare(derived, derive_pairs.load_artifact())
    assert any(
        "--warn-strong" in problem and "--success-bg" in problem and "contrast-probe" in problem
        for problem in problems
    ), "新增未配对颜色没有被拦下：" + "\n".join(problems)


def test_three_components_match_rendered_pairs():
    """抽查工具提示、状态徽标、句子情感底色三处，派生配对与 CSS 实际写法一致。"""
    derived, _used = _derive()

    def selectors(pair):
        return " ".join(derived.get(pair, set()))

    assert "feature-notice" in selectors(("--toast-fg", "--toast-bg"))

    assert "tp__badge" in selectors(("--positive", "--success-bg"))

    sentence = selectors(("--text", "--sent-pos-bg"))
    assert "sent--positive" in sentence
