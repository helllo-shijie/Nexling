// 公共 DTO / 值对象类型，字段名与 laa_core/shared/dto.py 的 snake_case 输出严格一致。
// 仅作前端类型约束，不做运行时校验。

export type TranslateMode = "fluent" | "literal";
export type TaskInputKind = "text" | "audio" | "document" | "image";
export type CapabilityStatus = "available" | "in_development" | "unavailable" | "roadmap";
export type TaskStatus =
  | "queued"
  | "preparing"
  | "running"
  | "paused"
  | "cancelling"
  | "cancelled"
  | "finalizing"
  | "succeeded"
  | "failed";
export type ConfidenceBand = "high" | "medium" | "low" | "unknown";
export type EmotionKind = "positive" | "negative" | "urgent" | "apology" | "emphasis" | "humor";
export type ModeScope = "rest" | "session";

/** TranslateRequest（dto.py） */
export interface TranslateRequest {
  text: string;
  target_lang: string;
  source_lang?: string | null;
  mode?: TranslateMode | null;
  scene_profile_id?: string | null;
  domain: string;
  task_hint?: string | null;
  session_id?: string | null;
  input_kind: TaskInputKind;
  media_refs?: unknown[] | null;
  stream: boolean;
  request_id?: string | null;
}

/** capability.list / app.info 中的能力视图（CapabilitySpec.to_view） */
export interface CapabilityView {
  id: string;
  name: string;
  group: string;
  stage: string;
  status: CapabilityStatus;
  entry_points: string[];
  command?: string | null;
  message_key: string;
  placeholder: boolean;
  available_since?: string | null;
  details_url?: string | null;
}

export interface AnnotatedSpanVariant {
  id: string;
  label: string;
  /** 候选译法的完整文本（用于替换） */
  text?: string;
  source?: string;
}

/** 句子级情感（span 相对 target_text；仅真实模型给出且能原样定位时存在） */
export interface SentenceSentiment {
  span: [number, number];
  text: string;
  positive: number;
  negative: number;
  neutral: number;
  label: "positive" | "negative" | "neutral";
  needs_review?: boolean;
}

/** 段落情感概率分布（总和 1） */
export interface SentimentDistribution {
  positive: number;
  negative: number;
  neutral: number;
  threshold: number;
  needs_review: boolean;
  /** 句子级情感；离线演示或模型未给出时为空/缺失（正文不做行内标注） */
  sentences?: SentenceSentiment[];
}

/** 翻译记忆命中 */
export interface MemoryHit {
  entry_id: string;
  source_text: string;
  target_text: string;
  score: number;
  match_kind: "exact" | "fuzzy" | "keyword" | string;
  glossary_version?: number;
  stale?: boolean;
}

/** 原文语气标注（span 相对 source_text） */
export interface ToneSpan {
  span: number[];
  label: string;
}

/** 工作台历史侧栏条目（history.list） */
export interface HistoryItem {
  task_id: string;
  source_text: string;
  src_lang: string;
  tgt_lang: string;
  mode: string;
  status: string;
  segment_count: number;
  created_at: string;
  completed_at?: string | null;
}

/** 术语发现候选（term.list / term.scan） */
export interface TermCandidate {
  id: string;
  normalized: string;
  source_term: string;
  target_term: string | null;
  lang: string;
  target_lang: string;
  task_id: string | null;
  segment_id: string | null;
  /** 翻译当时实际使用的术语库；为空表示未关联，采纳前需手动选择 */
  bank_id?: string;
  context: string;
  occurrences: number;
  confidence: number;
  status: "pending" | "accepted" | "ignored" | string;
  /** 质量分层：high ≥0.8 / medium ≥0.65 / low */
  quality?: "high" | "medium" | "low";
  /** 推荐理由：aligned（有对齐译词）/ repeated（反复出现）/ acronym（缩写） */
  reasons?: string[];
  created_at: string;
  updated_at: string;
}

export interface TermCandidateCounts {
  pending: number;
  accepted: number;
  ignored: number;
}

