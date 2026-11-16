// 开发演示数据源（仅当 VITE_MOCK=1 时经 src/api/laa.ts 使用，见 vite-env.d.ts）。
// 与真实桥接共享同一命令命名空间，输出严格按 dto 的 snake_case 字段；
// 用于在没有后端时预览 UI 渲染效果，不影响正式代码路径。
import { BridgeError } from "../bridge/client";
import type {
  CallDetail,
  GlossaryBank,
  GlossaryEntry,
  SceneProfileSummary,
  SegmentView,
  TranslationSnapshot,
  TranslationTask,
  UiEvent,
} from "../bridge/types";
import { DEFAULT_CAPABILITIES } from "../features/capability/registry";

const MOCK_TASK_ID = "01JZGSG8P0000000000000001";
const MOCK_CAPABILITIES = DEFAULT_CAPABILITIES;

const MOCK_SCENES: SceneProfileSummary[] = [
  {
    id: "academic-tech-neutral",
    name: "学术技术·中性",
    description: "技术文档、论文与研究报告的中性翻译",
    mode_default: "fluent",
    register: "formal",
    labels: ["academic", "tech", "neutral"],
    descriptors: ["客观中立", "术语精准", "句式严谨"],
    do: ["术语与原文一致", "保留公式与编号"],
    dont: ["口语化", "添加主观评价"],
    bank_ids: [],
    is_builtin: true,
    is_default: true,
    version: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "business-formal",
    name: "商务·正式",
    description: "合同、商务信函与正式往来",
    mode_default: "fluent",
    register: "formal",
    labels: ["business", "formal"],
    descriptors: ["正式得体", "用词严谨"],
    do: ["使用正式称谓", "保留法律与金额措辞"],
    dont: ["口语缩写", "娱乐化表达"],
    bank_ids: [],
    is_builtin: true,
    is_default: false,
    version: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "product-copy",
    name: "产品文案·营销",
    description: "营销文案、产品介绍与宣传",
    mode_default: "fluent",
    register: "semiformal",
    labels: ["marketing", "copy"],
    descriptors: ["有吸引力", "紧扣受众"],
    do: ["保留卖点", "语气有感染力"],
    dont: ["直译生硬", "夸大承诺"],
    bank_ids: [],
    is_builtin: true,
    is_default: false,
    version: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "casual-chat",
    name: "日常·随性",
    description: "聊天、社交媒体与日常交流",
    mode_default: "fluent",
    register: "informal",
    labels: ["casual", "chat"],
    descriptors: ["自然口语", "贴近日常"],
    do: ["口语化自然", "保留语气词"],
    dont: ["过于书面", "过度直译"],
    bank_ids: [],
    is_builtin: true,
    is_default: false,
    version: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
];

const MOCK_BANKS: GlossaryBank[] = [
  {
    id: "bank_personal",
    scope: "personal",
    name: "个人术语库",
    src_lang: "en",
    tgt_lang: "zh-Hans",
    domain: "general",
    readonly: 0,
    version: 3,
    entry_count: 3,
    owner: "me",
  },
  {
    id: "bank_builtin",
    scope: "builtin",
    name: "内置术语库",
    src_lang: "en",
    tgt_lang: "zh-Hans",
    domain: "general",
    readonly: 1,
    version: 1,
    entry_count: 2,
    owner: "system",
  },
];

const MOCK_ENTRIES: GlossaryEntry[] = [
  {
    id: "ent_1",
    bank_id: "bank_personal",
    source_term: "deadline",
    target_term: "截止日期",
    src_lang: "en",
    tgt_lang: "zh-Hans",
    domain: "general",
    part_of_speech: "n",
    definition: null,
    case_sensitive: 0,
    match_mode: "exact",
    forced: 1,
    status: "active",
    confidence: 0.9,
    origin: "manual",
    tags: ["work"],
    version: 2,
    refs: {},
    deleted_at: null,
    scene_variants: { "business-formal": "交付期限" },
  },
  {
    id: "ent_2",
    bank_id: "bank_personal",
    source_term: "migration",
    target_term: "迁移",
    src_lang: "en",
    tgt_lang: "zh-Hans",
    domain: "tech",
    part_of_speech: "n",
    definition: null,
    case_sensitive: 0,
    match_mode: "exact",
    forced: 0,
    status: "active",
    confidence: 0.8,
    origin: "auto",
    tags: [],
    version: 1,
    refs: {},
    deleted_at: null,
    scene_variants: {},
  },
  {
    id: "ent_3",
    bank_id: "bank_personal",
    source_term: "stack overflow",
    target_term: "栈溢出",
    src_lang: "en",
    tgt_lang: "zh-Hans",
    domain: "tech",
    part_of_speech: "n",
    definition: null,
    case_sensitive: 0,
    match_mode: "exact",
    forced: 0,
    status: "active",
    confidence: 0.75,
    origin: "manual",
    tags: [],
    version: 1,
    refs: {},
    deleted_at: null,
    scene_variants: {},
  },
  {
    id: "ent_4",
    bank_id: "bank_builtin",
    source_term: "API",
    target_term: "应用程序接口",
    src_lang: "en",
    tgt_lang: "zh-Hans",
    domain: "tech",
    part_of_speech: "n",
    definition: null,
    case_sensitive: 0,
    match_mode: "exact",
    forced: 1,
    status: "active",
    confidence: 1,
    origin: "official",
    tags: [],
    version: 1,
    refs: {},
    deleted_at: null,
    scene_variants: {},
  },
  {
    id: "ent_5",
    bank_id: "bank_builtin",
    source_term: "UI",
    target_term: "用户界面",
    src_lang: "en",
    tgt_lang: "zh-Hans",
    domain: "tech",
    part_of_speech: "n",
    definition: null,
    case_sensitive: 0,
    match_mode: "exact",
    forced: 1,
    status: "active",
    confidence: 1,
    origin: "official",
    tags: [],
    version: 1,
    refs: {},
    deleted_at: null,
    scene_variants: {},
  },
];

const MOCK_TASK: TranslationTask = {
  id: MOCK_TASK_ID,
  source_text: "Clean up the database before running the migration.",
  src_lang: "en",
  tgt_lang: "zh-Hans",
  detected_lang: "en",
  mode: "fluent",
  scene_profile_id: "academic-tech-neutral",
  resolved_scene: { profile_id: "academic-tech-neutral", name: "学术技术·中性", mode: "fluent", bank_ids: [], rules_hash: "", version: 1 },
  domain: "general",
  input_kind: "text",
  media_refs: null,
  status: "succeeded",
  checkpoint_seq: 2,
  resumable: false,
  risk_tier: "L0",
  routing: "auto_finalize",
  budget_limit: 0.5,
  cost_total: 0.001,
  segment_count: 2,
  created_at: new Date().toISOString(),
  completed_at: new Date().toISOString(),
};

const MOCK_SEGMENTS: SegmentView[] = [
  {
    segment_id: "01JZGSG8P0000000000000S01",
    source_text: "The server will ensure consistency across replicas.",
    target_text: "服务器将确保各副本之间的一致性。",
    spans: [
      { id: "sp_1", text: "服务器", span: [0, 3], kinds: ["terminology_applied"], term_ref: "term_server", variants: [{ id: "v1", label: "伺服器" }], confidence: 0.99, fix_ref: null, note: "" },
      { id: "sp_2", text: "将确保各副本之间的", span: [3, 12], kinds: [], term_ref: null, variants: [], confidence: null, fix_ref: null, note: "" },
      { id: "sp_3", text: "一致性", span: [12, 15], kinds: ["terminology_applied"], term_ref: "term_consistency", variants: [{ id: "v1", label: "一致性" }], confidence: 0.98, fix_ref: null, note: "" },
      { id: "sp_4", text: "。", span: [15, 16], kinds: [], term_ref: null, variants: [], confidence: null, fix_ref: null, note: "" },
    ],
    confidence: { segment_id: "01JZGSG8P0000000000000S01", score: 0.91, band: "high", drivers: [], method: "heuristic", threshold: 0.6 },
    emotions: [
      { emotion: "positive", intensity: 1, segment_id: "01JZGSG8P0000000000000S01", span: null, evidence: "consistent", note: "稳", confidence: 0.8, align_status: "matched" },
    ],
    risk: null,
    mode: "fluent",
    channel: "online",
    tones: [],
  },
  {
    segment_id: "01JZGSG8P0000000000000S02",
    source_text: "Clean up the database before running the migration.",
    target_text: "清理掉这个数据库之前运行这个迁移。 [AI TRANSLATED]",
    tones: [{ span: [22, 36], label: "催促" }],
    words: [
      { src: "Clean", target: "清理", alternatives: ["打扫", "清除"] },
      { src: "up", target: "掉", alternatives: ["完"] },
      { src: "the", target: "这个", alternatives: ["该"] },
      { src: "database", target: "数据库", alternatives: ["资料库"] },
      { src: "before", target: "之前", alternatives: ["在…之前"] },
      { src: "running", target: "运行", alternatives: ["执行"] },
      { src: "the", target: "这个", alternatives: ["该"] },
      { src: "migration.", target: "迁移。", alternatives: ["迁徙。"] },
    ],
    spans: [
      { id: "sp_5", text: "在运行", span: [0, 3], kinds: ["literal_style"], term_ref: null, variants: [], confidence: null, fix_ref: null, note: "" },
      { id: "sp_6", text: "迁移", span: [3, 5], kinds: ["terminology_applied"], term_ref: "term_migration", variants: [], confidence: 0.97, fix_ref: null, note: "" },
      { id: "sp_7", text: "之前清理", span: [5, 9], kinds: ["literal_style"], term_ref: null, variants: [], confidence: null, fix_ref: null, note: "" },
      { id: "sp_8", text: "数据库", span: [9, 12], kinds: ["low_confidence"], term_ref: null, variants: [], confidence: 0.42, fix_ref: "fix_1", note: "是否符合术语库用词待确认" },
      { id: "sp_9", text: "。", span: [12, 13], kinds: [], term_ref: null, variants: [], confidence: null, fix_ref: null, note: "" },
    ],
    confidence: { segment_id: "01JZGSG8P0000000000000S02", score: 0.54, band: "low", drivers: [], method: "heuristic", threshold: 0.6 },
    emotions: [
      { emotion: "urgent", intensity: 2, segment_id: "01JZGSG8P0000000000000S02", span: null, evidence: "before running", note: "顺序敏感", confidence: 0.75, align_status: "matched" },
    ],
    risk: { tier: "L1", reason: "术语一致性待确认" },
    mode: "literal",
    channel: "online",
  },
];

const MOCK_SNAPSHOT: TranslationSnapshot = {
  task: MOCK_TASK,
  segments: MOCK_SEGMENTS,
  checkpoint_seq: 2,
};

/** 以命令命名空间为 key 的演示应答工厂。 */
export async function mockInvoke<T, R>(cmd: string, _payload: T): Promise<R> {
  switch (cmd) {
    case "app.info":
      return { version: "0.1.0-mock", providers: [], capabilities: MOCK_CAPABILITIES } as unknown as R;
    case "capability.list":
      return { version: "0.1.0", items: MOCK_CAPABILITIES } as unknown as R;
    case "scene.list":
      return MOCK_SCENES as unknown as R;
    case "scene.manage": {
      const p = (_payload as Record<string, unknown> | null) ?? {};
      const action = String(p.action ?? "");
      if (action === "set_default") {
        return { default: String(p.scene_id ?? "") } as unknown as R;
      }
      if (action === "delete") {
        return { deleted: String(p.scene_id ?? "") } as unknown as R;
      }
      const sp = (p.scene_profile ?? {}) as Record<string, unknown>;
      const id = action === "save" && sp.id ? String(sp.id) : `scene_${Date.now()}`;
      const register = (["formal", "semiformal", "informal"].includes(
        String(sp.register),
      )
        ? String(sp.register)
        : "semiformal") as "formal" | "semiformal" | "informal";
      const saved: SceneProfileSummary = {
        id,
        name: String(sp.name ?? ""),
        description: String(sp.description ?? ""),
        mode_default: sp.mode_default === "literal" ? "literal" : "fluent",
        register,
        labels: [],
        descriptors: Array.isArray(sp.descriptors) ? (sp.descriptors as string[]) : [],
        do: Array.isArray(sp.do) ? (sp.do as string[]) : [],
        dont: Array.isArray(sp.dont) ? (sp.dont as string[]) : [],
        bank_ids: [],
        is_builtin: false,
        is_default: false,
        version: 1,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      return saved as unknown as R;
    }
    case "scene.ai": {
      const p = (_payload as Record<string, unknown> | null) ?? {};
      return {
        reply: "（离线演示）已按描述生成场景草稿，正式使用请接入真实模型。",
        scene_profile: {
          name: String(p.message ?? "自定义场景").slice(0, 24),
          description: "离线演示生成的场景草稿",
          register: "semiformal",
          mode_default: "fluent",
          descriptors: ["清晰", "自然"],
          do: ["保持术语一致"],
          dont: ["过度直译"],
          labels: [],
        },
      } as unknown as R;
    }
    case "usage.summary": {
      return {
        totals: { amount: 0.002184, input_tokens: 18420, output_tokens: 9120, calls: 12 },
        by_provider: [
          { k: "deepseek", input_tokens: 15420, output_tokens: 8120, amount: 0.0018, n: 9 },
          { k: "openai", input_tokens: 3000, output_tokens: 1000, amount: 0.000384, n: 3 },
        ],
        by_day: [
          { k: "2026-11-11", input_tokens: 5220, output_tokens: 2310, amount: 0.00062, n: 4 },
          { k: "2026-11-10", input_tokens: 13200, output_tokens: 6810, amount: 0.001564, n: 8 },
        ],
      } as unknown as R;
    }
    case "usage.list": {
      const p = (_payload as Record<string, unknown> | null) ?? {};
      const provider = p.provider ? String(p.provider) : "";
      const rows = Array.from({ length: 12 }, (_, i) => ({
        id: `usage_${i + 1}`,
        task_id: `task_${Math.floor(i / 3) + 1}`,
        segment_id: null,
        provider: i % 4 === 3 ? "openai" : "deepseek",
        model: i % 4 === 3 ? "gpt-4o-mini" : "deepseek-chat",
        purpose: i % 3 === 2 ? "qa" : "draft",
        input_tokens: 1200 + i * 37,
        output_tokens: 600 + i * 21,
        latency_ms: 900 + i * 40,
        amount: (1200 + i * 37) * 0.0000005 + (600 + i * 21) * 0.0000015,
        currency: "USD",
        created_at: `2026-11-11T${String(23 - Math.floor(i / 10)).padStart(2, "0")}:${String(59 - (i * 7) % 60).padStart(2, "0")}:00+00:00`,
      }));
      const filtered = provider ? rows.filter((r) => r.provider === provider) : rows;
      const limit = Number(p.limit ?? 50);
      const offset = Number(p.offset ?? 0);
      return {
        items: filtered.slice(offset, offset + limit),
        total: filtered.length,
      } as unknown as R;
    }
    case "history.list": {
      const p = (_payload as Record<string, unknown> | null) ?? {};
      const limit = Number(p.limit ?? 30);
      const offset = Number(p.offset ?? 0);
      const rows = [
        {
          task_id: MOCK_TASK_ID,
          source_text: "The compiler optimizes the loop, thanks for the detailed notes.",
          src_lang: "en",
          tgt_lang: "zh-Hans",
          mode: "literal",
          status: "succeeded",
          segment_count: 3,
          created_at: "2026-11-11T23:58:00+00:00",
          completed_at: "2026-11-11T23:58:06+00:00",
        },
        {
          task_id: "01JZGSG8P0000000000000002",
          source_text: "Please review the translation of the contract clause 4.2 before noon.",
          src_lang: "en",
          tgt_lang: "zh-Hans",
          mode: "fluent",
          status: "succeeded",
          segment_count: 2,
          created_at: "2026-11-11T22:31:00+00:00",
          completed_at: "2026-11-11T22:31:04+00:00",
        },
        {
          task_id: "01JZGSG8P0000000000000003",
          source_text: "这个方案我们再讨论一下，明天给你答复。",
          src_lang: "zh",
          tgt_lang: "en",
          mode: "fluent",
          status: "succeeded",
          segment_count: 1,
          created_at: "2026-11-10T18:12:00+00:00",
          completed_at: "2026-11-10T18:12:03+00:00",
        },
        {
          task_id: "01JZGSG8P0000000000000004",
          source_text: "Sorry for the late reply — the build broke and I had to fix it.",
          src_lang: "en",
          tgt_lang: "zh-Hans",
          mode: "literal",
          status: "failed",
          segment_count: 1,
          created_at: "2026-11-09T09:20:00+00:00",
          completed_at: null,
        },
        {
          task_id: "01JZGSG8P0000000000000005",
          source_text: "Good morning! Here is the agenda for today's sync.",
          src_lang: "en",
          tgt_lang: "zh-Hans",
          mode: "fluent",
          status: "succeeded",
          segment_count: 1,
          created_at: "2026-11-08T08:02:00+00:00",
          completed_at: "2026-11-08T08:02:02+00:00",
        },
      ];
      return { items: rows.slice(offset, offset + limit), total: rows.length } as unknown as R;
    }
    case "calls.list": {
      const p = (_payload as Record<string, unknown> | null) ?? {};
      const limit = Number(p.limit ?? 20);
      const offset = Number(p.offset ?? 0);
      const rows = [
        {
          id: "call_1",
          task_id: MOCK_TASK_ID,
          provider: "deepseek",
          model: "deepseek-chat",
          purpose: "draft",
          user_input: "The compiler optimizes the loop, thanks for the detailed notes.",
          input_tokens: 1840,
          output_tokens: 720,
          amount: 0.00092,
          latency_ms: 1280,
          created_at: "2026-11-11T23:58:00+00:00",
          response_preview: '{"segments":[{"segment_id":"seg_1","target_text":"编译器优化循环……"}]}',
        },
        {
          id: "call_2",
          task_id: "01JZGSG8P0000000000000002",
          provider: "deepseek",
          model: "deepseek-chat",
          purpose: "draft",
          user_input: "Please review the translation of the contract clause 4.2 before noon.",
          input_tokens: 960,
          output_tokens: 310,
          amount: 0.00048,
          latency_ms: 940,
          created_at: "2026-11-11T22:31:00+00:00",
          response_preview: '{"segments":[{"segment_id":"seg_1","target_text":"请在中午前审阅合同第 4.2 条的译文。"}]}',
        },
        {
          id: "call_3",
          task_id: "",
          provider: "fake",
          model: "offline",
          purpose: "qa",
          user_input: "ping",
          input_tokens: 12,
          output_tokens: 8,
          amount: 0,
          latency_ms: 5,
          created_at: "2026-11-10T18:12:00+00:00",
          response_preview: '{"segments":[],"emotions":"空"}',
        },
      ];
      return { items: rows.slice(offset, offset + limit), total: rows.length } as unknown as R;
    }
    case "calls.get": {
      const p = (_payload as Record<string, unknown> | null) ?? {};
      const callId = String(p.call_id ?? "");
      const detail: CallDetail = {
        id: callId || "call_1",
        task_id: MOCK_TASK_ID,
        provider: "deepseek",
        model: "deepseek-chat",
        purpose: "draft",
        user_input: "The compiler optimizes the loop, thanks for the detailed notes.",
        input_tokens: 1840,
        output_tokens: 720,
        amount: 0.00092,
        latency_ms: 1280,
        created_at: "2026-11-11T23:58:00+00:00",
        response_preview: '{"segments":[{"segment_id":"seg_1","target_text":"编译器优化循环……"}]}',
        prompt: {
          messages: [
            {
              role: "system",
              content:
                "你是专业翻译引擎。请只输出 JSON：{\"segments\":[{\"segment_id\":\"...\",\"target_text\":\"...\"}],\"emotions\":[...]}\n" +
                "风格与术语要求：技术文档，术语保持一致；语气保留原文。",
            },
            {
              role: "user",
              content:
                "原文（英文 → 简体中文，按段落翻译）：\n" +
                "1. The compiler optimizes the loop, thanks for the detailed notes.",
            },
          ],
        },
        response:
          '{\n  "segments": [\n    {\n      "segment_id": "seg_1",\n      "target_text": "编译器优化循环，感谢详细的说明。"\n    }\n  ],\n  "emotions": [{"emotion": "positive", "segment_id": "seg_1", "evidence": "thanks"}]\n}',
      };
      return detail as unknown as R;
    }
    case "translation.start":
      return { task_id: MOCK_TASK_ID, stream: {} } as unknown as R;
    case "translation.snapshot":
      return MOCK_SNAPSHOT as unknown as R;
    case "translation.cancel":
      return { cancelled: true } as unknown as R;
    case "translation.retranslate":
      return { task_id: MOCK_TASK_ID, queued: true } as unknown as R;
    case "translation.export":
      return { path: "/tmp/laa-export.txt" } as unknown as R;
    case "file.save_dialog":
      // mock 模式：无桌面原生对话框，前端应降级到浏览器文件选择器
      return { unsupported: true } as unknown as R;
    case "mode.set":
    case "mode.get":
      return { task_id: MOCK_TASK_ID, mode: "fluent" } as unknown as R;
    case "segment.word.pick": {
      const p = (_payload as Record<string, unknown> | null) ?? {};
      const segId = String(p.segment_id ?? "");
      const wi = Number(p.word_index ?? 0);
      const choice = String(p.choice ?? "");
      const base = MOCK_SEGMENTS.find((s) => s.segment_id === segId) ?? MOCK_SEGMENTS[0];
      const words = (base.words ?? []).map((w, i) => (i === wi && choice ? { ...w, target: choice } : w));
      return {
        ...base,
        words,
        target_text: words.map((w) => w.target).join("") + " [AI TRANSLATED]",
      } as unknown as R;
    }
    case "provider.list":
      // 内置离线引擎 fake 不出现在列表里，前端固定渲染。
      return [
        {
          id: "deepseek",
          name: "DeepSeek",
          kind: "translate",
          base_url: "https://api.deepseek.com/v1",
          model: "deepseek-chat",
          enabled: true,
          default: false,
          configured: true,
          preset: "deepseek",
        },
        {
          id: "openai",
          name: "OpenAI",
          kind: "translate",
          base_url: "https://api.openai.com/v1",
          model: "gpt-4o-mini",
          enabled: true,
          default: true,
          configured: false,
          preset: "openai",
        },
      ] as unknown as R;
    case "provider.upsert": {
      const p = ((_payload as Record<string, unknown> | null) ?? {}).profile as
        | Record<string, unknown>
        | null;
      const isDefault = p?.is_default === true;
      return { saved: true, default: isDefault } as unknown as R;
    }
    case "provider.test":
      return { ok: true, latency_ms: 87, detail: "连通" } as unknown as R;
    case "provider.delete":
      return { deleted: true } as unknown as R;
    case "glossary.package.list":
      return { items: MOCK_BANKS } as unknown as R;
    case "glossary.search": {
      const p = (_payload as Record<string, unknown> | null) ?? {};
      const bankId = String(p.bank_id ?? "bank_personal");
      const q = String(p.query ?? "").toLowerCase();
      let items = MOCK_ENTRIES.filter((e) => e.bank_id === bankId);
      if (q) {
        items = items.filter(
          (e) =>
            e.source_term.toLowerCase().includes(q) || e.target_term.toLowerCase().includes(q),
        );
      }
      return { items, total: items.length } as unknown as R;
    }
    case "glossary.manage": {
      const p = (_payload as Record<string, unknown> | null) ?? {};
      const action = String(p.action ?? "");
      if (action === "remove") {
        return { removed: String(p.entry_id ?? "") } as unknown as R;
      }
      const src = (p.entry ?? {}) as Record<string, unknown>;
      const id = `ent_${Date.now()}`;
      const created: GlossaryEntry = {
        id,
        bank_id: String(p.bank_id ?? "bank_personal"),
        source_term: String(src.source_term ?? ""),
        target_term: String(src.target_term ?? ""),
        src_lang: "en",
        tgt_lang: "zh-Hans",
        domain: String(src.domain ?? "general"),
        part_of_speech: null,
        definition: null,
        case_sensitive: 0,
        match_mode: "exact",
        forced: src.forced ? 1 : 0,
        status: "active",
        confidence: 0.9,
        origin: "manual",
        tags: [],
        version: 1,
        refs: {},
        deleted_at: null,
        scene_variants: (src.scene_variants as Record<string, string>) ?? {},
      };
      return { ok: true, entry: created } as unknown as R;
    }
    case "glossary.update": {
      const p = (_payload as Record<string, unknown> | null) ?? {};
      const entryId = String(p.entry_id ?? "");
      const src = (p.entry ?? {}) as Record<string, unknown>;
      const existing = MOCK_ENTRIES.find((e) => e.id === entryId);
      const base: GlossaryEntry = existing ?? ({
        id: entryId,
        bank_id: "bank_personal",
        source_term: "",
        target_term: "",
        src_lang: "en",
        tgt_lang: "zh-Hans",
        domain: "general",
        part_of_speech: null,
        definition: null,
        case_sensitive: 0,
        match_mode: "exact",
        forced: 0,
        status: "active",
        confidence: 0.8,
        origin: "manual",
        tags: [],
        version: 0,
        refs: {},
        deleted_at: null,
        scene_variants: {},
      } as GlossaryEntry);
      return {
        ...base,
        source_term: src.source_term !== undefined ? String(src.source_term) : base.source_term,
        target_term: src.target_term !== undefined ? String(src.target_term) : base.target_term,
        domain: src.domain !== undefined ? String(src.domain) : base.domain,
        forced: src.forced !== undefined ? (src.forced ? 1 : 0) : base.forced,
        scene_variants:
          src.scene_variants !== undefined
            ? (src.scene_variants as Record<string, string>)
            : base.scene_variants,
        version: base.version + 1,
      } as unknown as R;
    }
    case "glossary.import": {
      const p = (_payload as Record<string, unknown> | null) ?? {};
      const pkg = (p.package ?? {}) as { entries?: unknown };
      const count = Array.isArray(pkg.entries) ? pkg.entries.length : 0;
      return { inserted: count, updated: 0, skipped: 0 } as unknown as R;
    }
    case "glossary.export": {
      const p = (_payload as Record<string, unknown> | null) ?? {};
      const bankId = String(p.bank_id ?? "bank_personal");
      const items = MOCK_ENTRIES.filter((e) => e.bank_id === bankId);
      return {
        schema_version: 1,
        pack_id: `export-${bankId}`,
        entries: items.map((e) => ({ source_term: e.source_term, target_term: e.target_term })),
      } as unknown as R;
    }
    default:
      throw new BridgeError("LAA-1001", `mock 不支持的命令: ${cmd}`, false, { cmd });
  }
}

/** 演示事件泵：首次返回 task.completed，后续返回空批次（表示已收敛）。 */
export async function mockPollEvents(
  taskId: string,
  fromSeq: number,
): Promise<{ events: UiEvent[]; next_seq: number }> {
  if (fromSeq > 0 || taskId !== MOCK_TASK_ID) {
    return { events: [], next_seq: 2 };
  }
  const events: UiEvent[] = [
    {
      topic: "task.completed",
      payload: { task_id: MOCK_TASK_ID, status: "succeeded" },
      seq: 2,
      task_id: MOCK_TASK_ID,
    },
  ];
  return { events, next_seq: 2 };
}