"""从 webui 样式源码派生皮肤对比度校验配对。

为什么要有这个脚本：手工维护配对清单，每加一个组件就会漏。这里把
「选择器块里的文字色变量 × 底色变量」直接扫出来，生成
`laa_core/domain/skin/contrast_pairs.json`，运行时校验只读这份产物；
测试会重新派生并与产物比对，样式加配对但没重新生成时测试直接失败。

派生规则（与真实渲染一致的最小近似）：
- 同一规则块里同时出现文字色（`color`）与底色（`background` / `background-color` /
  `background-image` 里的颜色变量）时，两两配对；
- 只设了底色、没设文字色的块（如 `.span--risk`），文字继承正文色，按 `--text` 配对；
- 只设了文字色的块，组件可能落在页面或卡片上，对 `--bg` 与 `--surface` 各配一次；
- `text-decoration-color` 只画下划线，不承载文字，不参与派生。

阈值按前景语义决定：正文类 4.5，其余（次要文字、链接、状态/语义色）3.0。
确实不承载文字的装饰性底色（图表柱、滚动条、遮罩、色条）按“具体配对”进白名单，
必须逐条写理由；白名单不支持整变量通配。

用法：
    python tools/derive_contrast_pairs.py           # 重新生成 JSON
    python tools/derive_contrast_pairs.py --check   # 只检查是否与样式一致
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
STYLE_ROOT = ROOT / "webui" / "src" / "styles"
OUT_FILE = ROOT / "laa_core" / "domain" / "skin" / "contrast_pairs.json"

sys.path.insert(0, str(ROOT))
from laa_core.domain.skin.service import COLOR_KEYS  # noqa: E402

COLOR_KEY_SET = set(COLOR_KEYS)
TEXT_PROPERTIES = {"color"}
BACKGROUND_PROPERTIES = {"background", "background-color", "background-image"}
BODY_TEXT_VAR = "--text"
BODY_TEXT_MIN = 4.5
SECONDARY_MIN = 3.0
BODY_TEXT_KEYS = {
    "--text": 4.5,
    "--code-fg": 4.5,
    "--toast-fg": 4.5,
}

_VAR_RE = re.compile(r"var\(\s*(--[a-z0-9-]+)")
_STATE_RE = re.compile(
    r"::?(?:hover|focus|focus-visible|focus-within|active|disabled|checked|placeholder|"
    r"first-child|last-child|before|after)\b")
_COMBINATOR_RE = re.compile(r"\s*[>+~]\s*|\s+")

# 逐条白名单：确实不承载文字的装饰性底色。必须写明理由，且只豁免具体配对。
# 不要在这里写 “--chart-bar” 之类的整变量豁免。
WHITELIST: Dict[Tuple[str, str], str] = {
    ("--text", "--chart-bar"): "图表柱形/折线是纯图形，不含文字",
    ("--text", "--sent-pos-mark"): "句子情感色条是左侧装饰线，不含文字",
    ("--text", "--sent-neg-mark"): "句子情感色条是左侧装饰线，不含文字",
    ("--text", "--sent-neu-mark"): "句子情感色条是左侧装饰线，不含文字",
    ("--text", "--scrollbar-thumb"): "滚动条滑块，不承载文字",
    ("--text", "--scrollbar-track"): "滚动条轨道（透明），不承载文字",
    ("--text", "--scrim"): "弹层遮罩，文字在遮罩之上另行配对",
    ("--text", "--scrim-soft"): "轻遮罩，文字在遮罩之上另行配对",
    ("--text", "--accent"): "状态圆点/色块等纯图形元素，不含文字",
    ("--text", "--positive"): "情感占比条为纯色块，不含文字",
    ("--text", "--negative"): "情感占比条为纯色块，不含文字",
    ("--text", "--neutral"): "情感占比条为纯色块，不含文字",
    ("--text", "--accent-line"): "行左侧强调细线，不承载文字",
    ("--text", "--border-strong"): "进度条填充/滚动条滑块，纯图形",
    ("--text", "--risk-fg"): "进度条失败态填充，纯图形",
}


def iter_rules(text: str) -> Iterable[Tuple[str, List[str], int]]:
    """按大括号层级切出规则块，返回 (选择器, 声明列表, 行号)。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    frames: List[dict] = []
    prelude: List[str] = []
    line = 1
    for index, ch in enumerate(text):
        if ch == "{":
            frames.append({
                "selector": "".join(prelude).strip(),
                "decls": [],
                "children": 0,
                "line": line,
            })
            prelude = []
        elif ch == "}":
            if frames:
                frame = frames.pop()
                if frames:
                    frames[-1]["children"] += 1
                if frame["children"] == 0:
                    yield frame["selector"], frame["decls"], frame["line"]
            prelude = []
        elif ch == ";":
            if frames:
                decl = "".join(prelude).strip()
                if decl:
                    frames[-1]["decls"].append(decl)
            prelude = []
        else:
            prelude.append(ch)
        if ch == "\n":
            line += 1


def _vars_in(value: str) -> List[str]:
    return [v for v in _VAR_RE.findall(value) if v in COLOR_KEY_SET]