/** 候选术语三栏的条数上限；0 表示无上限 */
export interface TermCandidateLimits {
  pending: number;
  accepted: number;
  ignored: number;
}

/** 自动审批设置：默认关闭；阈值指待处理候选达到多少条时自动执行 */
export interface TermAutoReviewSettings {
  enabled: boolean;
  threshold: number;
  allow_manual: boolean;
}

/** 设置 → 术语 / 翻译记忆 / 长文本的容量与分批策略（settings.get / settings.save） */
export interface LongTextSettings {
  /** 硬上限；超过时明确报错而不是静默截断 */
  max_chars: number;
  /** 每批打包的字符预算 */
  batch_chars: number;
  /** 每批最多片段数 */
  batch_segments: number;
  /** 单批失败重试次数 */
  retries: number;
  /** 批间节流（毫秒） */
  throttle_ms: number;
}

export interface AppSettings {
  /** auto=超上限自动删最老；manual=只手动清理 */
  term_candidate_cleanup: "auto" | "manual";
  term_candidate_limits: TermCandidateLimits;
  /** 翻译记忆条数上限；0 表示无上限 */
  memory_limit: number;
  term_auto_review: TermAutoReviewSettings;
  /** 长文本分批与上限（V10） */
  long_text: LongTextSettings;
  /** 用量：调用历史保留策略与统计口径（V11） */
  usage: UsageCallsSettings;
}

/** 设置 → 用量 → 设置：调用历史保留与统计开关（只影响 calls 表，不动账单账本） */
export interface UsageCallsSettings {
  /** 保留条数；calls_unlimited=true 时忽略 */
  calls_retention: number;
  /** 无上限 */
  calls_unlimited: boolean;
  /** 0=不按天数清理；30 / 90 天 */
  calls_max_age_days: number;
  /** 统计概览页开关 */
  stats_enabled: boolean;
  /** 统计是否包含离线假引擎调用（花费恒为 0） */
  stats_include_offline: boolean;
}

/** usage.calls.status */
export interface UsageCallsStatus {
  count: number;
  /** 0 表示无上限 */
  limit: number;
  unlimited: boolean;
  /** 已有记录超过保留条数：只提示，等用户主动保存上限才清理 */
  over_limit: boolean;
  suggested: number;
  settings: UsageCallsSettings;
}

/** usage.stats：统计概览（来自 usage 账本，不受调用历史裁剪影响） */
export interface UsageStats {
  enabled: boolean;
  include_offline: boolean;
  totals: { calls: number; input_tokens: number; output_tokens: number; amount: number };
  by_day: { day: string; calls: number; input_tokens: number; output_tokens: number; amount: number }[];
  by_purpose: {
    purpose: string;
    calls: number;
    input_tokens: number;
    output_tokens: number;
    amount: number;
  }[];
  by_provider: { provider: string; calls: number; amount: number }[];
  range: { first_at: string | null; last_at: string | null };
}

/** 皮肤列表项（内置两套 + 已导入） */
export interface SkinSummary {
  id: string;
  name: string;
  author: string;
  description: string;
  mode: "light" | "dark";
  builtin: boolean;
  has_background: boolean;
  effects: Record<string, string>;
  updated_at: string;
}

/** skin.active / skin.select：变量表 + 可选背景图（data URL） */
export interface SkinView extends SkinSummary {
  vars: Record<string, string>;
  background: { data_url: string; scrim: "low" | "medium" | "high" } | null;
  active?: string;
}

/** term.auto_review.status 返回：可用性、阈值与上一轮批次 */
export interface TermAutoReviewStatus {
  enabled: boolean;
  threshold: number;
  allow_manual: boolean;
  available: boolean;
  reason: string;
  pending: number;
  last_batch: {
    id?: string;
    created_at?: string;
    counts?: { accepted?: number; ignored?: number; failed?: number };
  };
}

