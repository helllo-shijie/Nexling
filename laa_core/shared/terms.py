"""术语命中与替换：ASCII 按词边界，CJK 按子串。

术语库失效、任务术语统一等场景共用同一套规则，避免各写一份后判断不一致
（例如 `cache` 不应命中 `cachegate`，CJK 术语按子串命中 `神经元的`）。
"""
from __future__ import annotations

import re
from typing import Tuple

_ASCII_BOUNDARY = r"(?<![A-Za-z0-9_]){}(?![A-Za-z0-9_])"


def term_pattern(term: str) -> re.Pattern:
    return re.compile(_ASCII_BOUNDARY.format(re.escape(term)), re.IGNORECASE)


def term_hit(text: str, term: str) -> bool:
    """文本中是否出现了该术语（ASCII 词边界 / CJK 子串）。"""
    term = (term or "").strip()
    if not text or not term:
        return False
    if term.isascii():
        return bool(term_pattern(term).search(text))
    return term.lower() in text.lower()


def replace_term(text: str, old: str, new: str) -> Tuple[str, int]:
    """按同一套命中规则替换术语译法，返回 (新文本, 替换次数)。"""
    old = (old or "").strip()
    new = (new or "").strip()
    if not text or not old or not new or old == new:
        return text, 0
    if old.isascii():
        return term_pattern(old).subn(new, text)
    return re.compile(re.escape(old), re.IGNORECASE).subn(new, text)
