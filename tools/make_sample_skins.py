# -*- coding: utf-8 -*-
"""生成随交付目录提供的三套外置皮肤示例包（不内置进默认列表）。

用法：python tools/make_sample_skins.py
输出：skins/liquid-glass.nxlskin / night.nxlskin / warm-contrast.nxlskin
包内可含 screenshot.png（供人翻看挑选，软件不读取、不显示、不校验，导出时不会带上）。
"""
from __future__ import annotations

import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "skins")
SHOT_DIR = os.path.join(ROOT, "docs", "screenshots")

GLASS = {
    "--bg": "#e7eef2", "--bg-tint": "#dfe9ef", "--surface": "#f7fbfd",
    "--surface-2": "#eef5f9", "--surface-hover": "#e6eff5",
    "--border": "#d2e0e8", "--border-strong": "#b6cad6", "--border-subtle": "#e9f1f5",
    "--text": "#10222c", "--text-secondary": "#314a58", "--text-muted": "#5f7686",
    "--accent": "#2a6f86", "--accent-hover": "#1f5b6f", "--accent-soft": "#d9edf4",
    "--accent-line": "#a8cfdd", "--on-accent": "#ffffff",
    "--low-bg": "#fbf3dd", "--risk-bg": "#fbe6e4", "--risk-fg": "#9a3a30",
    "--positive": "#1f7a63", "--negative": "#a24a40", "--neutral": "#63798a",
    "--urgent": "#a55f24", "--apology": "#6a5aa0", "--emphasis": "#2a6f86", "--humor": "#2b7f8c",
    "--success-bg": "#dbf0e8", "--success-fg": "#1f7a63",
    "--warn-bg": "#fbf1d8", "--warn-fg": "#7f5a18", "--warn-strong": "#96682a",
    "--danger-bg": "#fbe8e4", "--danger-fg": "#9a3a30", "--danger-border": "#e0b3aa",
    "--info-bg": "#e2eff8",
    "--code-bg": "#eef6fa", "--code-fg": "#10222c",
    "--toast-bg": "#10222c", "--toast-fg": "#ffffff",
    "--scrim": "rgba(16,34,44,0.42)", "--scrim-soft": "rgba(16,34,44,0.30)",
    "--row-src-bg": "#f9fdfe", "--row-hover-bg": "#f1f8fb",
    "--row-src-hover-bg": "#e9f4f9", "--row-low-bg": "#fcf7e8", "--seg-low-bg": "#fbf3dd",
    "--chart-grid": "#d2e0e8", "--chart-bar": "#2a6f86",
    "--scrollbar-thumb": "#b6cad6", "--scrollbar-track": "transparent",
    "--emotion-positive-bg": "#dbf0e8", "--emotion-negative-bg": "#fbe6e4",
    "--emotion-urgent-bg": "#fbeeda", "--emotion-apology-bg": "#e9e4f7",
    "--emotion-emphasis-bg": "#dbedf6", "--emotion-humor-bg": "#d7f0f3",
    "--confidence-high-bg": "#dbf0e8", "--confidence-high-fg": "#1f7a63",
    "--confidence-medium-bg": "#fbf1d8", "--confidence-medium-fg": "#7f5a18",
    "--confidence-low-fg": "#6b4c12",
    "--sent-pos-bg": "rgba(31,122,99,0.10)", "--sent-neg-bg": "rgba(162,74,64,0.10)",
    "--sent-pos-mark": "#2f8c74", "--sent-neg-mark": "#b26055", "--sent-neu-mark": "#b3c7d2",
    "--shadow-sm": "0 1px 2px rgba(16,34,44,0.05)",
    "--shadow": "0 2px 10px rgba(16,34,44,0.07)",
    "--shadow-pop": "0 12px 32px rgba(16,34,44,0.13)",
    "--shadow-lg": "0 20px 52px rgba(16,34,44,0.18)",
    "--radius-xs": "10px", "--radius-sm": "14px", "--radius": "20px", "--radius-lg": "26px",
}

