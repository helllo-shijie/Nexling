"""皮肤包服务：声明式视觉变量 + 少量受控枚举开关。

设计约束（用户已明确）：
- 皮肤只能改视觉变量，不能改布局结构、不能换字体、不能携带字体文件；
- 不执行任意 CSS/JS：只认白名单里的键，值做类型与范围校验，未知字段直接拒绝；
- 可携带一张背景图（仅作用于主内容区，带遮罩）与一张工作台截图（软件不读取/不显示/不校验，
  导出时不导出）；单包总上限 5 MB；
- 同一 ID 再次导入视为更新，不并存版本；内置皮肤不可删除。

内置两套（默认浅色学术风、薄荷学术风）由本模块提供，前端只负责把变量写到 :root。
"""
from __future__ import annotations

import base64
import binascii
import colorsys
import io
import json
import os
import re
import shutil
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from ...shared import err, utc_now

PACKAGE_SUFFIX = ".nxlskin"
FORMAT = "nexling.skin"
FORMAT_VERSION = 1
MAX_PACKAGE_BYTES = 5 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_BACKGROUND_BYTES = 4 * 1024 * 1024

BUILTIN_IDS = ("default", "mint")
RESERVED_IDS = set(BUILTIN_IDS) | {"fake", "system"}

# ---- 变量白名单 ----
# 颜色：全部为可主题化的语义色；深色包必须给全，避免浅色默认值漏进来。
COLOR_KEYS = (
    "--bg", "--bg-tint", "--surface", "--surface-2", "--surface-hover",
    "--border", "--border-strong", "--border-subtle",
    "--text", "--text-secondary", "--text-muted",
    "--accent", "--accent-hover", "--accent-soft", "--accent-line", "--on-accent",
    "--low-bg", "--risk-bg", "--risk-fg",
    "--positive", "--negative", "--neutral", "--urgent", "--apology", "--emphasis", "--humor",
    "--success-bg", "--success-fg", "--warn-bg", "--warn-fg", "--warn-strong",
    "--danger-bg", "--danger-fg", "--danger-border", "--info-bg",
    "--code-bg", "--code-fg", "--toast-bg", "--toast-fg",
    "--scrim", "--scrim-soft",
    "--row-src-bg", "--row-hover-bg", "--row-src-hover-bg", "--row-low-bg", "--seg-low-bg",
    "--chart-grid", "--chart-bar",
    "--scrollbar-thumb", "--scrollbar-track",
    "--emotion-positive-bg", "--emotion-negative-bg", "--emotion-urgent-bg",
    "--emotion-apology-bg", "--emotion-emphasis-bg", "--emotion-humor-bg",
    "--confidence-high-bg", "--confidence-high-fg", "--confidence-medium-bg",
    "--confidence-medium-fg", "--confidence-low-fg",
    "--sent-pos-bg", "--sent-neg-bg", "--sent-pos-mark", "--sent-neg-mark", "--sent-neu-mark",
)
SHADOW_KEYS = ("--shadow-sm", "--shadow", "--shadow-pop", "--shadow-lg")
RADIUS_KEYS = ("--radius-xs", "--radius-sm", "--radius", "--radius-lg")
ALLOWED_VAR_KEYS = set(COLOR_KEYS) | set(SHADOW_KEYS) | set(RADIUS_KEYS)

# 深色包必须提供的完整变量，否则漏掉的键会回落到浅色默认值。
DARK_REQUIRED = set(COLOR_KEYS) | set(SHADOW_KEYS)