/** term.auto_review 的结果反馈 */
export interface TermAutoReviewResult {
  trigger: "auto" | "manual";
  processed: number;
  accepted_count: number;
  ignored_count: number;
  failed_count: number;
  skipped: number;
  accepted: string[];
  ignored: string[];
  failed: { id: string; source_term: string; reason: string }[];
  /** 高置信但未指定目标术语库：显式回报，保持待处理 */
  needs_bank: { id: string; source_term: string; reason: string }[];
  needs_bank_count: number;
  batch_id: string;
  counts: TermCandidateCounts;
  available?: boolean;
  reason?: string;
}

/** 设置 → 调用历史列表条目（calls.list） */
export interface CallSummary {
  id: string;
  task_id: string;
  provider: string;
  model: string;
  purpose: string;
  user_input: string;
  input_tokens: number;
  output_tokens: number;
  amount: number;
  latency_ms: number;
  created_at: string;
  response_preview: string;
}

/** 调用详情（calls.get）：完整提示词 + 回复 */
export interface CallDetail extends CallSummary {
  prompt: { messages: { role: string; content: string }[] };
  response: string;
}

/** 直译模式逐词对齐（后端 pipeline.norm_literal_words 产出） */
export interface LiteralWord {
  src: string;
  target: string;
  alternatives: string[];
  /** 首次生成的推荐译文；选中备选后保持不变 */
  recommended?: string;
  /** 完整候选集合（稳定顺序，推荐项在首位），选中只改 target */
  options?: string[];
}

/** AnnotatedSpan（dto.py） */
export interface AnnotatedSpan {
  id: string;
  text: string;
  span: number[];
  kinds: string[];
  term_ref?: string | null;
  variants?: AnnotatedSpanVariant[];
  confidence?: number | null;
  fix_ref?: string | null;
  note: string;
}

/** ConfidenceResult（dto.py） */
export interface ConfidenceResult {
  segment_id: string;
  score: number;
  band: ConfidenceBand;
  drivers?: unknown[];
  method: string;
  threshold: number;
}

/** EmotionAnnotation（dto.py） */
export interface EmotionAnnotation {
  emotion: EmotionKind;
  intensity: number;
  segment_id: string;
  span?: number[] | null;
  evidence: string;
  note: string;
  confidence: number;
  align_status: string;
}

/** SegmentView（dto.py）—— 核心渲染数据 */
export interface SegmentView {
  segment_id: string;
  source_text: string;
  target_text: string;
  spans: AnnotatedSpan[];
  /** 直译模式逐词对齐；流畅模式为空数组 */
  words?: LiteralWord[];
  /** 原文语气标注；无明显语气为空数组 */
  tones?: ToneSpan[];
  confidence: ConfidenceResult | null;
  emotions: EmotionAnnotation[];
  sentiment?: SentimentDistribution | null;
  /** 翻译记忆召回命中（后端按段查询后随视图下发） */
  tm_hits?: MemoryHit[];
  risk: { tier: string; reason?: string } | null;
  mode: TranslateMode;
  fix_record_id?: string | null;
  channel: string;
  /** 片段处理状态：pending / done / failed / cancelled（V10 分批进度） */
  status?: "pending" | "done" | "failed" | "cancelled" | string;
  /** 单句超长、无法在句子边界内切开时被强制按字数切分 */
  forced?: boolean;
  /** 当前译文版本号 */
  version_id?: string;
}

/** 任务级进度（translation.snapshot.progress / task.progress 事件） */
export interface TaskProgress {
  total: number;
  done: number;
  failed: number;
  cancelled: number;
  remaining: number;
  /** 计划批次数（含失败批次）；0 表示尚未开始 */
  batch_total: number;
  /** 已发出的模型调用数（真实调用后回填） */
  calls: number;
  input_tokens: number;
  output_tokens: number;
  /** 累计花费（USD） */
  cost: number;
}

/** translation.estimate 返回：提交前的分批与调用次数估算 */
export interface TranslationEstimate {
  chars: number;
  max_chars: number;
  over_limit: boolean;
  segments: number;
  batches: number;
  est_calls: number;
}

/** translation.retry 返回：只重跑失败/未完成片段 */
export interface TranslationRetryResult {
  task_id: string;
  queued: boolean;
  segment_count: number;
  /** 片段都已完成后收尾为成功（不重新调用模型） */
  finalized?: boolean;
}