NIGHT = {
    "--bg": "#0f141b", "--bg-tint": "#131a23", "--surface": "#171f2a",
    "--surface-2": "#1c2633", "--surface-hover": "#22303f",
    "--border": "#2a3745", "--border-strong": "#3a4c5f", "--border-subtle": "#222c38",
    "--text": "#e8eef6", "--text-secondary": "#c2cede", "--text-muted": "#93a3b8",
    "--accent": "#7aa7f0", "--accent-hover": "#94b8f5", "--accent-soft": "#1c2c45",
    "--accent-line": "#334f78", "--on-accent": "#0b1017",
    "--low-bg": "#2a2417", "--risk-bg": "#35201f", "--risk-fg": "#f08a80",
    "--positive": "#5cc99a", "--negative": "#f08a80", "--neutral": "#9aa8bb",
    "--urgent": "#e8a15a", "--apology": "#b39af0", "--emphasis": "#7aa7f0", "--humor": "#5fc7d4",
    "--success-bg": "#183026", "--success-fg": "#7fd6a8",
    "--warn-bg": "#2e2617", "--warn-fg": "#ebc078", "--warn-strong": "#f0c98a",
    "--danger-bg": "#331d1b", "--danger-fg": "#f3998e", "--danger-border": "#5c342f",
    "--info-bg": "#182638",
    "--code-bg": "#10161d", "--code-fg": "#dbe6f2",
    "--toast-bg": "#e8eef6", "--toast-fg": "#0b1017",
    "--scrim": "rgba(0,0,0,0.62)", "--scrim-soft": "rgba(0,0,0,0.45)",
    "--row-src-bg": "#131a23", "--row-hover-bg": "#18212c",
    "--row-src-hover-bg": "#1b2734", "--row-low-bg": "#201d14", "--seg-low-bg": "#241f12",
    "--chart-grid": "#2a3745", "--chart-bar": "#7aa7f0",
    "--scrollbar-thumb": "#3a4c5f", "--scrollbar-track": "transparent",
    "--emotion-positive-bg": "#183026", "--emotion-negative-bg": "#331d1b",
    "--emotion-urgent-bg": "#33261a", "--emotion-apology-bg": "#2a2340",
    "--emotion-emphasis-bg": "#1a2a44", "--emotion-humor-bg": "#173236",
    "--confidence-high-bg": "#183026", "--confidence-high-fg": "#7fd6a8",
    "--confidence-medium-bg": "#332a15", "--confidence-medium-fg": "#ebc078",
    "--confidence-low-fg": "#e0c89a",
    "--sent-pos-bg": "rgba(92,201,154,0.14)", "--sent-neg-bg": "rgba(240,138,128,0.14)",
    "--sent-pos-mark": "#5cc99a", "--sent-neg-mark": "#f08a80", "--sent-neu-mark": "#6b7c92",
    "--shadow-sm": "0 1px 2px rgba(0,0,0,0.35)",
    "--shadow": "0 2px 10px rgba(0,0,0,0.40)",
    "--shadow-pop": "0 12px 34px rgba(0,0,0,0.55)",
    "--shadow-lg": "0 20px 56px rgba(0,0,0,0.62)",
    "--radius-xs": "6px", "--radius-sm": "8px", "--radius": "10px", "--radius-lg": "14px",
}

