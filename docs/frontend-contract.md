# 前端桥接契约（webui）

## 1. 传输

- Base URL = 空字符串（同源）。后端由 `laa_core/bridge/http_server.py` 提供，开发期与静态资源同源。
- 命令调用：`POST /api/invoke`，请求体 `{"cmd": string, "payload": object, "request_id"?: string}`。
  响应：`{"ok": true, "data": object, "trace_id": string}` 或 `{"ok": false, "error": {"code":"LAA-xxxx","message":string,"retryable":bool,"details":object}, "trace_id": string}`。
- 事件拉取（轮询）：`GET /api/events?task_id=<id>&from_seq=<n>` → `{"events": [UiEvent,...], "next_seq": int}`。
  `UiEvent = {"topic": string, "payload": object, "seq": int, "task_id"?: string, "trace_id"?: string}`。
  V10 新增 `task.progress`：`{total, done, failed, cancelled, remaining, batch, batch_total, status}`，每批结束发出一次；
  界面以它驱动进度条，片段文本仍由 `segment.view` 追加。
  V11 新增 `skin.*`（皮肤列表/切换/导入/导出/删除）与 `usage.stats`、`usage.calls.*`、`usage.settings.save`；
  `file.save_dialog` 增加 `base64_encoded`，用于 `.nxlskin` 二进制导出。
- 能力清单也可直接 `invoke("capability.list")`。

## 2. 关键命令（字段与 §6.2 一致，snake_case）

- `app.info` → `{version, providers, capabilities}`。
- `capability.list {group?}` → `{version, items: [CapabilityView]}`。
- `translation.start <TranslateRequest>` → `{task_id, stream: {...}, estimate}`；随后事件流。
  `TranslateRequest = {text, target_lang="zh-Hans", source_lang?, mode?("fluent"|"literal"), scene_profile_id?, domain="general", input_kind="text"}`。
  `estimate = {chars, max_chars, over_limit, segments, batches, est_calls}`；超过 `max_chars` 时抛 `LAA-3002`（不截断）。
- `translation.estimate {text}` → `{chars, max_chars, over_limit, segments, batches, est_calls}`：提交前估算，超限时前端应阻止提交并提示。
- `translation.snapshot {task_id, from_seq?}` → `{task, segments: [SegmentView], checkpoint_seq, progress, terms: [TaskTerm]}`。
  `progress = {total, done, failed, cancelled, remaining, batch_total, calls, input_tokens, output_tokens, cost}`；
  `calls / input_tokens / output_tokens / cost` 为真实调用后由成本账本回填的实际值。
- `translation.cancel {task_id}` → `{cancelled: bool}`：批次间生效，已完成片段保留，未完成片段标 `cancelled`
  （含首批尚未开始就取消：所有未开始片段都落为 `cancelled`，可直接重试）。
- `translation.retry {task_id}` → `{task_id, queued, segment_count, finalized?}`：只重跑 `failed / pending / cancelled` 片段；
  片段其实已全部 `done` 但任务停在 `paused` 时不做模型调用，直接收尾为 `succeeded` 并返回 `finalized: true`。
- `task.term.list {task_id}` → `{task_id, items: [TaskTerm]}`；
  `task.term.set {task_id, source_term, target_term}` → `{task_id, term: TaskTerm, affected, rewritten, segment_ids, queued, matched, already}`：
  写入用户指定译法；旧译法可在译文中定位时直接替换（`rewritten`，不调用模型），
  其余受影响片段进入 `segment_ids` 并重译（`queued=true`），不整篇重翻。
  命中/替换按 ASCII 词边界、CJK 子串（与翻译记忆失效同一套规则）；`matched` 为原文含该术语的片段数，
  `already` 为译法已一致的片段数，`matched=0` 表示本文没有该术语，界面应如实提示而不是“已统一”。
  `TaskTerm = {task_id, source_term, target_term, term_id, origin("model"|"glossary"|"user"), segment_id, updated_at}`；
  同一术语的优先级 `user > glossary > model`，低优先级不覆盖高优先级。
