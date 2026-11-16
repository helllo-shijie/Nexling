"""Scene == Profile: the single preference model (§6.11/8.4).

Four builtin profiles; creation/toggle/default management; deterministic prompt build.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Dict, List, Optional

from laa_core.shared import (
    PromptPlan,
    ResolvedScene,
    SceneProfile,
    TranslateRequest,
    err,
    new_id,
    utc_now,
)
from laa_core.shared.types import TranslateMode


def _norm_name(name: str) -> str:
    import unicodedata

    return "".join(ch for ch in unicodedata.normalize("NFKC", name).lower() if not ch.isspace())


BUILTIN_PROFILES: List[SceneProfile] = [
    SceneProfile(
        id="academic-tech-neutral", name="学术技术·中性", description="技术文档、论文与研究报告的中性翻译",
        labels=["academic", "tech", "neutral"], mode_default=TranslateMode.FLUENT.value, register="formal",
        descriptors=["客观中立", "术语精准", "句式严谨"],
        do=["术语与原文一致", "保留公式与编号", "长句按逻辑切分"], dont=["口语化", "添加主观评价", "漏译引用"],
        examples=[{"source": "The latency is bounded by the cache miss rate.", "target": "延迟受限于缓存未命中率。"}],
        bank_ids=[], rules=[], template_id="academic", is_builtin=True, is_default=True, version=1,
        created_at="", updated_at="",
    ),
    SceneProfile(
        id="business-formal", name="商务·正式", description="合同、商务信函与正式往来",
        labels=["business", "formal"], mode_default=TranslateMode.FLUENT.value, register="formal",
        descriptors=["正式得体", "用词严谨", "语气专业"],
        do=["使用正式称谓", "保留法律与金额措辞", "语气得体"], dont=["口语缩写", "娱乐化表达", "省略免责条款"],
        examples=[{"source": "Please find the attached agreement for your review.", "target": "请查收所附协议,以便贵方审阅。"}],
        bank_ids=[], rules=[], template_id="business", is_builtin=True, is_default=False, version=1,
        created_at="", updated_at="",
    ),
    SceneProfile(
        id="product-copy", name="产品文案·营销", description="营销文案、产品介绍与宣传",
        labels=["marketing", "copy"], mode_default=TranslateMode.FLUENT.value, register="semiformal",
        descriptors=["有吸引力", "紧扣受众", "句式鲜活"],
        do=["保留卖点", "语气有感染力", "符合目标文化"], dont=["直译生硬", "夸大承诺", "丢失品牌调性"],
        examples=[{"source": "A smarter way to manage your tasks.", "target": "更聪明地管理你的任务。"}],
        bank_ids=[], rules=[], template_id="marketing", is_builtin=True, is_default=False, version=1,
        created_at="", updated_at="",
    ),
    SceneProfile(
        id="casual-chat", name="日常·随性", description="聊天、社交媒体与日常交流",
        labels=["casual", "chat"], mode_default=TranslateMode.FLUENT.value, register="informal",
        descriptors=["自然口语", "贴近日常", "轻松随意"],
        do=["口语化自然", "保留语气词", "简短直接"], dont=["过于书面", "过度直译", "僵硬"],
        examples=[{"source": "Hey, are we still on for tomorrow?", "target": "嘿,明天我们还照常吗?"}],
        bank_ids=[], rules=[], template_id="casual", is_builtin=True, is_default=False, version=1,
        created_at="", updated_at="",
    ),
]


class ModeController:
    def resolve(self, task_mode: Optional[str], scene: Optional[SceneProfile]) -> str:
        if task_mode in (TranslateMode.FLUENT.value, TranslateMode.LITERAL.value):
            return task_mode
        if scene is not None and scene.mode_default in (TranslateMode.FLUENT.value, TranslateMode.LITERAL.value):
            return scene.mode_default
        return TranslateMode.FLUENT.value

    def ensure_marker(self, text: str) -> str:
        if text.rstrip().endswith("[AI TRANSLATED]"):
            return text
        return text + " [AI TRANSLATED]"

    def build_constraints(self, mode: str, src: str, tgt: str) -> str:
        if mode == TranslateMode.LITERAL.value:
            return ("直译模式（逐词义项 · 保留原文语序）："
                    "1) 你的任务是逐词语义标注：把原文按词（或不可拆的固定搭配）切分后逐词对译，严格保持原文词序，"
                    "不合并分句、不省略、不调整语序、不做整句意译；"
                    "2) 每个词的 target 是**在本句语境与搭配下最贴切、最能让人读懂整句的义项**（推荐译法）："
                    "不要机械取该词孤立时的字典本义，也不要把整句或习语整体意译成一句话；"
                    "当某个词在特定结构里固定承担某种意思（疑问、度量、时间、数量等常见搭配）时，推荐该意思，"
                    "把该词孤立时的本义放到 alternatives 里作为备选；"
                    "3) target 必须是词或极短词组（通常 1~4 个汉字，或 1~2 个西文词），不能是整句、从句或润色后的表达；"
                    "4) alternatives 给出该词的其他可能义项（包含孤立本义），按在当前语境下的贴合度从高到低排列，同样是词义而非整句改写；"
                    "5) 为了让逐词拼接读得通，可以取该词在固定搭配里承担的那个义项；但每一格仍必须对应原文的那一个词，"
                    "不得把整句译文塞进某一格，也不得输出读不通的逐字硬拼；"
                    "6) words 中每个词的 target 按顺序拼接即为整句直译（中文等无空格语言直接相连，英文等用空格分隔），"
                    "标点附在前一个词的 target 末尾；target_text 必须与拼接结果一致，不得额外润色；"
                    "7) 判断标准：逐词拼接后的整句应当让读者大致看懂原意；宁可再生硬，也要逐词对应且义项选对。"
                    "段末输出标识 [AI TRANSLATED]。")
        return "流畅模式：以目标语言的自然表达重述,保持语义完整,符合目标语习惯。"


class SceneProfileService:
    def __init__(self, repo=None):
        self._repo = repo
        self._memory: Optional[Dict[str, SceneProfile]] = None

    def _profiles(self) -> Dict[str, SceneProfile]:
        if self._memory is not None:
            return self._memory
        if self._repo is None:
            self._memory = {p.id: deepcopy(p) for p in BUILTIN_PROFILES}
            return self._memory
        # seed builtins if absent
        names = {d["id"] for d in self._repo.list_scenes()}
        for bp in BUILTIN_PROFILES:
            if bp.id not in names:
                self._save(bp)
        self._memory = {d["id"]: self._to_profile(d) for d in self._repo.list_scenes()}
        return self._memory

    @staticmethod
    def _to_profile(d: Dict[str, Any]) -> SceneProfile:
        return SceneProfile(**d)

    def _save(self, profile: SceneProfile) -> None:
        if self._repo is not None:
            self._repo.save_scene(profile.to_dict())
        if self._memory is not None:
            self._memory[profile.id] = profile

    def list(self) -> List[Dict[str, Any]]:
        out = sorted(self._profiles().values(), key=lambda p: (-int(p.is_default), p.name))
        return [p.to_dict() for p in out]

    def get(self, scene_id: str) -> Optional[SceneProfile]:
        return self._profiles().get(scene_id)

    def norm(self, name: str) -> str:
        return _norm_name(name)

    def save(self, profile: SceneProfile) -> SceneProfile:
        profiles = self._profiles()
        key = self.norm(profile.name)
        for p in profiles.values():
            if self.norm(p.name) == key and p.id != profile.id:
                raise err("LAA-1002", message="场景名称已存在")
        if profile.id not in profiles:
            profile.id = new_id()
            profile.is_builtin = False
            profile.is_default = False
            profile.version = 1
            profile.created_at = utc_now()
        else:
            profile.version += 1
        profile.updated_at = utc_now()
        self._save(profile)
        return profile

    def save_from_dict(self, d: Dict[str, Any]) -> Dict[str, Any]:
        sid = d.get("id")
        if sid and sid in self._profiles():
            base = self._profiles()[sid]
            merged = {**base.to_dict(), **{k: v for k, v in d.items() if v is not None}}
        else:
            merged = {**SceneProfile(id=new_id(), name="", version=1).to_dict(),
                      **{k: v for k, v in d.items() if v is not None}}
        saved = self.save(self._to_profile(merged))
        return saved.to_dict()

    def duplicate(self, scene_id: str, new_name: str) -> SceneProfile:
        src = self._profiles().get(scene_id)
        if src is None:
            raise err("LAA-7006", message="场景档案不存在")
        copy = deepcopy(src)
        copy.id = new_id()
        copy.name = new_name
        copy.is_builtin = False
        copy.is_default = False
        copy.version = 1
        copy.created_at = utc_now()
        copy.updated_at = utc_now()
        self._save(copy)
        return copy

    def delete(self, scene_id: str) -> Dict[str, Any]:
        p = self._profiles().get(scene_id)
        if p is None:
            raise err("LAA-7006", message="场景档案不存在")
        if p.is_builtin or p.is_default:
            raise err("LAA-4004", message="内置或默认场景不可删除")
        self._profiles().pop(scene_id, None)
        if self._repo is not None:
            self._repo.delete_scene(scene_id)
        return {"deleted": scene_id}

    def set_default(self, scene_id: str) -> Dict[str, Any]:
        if scene_id not in self._profiles():
            raise err("LAA-7006", message="场景档案不存在")
        for p in self._profiles().values():
            if p.is_default and p.id != scene_id:
                p.is_default = False
                self._save(p)
        target = self._profiles()[scene_id]
        target.is_default = True
        self._save(target)
        return {"default": scene_id}

    def resolve(self, ref: Optional[str]) -> ResolvedScene:
        profiles = self._profiles()
        if ref and ref in profiles:
            p = profiles[ref]
        else:
            p = next((x for x in profiles.values() if x.is_default), None) or next(iter(profiles.values()))
        rules_hash = hashlib.sha256(json.dumps({"rules": p.rules}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
        return ResolvedScene(profile_id=p.id, name=p.name, mode=p.mode_default,
                             bank_ids=list(p.bank_ids), rules_hash=rules_hash, version=p.version)


_TARGET_LANG_NAMES = {
    "zh-hans": "简体中文", "zh": "中文", "en": "英语", "ja": "日语", "ko": "韩语",
    "fr": "法语", "de": "德语", "es": "西班牙语", "ru": "俄语", "auto": "自动",
}


class PromptComposer:
    def compose(self, req: TranslateRequest, scene: SceneProfile, glossary_block: str = "",
                mode: str = TranslateMode.FLUENT.value, segments: Optional[List[Any]] = None,
                locked_terms: str = "") -> PromptPlan:
        mode = mode or (scene.mode_default if scene else TranslateMode.FLUENT.value)
        mode = mode if mode in (TranslateMode.FLUENT.value, TranslateMode.LITERAL.value) else TranslateMode.FLUENT.value
        lang_name = _TARGET_LANG_NAMES.get((req.target_lang or "").lower(), req.target_lang)
        system_parts = [f"你是翻译引擎,目标语言 {lang_name}（{req.target_lang}）,源语言由你自动识别，不要假设源语言。"]
        if scene is not None:
            system_parts.append(f"场景:{scene.name}。{scene.description or ''}")
            if scene.descriptors:
                system_parts.append("风格:" + "、".join(scene.descriptors) + "。")
            if scene.do:
                system_parts.append("要求:" + "；".join(scene.do) + "。")
            if scene.dont:
                system_parts.append("禁止:" + "；".join(scene.dont) + "。")
            if scene.examples:
                ex = "；".join(f"{e.get('source','')}→{e.get('target','')}" for e in scene.examples[:2])
                system_parts.append(f"示例:{ex}。")
        system_parts.append(ModeController().build_constraints(mode, req.source_lang or "", req.target_lang))
        system_parts.append(
            "语气识别（原文侧）：逐段判断原文语气，只有明显特殊语气才标注"
            "（例如 讽刺、愤怒、警告、催促、亲昵、正式、客套、犹豫、命令、调侃），中性陈述不要标注。"
            "tones 里每条给出 start、end、label：start/end 是该语气片段在本段原文中的字符下标"
            "（左闭右开、从 0 开始、按 Unicode 字符计），label 用 2~4 个汉字概括语气；"
            "没有明显语气时 tones 输出空数组 []。译文侧必须保留原文语气，不得抹平成中性。"
        )
        system_parts.append(
            "情感概率（逐段）：sentiment 给出 positive / negative / neutral 三个 0~1 的概率，三项相加为 1，"
            "用于衡量该段原文整体情感倾向；中性陈述请让 neutral 明显偏高，不要把中性内容强行判成积极或消极。"
        )
        system_parts.append(
            "句子级情感（仅流畅模式）：在每段里额外给出 sentences 数组，由你按语义给原文分句后再逐句标注译文情感。"
            "每条写成 {\"source\":\"原文中的完整一句（必须从该段原文原样连续复制，不得改写）\","
            "\"text\":\"该句译文（必须从 target_text 原样复制同一句，不得改写）\","
            "\"sentiment\":{\"positive\":0.7,\"negative\":0.1,\"neutral\":0.2}}；三项概率相加为 1。"
            "分句规则：按语义成句，不要机械按每个句号/问号切割；标点误用、残句、语气词碎片要合并成完整一句，"
            "没有标点的长句也要能切成完整句。所有 source 按顺序拼接后必须与原文该段完全一致（不吞字、不重复）；"
            "所有 text 按顺序拼接后必须与 target_text 完全一致；对不齐时服务端会整段丢弃句子标注并降级为段落级。"
            "没有把握的句子直接省略，不要猜。"
        )
        system_parts.append(
            "候选译法（仅流畅模式）：variants 给出 0~2 个最值得比较的短语替换方案；"
            "text 必须是 target_text 中已出现的连续片段，options 是 1~3 个可直接替换该片段的说法（更直白或更书面），"
            "不要给整句改写；没有合适片段时输出 []。"
        )
        if mode == TranslateMode.LITERAL.value:
            system_parts.append(
                "输出必须是 JSON 对象:{\"segments\":[{\"segment_id\":\"...\",\"target_text\":\"由 words 的 target 依序拼接而成，不得润色\","
                "\"words\":[{\"src\":\"原文词\",\"target\":\"该词在当前语境下的推荐义项\",\"alternatives\":[\"其他义项1\",\"其他义项2\"]}],"
                "\"terms\":[{\"source\":\"原文术语\",\"target\":\"target_text 中的实际译法\"}],"
                "\"tones\":[{\"start\":0,\"end\":5,\"label\":\"讽刺\"}],"
                "\"sentiment\":{\"positive\":0.7,\"negative\":0.1,\"neutral\":0.2}}],"
                "\"emotions\":[{\"emotion\":\"positive|negative|urgent|apology|emphasis|humor\",\"segment_id\":\"...\","
                "\"evidence\":\"...\",\"intensity\":1,\"note\":\"\"}] 或 \"空\"}。"
                "words 按原文词序覆盖本段所有词（含虚词）。每个词的 target 是**当前语境下最贴切的推荐义项**（词或极短词组），"
                "要让人逐词拼起来能读懂整句，而不是取孤立字典本义或整句意译；alternatives 是该词其他义项（含孤立本义），"
                "按贴合度从高到低排列，也是词义。tones 没有明显语气时给 []。"
                "每段的 segment_id 必须与下方输入分段给出的 id 完全一致。不要输出除 JSON 外的任何文字。"
            )
        else:
            system_parts.append(
                "输出必须是 JSON 对象:{\"segments\":[{\"segment_id\":\"...\",\"target_text\":\"...\","
                "\"tones\":[{\"start\":0,\"end\":5,\"label\":\"讽刺\"}],"
                "\"sentiment\":{\"positive\":0.7,\"negative\":0.1,\"neutral\":0.2},"
                "\"sentences\":[{\"source\":\"原文中的一句\",\"text\":\"译文中的一句\",\"sentiment\":{\"positive\":0.6,\"negative\":0.1,\"neutral\":0.3}}],"
                "\"terms\":[{\"source\":\"原文术语\",\"target\":\"target_text 中的实际译法\"}],"
                "\"variants\":[{\"text\":\"译文中的连续片段\",\"options\":[\"更直白的说法\",\"更书面的说法\"]}]}],"
                "\"emotions\":[{\"emotion\":\"positive|negative|urgent|apology|emphasis|humor\",\"segment_id\":\"...\","
                "\"evidence\":\"...\",\"intensity\":1,\"note\":\"\"}] 或 \"空\"}。"
                "tones 没有明显语气时给 []。每段的 segment_id 必须与下方输入分段给出的 id 完全一致。"
                "terms 只列本段真实出现的术语：source 必须能在该段原文中找到，target 必须是 target_text 中实际使用的译法；"
                "对不上就省略，不要编造。同一术语在全篇必须使用同一译法，已给出「已定译法」时不得另起新译。"
                "不要输出除 JSON 外的任何文字。"
            )
        user_parts = [f"原文:\n{req.text}"]
        if segments:
            numbered = "\n".join(f"[{getattr(s, 'id', '')}] {getattr(s, 'text', '')}" for s in segments)
            user_parts.append(f"输入分段(逐段翻译,保留此 segment_id):\n{numbered}")
        if glossary_block:
            user_parts.append(f"术语约束(必须逐条落实):\n{glossary_block}")
        if locked_terms:
            user_parts.append(
                "已定译法(全篇统一，必须沿用，与术语库冲突时以本表为准):\n"
                + locked_terms
            )
        user_parts.append("请逐段翻译，并给出情感概率、原文语气标注与候选译法。")

        fingerprint_src = json.dumps({
            "template": scene.template_id if scene else "default", "mode": mode,
            "glossary": glossary_block, "locked": locked_terms, "target": req.target_lang,
        }, sort_keys=True, ensure_ascii=False)
        fingerprint = hashlib.sha256(fingerprint_src.encode("utf-8")).hexdigest()

        return PromptPlan(
            template_id=scene.template_id if scene else "default",
            template_version="1",
            messages=[{"role": "system", "content": "\n".join(system_parts)},
                      {"role": "user", "content": "\n".join(user_parts)}],
            mode=mode,
            scene_profile_id=scene.id if scene else None,
            scene_version=scene.version if scene else 1,
            glossary_terms=[],
            output_schema={"type": "json_object"},
            max_output_tokens=2048,
            literal_flag=(mode == TranslateMode.LITERAL.value),
            fingerprint=fingerprint,
        )