WARM = {
    "--bg": "#fbf4e8", "--bg-tint": "#f5e9d5", "--surface": "#fffdf7",
    "--surface-2": "#f8efe1", "--surface-hover": "#f2e4d1",
    "--border": "#e3d3bd", "--border-strong": "#cbb392", "--border-subtle": "#f0e4d4",
    "--text": "#1f1508", "--text-secondary": "#43331d", "--text-muted": "#6b5638",
    "--accent": "#a23a0e", "--accent-hover": "#832e0a", "--accent-soft": "#fbe3d2",
    "--accent-line": "#e8b899", "--on-accent": "#fffdf7",
    "--low-bg": "#fff0c8", "--risk-bg": "#fbe0d8", "--risk-fg": "#8f2410",
    "--positive": "#1f6b3a", "--negative": "#9a2e16", "--neutral": "#5f5140",
    "--urgent": "#9a4a00", "--apology": "#6b3fa0", "--emphasis": "#8a3a0c", "--humor": "#146b73",
    "--success-bg": "#dff0df", "--success-fg": "#1f6b3a",
    "--warn-bg": "#fbecc8", "--warn-fg": "#7a4a05", "--warn-strong": "#8f5a10",
    "--danger-bg": "#fbe2da", "--danger-fg": "#8f2410", "--danger-border": "#d9a48e",
    "--info-bg": "#e6eefb",
    "--code-bg": "#f6ece0", "--code-fg": "#2a1c0c",
    "--toast-bg": "#2a1c0c", "--toast-fg": "#fffdf7",
    "--scrim": "rgba(42,28,12,0.50)", "--scrim-soft": "rgba(42,28,12,0.34)",
    "--row-src-bg": "#fffcf5", "--row-hover-bg": "#fdf4e6",
    "--row-src-hover-bg": "#f8ebd9", "--row-low-bg": "#fff3d4", "--seg-low-bg": "#fff0c8",
    "--chart-grid": "#e3d3bd", "--chart-bar": "#a23a0e",
    "--scrollbar-thumb": "#cbb392", "--scrollbar-track": "transparent",
    "--emotion-positive-bg": "#dff0df", "--emotion-negative-bg": "#fbe0d8",
    "--emotion-urgent-bg": "#fbe7cf", "--emotion-apology-bg": "#ebe2f8",
    "--emotion-emphasis-bg": "#fbe3d2", "--emotion-humor-bg": "#d9f0f0",
    "--confidence-high-bg": "#dff0df", "--confidence-high-fg": "#1f6b3a",
    "--confidence-medium-bg": "#fbecc8", "--confidence-medium-fg": "#7a4a05",
    "--confidence-low-fg": "#5f3a04",
    "--sent-pos-bg": "rgba(31,107,58,0.10)", "--sent-neg-bg": "rgba(154,46,22,0.10)",
    "--sent-pos-mark": "#2f7f4a", "--sent-neg-mark": "#b2563c", "--sent-neu-mark": "#bfae95",
    "--shadow-sm": "0 1px 2px rgba(63,42,17,0.06)",
    "--shadow": "0 2px 8px rgba(63,42,17,0.10)",
    "--shadow-pop": "0 12px 30px rgba(63,42,17,0.16)",
    "--shadow-lg": "0 18px 44px rgba(63,42,17,0.22)",
    "--radius-xs": "3px", "--radius-sm": "4px", "--radius": "6px", "--radius-lg": "10px",
}

PACKS = [
    {
        "id": "liquid-glass",
        "name": "液态玻璃",
        "author": "NexLing 示例",
        "description": "仿液态玻璃的冷银浅色皮肤：只在顶栏、历史侧栏、抽屉与设置导航上做小面积毛玻璃，不做整页模糊。",
        "mode": "light",
        "vars": GLASS,
        "effects": {"glass": "on"},
    },
    {
        "id": "night",
        "name": "深空夜色",
        "author": "NexLing 示例",
        "description": "深色皮肤：完整覆盖情感概率条、置信度、术语高亮、行内句子底色、代码块、图表、滚动条与原生控件配色。",
        "mode": "dark",
        "vars": NIGHT,
        "effects": {"glass": "off"},
    },
    {
        "id": "warm-contrast",
        "name": "暖白高对比",
        "author": "NexLing 示例",
        "description": "偏暖的纸白底与砖红主色，收紧圆角、加深文字对比，适合长时间阅读。",
        "mode": "light",
        "vars": WARM,
        "effects": {"glass": "off"},
    },
]


def build(pack: dict) -> str:
    manifest = {
        "format": "nexling.skin",
        "version": 1,
        "id": pack["id"],
        "name": pack["name"],
        "author": pack["author"],
        "description": pack["description"],
        "mode": pack["mode"],
        "vars": pack["vars"],
        "effects": pack["effects"],
        "background": None,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    target = os.path.join(OUT_DIR, f"{pack['id']}.nxlskin")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("skin.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        shot = os.path.join(SHOT_DIR, f"{pack['id']}.png")
        if os.path.isfile(shot):
            archive.write(shot, "screenshot.png")
    return target


def main() -> int:
    for pack in PACKS:
        path = build(pack)
        print(f"{os.path.basename(path)}\t{os.path.getsize(path) / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