- `mode.set {task_id, mode, scope:"rest"|"session"}` / `mode.get {task_id}`。
- `translation.retranslate {task_id, segment_ids?}` → `{task_id, queued}`。
- `translation.export {task_id, format:"txt"|"md"|"json", include_meta}` → `{path?}`（`txt` 纯译文；`md` 双语对照；`json` 含元数据与逐段情感）。
- `segment.variant.pick {task_id, segment_id, span_id, variant_id}` → 更新后的 `SegmentView`（候选译法替换，保存新版本）。
- `segment.override {task_id, segment_id, target_text, origin?}` → 更新后的 `SegmentView`（人工改译 / 采用翻译记忆）。
- `memory.lookup {source_text, src_lang, tgt_lang, domain?}` → `[TmHit]`；`TmHit = {entry_id, source_text, target_text, score, match_kind("exact"|"fuzzy"|"keyword"), glossary_version, stale}`。
- `memory.list {query?, lang_pair?, include_stale?, limit?, offset?}` → `{items: [MemoryRow], total, pairs}`；
  `MemoryRow = {entry_id, source_text, target_text, lang_pair, domain, approved, quality, stale, use_count, last_used_at}`。
- `memory.delete {entry_id}` → `{entry_id, deleted}`（翻译记忆管理页）。
- `scene.list` → `[SceneProfileSummary]`；`scene.manage {action:"create"|"save"|"delete"|"set_default", scene_profile?, source_id?}`。
- `glossary.search {bank_id, query, limit}` / `glossary.import` / `glossary.export {bank_id}` / `glossary.promote`。
- `term.scan {task_id}` → `{scanned, items: [TermCandidate], counts, auto_review?}`：从任务原文按规则抽取候选术语并落库（不调模型）；开启自动审批且达到阈值时 `auto_review` 返回本轮结果或不可用原因。
- `term.list {status:"pending"|"accepted"|"ignored"}` → `{items: [TermCandidate], counts: {pending, accepted, ignored}}`。
- `term.accept {id, target_term, bank_id?}` → `{ok, entry, candidate, counts}`：写入术语库并把候选标记为 accepted。
- `term.ignore {ids:[...]}` → `{ignored:[id], counts}`：标记为 ignored，之后扫描不再产生同名词形。
  `TermCandidate = {id, normalized, source_term, target_term, lang, target_lang, task_id, segment_id, context, occurrences, confidence, status, created_at, updated_at}`。
- `term.clear {status:"pending"|"accepted"|"ignored"|"all", task_id?}` → `{removed, counts}`：手动清空候选栏（不删除已写入术语库的词条）。
- `term.auto_review.status {task_id?}` → `{enabled, threshold, allow_manual, available, reason, pending, last_batch}`：
  `available=false` 时 `reason` 必须展示（离线演示 / 未配置密钥 / 配置不完整）。
- `term.auto_review {task_id?}` → `{trigger:"manual", processed, accepted_count, ignored_count, failed_count, skipped, accepted, ignored, failed:[{id,source_term,reason}], needs_bank:[{id,source_term,reason}], needs_bank_count, batch_id, counts}`；
  规则：高置信（≥0.8）且有译词→采纳；高置信但未指定术语库→计入 `needs_bank` 并保持待处理；
  低置信（<0.65）或单次无译词→忽略；其余保持待处理；不可用时抛 `LAA-1002`。
- `term.auto_review.undo {batch_id?}` → `{restored, restored_ignored, counts}`：把本轮自动采纳**与自动忽略**的候选都恢复为待处理，
  并撤销本轮新建/改写词条。
- `settings.get` → `{term_candidate_limits:{pending,accepted,ignored}, term_candidate_cleanup:"auto"|"manual", memory_limit, term_auto_review:{enabled,threshold,allow_manual}, long_text:{max_chars,batch_chars,batch_segments,retries,throttle_ms}, usage:{calls_retention,calls_unlimited,calls_max_age_days,stats_enabled,stats_include_offline}}`；
  `settings.save {settings}` → `{settings, removed:{term_candidates, memory}, auto_review?}`。上限 `0` 表示无上限，超限自动删最老记录。
  `long_text` 边界：`max_chars` 1000–5,000,000、`batch_chars` 200–20,000、`batch_segments` 1–50、`retries` 0–5、`throttle_ms` 0–5000；越界抛 `LAA-1002`。
  `usage.calls_retention` 100–200,000（`calls_unlimited=true` 时不裁剪）；`calls_max_age_days` 仅 `0/30/90`。
  **普通 `settings.save` 不裁剪调用历史**，只更新配置。