def _declarations(decls: Iterable[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for decl in decls:
        if ":" not in decl:
            continue
        prop, value = decl.split(":", 1)
        out[prop.strip().lower()] = value.strip()
    return out


def minimum_for(fg: str) -> float:
    return BODY_TEXT_KEYS.get(fg, SECONDARY_MIN)


def _selector_bases(selector: str) -> List[str]:
    """把选择器化简成可用于查找继承文字色的候选：去掉状态伪类，再取最后一个复合选择器。"""
    bases: List[str] = []
    for part in selector.split(","):
        normalized = " ".join(part.split())
        normalized = _STATE_RE.sub("", normalized).strip()
        if normalized and normalized not in bases:
            bases.append(normalized)
        last = _COMBINATOR_RE.split(normalized)[-1] if normalized else ""
        if last and last not in bases:
            bases.append(last)
    return bases


def derive(css_texts: Dict[str, str]) -> Tuple[Dict[Tuple[str, str], Set[str]], Dict[str, Set[str]]]:
    """返回 (配对 -> 选择器集合, 用到的颜色变量 -> 选择器集合)。"""
    rules: List[Tuple[str, str, int, Set[str], Set[str]]] = []
    used: Dict[str, Set[str]] = {}
    colors: Dict[str, Set[str]] = {}

    for filename, text in css_texts.items():
        for selector, decls, line in iter_rules(text):
            if not selector or selector.startswith("@"):
                continue
            props = _declarations(decls)
            where = f"{filename}:{line} {selector}"
            fgs: Set[str] = set()
            bgs: Set[str] = set()
            for prop, value in props.items():
                if prop in TEXT_PROPERTIES:
                    fgs.update(_vars_in(value))
                elif prop in BACKGROUND_PROPERTIES:
                    bgs.update(_vars_in(value))
            for var in fgs | bgs:
                used.setdefault(var, set()).add(where)
            for base in _selector_bases(selector):
                colors.setdefault(base, set()).update(fgs)
            rules.append((selector, where, line, fgs, bgs))

    pairs: Dict[Tuple[str, str], Set[str]] = {}

    def add(fg: str, bg: str, selector: str) -> None:
        if (fg, bg) in WHITELIST:
            return
        pairs.setdefault((fg, bg), set()).add(selector)

    for selector, where, _line, fgs, bgs in rules:
        if fgs and bgs:
            for fg in fgs:
                for bg in bgs:
                    add(fg, bg, where)
        elif bgs:
            inherited: Set[str] = set()
            for base in _selector_bases(selector):
                if colors.get(base):
                    inherited |= colors[base]
                    break
            for bg in bgs:
                for fg in inherited or {BODY_TEXT_VAR}:
                    add(fg, bg, where)
        elif fgs:
            for fg in fgs:
                add(fg, "--bg", where)
                add(fg, "--surface", where)
    return pairs, used


def load_styles(root: Path = STYLE_ROOT) -> Dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8")
            for path in sorted(root.glob("*.css"))}


def build_entries(pairs: Dict[Tuple[str, str], Set[str]]) -> List[dict]:
    entries = [{"fg": fg, "bg": bg, "min": minimum_for(fg)} for fg, bg in sorted(pairs)]
    return entries


def load_artifact(path: Path = OUT_FILE) -> List[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)["pairs"]


def compare(derived: Dict[Tuple[str, str], Set[str]], saved: List[dict]) -> List[str]:
    """返回人类可读的差异列表；为空表示产物与样式一致。"""
    saved_pairs = {(item["fg"], item["bg"]) for item in saved}
    problems: List[str] = []
    for pair in sorted(set(derived) - saved_pairs):
        selectors = ", ".join(sorted(derived[pair]))
        problems.append(f"缺少配对 {pair[0]} / {pair[1]}（来自 {selectors}）")
    for pair in sorted(saved_pairs - set(derived)):
        problems.append(f"多余配对 {pair[0]} / {pair[1]}（样式里已不存在）")
    for item in saved:
        pair = (item["fg"], item["bg"])
        if pair in derived and float(item["min"]) != minimum_for(pair[0]):
            problems.append(f"阈值不一致 {pair[0]} / {pair[1]}：产物 {item['min']}，派生 {minimum_for(pair[0])}")
    return problems


def uncovered(derived: Dict[Tuple[str, str], Set[str]], used: Dict[str, Set[str]]) -> List[str]:
    covered: Set[str] = set()
    for fg, bg in derived:
        covered.add(fg)
        covered.add(bg)
    for fg, bg in WHITELIST:
        covered.add(fg)
        covered.add(bg)
    problems = []
    for var in sorted(set(used) - covered):
        selectors = ", ".join(sorted(used[var]))
        problems.append(f"颜色变量 {var} 没有被任何配对覆盖（用于 {selectors}）")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    derived, used = derive(load_styles())
    if args.check:
        problems = compare(derived, load_artifact()) + uncovered(derived, used)
        for problem in problems:
            print(problem)
        return 1 if problems else 0

    OUT_FILE.write_text(
        json.dumps({"pairs": build_entries(derived)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"已写入 {OUT_FILE}：{len(derived)} 组配对")
    for problem in uncovered(derived, used):
        print(problem)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