/** TranslationTask（dto.py） */
export interface TranslationTask {
  id: string;
  source_text: string;
  src_lang: string;
  tgt_lang: string;
  detected_lang?: string | null;
  mode: TranslateMode;
  scene_profile_id?: string | null;
  resolved_scene: Record<string, unknown>;
  domain: string;
  input_kind: TaskInputKind;
  media_refs?: unknown[] | null;
  status: TaskStatus;
  checkpoint_seq: number;
  resumable: boolean;
  risk_tier: string;
  routing: string;
  budget_limit: number;
  cost_total: number;
  segment_count: number;
  /** 计划批次数（V10） */
  batch_total?: number;
  /** 失败批次明细 JSON（V10，失败时可重试） */
  failed_batches?: string;
  created_at: string;
  completed_at?: string | null;
}

/** 场景语域 formal / semiformal / informal */
export type SceneRegister = "formal" | "semiformal" | "informal";

/** scene.list 返回的场景档案（已扩展为完整 profile）。 */
export interface SceneProfileSummary {
  id: string;
  name: string;
  description: string;
  mode_default: TranslateMode;
  register?: SceneRegister | null;
  labels: string[];
  descriptors: string[];
  do: string[];
  dont: string[];
  examples?: string[] | Record<string, unknown>;
  bank_ids: string[];
  rules?: Record<string, unknown> | null;
  template_id?: string | null;
  is_builtin: boolean;
  is_default: boolean;
  version?: number;
  created_at?: string;
  updated_at?: string;
}

/** scene.manage create / save 的输入载荷。 */
export interface SceneProfileInput {
  id?: string;
  name: string;
  description?: string;
  register?: SceneRegister;
  mode_default?: TranslateMode;
  descriptors?: string[];
  do?: string[];
  dont?: string[];
}

/** scene.ai 对话中的单条消息。 */
export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

/** scene.ai 返回结果：助手回复 + 修复后的场景档案（结构固定，只能用于场景档案生成/修改）。 */
export interface SceneAiResult {
  reply: string;
  scene_profile: {
    name: string;
    description: string;
    register: SceneRegister;
    mode_default: TranslateMode;
    descriptors: string[];
    do: string[];
    dont: string[];
    labels: string[];
  };
}

/** UiEvent 信封（events.py） */
export interface UiEvent {
  topic: string;
  payload: Record<string, unknown>;
  seq: number;
  task_id?: string | null;
  trace_id?: string | null;
}

export interface InvokeOkBody<T> {
  ok: true;
  data: T;
  trace_id: string;
}

export interface InvokeErrorBody {
  ok: false;
  error: {
    code: string;
    message: string;
    retryable: boolean;
    details: Record<string, unknown>;
  };
  trace_id: string;
}

export interface AppInfo {
  version: string;
  providers: unknown[];
  capabilities: CapabilityView[];
}

export interface TaskStarted {
  task_id: string;
  stream: Record<string, unknown>;
  /** 提交时的分批与调用次数估算（V10） */
  estimate?: TranslationEstimate;
}

export interface TaskTerm {
  task_id: string;
  source_term: string;
  target_term: string;
  term_id?: string;
  origin: "model" | "glossary" | "user" | string;
  segment_id?: string;
  updated_at?: string;
}

export interface TranslationSnapshot {
  task: TranslationTask;
  segments: SegmentView[];
  checkpoint_seq: number;
  /** 任务级进度（V10：总片段 / 已完成 / 失败 / 剩余 / 批次数 / 实际调用与花费） */
  progress?: TaskProgress;
  /** 本文出现过的术语及实际译法（按任务持久化，可指定统一译法） */
  terms?: TaskTerm[];
}

export interface CancelResult {
  cancelled: boolean;
}

export interface RetranslateResult {
  task_id: string;
  queued: boolean;
}

export interface ExportResult {
  path: string;
}