- `usage.stats` → `{totals:{calls,input_tokens,output_tokens,amount}, by_day:[{day,calls,input_tokens,output_tokens,amount}], by_purpose, by_provider, range, exclude_offline, stats_enabled}`；只读 `usage` 账本。
- `usage.calls.status` → `{count, limit, unlimited, over_limit, max_age_days}`；超限只提示，不删除。
- `usage.settings.save {usage}` → `{settings, removed:{calls}, calls}`；**仅此命令**在用户主动保存时按保留条数裁剪。
- `usage.calls.cleanup {days:0|30|90}` → `{removed, days, cutoff, calls}`；`days=0` 表示不按天数清理，
  原样返回 `removed=0` 且一条不删；只删 `calls`，不动 `usage`。界面在选 0 时禁用清理按钮，
  30/90 天清理需二次确认。
- `usage.calls.clear` → `{removed, billing, calls}`；`billing` 为清空后的账单汇总，用于确认聚合未被清除。
- `provider.list` / `provider.upsert {profile, secret_handle?}` / `provider.test {provider_id}`。
- `cost.summary {range, group_by}` / `memory.add {task_id, segment_id}` / `memory.delete {entry_id}` / `memory.lookup {source_text, src_lang, tgt_lang}` / `diagnostics.export`。
  `memory.add` 仅接受在线渠道译文：离线/演示译文与空句对返回 `LAA-1002`；返回 `{entry_id, entry, removed}`，写入后受记忆上限约束。
- `usage.summary` → `{totals, by_provider, by_day}`；`usage.list {limit?, offset?, provider?}` → `{items: [UsageRecord], total}`。
- `history.list {limit?, offset?}` → `{items: [{task_id, source_text, src_lang, tgt_lang, mode, status, segment_count, created_at, completed_at?}], total}`（工作台历史侧栏）。
- `calls.list {limit?, offset?, task_id?}` → `{items: [CallSummary], total}`；`CallSummary = {id, task_id, provider, model, purpose, user_input, input_tokens, output_tokens, amount, latency_ms, created_at, response_preview}`。
- `calls.get {call_id}` → `CallDetail = CallSummary + {prompt: {messages: [{role, content}]}, response}`（设置 → 调用历史详情，提示词默认只展示 `user_input`）。
- `skin.list` → `{active, items:[SkinSummary]}`；`SkinSummary = {id, name, author, description, mode:"light"|"dark", builtin, has_background:boolean, effects:{glass:"on"|"off"}, updated_at}`。
- `skin.active` → `SkinView`；`SkinView = SkinSummary + {vars: Record<string,string>, background:null|{data_url, scrim:"low"|"medium"|"high"}, active?}`。
- `skin.select {id}` → `SkinView`（即时生效，不重载页面；深色会同步 DWM 标题栏）。
- `skin.import {filename, data}` → `{skin, updated}`；`data` 为单文件包的 base64，导入校验白名单、深色完整性与 5 MB 上限；同 ID 为更新。
- `skin.export {id}` → `{filename, data(base64), bytes}`；只含 `skin.json` 与可选背景图，**不含截图**。
- `skin.delete {id}` → `{deleted, active}`；内置皮肤拒绝删除，删除当前外置皮肤会回退 `default`。
- `file.save_dialog {suggested_name, content, base64_encoded?}` → 原生保存对话框；`base64_encoded=true` 时按字节写入，用于 `.nxlskin` 导出。

## 3. 核心渲染数据 `SegmentView`

`{segment_id, index, source_text, target_text, spans:[AnnotatedSpan], words?:[{src,target,alternatives,recommended?,options?}], tones?:[{span:[s,e],label}], sentiment:null|{positive,negative,neutral,threshold,needs_review,sentences?:[{span:[s,e],text,positive,negative,neutral,label,needs_review}]}, confidence:null|{score,band}, emotions:[EmotionAnnotation], risk:null|{tier,reason}, mode, channel, status, forced}`。