# 导入校验基线：皮肤包只给部分变量时，与内置基线合并后再算对比度。
# 浅色取 global.css 的默认学术风；深色取内置深色语义（与 night 示例一致）。
LIGHT_BASELINE: Dict[str, str] = {
    "--bg": "#f7f8fa",
    "--bg-tint": "#eef2f7",
    "--surface": "#ffffff",
    "--surface-2": "#f4f6f9",
    "--surface-hover": "#edf1f6",
    "--row-src-bg": "#fbfcfd",
    "--row-hover-bg": "#f7f9fc",
    "--row-src-hover-bg": "#f2f6fb",
    "--text": "#1b2430",
    "--text-secondary": "#46536a",
    "--text-muted": "#7a8699",
    "--accent": "#3b5c8f",
    "--accent-hover": "#2f4b77",
    "--accent-soft": "#e8eef8",
    "--on-accent": "#ffffff",
    "--positive": "#2f7a5c",
    "--negative": "#a4443f",
    "--neutral": "#6f7c91",
    "--urgent": "#b06a2c",
    "--apology": "#6b5b95",
    "--emphasis": "#3b5c8f",
    "--humor": "#3f7f8c",
    "--low-bg": "#fdf6e3",
    "--row-low-bg": "#fffcf1",
    "--seg-low-bg": "#fffbe9",
    "--code-bg": "#f4f6f9",
    "--code-fg": "#1b2430",
    "--toast-bg": "#1b2430",
    "--toast-fg": "#ffffff",
    "--success-bg": "#eaf2ee",
    "--success-fg": "#1f7a4d",
    "--warn-bg": "#fbf3e2",
    "--warn-fg": "#8a6120",
    "--warn-strong": "#a06a2c",
    "--danger-bg": "#fdf1ee",
    "--danger-fg": "#a3422f",
    "--risk-bg": "#fbeaea",
    "--risk-fg": "#a4443f",
    "--confidence-high-bg": "#dcfce7",
    "--confidence-high-fg": "#166534",
    "--confidence-medium-bg": "#fef3c7",
    "--confidence-medium-fg": "#92400e",
    "--confidence-low-fg": "#713f12",
    "--emotion-positive-bg": "#dcfce7",
    "--emotion-negative-bg": "#fbeaea",
    "--emotion-urgent-bg": "#ffedd5",
    "--emotion-apology-bg": "#ede9fe",
    "--emotion-emphasis-bg": "#dbeafe",
    "--emotion-humor-bg": "#cffafe",
    "--sent-pos-bg": "rgba(127, 168, 138, 0.09)",
    "--sent-neg-bg": "rgba(192, 138, 132, 0.1)",
}

DARK_BASELINE: Dict[str, str] = {
    "--bg": "#0f141b",
    "--bg-tint": "#131a23",
    "--surface": "#171f2a",
    "--surface-2": "#1c2633",
    "--surface-hover": "#22303f",
    "--row-src-bg": "#131a23",
    "--row-hover-bg": "#18212c",
    "--row-src-hover-bg": "#1b2734",
    "--text": "#e8eef6",
    "--text-secondary": "#c2cede",
    "--text-muted": "#93a3b8",
    "--accent": "#7aa7f0",
    "--accent-hover": "#94b8f5",
    "--accent-soft": "#1c2c45",
    "--on-accent": "#0b1017",
    "--positive": "#5cc99a",
    "--negative": "#f08a80",
    "--neutral": "#9aa8bb",
    "--urgent": "#e8a15a",
    "--apology": "#b39af0",
    "--emphasis": "#7aa7f0",
    "--humor": "#5fc7d4",
    "--low-bg": "#2a2417",
    "--row-low-bg": "#201d14",
    "--seg-low-bg": "#241f12",
    "--code-bg": "#10161d",
    "--code-fg": "#dbe6f2",
    "--toast-bg": "#e8eef6",
    "--toast-fg": "#0b1017",
    "--success-bg": "#183026",
    "--success-fg": "#7fd6a8",
    "--warn-bg": "#2e2617",
    "--warn-fg": "#ebc078",
    "--warn-strong": "#f0c98a",
    "--danger-bg": "#331d1b",
    "--danger-fg": "#f3998e",
    "--risk-bg": "#35201f",
    "--risk-fg": "#f08a80",
    "--confidence-high-bg": "#183026",
    "--confidence-high-fg": "#7fd6a8",
    "--confidence-medium-bg": "#332a15",
    "--confidence-medium-fg": "#ebc078",
    "--confidence-low-fg": "#e0c89a",
    "--emotion-positive-bg": "#183026",
    "--emotion-negative-bg": "#331d1b",
    "--emotion-urgent-bg": "#33261a",
    "--emotion-apology-bg": "#2a2340",
    "--emotion-emphasis-bg": "#1a2a44",
    "--emotion-humor-bg": "#173236",
    "--sent-pos-bg": "rgba(92, 201, 154, 0.14)",
    "--sent-neg-bg": "rgba(240, 138, 128, 0.14)",
}

# 配对不在这里手工维护：tools/derive_contrast_pairs.py 扫描 webui 样式源码，
# 把每个规则块里的“文字色变量 × 底色变量”派生出来写入 contrast_pairs.json，
# 测试负责保证产物与样式一致，样式新增配色组合但没重跑生成器时测试直接失败。
_PAIRS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contrast_pairs.json")
_PAIRS_CACHE: Optional[Tuple[Tuple[str, str, float], ...]] = None