/** provider.list 返回的在线供应商条目（内置离线引擎 fake 不出现在此列表）。 */
export interface ProviderProfile {
  id: string;
  name: string;
  kind: string;
  base_url: string;
  model: string;
  enabled: boolean;
  default: boolean;
  configured: boolean;
  preset: string;
  /** 用户显式确认过"允许自定义端点"（落库标记） */
  custom_endpoint: boolean;
  /** base_url 属于官方白名单 */
  official: boolean;
  /** 旧库非法地址：用户确认前不进入路由 */
  blocked: boolean;
}

/** provider.upsert 的 profile 载荷（注意使用 is_default）。 */
export interface ProviderUpsertProfile {
  id: string;
  name: string;
  kind: string;
  base_url: string;
  model: string;
  is_default: boolean;
  enabled: boolean;
  /** 勾选后允许自定义/中转 base_url（落库标记，用户可随时取消） */
  allow_custom_endpoint?: boolean;
}

export interface ProviderUpsertRequest {
  profile: ProviderUpsertProfile;
  api_key: string;
}

export interface ProviderUpsertResult {
  saved: boolean;
  default: boolean;
}

export interface ProviderTestRequest {
  provider_id: string;
  base_url: string;
  model: string;
  api_key: string;
  allow_custom_endpoint?: boolean;
}

export interface ProviderTestResult {
  ok: boolean;
  latency_ms: number;
  detail: string;
}

export interface ProviderDeleteResult {
  deleted: boolean;
}

/** glossary.package.list 返回的词库 DTO。readonly 为 0|1；scope!=='personal' 也视为只读。 */
export interface GlossaryBank {
  id: string;
  scope: string;
  name: string;
  src_lang: string;
  tgt_lang: string;
  domain: string;
  readonly: number;
  version: number;
  entry_count: number;
  owner: string;
}

/** glossary.search 返回的词条 DTO。case_sensitive / forced 为 0|1。 */
export interface GlossaryEntry {
  id: string;
  bank_id: string;
  source_term: string;
  target_term: string;
  src_lang: string;
  tgt_lang: string;
  domain: string;
  part_of_speech: string | null;
  definition: string | null;
  case_sensitive: number;
  match_mode: string;
  forced: number;
  status: string;
  confidence: number;
  origin: string;
  tags: string[];
  version: number;
  refs: Record<string, unknown>;
  deleted_at: string | null;
  scene_variants: Record<string, string>;
}

/** glossary.manage(add) / glossary.update 的 entry 输入载荷。forced 为布尔。 */
export interface GlossaryEntryInput {
  source_term?: string;
  target_term?: string;
  domain?: string;
  forced?: boolean;
  scene_variants?: Record<string, string>;
}

/** glossary.import / glossary.export 的术语包对象与条目。 */
export interface GlossaryPackageEntry {
  source_term: string;
  target_term: string;
  domain?: string;
  forced?: boolean;
  part_of_speech?: string;
  definition?: string;
  scene_variants?: Record<string, string>;
  [key: string]: unknown;
}

export interface GlossaryPackage {
  entries: GlossaryPackageEntry[];
  [key: string]: unknown;
}

/** glossary.import 返回的导入统计。 */
export interface GlossaryImportResult {
  inserted: number;
  updated: number;
  skipped: number;
}

/** usage.summary 的总计。amount 为 USD（6 位小数，可能极小）。 */
export interface UsageTotals {
  amount: number;
  input_tokens: number;
  output_tokens: number;
  calls: number;
}

/** usage.summary 的分组行（k = 供应商 id 或日期 "YYYY-MM-DD"）。 */
export interface UsageAggRow {
  k: string;
  input_tokens: number;
  output_tokens: number;
  amount: number;
  n: number;
}

export interface UsageSummary {
  totals: UsageTotals;
  by_provider: UsageAggRow[];
  by_day: UsageAggRow[];
}

/** usage.list 单条明细（按 created_at 倒序）。 */
export interface UsageRecord {
  id: string;
  task_id: string | null;
  segment_id: string | null;
  provider: string;
  model: string;
  purpose: string;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  amount: number;
  currency: string;
  created_at: string;
}