`words[]` 的 `recommended` 是首次生成的推荐译文，`options` 是稳定顺序的完整候选（推荐项在首位）；
`segment.word.pick` 只把 `target` 改为所选项，不重排 `options`、不改 `recommended`，
前端据此把「推荐」标签固定留给原推荐项，另用当前态标记实际采用项。
`status` 为片段处理状态（`pending` / `done` / `failed` / `cancelled`）：无译文时界面应显示对应状态而不是空白；
`forced=true` 表示单句超长被按字数强制切分，界面需给出标记与解释。
`index` 为该段在任务中的顺序号（从 1 开始）；`sentiment` 为 0–1 概率，`needs_review` 由阈值判定，界面需给出人工确认提示。
`sentences` 为句子级情感，`span` 相对 `target_text`，`text` 必须与区间内容完全一致，且对应原文分句必须与 `source_text` 逐字对齐；
任一条缺失/对不齐/出现“很。”“到你”这类碎片时整段丢弃（段落级展示），界面不得自行猜测。离线演示不产生句子级标注。
`channel` 为 `online` 或 `offline`；`offline` 时情感概率来自关键词规则，界面必须标注“离线演示 · 规则估算”，不能只当作纯概率展示。
`AnnotatedSpan = {id, text, span:[s,e], kinds:[...], term_ref?, variants:[{id,label,source?,text?}], confidence?, fix_ref?, note?}`。
候选译法的 `variants[i].text` 与 `label` 都是该候选的译文片段（同一个字符串），`variants[i].source` 是候选来源标签（`model` / `literal` / `glossary`），不是区间；span 自身的 `span:[s,e]` 才是当前译文里的位置。`kinds` 含 `alternate_translation` 时界面用点线下划线区分。
`kinds` 含 `source_lang_kept` 时表示译文中保留的原文中文，界面加浅色细下划线（仅当目标语言非中文时产生）。
`EmotionAnnotation = {emotion, intensity, segment_id, span?, evidence, note, confidence, align_status}`。
`tones` 的 span 相对 `source_text`，label 为 2~4 个汉字语气词；无语气时为空数组（界面不标注）。
`words` 仅直译模式有值；点词改义用 `segment.word.pick {task_id, segment_id, word_index, choice}`。

## 4. 能力注册表（12 条 + message_key）

| capability_id | name | group | status |
|---|---|---|---|
| translation.text | 文本翻译 | input | available |
| glossary.personal | 个人术语库 | extend | available |
| glossary.official | 官方术语包 | extend | available |
| glossary.discovery | 术语自动发现 | extend | available |
| glossary.community | 开源术语仓库 | extend | roadmap |
| input.voice | 语音输入 | input | roadmap |
| output.voice | 语音朗读 | output | roadmap |
| input.document | 文档翻译 | input | roadmap |
| extend.plugin | 插件 | extend | roadmap |
| platform.multi | 多端使用 | platform | roadmap |
| model.local | 本地能力 | extend | roadmap |

**占位入口要求（历史说明）**：早期版本要求占位入口与可用入口外观一致并弹 toast；V1 起改为**不再在主界面出现空壳入口**，
统一收进「设置 → 路线图」并标注阶段与状态（`available` 5 条 / `roadmap` 7 条）。

## 5. 页面

1. 工作台 Workbench：输入区（textarea + 发送）、模式分段控件（流畅/直译，默认流畅）、场景档案选择器（顶部）、
   长文本进度条（已完成/失败/剩余/批次数/调用与花费，失败片段可重试）、结果区（SegmentList + SpanRenderer + 置信度/情感/气泡，
   每段带圆形加号按钮写入翻译记忆、已加入显示对勾并可撤回）。
2. 设置 Settings：模型（供应商配置 + 本地能力占位）、翻译（长文本上限与分批参数）、术语（候选上限 / 清理策略 / 翻译记忆条数上限）、翻译场景、存储、关于（多端占位）、扩展（插件占位）。
3. 术语候选（术语库 → 「候选术语」页签，glossary.discovery）。

## 6. 技术栈与约束

- React 18 + TypeScript + Vite + Zustand；样式用纯 CSS/CSS-Module 或 Tailwind 均可（优先纯 CSS 减少构建风险）。
- 不给后端写死中文文案之外的业务判定；错误码 `LAA-2005` → 提示"正在开发中"。
- 渲染全部按纯文本（React 默认转义），禁止 `dangerouslySetInnerHTML`。