def contrast_pairs() -> Tuple[Tuple[str, str, float], ...]:
    """返回派生出的前景/背景配对；文件缺失说明构建产物不完整，直接报错。"""
    global _PAIRS_CACHE
    if _PAIRS_CACHE is None:
        with open(_PAIRS_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
        _PAIRS_CACHE = tuple(
            (item["fg"], item["bg"], float(item["min"])) for item in data["pairs"])
    return _PAIRS_CACHE

ALLOWED_MANIFEST_KEYS = {"format", "version", "id", "name", "author", "description",
                         "mode", "vars", "effects", "background"}
ALLOWED_EFFECTS = {"glass": ("on", "off")}
BACKGROUND_SCRIMS = ("low", "medium", "high")
SCRIM_ALPHA = {"low": 0.55, "medium": 0.72, "high": 0.86}
IMAGE_MAGIC = {
    ".png": b"\x89PNG\r\n\x1a\n",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
    ".webp": b"RIFF",
    ".gif": b"GIF8",
}

_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
_COLOR_FUNC_RE = re.compile(r"^(rgba?|hsla?)\s*\((.*)\)$", re.I)
_HEX_RE = re.compile(r"^#[0-9a-fA-F]+$")
_SHADOW_RE = re.compile(r"^[0-9a-zA-Z#().,%\s-]+$")
_RADIUS_RE = re.compile(r"^(?:0|[0-9]{1,2}(?:\.[0-9]{1,2})?)px$")


def _err(message: str) -> Exception:
    return err("LAA-1002", message=message)


def _guess_ext(name: str) -> str:
    ext = os.path.splitext(name or "")[1].lower()
    return ext if ext in IMAGE_MAGIC else ""


def _var_key(raw: Any) -> str:
    key = str(raw or "").strip()
    return key if key.startswith("--") else f"--{key}"


def _validate_color(key: str, value: Any) -> str:
    text = str(value or "").strip()
    # 所有实际允许的颜色写法都必须能被 _parse_color 解析；解析不了就拒绝导入，
    # 不能因为“对比度算不出来”而跳过可读性检查。
    if not text or _parse_color(text) is None:
        raise _err(f"皮肤变量 {key} 不是合法颜色值：{text[:40]}")
    return text


def _validate_shadow(key: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 220 or not _SHADOW_RE.match(text):
        raise _err(f"皮肤变量 {key} 不是合法阴影值")
    if re.search(r"(url|var|expression|@|;|[{}<>\"'\\])", text, re.I):
        raise _err(f"皮肤变量 {key} 含有不被允许的写法")
    return text


def _validate_radius(key: str, value: Any) -> str:
    text = str(value or "").strip()
    if not _RADIUS_RE.match(text):
        raise _err(f"皮肤变量 {key} 必须是 0–32px 的圆角值")
    number = float(text[:-2])
    if number > 32:
        raise _err(f"皮肤变量 {key} 超出范围（0–32px）")
    return text


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _alpha_token(token: Optional[str]) -> Optional[float]:
    if token is None:
        return 1.0
    text = token.strip()
    try:
        if text.endswith("%"):
            return _clamp01(float(text[:-1]) / 100.0)
        return _clamp01(float(text))
    except ValueError:
        return None


def _parse_color(text: str) -> Optional[Tuple[float, float, float, float]]:
    """把白名单允许的颜色写法解析成 (r, g, b, alpha)；无法解析返回 None。

    覆盖 hex(3/4/6/8)、rgb()/rgba()、hsl()/hsla()（逗号或空格 + 斜杠写法、
    可选 deg 角度、百分比通道与 alpha）以及 transparent。
    """
    value = (text or "").strip().lower()
    if value == "transparent":
        return (0.0, 0.0, 0.0, 0.0)
    if value.startswith("#"):
        if not _HEX_RE.match(value):
            return None
        body = value[1:]
        if len(body) in (3, 4):
            body = "".join(ch * 2 for ch in body)
        if len(body) not in (6, 8):
            return None
        try:
            channels = [int(body[i:i + 2], 16) for i in range(0, len(body), 2)]
        except ValueError:
            return None
        alpha = channels[3] / 255.0 if len(channels) == 4 else 1.0
        return (float(channels[0]), float(channels[1]), float(channels[2]), alpha)

    m = _COLOR_FUNC_RE.match(value)
    if not m:
        return None
    fn, body = m.group(1), m.group(2)
    parts = [p for p in re.split(r"[,\s/]+", body.strip()) if p]
    if len(parts) not in (3, 4):
        return None
    alpha = _alpha_token(parts[3] if len(parts) == 4 else None)
    if alpha is None:
        return None

    if fn.startswith("rgb"):
        channels: List[float] = []
        for token in parts[:3]:
            try:
                if token.endswith("%"):
                    channels.append(_clamp01(float(token[:-1]) / 100.0) * 255.0)
                else:
                    channels.append(float(token))
            except ValueError:
                return None
        if any(v < 0 or v > 255 for v in channels):
            return None
        return (channels[0], channels[1], channels[2], alpha)

    # hsl / hsla
    try:
        hue_token = parts[0]
        if hue_token.endswith("deg"):
            hue_token = hue_token[:-3]
        hue = float(hue_token) % 360.0
        sat_token, light_token = parts[1], parts[2]
        sat = float(sat_token[:-1]) if sat_token.endswith("%") else float(sat_token)
        light = float(light_token[:-1]) if light_token.endswith("%") else float(light_token)
    except ValueError:
        return None
    if not (0 <= sat <= 100 and 0 <= light <= 100):
        return None
    r, g, b = colorsys.hls_to_rgb(hue / 360.0, light / 100.0, sat / 100.0)
    return (r * 255.0, g * 255.0, b * 255.0, alpha)


def _blend(top: Tuple[float, float, float, float],
           base: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """按 alpha 把颜色叠到已知底色上；不透明色直接返回自身。"""
    alpha = top[3]
    if alpha >= 1.0:
        return (top[0], top[1], top[2])
    return tuple(top[i] * alpha + base[i] * (1.0 - alpha) for i in range(3))


def _luminance(rgb: Tuple[float, float, float]) -> float:
    def channel(v: float) -> float:
        c = v / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(fg: Optional[Tuple[float, float, float, float]],
              bg: Optional[Tuple[float, float, float, float]],
              base: Tuple[float, float, float]) -> Optional[float]:
    if fg is None or bg is None:
        return None
    if fg[3] <= 0.0:
        # 完全透明的前景文字不可能满足任何可读性门槛
        return 1.0
    bg_rgb = _blend(bg, base)
    fg_rgb = _blend(fg, bg_rgb)
    la, lb = _luminance(fg_rgb), _luminance(bg_rgb)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _check_contrast(vars_map: Dict[str, str], mode: str = "light") -> None:
    """把包内变量合并到内置基线后，按样式派生出的配对逐一检查。

    不接受「只提供部分变量所以跳过」：配对来自 contrast_pairs.json（由
    tools/derive_contrast_pairs.py 从 webui 样式派生），基线补齐后任一组合
    解析失败、任一侧透明或低于阈值都拒绝导入。
    """
    pairs = contrast_pairs()
    baseline = DARK_BASELINE if mode == "dark" else LIGHT_BASELINE
    merged = {**baseline, **vars_map}
    page: Tuple[float, float, float] = (9.0, 12.0, 16.0) if mode == "dark" else (255.0, 255.0, 255.0)

    def parsed(key: str) -> Tuple[float, float, float, float]:
        if key not in merged:
            raise _err(f"皮肤校验基线缺少 {key}，无法完成可读性检查")
        rgba = _parse_color(merged[key])
        if rgba is None:
            raise _err(f"皮肤变量 {key} 的颜色写法无法解析，拒绝导入")
        return rgba

    bg_rgba = parsed("--bg")
    if bg_rgba[3] <= 0.0:
        raise _err("皮肤可读性不足：--bg 是透明色，无法确认文字可读")
    bg_rgb = _blend(bg_rgba, page)
    surface_rgba = parsed("--surface")
    if surface_rgba[3] <= 0.0:
        raise _err("皮肤可读性不足：--surface 是透明色，无法确认文字可读")
    surface_rgb = _blend(surface_rgba, bg_rgb)

    bases: Dict[str, Tuple[float, float, float]] = {"--bg": bg_rgb, "--surface": surface_rgb}
    for _, bg_key, _minimum in pairs:
        if bg_key in bases:
            continue
        rgba = parsed(bg_key)
        if rgba[3] <= 0.0:
            raise _err(f"皮肤可读性不足：{bg_key} 是透明色，无法确认文字可读")
        bases[bg_key] = _blend(rgba, surface_rgb)

    for fg_key, bg_key, minimum in pairs:
        fg = parsed(fg_key)
        if fg[3] <= 0.0:
            raise _err(f"皮肤可读性不足：{fg_key} 是透明色，文字无法辨认")
        ratio = _contrast(fg, parsed(bg_key), bases[bg_key])
        if ratio is not None and ratio < minimum:
            raise _err(
                f"皮肤可读性不足：{fg_key} 与 {bg_key} 的对比度 {ratio:.1f}:1 "
                f"低于 {minimum}:1，请调整后再导入"
            )


def _normalize_vars(raw: Any) -> Dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise _err("皮肤字段 vars 必须是对象")
    out: Dict[str, str] = {}
    for key, value in raw.items():
        name = _var_key(key)
        if name not in ALLOWED_VAR_KEYS:
            raise _err(f"皮肤包包含未知变量 {name}（不在允许的视觉变量白名单内）")
        if name in COLOR_KEYS:
            out[name] = _validate_color(name, value)
        elif name in SHADOW_KEYS:
            out[name] = _validate_shadow(name, value)
        else:
            out[name] = _validate_radius(name, value)
    return out


def _normalize_effects(raw: Any) -> Dict[str, str]:
    if raw is None:
        return {"glass": "off"}
    if not isinstance(raw, dict):
        raise _err("皮肤字段 effects 必须是对象")
    out = {"glass": "off"}
    for key, value in raw.items():
        if key not in ALLOWED_EFFECTS:
            raise _err(f"皮肤包包含未知开关 {key}")
        text = str(value or "").strip().lower()
        if text not in ALLOWED_EFFECTS[key]:
            raise _err(f"皮肤开关 {key} 只接受 {'/'.join(ALLOWED_EFFECTS[key])}")
        out[key] = text
    return out


def _normalize_background(raw: Any, files: Dict[str, bytes]) -> Optional[Dict[str, str]]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _err("皮肤字段 background 必须是对象")
    allowed = {"file", "scrim"}
    unknown = [k for k in raw if k not in allowed]
    if unknown:
        raise _err(f"皮肤背景包含未知字段 {', '.join(unknown)}")
    name = str(raw.get("file") or "").strip()
    if not name:
        raise _err("皮肤背景缺少 file")
    ext = _guess_ext(name)
    if not ext:
        raise _err("皮肤背景图只支持 png / jpg / webp / gif")
    data = files.get(name) or files.get(os.path.basename(name))
    if data is None:
        raise _err(f"皮肤背景图 {name} 不在包内")
    if len(data) > MAX_BACKGROUND_BYTES:
        raise _err("皮肤背景图超过 4 MB")
    if not data.startswith(IMAGE_MAGIC[ext]):
        raise _err("皮肤背景图内容与扩展名不符")
    scrim = str(raw.get("scrim") or "medium").strip().lower()
    if scrim not in BACKGROUND_SCRIMS:
        raise _err(f"皮肤背景遮罩只接受 {'/'.join(BACKGROUND_SCRIMS)}")
    return {"file": f"background{ext}", "scrim": scrim}


def _public_meta(manifest: Dict[str, Any], builtin: bool) -> Dict[str, Any]:
    background = manifest.get("background") or {}
    return {
        "id": manifest["id"],
        "name": manifest["name"],
        "author": manifest.get("author") or "",
        "description": manifest.get("description") or "",
        "mode": manifest.get("mode") or "light",
        "builtin": builtin,
        "has_background": bool(background),
        "effects": dict(manifest.get("effects") or {}),
        "updated_at": manifest.get("updated_at") or "",
    }


def _view(manifest: Dict[str, Any], builtin: bool, background_data_url: Optional[str]) -> Dict[str, Any]:
    view = _public_meta(manifest, builtin)
    view["vars"] = dict(manifest.get("vars") or {})
    background = manifest.get("background") or None
    view["background"] = (
        {"data_url": background_data_url, "scrim": background.get("scrim", "medium")}
        if background and background_data_url else None
    )
    return view


def _builtin_manifest(skin_id: str) -> Dict[str, Any]:
    return dict(BUILTIN_SKINS[skin_id])


def _win_light_defaults() -> Dict[str, str]:
    """默认皮肤：不覆盖任何变量，直接使用 global.css 的浅色学术风。"""
    return {}


def _mint_palette() -> Dict[str, str]:
    return {
        "--bg": "#f5f7f9", "--bg-tint": "#eaf2f0", "--surface": "#ffffff",
        "--surface-2": "#f0f3f7", "--surface-hover": "#e7ecf2",
        "--border": "#e2e8f0", "--border-strong": "#cbd6e2", "--border-subtle": "#eef2f6",
        "--text": "#1e293b", "--text-secondary": "#334155", "--text-muted": "#64748b",
        "--accent": "#20a088", "--accent-hover": "#178a75", "--accent-soft": "#d6f4ec",
        "--accent-line": "#9fdfd0", "--on-accent": "#ffffff",
        "--low-bg": "#fff6d9", "--risk-bg": "#fee2e2", "--risk-fg": "#b91c1c",
        "--positive": "#109870", "--negative": "#b91c1c", "--neutral": "#64748b",
        "--urgent": "#c2410c", "--apology": "#7c3aed", "--emphasis": "#2563eb",
        "--humor": "#0891b2",
        "--success-bg": "#d9f5ea", "--success-fg": "#0f7a5c",
        "--warn-bg": "#fff3d6", "--warn-fg": "#8a5a12", "--warn-strong": "#a06a2c",
        "--danger-bg": "#fdecea", "--danger-fg": "#a32f22", "--danger-border": "#f0c2ba",
        "--info-bg": "#e8f1fb",
        "--code-bg": "#f2f6f9", "--code-fg": "#17202b",
        "--toast-bg": "#123c33", "--toast-fg": "#ffffff",
        "--scrim": "rgba(15,23,42,0.45)", "--scrim-soft": "rgba(15,23,42,0.32)",
        "--row-src-bg": "#fbfdfc", "--row-hover-bg": "#f7fbfa",
        "--row-src-hover-bg": "#eef7f4", "--row-low-bg": "#fffcf0", "--seg-low-bg": "#fffbe9",
        "--chart-grid": "#e2e8f0", "--chart-bar": "#20a088",
        "--scrollbar-thumb": "#c3d2cc", "--scrollbar-track": "transparent",
        "--emotion-positive-bg": "#d9f5ea", "--emotion-negative-bg": "#fee2e2",
        "--emotion-urgent-bg": "#ffedd5", "--emotion-apology-bg": "#ede9fe",
        "--emotion-emphasis-bg": "#dbeafe", "--emotion-humor-bg": "#cffafe",
        "--confidence-high-bg": "#d9f5ea", "--confidence-high-fg": "#0f7a5c",
        "--confidence-medium-bg": "#fef3c7", "--confidence-medium-fg": "#8a5a12",
        "--confidence-low-fg": "#713f12",
        "--sent-pos-bg": "rgba(32,160,136,0.10)", "--sent-neg-bg": "rgba(185,28,28,0.09)",
        "--sent-pos-mark": "#2f9d80", "--sent-neg-mark": "#c1675f", "--sent-neu-mark": "#b6c2cf",
        "--shadow-sm": "0 1px 2px rgba(15,23,42,0.04)",
        "--shadow": "0 2px 10px rgba(15,23,42,0.06)",
        "--shadow-pop": "0 12px 32px rgba(15,23,42,0.12)",
        "--shadow-lg": "0 18px 48px rgba(15,23,42,0.16)",
        "--radius-xs": "6px", "--radius-sm": "9px", "--radius": "12px", "--radius-lg": "16px",
    }


BUILTIN_SKINS: Dict[str, Dict[str, Any]] = {
    "default": {
        "format": FORMAT, "version": FORMAT_VERSION, "id": "default",
        "name": "学术浅色", "author": "NexLing", "mode": "light",
        "description": "内置默认皮肤：克制的蓝灰主色与中性纸白，层级靠细线与留白。",
        "vars": _win_light_defaults(), "effects": {"glass": "off"}, "background": None,
    },
    "mint": {
        "format": FORMAT, "version": FORMAT_VERSION, "id": "mint",
        "name": "薄荷学术", "author": "NexLing", "mode": "light",
        "description": "内置皮肤：薄荷青主色、柔和圆角与轻阴影，参考旧版浅色学术风。",
        "vars": _mint_palette(), "effects": {"glass": "off"}, "background": None,
    },
}


class SkinService:
    """皮肤包读写与当前生效皮肤。"""

    def __init__(self, repo, data_dir: str, on_mode_change=None) -> None:
        self.repo = repo
        self.root = os.path.join(data_dir, "skins")
        self.on_mode_change = on_mode_change

    # ---- 路径 / 读取 ----
    def _skin_dir(self, skin_id: str) -> str:
        return os.path.join(self.root, skin_id)

    def _load_external(self, skin_id: str) -> Optional[Dict[str, Any]]:
        if not _ID_RE.match(skin_id or "") or skin_id in BUILTIN_IDS:
            return None
        path = os.path.join(self._skin_dir(skin_id), "skin.json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(manifest, dict) or manifest.get("id") != skin_id:
            return None
        return manifest

    def _list_external(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        if not os.path.isdir(self.root):
            return items
        for name in sorted(os.listdir(self.root)):
            manifest = self._load_external(name)
            if manifest:
                items.append(manifest)
        return items

    def _background_data_url(self, manifest: Dict[str, Any], builtin_dir: Optional[str] = None) -> Optional[str]:
        background = manifest.get("background") or None
        if not background:
            return None
        base = builtin_dir or self._skin_dir(manifest["id"])
        path = os.path.join(base, str(background.get("file") or ""))
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "rb") as fh:
                data = fh.read(MAX_BACKGROUND_BYTES + 1)
        except OSError:
            return None
        if not data or len(data) > MAX_BACKGROUND_BYTES:
            return None
        ext = os.path.splitext(path)[1].lower()
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp", ".gif": "image/gif"}.get(ext, "application/octet-stream")
        return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")

    # ---- 当前生效 ----
    def _active_id(self) -> str:
        raw = self.repo.get_config("app.skin.active", "default")
        skin_id = str(raw or "default")
        if skin_id in BUILTIN_IDS:
            return skin_id
        if self._load_external(skin_id):
            return skin_id
        # 外置包被手工删除等异常：回退默认皮肤
        try:
            self.repo.set_config("app.skin.active", "default")
        except Exception:  # noqa: BLE001 - 回退失败不影响本次读取
            pass
        return "default"

    def _active_view(self) -> Dict[str, Any]:
        skin_id = self._active_id()
        if skin_id in BUILTIN_IDS:
            manifest = _builtin_manifest(skin_id)
            return _view(manifest, True, self._background_data_url(manifest))
        manifest = self._load_external(skin_id) or _builtin_manifest("default")
        builtin = manifest.get("id") in BUILTIN_IDS
        return _view(manifest, builtin, self._background_data_url(manifest))

    def list(self) -> Dict[str, Any]:
        items = [_public_meta(_builtin_manifest(sid), True) for sid in BUILTIN_IDS]
        items += [_public_meta(m, False) for m in self._list_external()]
        return {"active": self._active_id(), "items": items}

    def active(self) -> Dict[str, Any]:
        view = self._active_view()
        view["active"] = view["id"]
        return view

    def active_mode(self) -> str:
        """当前生效皮肤的明暗（不读取背景图，供启动时设置标题栏/窗口底色）。"""
        skin_id = self._active_id()
        if skin_id in BUILTIN_IDS:
            return str(_builtin_manifest(skin_id).get("mode") or "light")
        manifest = self._load_external(skin_id) or {}
        return str(manifest.get("mode") or "light")

    def select(self, skin_id: str) -> Dict[str, Any]:
        skin_id = str(skin_id or "").strip()
        if skin_id not in BUILTIN_IDS and not self._load_external(skin_id):
            raise err("LAA-3005", message="皮肤不存在，可能已被删除")
        self.repo.set_config("app.skin.active", skin_id)
        view = self._active_view()
        self._notify_mode(view.get("mode") or "light")
        view["active"] = view["id"]
        return view

    def _notify_mode(self, mode: str) -> None:
        if self.on_mode_change is None:
            return
        try:
            self.on_mode_change(mode)
        except Exception:  # noqa: BLE001 - 标题栏跟随失败不影响皮肤本身
            pass

    # ---- 导入 ----
    def import_package(self, filename: str, data_b64: str) -> Dict[str, Any]:
        raw = self._decode(data_b64)
        if len(raw) > MAX_PACKAGE_BYTES:
            raise _err(f"皮肤包超过 5 MB 上限（当前 {len(raw) / 1024 / 1024:.1f} MB）")
        try:
            archive = zipfile.ZipFile(io.BytesIO(raw))
        except (zipfile.BadZipFile, OSError):
            raise _err("皮肤包不是合法的 zip 文件")
        with archive:
            infos = [i for i in archive.infolist() if not i.is_dir()]
            total = sum(max(0, int(i.file_size)) for i in infos)
            if total > MAX_PACKAGE_BYTES:
                raise _err(f"皮肤包解压后超过 5 MB 上限（当前 {total / 1024 / 1024:.1f} MB）")
            names = {os.path.basename(i.filename): i for i in infos}
            # 只按需读取白名单文件；截图与其它文件一律不读、不校验、不保存
            manifest_info = names.get("skin.json")
            if manifest_info is None:
                raise _err("皮肤包缺少 skin.json")
            if int(manifest_info.file_size) > MAX_MANIFEST_BYTES:
                raise _err("皮肤包 skin.json 过大")
            try:
                manifest_raw = json.loads(archive.read(manifest_info).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise _err("皮肤包 skin.json 不是合法 JSON")
            manifest = self._normalize_manifest(manifest_raw)

            files: Dict[str, bytes] = {}
            bg_field = manifest_raw.get("background") if isinstance(manifest_raw, dict) else None
            if isinstance(bg_field, dict):
                bg_name = str(bg_field.get("file") or "")
                info = names.get(os.path.basename(bg_name))
                if info is None:
                    raise _err(f"皮肤背景图 {bg_name} 不在包内")
                if int(info.file_size) > MAX_BACKGROUND_BYTES:
                    raise _err("皮肤背景图超过 4 MB")
                files[os.path.basename(bg_name)] = archive.read(info)
            background = _normalize_background(bg_field, files)

        _check_contrast(manifest["vars"], manifest.get("mode") or "light")
        skin_id = manifest["id"]
        existed = self._load_external(skin_id) is not None
        target = self._skin_dir(skin_id)
        tmp = target + ".tmp"
        try:
            if os.path.isdir(tmp):
                shutil.rmtree(tmp, ignore_errors=True)
            os.makedirs(tmp, exist_ok=True)
            if background:
                data = files.get(os.path.basename(str(bg_field.get("file")))) or b""
                with open(os.path.join(tmp, background["file"]), "wb") as fh:
                    fh.write(data)
            manifest["background"] = background
            manifest["updated_at"] = utc_now()
            manifest["source_name"] = os.path.basename(str(filename or ""))[:120]
            with open(os.path.join(tmp, "skin.json"), "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, ensure_ascii=False, indent=2)
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
            os.replace(tmp, target)
        except OSError as exc:
            shutil.rmtree(tmp, ignore_errors=True)
            raise err("LAA-9001", message=f"保存皮肤包失败：{exc}")
        return {"skin": _public_meta(manifest, False), "updated": existed}

    def _decode(self, data_b64: str) -> bytes:
        text = str(data_b64 or "")
        if "," in text[:80] and text.lstrip().startswith("data:"):
            text = text.split(",", 1)[1]
        try:
            return base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError):
            raise _err("皮肤包内容不是合法的 base64")

    def _normalize_manifest(self, raw: Any) -> Dict[str, Any]:
        if not isinstance(raw, dict):
            raise _err("皮肤包 skin.json 必须是对象")
        unknown = sorted(k for k in raw if k not in ALLOWED_MANIFEST_KEYS)
        if unknown:
            raise _err(f"皮肤包包含未知字段 {', '.join(unknown)}")
        if raw.get("format") != FORMAT:
            raise _err(f"皮肤包格式标识必须是 {FORMAT}")
        try:
            version = int(raw.get("version"))
        except (TypeError, ValueError):
            raise _err("皮肤包 version 必须是整数")
        if version != FORMAT_VERSION:
            raise _err(f"皮肤包版本 {version} 不受支持（当前支持 {FORMAT_VERSION}）")
        skin_id = str(raw.get("id") or "").strip()
        if not _ID_RE.match(skin_id):
            raise _err("皮肤 id 只能用小写字母/数字/连字符，2–40 个字符且以字母开头")
        if skin_id in RESERVED_IDS:
            raise _err(f"皮肤 id {skin_id} 是内置保留标识")
        name = str(raw.get("name") or "").strip()
        if not name or len(name) > 60:
            raise _err("皮肤 name 必填且不超过 60 个字符")
        mode = str(raw.get("mode") or "").strip().lower()
        if mode not in ("light", "dark"):
            raise _err("皮肤 mode 只能是 light 或 dark")
        author = str(raw.get("author") or "").strip()
        description = str(raw.get("description") or "").strip()
        if len(author) > 80 or len(description) > 400:
            raise _err("皮肤 author / description 过长")
        vars_map = _normalize_vars(raw.get("vars"))
        if mode == "dark":
            missing = sorted(DARK_REQUIRED - set(vars_map))
            if missing:
                raise _err("深色皮肤必须提供完整变量，缺少：" + ", ".join(missing[:12])
                           + (" 等" if len(missing) > 12 else ""))
        effects = _normalize_effects(raw.get("effects"))
        return {
            "format": FORMAT, "version": FORMAT_VERSION, "id": skin_id,
            "name": name, "author": author, "description": description,
            "mode": mode, "vars": vars_map, "effects": effects, "background": None,
        }

    # ---- 导出 ----
    def export_package(self, skin_id: str) -> Dict[str, Any]:
        skin_id = str(skin_id or "").strip()
        if skin_id in BUILTIN_IDS:
            manifest = _builtin_manifest(skin_id)
            bg_bytes = None
        else:
            manifest = self._load_external(skin_id)
            if not manifest:
                raise err("LAA-3005", message="皮肤不存在，可能已被删除")
            bg_bytes = None
            background = manifest.get("background") or None
            if background:
                path = os.path.join(self._skin_dir(skin_id), str(background.get("file") or ""))
                try:
                    with open(path, "rb") as fh:
                        bg_bytes = fh.read(MAX_BACKGROUND_BYTES + 1)
                except OSError:
                    bg_bytes = None
        payload = {
            "format": FORMAT, "version": FORMAT_VERSION, "id": manifest["id"],
            "name": manifest["name"], "author": manifest.get("author") or "",
            "description": manifest.get("description") or "",
            "mode": manifest.get("mode") or "light",
            "vars": dict(manifest.get("vars") or {}),
            "effects": dict(manifest.get("effects") or {"glass": "off"}),
            "background": None,
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            if bg_bytes:
                background = manifest.get("background") or {}
                name = str(background.get("file") or "background.png")
                payload["background"] = {"file": name, "scrim": background.get("scrim", "medium")}
                archive.writestr(name, bg_bytes)
            archive.writestr("skin.json", json.dumps(payload, ensure_ascii=False, indent=2))
        data = buffer.getvalue()
        return {
            "filename": f"{manifest['id']}{PACKAGE_SUFFIX}",
            "data": base64.b64encode(data).decode("ascii"),
            "bytes": len(data),
        }

    # ---- 删除 ----
    def delete(self, skin_id: str) -> Dict[str, Any]:
        skin_id = str(skin_id or "").strip()
        if skin_id in BUILTIN_IDS:
            raise _err("内置皮肤不可删除")
        if not self._load_external(skin_id):
            raise err("LAA-3005", message="皮肤不存在，可能已被删除")
        shutil.rmtree(self._skin_dir(skin_id), ignore_errors=True)
        active = self._active_id()
        if active == skin_id:
            self.repo.set_config("app.skin.active", "default")
            self._notify_mode("light")
        return {"deleted": skin_id, "active": self._active_id()}
