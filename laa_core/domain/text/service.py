"""Text processing: normalization, language detection, segmentation, token estimate.

Fully deterministic, no external deps. Only imports laa_core.shared.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional

from laa_core.shared import TextSegment, new_id

_CJK = (0x4E00, 0x9FFF)
_HIRAGANA = (0x3040, 0x309F)
_KATAKANA = (0x30A0, 0x30FF)
_HANGUL = (0xAC00, 0xD7AF)


class OffsetMap:
    """Bidirectional char-offset mapping between original and normalized text."""

    def __init__(self, norm_to_orig: List[int], orig_to_norm: List[int]):
        self.norm_to_orig = norm_to_orig
        self.orig_to_norm = orig_to_norm

    def to_original(self, span) -> list:
        start, end = int(span[0]), int(span[1])
        s = self.norm_to_orig[start] if start < len(self.norm_to_orig) else 0
        e = self.norm_to_orig[end - 1] + 1 if end > 0 and end - 1 < len(self.norm_to_orig) else start
        return [s, e]

    def to_normalized(self, span) -> list:
        start, end = int(span[0]), int(span[1])
        s = self.orig_to_norm[start] if start < len(self.orig_to_norm) else 0
        e = self.orig_to_norm[end - 1] + 1 if end > 0 and end - 1 < len(self.orig_to_norm) else start
        return [s, e]


class TextNormalizer:
    """Fullwidth->halfwidth, whitespace folding, invisible-char removal."""

    def normalize(self, text: str) -> dict:
        norm_to_orig: List[int] = []
        orig_to_norm: List[int] = [-1] * len(text)
        out: List[str] = []
        prev_space = False
        for idx, ch in enumerate(text):
            codepoint = ord(ch)
            # invisible / zero-width chars
            if ch in "\x00\u200b\u200c\u200d\ufeff" or unicodedata.category(ch) in ("Cc", "Cf"):
                orig_to_norm[idx] = len(out) if not prev_space else len(out) - 1
                continue
            nf = unicodedata.normalize("NFKC", ch)[0] if unicodedata.normalize("NFKC", ch) else " "
            # fold all whitespace to single space
            if nf.isspace():
                if not prev_space and out:
                    out.append(" ")
                    norm_to_orig.append(idx)
                elif not out:
                    out.append(" ")
                    norm_to_orig.append(idx)
                prev_space = True
                orig_to_norm[idx] = len(out) - 1 if out else 0
                continue
            prev_space = False
            orig_to_norm[idx] = len(out)
            out.append(nf)
            norm_to_orig.append(idx)
        normalized = "".join(out).strip()
        # strip trailing/leading spaces also fix mapping len
        return {"text": normalized, "offset_map": OffsetMap(norm_to_orig, orig_to_norm)}


def normalize_text(text: str) -> dict:
    return TextNormalizer().normalize(text)


class LanguageDetector:
    """Rule-based language detection (zh-Hans/zh-Hant/ja/ko/en + mixed hint)."""

    def detect(self, text: str, hint: Optional[str] = None) -> dict:
        # "auto"/空/None 都归一化为“无提示”，否则会被当成显式语言原样返回
        hint = (hint or "").strip()
        if hint.lower() in ("auto", "und", "unknown"):
            hint = ""
        if not text:
            return {"lang": "en", "confidence": 0.0, "mixed": [], "method": "empty"}
        cjk = hira = kata = hangul = latin = 0
        for ch in text:
            cp = ord(ch)
            if _CJK[0] <= cp <= _CJK[1]:
                cjk += 1
            elif _HIRAGANA[0] <= cp <= _HIRAGANA[1]:
                hira += 1
            elif _KATAKANA[0] <= cp <= _KATAKANA[1]:
                kata += 1
            elif _HANGUL[0] <= cp <= _HANGUL[1]:
                hangul += 1
            elif ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
                latin += 1
        total = max(1, cjk + hira + kata + hangul + latin)
        mixed = []
        if kana := (hira + kata):
            if latin and latin / total > 0.2:
                mixed.append("latin")
            lang = "ja"
        elif hangul:
            lang = "ko"
        elif cjk:
            lang = self._han_variant(text, cjk)
        elif latin:
            lang = "en"
            mixed.append("latin")
        else:
            lang = "und"
        confidence = round(max(cjk, hira, kata, hangul, latin) / total, 3)
        if hint:
            if not self._compatible(lang, hint):
                return {"lang": hint, "confidence": 0.9, "mixed": mixed, "method": "hint"}
        return {"lang": lang, "confidence": confidence, "mixed": mixed, "method": "script"}

    @staticmethod
    def _han_variant(text: str, cjk: int) -> str:
        trad_markers = "這個們來說話與從學時對國關個經為"
        trad_hits = sum(1 for ch in text if ch in trad_markers)
        return "zh-Hant" if trad_hits >= 3 else "zh-Hans"

    @staticmethod
    def _compatible(lang: str, hint: str) -> bool:
        base = lang.split("-")[0].lower()
        hbase = hint.split("-")[0].lower()
        return base == hbase or (base == "und") or (hbase in ("zh",) and base == "zh")


def detect_language(text: str, hint: Optional[str] = None) -> dict:
    return LanguageDetector().detect(text, hint)


_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;])\s*")
_HARD_SPLIT = re.compile(r"(?<=[，,、.\u3002])\s*")


_SENTENCE_RE = re.compile(r"(?:[^。！？!?；;]*[。！？!?；;]+|[^。！？!?；;]+)")

# 常见英文缩写：句点属于缩写本身，不能当作句末。
_ABBREVIATIONS = {
    "e.g", "i.e", "etc", "vs", "cf", "al", "mr", "mrs", "ms", "dr", "prof",
    "fig", "figs", "no", "nos", "inc", "ltd", "co", "jr", "sr", "st", "approx",
    "resp", "dept", "univ", "est", "min", "max", "avg", "sec", "ref", "refs",
    "eq", "eqs", "vol", "vols", "pp", "ch", "chap", "art", "para", "ph.d",
    "u.s", "u.k", "a.m", "p.m", "jan", "feb", "mar", "apr", "jun", "jul",
    "aug", "sep", "sept", "oct", "nov", "dec",
}


def _token_before_dot(text: str, dot: int) -> str:
    """取句点前连续的字词与内部句点（支持 e.g / Ph.D 这类多段缩写）。"""
    i = dot
    while i > 0 and (text[i - 1].isalnum() or text[i - 1] == "."):
        i -= 1
    return text[i:dot].strip().rstrip(".").lower()


def _dot_is_abbrev(text: str, dot: int) -> bool:
    token = _token_before_dot(text, dot)
    if not token:
        return False
    if token in _ABBREVIATIONS:
        return True
    # 单字母（人名首字母 J. / A.）也不在句点处断开
    return len(token) == 1 and token.isalpha()


def _cut_ok(text: str, cut: int) -> bool:
    """强制切分点是否安全：不切断单词、缩写与小数点。"""
    if cut <= 0 or cut >= len(text):
        return True
    prev, nxt = text[cut - 1], text[cut]
    if prev.isalnum() and nxt.isalnum():
        return False
    if nxt == "." and prev.isalpha():
        return False
    if prev == ".":
        if cut >= 2 and text[cut - 2].isdigit() and nxt.isdigit():
            return False
        if _dot_is_abbrev(text, cut - 1):
            return False
    return True


def _natural_cut(text: str, start: int, limit: int) -> int:
    """在 [limit-40, limit] 内回退到安全切点；找不到就用硬边界。"""
    hard = start + limit
    lo = max(start + 1, hard - min(40, limit // 4))
    for cut in range(hard, lo - 1, -1):
        if _cut_ok(text, cut) and text[cut - 1] in " \t\r\n，,、。；;：:！？!?":
            return cut
    for cut in range(hard, lo - 1, -1):
        if _cut_ok(text, cut):
            return cut
    return hard


def _sentence_spans(text: str) -> List[tuple]:
    """Return contiguous [start,end) sentence spans (lossless over the whole text).

    Terminators: 。！？!?；; always; ASCII '.' when not between digits and not
    part of a common abbreviation (e.g. / i.e. / etc. / Mr. / Fig.).
    """
    spans: List[tuple] = []
    start = 0
    n = len(text)
    for i, ch in enumerate(text):
        is_term = ch in "。！？!?；;"
        is_dot = ch == "." and not ((i > 0 and text[i - 1].isdigit()) and (i + 1 < n and text[i + 1].isdigit())) \
            and not _dot_is_abbrev(text, i)
        if is_term or is_dot:
            j = i + 1
            while j < n and text[j] in " \t\r":
                j += 1
            if j > start:
                spans.append((start, j))
                start = j
    if start < n:
        spans.append((start, n))
    elif not spans and n > 0:
        spans.append((0, n))
    return spans


_MAX_SEG_CHARS = 500


def _paragraph_spans(text: str) -> List[tuple]:
    """按空行/换行切段落，段落含其后的换行；覆盖率与原文一致（空白块会被跳过）。"""
    spans: List[tuple] = []
    n = len(text)
    start = 0
    i = 0
    while i < n:
        if text[i] in "\r\n":
            j = i
            while j < n and text[j] in "\r\n":
                j += 1
            if j > start:
                spans.append((start, j))
            start = j
            i = j
        else:
            i += 1
    if start < n:
        spans.append((start, n))
    if not spans and n > 0:
        spans.append((0, n))
    return spans


def _merge_tiny_spans(spans: List[tuple], text: str, min_len: int = 5) -> List[tuple]:
    """把标点误用产生的超短碎片并入相邻句，保持区间连续且不丢字。"""
    if len(spans) <= 1:
        return spans
    merged: List[tuple] = []
    for s, e in spans:
        if merged and len(text[s:e].strip()) < min_len:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    # 首句本身过短且后面还有内容时，并入后一句
    if len(merged) > 1 and len(text[merged[0][0]:merged[0][1]].strip()) < min_len:
        merged[0] = (merged[0][0], merged[1][1])
        merged.pop(1)
    return merged


def _spans_from_sentences(sentences: List[str]) -> Optional[List[tuple]]:
    """把模型返回的句子列表转成连续区间；拼接必须与原段落逐字一致。"""
    spans: List[tuple] = []
    pos = 0
    for s in sentences:
        if not isinstance(s, str) or not s:
            return None
        spans.append((pos, pos + len(s)))
        pos += len(s)
    return spans or None


class Segmenter:
    """分层切分：段落优先；超长段落优先用模型分句，失败时退回本地分句；单句仍超限时强制切分。"""

    def split(self, text: str, lang: str = "", estimator=None,
              max_chars: int = _MAX_SEG_CHARS, sentence_splitter=None) -> List[TextSegment]:
        raw = text
        limit = max(50, int(max_chars or _MAX_SEG_CHARS))
        segments: List[TextSegment] = []

        def mk(s: int, e: int, forced: bool = False) -> None:
            if e <= s or not raw[s:e].strip():
                return
            seg = self._mk(raw[s:e], s, e, len(segments), lang)
            seg.forced = forced
            segments.append(seg)

        for ps, pe in _paragraph_spans(raw):
            # 段尾换行属于分隔符，不并入片段文本（避免导出/记忆多出空行）
            while pe > ps and raw[pe - 1] in "\r\n":
                pe -= 1
            if pe - ps <= limit:
                mk(ps, pe)
                continue
            cur_s: Optional[int] = None
            cur_e = 0
            paragraph = raw[ps:pe]
            local_spans = _merge_tiny_spans(_sentence_spans(paragraph), paragraph)
            sent_spans: Optional[List[tuple]] = None
            if sentence_splitter is not None:
                try:
                    cand = sentence_splitter(paragraph)
                except Exception:  # noqa: BLE001 - 模型分句失败时退回本地兜底
                    cand = None
                if isinstance(cand, list) and "".join(cand) == paragraph:
                    sent_spans = _spans_from_sentences(cand)
            for ss, se in (sent_spans or local_spans):
                ss += ps
                se += ps
                if se - ss > limit:
                    # 单句超长：先收尾当前打包，再强制按字数切开（避开缩写/小数点/单词内部）
                    if cur_s is not None:
                        mk(cur_s, cur_e)
                        cur_s = None
                    pos = ss
                    while se - pos > limit:
                        cut = _natural_cut(raw, pos, limit)
                        if cut <= pos:
                            cut = pos + limit
                        mk(pos, cut, forced=True)
                        pos = cut
                    if pos < se:
                        mk(pos, se, forced=True)
                    continue
                if cur_s is None:
                    cur_s, cur_e = ss, se
                elif se - cur_s <= limit:
                    cur_e = se
                else:
                    mk(cur_s, cur_e)
                    cur_s, cur_e = ss, se
            if cur_s is not None:
                mk(cur_s, cur_e)
        return segments

    @staticmethod
    def _mk(txt: str, start: int, end: int, index: int, lang: str) -> TextSegment:
        return TextSegment(id=new_id(), index=index, text=txt, span=[start, end],
                           lang=lang, token_estimate=estimate_tokens(txt), status="pending")


def segment_text(text: str, lang: str = "", max_chars: int = _MAX_SEG_CHARS,
                 sentence_splitter=None) -> List[TextSegment]:
    segs = Segmenter().split(text, lang, max_chars=max_chars, sentence_splitter=sentence_splitter)
    for s in segs:
        s.token_estimate = estimate_tokens(s.text)
    return segs


def plan_batches(segments, max_chars: int = 2000, max_segments: int = 8) -> List[list]:
    """按字符预算与条数上限把片段打包成批；批内保持原顺序。"""
    limit = max(50, int(max_chars or 2000))
    cap = max(1, int(max_segments or 8))
    batches: List[list] = []
    cur: list = []
    used = 0
    for s in segments:
        txt = s.text if hasattr(s, "text") else str(s.get("text") or "")
        size = len(txt)
        if cur and (used + size > limit or len(cur) >= cap):
            batches.append(cur)
            cur = []
            used = 0
        cur.append(s)
        used += size
    if cur:
        batches.append(cur)
    return batches


class TokenEstimator:
    """Rough deterministic token estimate (cit ≈ 0.6/char, latin ≈ 1.3/word)."""

    def estimate(self, text: str, model: str = "") -> int:
        if not text:
            return 0
        return self._estimate(text)

    @staticmethod
    def _estimate(text: str) -> int:
        cjk = sum(1 for ch in text if _CJK[0] <= ord(ch) <= _CJK[1] or
                  _HIRAGANA[0] <= ord(ch) <= _HIRAGANA[1] or _HANGUL[0] <= ord(ch) <= _HANGUL[1] or
                  _KATAKANA[0] <= ord(ch) <= _KATAKANA[1])
        latin_words = len(re.findall(r"[a-zA-Z0-9]+(?:[''-][a-zA-Z0-9]+)*", text))
        other = max(0, len(re.sub(r"\s", "", text)) - cjk)
        import math

        return int(math.ceil(cjk * 0.6 + latin_words * 1.3 + other * 0.9))


def estimate_tokens(text: str, model: str = "") -> int:
    return TokenEstimator().estimate(text, model)