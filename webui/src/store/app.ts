// 应用全局状态（Zustand）。
// 状态：capabilities / task / segments / mode / scene / busy（+ scenes / termAutoReview 等）。
// 动作：submit / cancel / setMode / retranslate / applyEvent（+ bootstrap / setScene 等）。
import { create } from "zustand";
import { invoke, pollEvents } from "../api/laa";
import { saveBinaryFile } from "../bridge/nativeSave";
import { mark } from "../perf/marks";
import type {
  AppSettings,
  CallDetail,
  CallSummary,
  CapabilityView,
  ChatTurn,
  GlossaryBank,
  GlossaryEntry,
  GlossaryEntryInput,
  GlossaryImportResult,
  GlossaryPackage,
  HistoryItem,
  ModeScope,
  ProviderProfile,
  ProviderTestRequest,
  ProviderTestResult,
  ProviderUpsertProfile,
  ProviderUpsertResult,
  SceneProfileInput,
  SceneProfileSummary,
  SceneAiResult,
  SegmentView,
  SkinSummary,
  SkinView,
  TermAutoReviewResult,
  TermAutoReviewStatus,
  TaskTerm,
  TermCandidate,
  TermCandidateCounts,
  TranslationSnapshot,
  TranslationEstimate,
  TranslationRetryResult,
  TranslationTask,
  TranslateMode,
  TaskProgress,
  UiEvent,
  UsageRecord,
  UsageCallsSettings,
  UsageCallsStatus,
  UsageStats,
  UsageSummary,
} from "../bridge/types";
import { DEFAULT_CAPABILITIES } from "../features/capability/registry";
import { notifyInfo } from "./notice";
import { setUiLang, errorText, t, type UiLang } from "../i18n/ui";

/** 顶层视图 id（提升到 store 供设置页等跨组件跳转）。 */
export type AppView = "workbench" | "settings" | "glossary";

interface AppState {
  capabilities: CapabilityView[];
  task: TranslationTask | null;
  segments: SegmentView[];
  /** 本文术语→实际译法（任务级，后续批次与用户指定共用） */
  terms: TaskTerm[];
  scenes: SceneProfileSummary[];
  scene: SceneProfileSummary | null;
  mode: TranslateMode;
  /** 目标语言（源语言始终自动识别） */
  targetLang: string;
  /** 界面语言（本版：中文 / English） */
  uiLang: UiLang;
  setUiLang: (lang: UiLang) => void;
  busy: boolean;
  error: string | null;
  checkpointSeq: number;
  /** 任务级进度（V10：分批翻译的总片段 / 已完成 / 失败 / 剩余 / 调用与花费） */
  progress: TaskProgress | null;
  /** 提交时的分批与调用次数估算（真实调用后由 progress 回填实际值） */
  estimate: TranslationEstimate | null;
  capabilitiesLoaded: boolean;
  providers: ProviderProfile[];
  view: AppView;
  banks: GlossaryBank[];
  glossaryEntries: GlossaryEntry[];
  glossaryBankId: string;
  glossaryLoading: boolean;
  /** 术语发现候选（术语库 → 候选术语） */
  termCandidates: TermCandidate[];
  termCounts: TermCandidateCounts;
  termStatus: "pending" | "accepted" | "ignored";
  termLoading: boolean;
  termScanning: boolean;
  /** 翻译完成后自动扫描候选术语（本地规则，零 API 调用） */
  termAutoScan: boolean;
  termLastScanAt: number | null;
  /** 上次批量采纳失败的候选：界面逐条显示目标库与原因，不静默吞掉 */
  termBulkFailures: { id: string; source_term: string; bank_id: string; error: string }[];
  /** 术语候选自动审批：状态、结果与上一轮可撤回批次 */
  termAutoReview: TermAutoReviewStatus | null;
  termAutoReviewBusy: boolean;
  termAutoReviewLast: TermAutoReviewResult | null;
  /** 设置 → 术语 / 翻译记忆容量策略 */
  settings: AppSettings | null;
  settingsSaving: boolean;
  draftText: string;
  /** 工作台历史侧栏 */
  historyItems: HistoryItem[];
  historyLoading: boolean;
  historyError: string | null;
  /** 设置 → 调用历史 */
  calls: CallSummary[];
  callsTotal: number;
  callsLoading: boolean;
  callsError: string | null;
  callDetail: CallDetail | null;
  callDetailLoading: boolean;
  /** 皮肤：内置两套 + 已导入；activeSkin 为当前生效的完整变量表 */
  skins: SkinSummary[];
  activeSkinId: string;
  activeSkin: SkinView | null;
  skinBusy: boolean;
  /** 用量：调用历史保留状态与统计概览 */
  usageStatus: UsageCallsStatus | null;
  usageStats: UsageStats | null;

  bootstrap: () => Promise<void>;
  submit: (text: string) => Promise<void>;
  cancel: () => Promise<void>;
  setMode: (mode: TranslateMode, scope?: ModeScope) => Promise<void>;
  retranslate: (segmentIds?: string[]) => Promise<void>;
  /** 只重试失败 / 未完成片段，不重跑已完成部分（V10） */
  retryFailed: () => Promise<void>;
  pickWord: (segmentId: string, wordIndex: number, choice: string) => Promise<void>;
  pickVariant: (segmentId: string, span: number[], choice: string) => Promise<void>;
  /** 指定某术语的统一译法；只重译受影响片段 */
  setTaskTerm: (sourceTerm: string, targetTerm: string) => Promise<void>;
  overrideTarget: (segmentId: string, text: string, origin?: string, tmEntryId?: string) => Promise<void>;
  setTargetLang: (lang: string) => void;
  setScene: (sceneId: string | null) => void;
  setView: (view: AppView) => void;
  applyEvent: (evt: UiEvent) => void;
  clearError: () => void;
  setDraftText: (text: string) => void;
  loadProviders: () => Promise<void>;
  saveProvider: (profile: ProviderUpsertProfile, apiKey: string) => Promise<boolean>;
  testProvider: (request: ProviderTestRequest) => Promise<ProviderTestResult | null>;
  deleteProvider: (providerId: string) => Promise<void>;
  loadBanks: () => Promise<void>;
  setGlossaryBankId: (bankId: string) => void;
  searchGlossary: (bankId?: string, query?: string) => Promise<void>;
  addGlossaryEntry: (bankId: string, entry: GlossaryEntryInput) => Promise<boolean>;
  updateGlossaryEntry: (entryId: string, entry: GlossaryEntryInput) => Promise<boolean>;
  deleteGlossaryEntry: (entryId: string) => Promise<void>;
  importGlossaryPackage: (
    pkg: GlossaryPackage,
    opts?: { mode?: "merge" | "append"; target_bank_id?: string },
  ) => Promise<GlossaryImportResult | null>;
  createGlossaryBank: (
    input: { name: string; src_lang?: string; tgt_lang?: string; domain?: string },
  ) => Promise<GlossaryBank | null>;
  loadTermCandidates: (status?: "pending" | "accepted" | "ignored") => Promise<void>;
  scanTerms: () => Promise<void>;
  setTermAutoScan: (on: boolean) => void;
  acceptHighQualityTerms: (bankId?: string) => Promise<void>;
  acceptTermCandidate: (id: string, target: string, bankId?: string) => Promise<boolean>;
  ignoreTermCandidates: (ids: string[]) => Promise<void>;
  refreshTermCounts: () => Promise<void>;
  clearTermColumn: (status: "pending" | "accepted" | "ignored") => Promise<void>;
  loadTermAutoReview: () => Promise<void>;
  runTermAutoReview: () => Promise<void>;
  undoTermAutoReview: () => Promise<void>;
  applyAutoReviewResult: (result: TermAutoReviewResult) => void;
  /** 工作台行内标注（术语下划线 / 语气标签 / 句子级情感）总开关 */
  showAnnotations: boolean;
  setShowAnnotations: (on: boolean) => void;
  loadSettings: () => Promise<AppSettings | null>;
  saveSettings: (settings: AppSettings) => Promise<AppSettings | null>;
  memoryAdd: (segmentId: string) => Promise<boolean>;
  memoryRemove: (entryId: string, segmentId: string) => Promise<boolean>;
  loadScenes: () => Promise<void>;
  loadUsageSummary: () => Promise<UsageSummary | null>;
  loadUsageList: (opts?: {
    limit?: number;
    offset?: number;
    provider?: string;
  }) => Promise<{ items: UsageRecord[]; total: number } | null>;
  createScene: (input: SceneProfileInput) => Promise<SceneProfileSummary | null>;
  saveScene: (input: SceneProfileInput) => Promise<SceneProfileSummary | null>;
  deleteScene: (sceneId: string) => Promise<void>;
  setSceneDefault: (sceneId: string) => Promise<void>;
  sceneAiChat: (input: {
    message: string;
    scene_profile?: Record<string, unknown>;
    history?: ChatTurn[];
  }) => Promise<SceneAiResult | null>;
  loadHistory: () => Promise<void>;
  openHistoryTask: (taskId: string) => Promise<void>;
  loadCalls: (offset?: number, limit?: number) => Promise<void>;
  openCall: (callId: string) => Promise<void>;
  closeCallDetail: () => void;
  // 皮肤（V11）
  loadSkins: () => Promise<void>;
  selectSkin: (skinId: string) => Promise<boolean>;
  importSkin: (filename: string, data: string) => Promise<{ ok: boolean; updated: boolean }>;
  exportSkin: (skinId: string) => Promise<boolean>;
  deleteSkin: (skinId: string) => Promise<boolean>;
  // 用量（V11）
  loadUsageStatus: () => Promise<void>;
  loadUsageStats: () => Promise<void>;
  saveUsageSettings: (usage: UsageCallsSettings) => Promise<boolean>;
  cleanupCalls: (days: number) => Promise<void>;
  clearCalls: () => Promise<void>;
}

let pollTimer: ReturnType<typeof setTimeout> | null = null;

function stopPolling(): void {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function startPolling(taskId: string): void {
  stopPolling();
  let fromSeq = useAppStore.getState().checkpointSeq;

  const tick = async (): Promise<void> => {
    const state = useAppStore.getState();
    if (
      !state.task ||
      state.task.id !== taskId ||
      state.task.status === "succeeded" ||
      state.task.status === "failed" ||
      state.task.status === "cancelled"
    ) {
      return;
    }
    try {
      const { events, next_seq } = await pollEvents(taskId, fromSeq);
      for (const evt of events) {
        useAppStore.getState().applyEvent(evt);
      }
      fromSeq = next_seq;
    } catch {
      // 拉取失败：静默，下一轮重试
    }
    pollTimer = setTimeout(() => void tick(), 800);
  };

  pollTimer = setTimeout(() => void tick(), 400);
}

function messageOf(e: unknown): string {
  if (e instanceof Error && e.message) {
    const code = (e as { code?: string }).code;
    return errorText(code, e.message);
  }
  return t("common.unknown_error");
}

const DRAFT_KEY = "laa.workbench.draft";
const TARGET_LANG_KEY = "laa.workbench.target_lang";
const UI_LANG_KEY = "nexling.ui_lang";

function loadUiLang(): UiLang {
  let lang: UiLang = "zh";
  try {
    const saved = localStorage.getItem(UI_LANG_KEY);
    if (saved === "en" || saved === "zh") lang = saved;
  } catch {
    // 忽略读取失败
  }
  setUiLang(lang);
  return lang;
}

/** 从 localStorage 恢复工作台输入草稿（跨切页 / 重启保留）。 */
function loadDraft(): string {
  try {
    return localStorage.getItem(DRAFT_KEY) ?? "";
  } catch {
    return "";
  }
}

const AUTO_SCAN_KEY = "nexling.term.autoscan";
const ANNOTATIONS_KEY = "nexling.workbench.annotations";

function loadAnnotations(): boolean {
  try {
    return localStorage.getItem(ANNOTATIONS_KEY) !== "off";
  } catch {
    return true;
  }
}

function loadAutoScan(): boolean {
  try {
    return localStorage.getItem(AUTO_SCAN_KEY) !== "off";
  } catch {
    return true;
  }
}

function saveDraft(text: string): void {
  try {
    localStorage.setItem(DRAFT_KEY, text);
  } catch {
    // 忽略写入失败（隐私模式 / 配额）
  }
}

function loadTargetLang(): string {
  try {
    return localStorage.getItem(TARGET_LANG_KEY) || "zh-Hans";
  } catch {
    return "zh-Hans";
  }
}

export const useAppStore = create<AppState>((set, get) => {
  const fail = (e: unknown): void => {
    const maybeCode = (e as { code?: unknown }).code;
    if (maybeCode === "LAA-2005") {
      set({ error: t("err.dev_in_progress"), busy: false });
    } else if (e instanceof Error && e.message) {
      set({ error: e.message, busy: false });
    } else {
      set({ error: t("common.unknown_error"), busy: false });
    }
  };

  /** 重新拉取当前任务快照（记忆写入/删除后刷新 tm_hits 与段落状态）。 */
  const refreshSnapshot = async (): Promise<void> => {
    const task = get().task;
    if (!task) return;
    const snap = await invoke<unknown, TranslationSnapshot>("translation.snapshot", {
      task_id: task.id,
    });
    set({
      segments: snap.segments, terms: snap.terms ?? [],
      checkpointSeq: snap.checkpoint_seq,
      progress: snap.progress ?? get().progress,
    });
  };

  return {
    capabilities: DEFAULT_CAPABILITIES,
    task: null,
    segments: [],
    terms: [],
    scenes: [],
    scene: null,
    mode: "fluent",
    targetLang: loadTargetLang(),
    uiLang: loadUiLang(),
    busy: false,
    error: null,
    checkpointSeq: 0,
    progress: null,
    estimate: null,
    capabilitiesLoaded: false,
    providers: [],
    view: "workbench",
    banks: [],
    glossaryEntries: [],
    glossaryBankId: "",
    glossaryLoading: false,
    termCandidates: [],
    termCounts: { pending: 0, accepted: 0, ignored: 0 },
    termStatus: "pending",
    termLoading: false,
    termScanning: false,
    termAutoScan: loadAutoScan(),
    termLastScanAt: null,
    termBulkFailures: [],
    termAutoReview: null,
    termAutoReviewBusy: false,
    termAutoReviewLast: null,
    showAnnotations: loadAnnotations(),
    settings: null,
    settingsSaving: false,
    draftText: loadDraft(),
    historyItems: [],
    historyLoading: false,
    historyError: null,
    calls: [],
    callsTotal: 0,
    callsLoading: false,
    callsError: null,
    callDetail: null,
    callDetailLoading: false,
    skins: [],
    activeSkinId: "default",
    activeSkin: null,
    skinBusy: false,
    usageStatus: null,
    usageStats: null,

    bootstrap: async () => {
      // 初始恰好一次 capability.list；失败则回退到静态注册表（不打断 UI）。
      try {
        const list = await invoke<unknown, { version: string; items: CapabilityView[] }>(
          "capability.list",
          {},
        );
        set({ capabilities: list.items, capabilitiesLoaded: true });
        mark("bridge_ready");  // 原生桥 token 握手成功（写入 startup.log 供启动自检）
      } catch {
        set({ capabilitiesLoaded: true });
      }
      await get().loadScenes();
      // 皮肤在首屏就应用：启动时读取当前生效皮肤，避免先闪默认浅色再切换
      await get().loadSkins();
    },

    submit: async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) {
        set({ error: t("err.empty_input") });
        return;
      }
      set({ busy: true, error: null, segments: [], terms: [], progress: null, estimate: null });
      try {
        // 提交前先估算：超硬上限时明确报错（不静默截断），多批时说明将分批处理
        const est = await invoke<unknown, TranslationEstimate>("translation.estimate", {
          text: trimmed,
        });
        if (est?.over_limit) {
          set({
            busy: false,
            error: t("wb.long.over_limit", {
              n: String(est.chars),
              max: String(est.max_chars),
            }),
          });
          return;
        }
        if (est && est.batches > 1) {
          notifyInfo(
            t("wb.long.batched"),
            t("wb.long.batched_detail", {
              batches: String(est.batches),
              segments: String(est.segments),
            }),
          );
        }
        const { scene, mode, targetLang } = get();
        const started = await invoke<
          unknown,
          { task_id: string; stream: Record<string, unknown> }
        >("translation.start", {
          text: trimmed,
          target_lang: targetLang,
          mode,
          scene_profile_id: scene?.id ?? undefined,
          domain: "general",
          input_kind: "text",
        });
        const taskId = started.task_id;
        const snap = await invoke<unknown, TranslationSnapshot>("translation.snapshot", {
          task_id: taskId,
        });
        set({
          task: snap.task,
          segments: snap.segments, terms: snap.terms ?? [],
          checkpointSeq: snap.checkpoint_seq,
          progress: snap.progress ?? null,
          estimate: est ?? null,
          busy: true,
          error: null,
        });
        startPolling(taskId);
      } catch (e) {
        fail(e);
      }
    },

    cancel: async () => {
      const { task } = get();
      if (!task) return;
      stopPolling();
      try {
        await invoke<unknown, { cancelled: boolean }>("translation.cancel", {
          task_id: task.id,
        });
      } catch {
        // 取消失败也按本地取消处理
      }
      // 等后端把未完成片段标记为 cancelled，再刷新一次，避免界面停在半截状态
      let last: TranslationSnapshot | null = null;
      for (let i = 0; i < 20; i += 1) {
        try {
          last = await invoke<unknown, TranslationSnapshot>("translation.snapshot", {
            task_id: task.id,
          });
          if (last.task.status === "cancelled" || last.task.status === "failed") break;
        } catch {
          break;
        }
        await new Promise((r) => setTimeout(r, 100));
      }
      set({
        busy: false,
        task: last?.task ?? { ...task, status: "cancelled" },
        segments: last?.segments ?? get().segments,
        terms: last?.terms ?? get().terms,
        progress: last?.progress ?? get().progress,
      });
    },

    setMode: async (mode, scope = "rest") => {
      set({ mode });
      const { task } = get();
      if (!task) return;
      try {
        await invoke<unknown, unknown>("mode.set", {
          task_id: task.id,
          mode,
          scope,
        });
      } catch (e) {
        fail(e);
      }
    },

    retranslate: async (segmentIds) => {
      const { task } = get();
      if (!task) return;
      set({ busy: true, error: null });
      try {
        await invoke<unknown, { task_id: string; queued: boolean }>("translation.retranslate", {
          task_id: task.id,
          segment_ids: segmentIds,
        });
        const snap = await invoke<unknown, TranslationSnapshot>("translation.snapshot", {
          task_id: task.id,
        });
        set({
          task: snap.task,
          segments: snap.segments, terms: snap.terms ?? [],
          checkpointSeq: snap.checkpoint_seq,
          progress: snap.progress ?? get().progress,
        });
        startPolling(task.id);
      } catch (e) {
        fail(e);
      }
    },

    retryFailed: async () => {
      const { task } = get();
      if (!task) return;
      set({ busy: true, error: null });
      try {
        const res = await invoke<unknown, TranslationRetryResult>("translation.retry", {
          task_id: task.id,
        });
        if (res.finalized) {
          // 片段其实都已完成：后端直接收尾为成功，无需再轮询。
          const snap = await invoke<unknown, TranslationSnapshot>("translation.snapshot", {
            task_id: task.id,
          });
          set({
            task: snap.task,
            segments: snap.segments, terms: snap.terms ?? [],
            checkpointSeq: snap.checkpoint_seq,
            progress: snap.progress ?? get().progress,
            busy: false,
          });
          notifyInfo(t("wb.retry.finalized"), t("wb.retry.finalized_hint"));
          return;
        }
        notifyInfo(t("wb.retry.started"), t("wb.retry.count", { n: String(res.segment_count) }));
        const snap = await invoke<unknown, TranslationSnapshot>("translation.snapshot", {
          task_id: task.id,
        });
        set({
          task: snap.task,
          segments: snap.segments, terms: snap.terms ?? [],
          checkpointSeq: snap.checkpoint_seq,
          progress: snap.progress ?? get().progress,
          busy: true,
        });
        startPolling(task.id);
      } catch (e) {
        fail(e);
      }
    },

    pickWord: async (segmentId, wordIndex, choice) => {
      const { task } = get();
      if (!task) return;
      try {
        const view = await invoke<unknown, SegmentView>("segment.word.pick", {
          task_id: task.id,
          segment_id: segmentId,
          word_index: wordIndex,
          choice,
        });
        set((s) => {
          const idx = s.segments.findIndex((x) => x.segment_id === segmentId);
          if (idx === -1) return {};
          const next = s.segments.slice();
          next[idx] = { ...next[idx], ...view };
          return { segments: next };
        });
      } catch (e) {
        notifyInfo(t("notice.pick_word_failed"), messageOf(e));
      }
    },

    pickVariant: async (segmentId, span, choice) => {
      const { task } = get();
      if (!task) return;
      try {
        const view = await invoke<unknown, SegmentView>("segment.variant.pick", {
          task_id: task.id,
          segment_id: segmentId,
          span,
          choice,
        });
        set((s) => {
          const idx = s.segments.findIndex((x) => x.segment_id === segmentId);
          if (idx === -1) return {};
          const next = s.segments.slice();
          next[idx] = { ...next[idx], ...view };
          return { segments: next };
        });
      } catch (e) {
        notifyInfo(t("notice.pick_variant_failed"), messageOf(e));
      }
    },

    setTaskTerm: async (sourceTerm, targetTerm) => {
      const { task } = get();
      if (!task) return;
      try {
        const res = await invoke<
          unknown,
          {
            affected: number;
            rewritten: number;
            queued: boolean;
            matched?: number;
            already?: number;
            term: TaskTerm;
          }
        >("task.term.set", { task_id: task.id, source_term: sourceTerm, target_term: targetTerm });
        set((s) => {
          const rest = s.terms.filter((x) => x.source_term !== sourceTerm);
          return { terms: [...rest, res.term] };
        });
        notifyInfo(
          t("term.panel.saved"),
          res.queued
            ? t("term.panel.affected", { n: String(res.affected - res.rewritten) })
            : res.rewritten > 0
              ? t("term.panel.rewritten", { n: String(res.rewritten) })
              : res.matched === 0
                ? t("term.panel.notfound")
                : t("term.panel.nochange"),
        );
        if (res.queued) {
          const snap = await invoke<unknown, TranslationSnapshot>("translation.snapshot", {
            task_id: task.id,
          });
          set({
            task: snap.task,
            segments: snap.segments, terms: snap.terms ?? [],
            checkpointSeq: snap.checkpoint_seq,
            progress: snap.progress ?? get().progress,
          });
          startPolling(task.id);
        }
      } catch (e) {
        fail(e);
      }
    },

    overrideTarget: async (segmentId, text, origin = "manual_edit", tmEntryId) => {
      const { task } = get();
      if (!task) return;
      try {
        const view = await invoke<unknown, SegmentView>("segment.override", {
          task_id: task.id,
          segment_id: segmentId,
          target_text: text,
          origin,
          tm_entry_id: tmEntryId,
        });
        set((s) => {
          const idx = s.segments.findIndex((x) => x.segment_id === segmentId);
          if (idx === -1) return {};
          const next = s.segments.slice();
          next[idx] = { ...next[idx], ...view };
          return { segments: next };
        });
        notifyInfo(t("notice.updated"), origin === "tm_apply" ? t("notice.tm_applied") : text.slice(0, 24));
      } catch (e) {
        notifyInfo(t("notice.update_failed"), messageOf(e));
      }
    },

    setTargetLang: (lang) => {
      set({ targetLang: lang });
      try {
        localStorage.setItem(TARGET_LANG_KEY, lang);
      } catch {
        // 忽略写入失败
      }
    },

    setUiLang: (lang) => {
      setUiLang(lang);
      set({ uiLang: lang });
      try {
        localStorage.setItem(UI_LANG_KEY, lang);
      } catch {
        // 忽略写入失败
      }
    },

    setScene: (sceneId) => {
      const { scenes } = get();
      set({ scene: scenes.find((s) => s.id === sceneId) ?? null });
    },

    setView: (view) => {
      set({ view });
    },

    applyEvent: (evt) => {
      const { task, progress } = get();
      switch (evt.topic) {
        case "task.progress": {
          // 任务级进度：done/total/failed/remaining 边翻边更新；调用数与花费由快照回填
          const p = evt.payload as Record<string, unknown>;
          if (typeof p.total !== "number") break;
          const base: TaskProgress = progress ?? {
            total: 0, done: 0, failed: 0, cancelled: 0, remaining: 0,
            batch_total: 0, calls: 0, input_tokens: 0, output_tokens: 0, cost: 0,
          };
          set({
            progress: {
              ...base,
              total: Number(p.total),
              done: Number(p.done ?? base.done),
              failed: Number(p.failed ?? base.failed),
              cancelled: Number(p.cancelled ?? base.cancelled),
              remaining: Number(p.remaining ?? base.remaining),
              batch_total: Number(p.batch_total ?? base.batch_total),
              calls: Number(p.calls ?? base.calls),
              input_tokens: Number(p.input_tokens ?? base.input_tokens),
              output_tokens: Number(p.output_tokens ?? base.output_tokens),
              cost: Number(p.cost ?? base.cost),
            },
            task: task ? { ...task, ...(p.status ? { status: p.status as TranslationTask["status"] } : {}) } : task,
          });
          break;
        }
        case "task.cancelled":
          set({ task: task ? { ...task, ...(evt.payload as Partial<TranslationTask>) } : task, busy: false });
          // 取消后仍有已完成片段与已记录术语，刷新一次让结果区与术语面板对齐
          void refreshSnapshot();
          break;
        case "task.created":
        case "task.paused":
        case "task.cancelling":
        case "task.finalizing":
        case "task.checkpoint":
          set({ task: task ? { ...task, ...(evt.payload as Partial<TranslationTask>) } : task });
          break;
        case "task.completed":
          stopPolling();
          set({
            busy: false,
            task: task ? { ...task, status: "succeeded" } : task,
          });
          // 完成后再拉一次快照：回填实际调用数 / token / 花费与片段状态
          void refreshSnapshot();
          if (get().termAutoScan) {
            // 自动扫描候选术语：纯本地规则抽取，不产生模型调用；
            // 失败只在术语页提示，不影响翻译结果。
            void get().scanTerms();
          }
          break;
        case "task.failed":
          stopPolling();
          set({
            busy: false,
            error: (evt.payload.message as string) ?? t("err.translate_failed"),
            task: task ? { ...task, status: "failed" } : task,
          });
          void refreshSnapshot();
          break;
        case "segment.view":
        case "segment.draft": {
          // 后端旧版会把完整视图包在 payload.view 里；新版直接平铺。两态兼容。
          const raw = evt.payload as Record<string, unknown>;
          const seg = ((raw.view as SegmentView | undefined) ?? raw) as SegmentView;
          if (seg && seg.segment_id && typeof seg.target_text === "string") {
            set((s) => {
              const idx = s.segments.findIndex((x) => x.segment_id === seg.segment_id);
              if (idx === -1) {
                return { segments: [...s.segments, seg] };
              }
              const next = s.segments.slice();
              next[idx] = { ...next[idx], ...seg };
              return { segments: next };
            });
          }
          break;
        }
        default:
          break;
      }
    },

    loadProviders: async () => {
      try {
        const list = await invoke<unknown, ProviderProfile[]>("provider.list", {});
        set({ providers: list });
      } catch (e) {
        notifyInfo(t("notice.provider.list_failed"), messageOf(e));
      }
    },

    saveProvider: async (profile, apiKey) => {
      try {
        const res = await invoke<unknown, ProviderUpsertResult>("provider.upsert", {
          profile,
          api_key: apiKey,
        });
        await get().loadProviders();
        notifyInfo(t("notice.saved"),
          res.default ? t("notice.saved_default", { name: profile.name }) : profile.name);
        return res.saved;
      } catch (e) {
        notifyInfo(t("notice.save_failed"), messageOf(e));
        return false;
      }
    },

    testProvider: async (request) => {
      try {
        const res = await invoke<unknown, ProviderTestResult>("provider.test", request);
        if (res.ok) {
          notifyInfo(t("notice.test_ok"), t("notice.test_ok_detail", {
            detail: res.detail || t("notice.test_connected"),
            ms: String(res.latency_ms ?? 0),
          }));
        } else {
          notifyInfo(t("notice.test_failed"), res.detail || t("notice.test_unreachable"));
        }
        return res;
      } catch (e) {
        notifyInfo(t("notice.test_error"), messageOf(e));
        return null;
      }
    },

    deleteProvider: async (providerId) => {
      try {
        await invoke<unknown, { deleted: boolean }>("provider.delete", {
          provider_id: providerId,
        });
        await get().loadProviders();
        notifyInfo(t("notice.deleted"), providerId);
      } catch (e) {
        notifyInfo(t("notice.delete_failed"), messageOf(e));
      }
    },

    loadBanks: async () => {
      try {
        const res = await invoke<unknown, { items: GlossaryBank[] }>("glossary.package.list", {});
        const items = res.items ?? [];
        const preferred = items.find((b) => b.scope === "personal") ?? items[0] ?? null;
        set({
          banks: items,
          glossaryBankId: preferred?.id ?? "",
        });
      } catch (e) {
        notifyInfo(t("notice.bank.list_failed"), messageOf(e));
      }
    },

    setGlossaryBankId: (bankId) => {
      set({ glossaryBankId: bankId });
    },

    searchGlossary: async (bankId, query) => {
      const bank = bankId ?? get().glossaryBankId;
      if (!bank) return;
      set({ glossaryBankId: bank, glossaryLoading: true });
      try {
        const res = await invoke<unknown, { items: GlossaryEntry[]; total: number }>(
          "glossary.search",
          {
            bank_id: bank,
            query: query && query.trim() ? query.trim() : undefined,
            limit: 200,
          },
        );
        set({ glossaryEntries: res.items ?? [], glossaryLoading: false });
      } catch (e) {
        notifyInfo(t("notice.entry.list_failed"), messageOf(e));
        set({ glossaryLoading: false });
      }
    },

    addGlossaryEntry: async (bankId, entry) => {
      try {
        await invoke<unknown, { ok: boolean; entry: GlossaryEntry }>("glossary.manage", {
          action: "add",
          bank_id: bankId,
          entry,
        });
        await get().loadBanks();
        await get().searchGlossary(bankId, "");
        notifyInfo(t("notice.entry.added"), entry.source_term ?? "");
        return true;
      } catch (e) {
        notifyInfo(t("notice.add_failed"), messageOf(e));
        return false;
      }
    },

    updateGlossaryEntry: async (entryId, entry) => {
      try {
        await invoke<unknown, GlossaryEntry>("glossary.update", {
          entry_id: entryId,
          entry,
        });
        await get().loadBanks();
        await get().searchGlossary(get().glossaryBankId, "");
        notifyInfo(t("notice.entry.updated"), entry.source_term ?? entryId);
        return true;
      } catch (e) {
        notifyInfo(t("notice.update_failed"), messageOf(e));
        return false;
      }
    },

    deleteGlossaryEntry: async (entryId) => {
      try {
        await invoke<unknown, { removed: string }>("glossary.manage", {
          action: "remove",
          entry_id: entryId,
        });
        await get().loadBanks();
        await get().searchGlossary(get().glossaryBankId, "");
        notifyInfo(t("notice.entry.removed"), entryId);
      } catch (e) {
        notifyInfo(t("notice.delete_failed"), messageOf(e));
      }
    },

    importGlossaryPackage: async (pkg, opts) => {
      try {
        const target = opts?.target_bank_id ?? "personal-default";
        const res = await invoke<unknown, GlossaryImportResult>("glossary.import", {
          package: pkg,
          mode: opts?.mode ?? "merge",
          target_bank_id: target,
        });
        await get().loadBanks();
        await get().searchGlossary(target, "");
        notifyInfo(
          t("notice.import_done"),
          t("notice.import_summary", {
            inserted: String(res.inserted),
            updated: String(res.updated),
            skipped: String(res.skipped),
          }),
        );
        return res;
      } catch (e) {
        notifyInfo(t("notice.import_failed"), messageOf(e));
        return null;
      }
    },

    createGlossaryBank: async (input) => {
      try {
        const res = await invoke<unknown, { ok: boolean; bank: GlossaryBank }>(
          "glossary.bank.create",
          input,
        );
        await get().loadBanks();
        const created = res.bank;
        if (created) {
          set({ glossaryBankId: created.id });
          await get().searchGlossary(created.id, "");
        }
        notifyInfo(t("notice.bank.created"), created?.name ?? "");
        return created ?? null;
      } catch (e) {
        notifyInfo(t("notice.bank.create_failed"), messageOf(e));
        return null;
      }
    },

    loadTermCandidates: async (status) => {
      const wanted = status ?? get().termStatus;
      set({ termStatus: wanted, termLoading: true });
      try {
        const res = await invoke<unknown, { items: TermCandidate[]; counts: TermCandidateCounts }>(
          "term.list",
          { status: wanted, task_id: get().task?.id ?? "" },
        );
        set({ termCandidates: res.items, termCounts: res.counts, termLoading: false });
      } catch {
        set({ termCandidates: [], termLoading: false });
      }
    },

    scanTerms: async () => {
      const task = get().task;
      if (!task) {
        set({ error: t("term.need_task") });
        return;
      }
      set({ termScanning: true });
      try {
        const res = await invoke<unknown, { auto_review?: TermAutoReviewResult }>("term.scan", {
          task_id: task.id,
        });
        // 刷新当前页签（不把用户从已采纳/已忽略页签强行切走）
        await get().loadTermCandidates();
        set({ termLastScanAt: Date.now() });
        await get().loadTermAutoReview();
        if (res?.auto_review) get().applyAutoReviewResult(res.auto_review);
      } catch (e) {
        notifyInfo(t("term.scan_failed"), messageOf(e));
      } finally {
        set({ termScanning: false });
      }
    },

    setTermAutoScan: (on) => {
      try {
        localStorage.setItem(AUTO_SCAN_KEY, on ? "on" : "off");
      } catch {
        // 忽略写入失败
      }
      set({ termAutoScan: on });
    },

    acceptHighQualityTerms: async (bankId) => {
      const task = get().task;
      if (!task) {
        // 候选按任务隔离：没有当前任务就没有可采纳的候选
        set({ error: t("term.need_task") });
        notifyInfo(t("term.accept_failed"), t("term.need_task"));
        return;
      }
      try {
        set({ termBulkFailures: [] });
        const res = await invoke<unknown, {
          accepted: string[];
          needs_bank?: string[];
          failed?: { id: string; error: string }[];
          counts: TermCandidateCounts;
        }>("term.accept_bulk", {
          min_confidence: 0.8,
          task_id: task.id,
          ...(bankId ? { bank_id: bankId } : {}),
        });
        // 失败项保留可读信息：哪个词、写到哪个库、为什么失败
        const before = new Map(get().termCandidates.map((c) => [c.id, c]));
        const failures = (res.failed ?? []).map((f) => ({
          id: f.id,
          source_term: before.get(f.id)?.source_term ?? f.id,
          bank_id: bankId || before.get(f.id)?.bank_id || "",
          error: f.error,
        }));
        set({ termBulkFailures: failures });
        await get().loadTermCandidates();
        await get().loadBanks();
        const bank = bankId || get().glossaryBankId;
        if (bank) await get().searchGlossary(bank, "");
        const pendingBank = res.needs_bank?.length ?? 0;
        if (pendingBank > 0) {
          notifyInfo(t("term.bulk.need_bank"), String(pendingBank));
        } else {
          notifyInfo(t("term.bulk.done"), String(res.accepted.length));
        }
      } catch (e) {
        notifyInfo(t("term.accept_failed"), messageOf(e));
      }
    },

    refreshTermCounts: async () => {
      try {
        const res = await invoke<unknown, { counts: TermCandidateCounts }>("term.list", {
          status: "pending",
          task_id: get().task?.id ?? "",
        });
        set({ termCounts: res.counts });
      } catch {
        // 角标不是关键路径，失败忽略
      }
    },

    clearTermColumn: async (status) => {
      try {
        const res = await invoke<unknown, { removed: number; counts: TermCandidateCounts }>(
          "term.clear",
          { status, task_id: get().task?.id ?? "" },
        );
        set({ termCounts: res.counts });
        await get().loadTermCandidates(status);
        notifyInfo(t("notice.term_cleared"), String(res.removed));
      } catch (e) {
        notifyInfo(t("notice.term_clear_failed"), messageOf(e));
      }
    },

    applyAutoReviewResult: (result) => {
      set({ termAutoReviewLast: result, termCounts: result.counts });
      if (result.available === false) {
        notifyInfo(t("term.auto.unavailable"), result.reason || "");
        return;
      }
      if (!result.processed) return;
      const base = t("term.auto.summary", {
        n: String(result.processed),
        accepted: String(result.accepted_count),
        ignored: String(result.ignored_count),
        failed: String(result.failed_count),
      });
      notifyInfo(
        t("term.auto.done"),
        result.needs_bank_count
          ? `${base} · ${t("term.auto.needs_bank", { n: String(result.needs_bank_count) })}`
          : base,
      );
    },

    loadTermAutoReview: async () => {
      try {
        const st = await invoke<unknown, TermAutoReviewStatus>("term.auto_review.status", {
          task_id: get().task?.id ?? "",
        });
        set({ termAutoReview: st });
      } catch {
        set({ termAutoReview: null });
      }
    },

    runTermAutoReview: async () => {
      if (get().termAutoReviewBusy) return;
      set({ termAutoReviewBusy: true });
      try {
        const res = await invoke<unknown, TermAutoReviewResult>("term.auto_review", {
          task_id: get().task?.id ?? "",
        });
        set({ termAutoReviewBusy: false });
        get().applyAutoReviewResult(res);
        await get().loadTermCandidates();
        await get().loadBanks();
        await get().loadTermAutoReview();
      } catch (e) {
        set({ termAutoReviewBusy: false });
        notifyInfo(t("term.auto.unavailable"), messageOf(e));
      }
    },

    undoTermAutoReview: async () => {
      const last = get().termAutoReviewLast;
      const batchId = last?.batch_id || get().termAutoReview?.last_batch?.id || "";
      if (!batchId) return;
      try {
        const res = await invoke<unknown, {
          restored: number;
          restored_ignored: number;
          counts: TermCandidateCounts;
        }>("term.auto_review.undo", { batch_id: batchId });
        set({ termAutoReviewLast: null, termCounts: res.counts });
        notifyInfo(
          t("term.auto.undo.done"),
          t("term.auto.undo.restored", {
            n: String(res.restored),
            ignored: String(res.restored_ignored ?? 0),
          }),
        );
        await get().loadTermCandidates();
        await get().loadBanks();
        await get().loadTermAutoReview();
      } catch (e) {
        notifyInfo(t("term.auto.undo.failed"), messageOf(e));
      }
    },

    setShowAnnotations: (on) => {
      try {
        localStorage.setItem(ANNOTATIONS_KEY, on ? "on" : "off");
      } catch {
        /* 无本地存储时仅本次生效 */
      }
      set({ showAnnotations: on });
    },

    loadSettings: async () => {
      try {
        const settings = await invoke<unknown, AppSettings>("settings.get", {});
        set({ settings });
        return settings;
      } catch (e) {
        notifyInfo(t("notice.settings.load_failed"), messageOf(e));
        return null;
      }
    },

    saveSettings: async (settings) => {
      set({ settingsSaving: true });
      try {
        const res = await invoke<unknown, { settings: AppSettings; removed: { term_candidates: number; memory: number }; auto_review?: TermAutoReviewResult }>(
          "settings.save",
          { settings },
        );
        set({ settings: res.settings, settingsSaving: false });
        await get().refreshTermCounts();
        if (res.auto_review) get().applyAutoReviewResult(res.auto_review);
        const trimmed = (res.removed?.term_candidates ?? 0) + (res.removed?.memory ?? 0);
        notifyInfo(t("notice.saved"),
          trimmed > 0 ? t("notice.settings.trimmed", { n: String(trimmed) }) : "");
        return res.settings;
      } catch (e) {
        set({ settingsSaving: false });
        notifyInfo(t("notice.save_failed"), messageOf(e));
        return null;
      }
    },

    memoryAdd: async (segmentId) => {
      const task = get().task;
      if (!task) return false;
      try {
        await invoke<unknown, { entry_id: string }>("memory.add", {
          task_id: task.id,
          segment_id: segmentId,
        });
        await refreshSnapshot();
        notifyInfo(t("notice.memory.added"), "");
        return true;
      } catch (e) {
        notifyInfo(t("notice.memory.add_failed"), messageOf(e));
        return false;
      }
    },

    memoryRemove: async (entryId, segmentId) => {
      try {
        const res = await invoke<unknown, { deleted: boolean }>("memory.delete", { entry_id: entryId });
        if (!res?.deleted) {
          notifyInfo(t("notice.memory.remove_failed"), t("notice.memory.not_found"));
          return false;
        }
        await refreshSnapshot();
        notifyInfo(t("notice.memory.removed"), segmentId);
        return true;
      } catch (e) {
        notifyInfo(t("notice.memory.remove_failed"), messageOf(e));
        return false;
      }
    },

    acceptTermCandidate: async (id, target, bankId) => {
      const trimmed = target.trim();
      if (!trimmed) {
        notifyInfo(t("term.need_target"), "");
        return false;
      }
      try {
        await invoke<unknown, unknown>("term.accept", {
          id,
          target_term: trimmed,
          bank_id: bankId,
          task_id: get().task?.id ?? "",
        });
        await get().loadTermCandidates();
        await get().loadBanks();
        const bank = get().glossaryBankId;
        if (bank) await get().searchGlossary(bank, "");
        notifyInfo(t("term.accepted"), trimmed);
        return true;
      } catch (e) {
        notifyInfo(t("term.accept_failed"), messageOf(e));
        return false;
      }
    },

    ignoreTermCandidates: async (ids) => {
      if (ids.length === 0) return;
      try {
        await invoke<unknown, unknown>("term.ignore", { ids });
        await get().loadTermCandidates();
      } catch (e) {
        notifyInfo(t("term.ignore_failed"), messageOf(e));
      }
    },

    loadScenes: async () => {
      try {
        const scenes = await invoke<unknown, SceneProfileSummary[]>("scene.list", {});
        set({
          scenes,
          scene: scenes.find((s) => s.is_default) ?? scenes[0] ?? get().scene,
        });
      } catch {
        // 场景列表非必需，忽略
      }
    },

    loadUsageSummary: async () => {
      try {
        return await invoke<unknown, UsageSummary>("usage.summary", {});
      } catch (e) {
        notifyInfo(t("notice.usage.list_failed"), messageOf(e));
        return null;
      }
    },

    loadUsageList: async (opts) => {
      try {
        return await invoke<unknown, { items: UsageRecord[]; total: number }>("usage.list", {
          limit: opts?.limit ?? 50,
          offset: opts?.offset ?? 0,
          provider: opts?.provider || undefined,
        });
      } catch (e) {
        notifyInfo(t("notice.usage.detail_failed"), messageOf(e));
        return null;
      }
    },

    createScene: async (input) => {
      try {
        const saved = await invoke<unknown, SceneProfileSummary>("scene.manage", {
          action: "create",
          scene_profile: input,
        });
        await get().loadScenes();
        notifyInfo(t("notice.scene.created"), saved?.name ?? input.name);
        return saved;
      } catch (e) {
        notifyInfo(t("notice.create_failed"), messageOf(e));
        return null;
      }
    },

    saveScene: async (input) => {
      try {
        const saved = await invoke<unknown, SceneProfileSummary>("scene.manage", {
          action: "save",
          scene_profile: input,
        });
        await get().loadScenes();
        notifyInfo(t("notice.scene.saved"), saved?.name ?? input.name);
        return saved;
      } catch (e) {
        notifyInfo(t("notice.save_failed"), messageOf(e));
        return null;
      }
    },

    deleteScene: async (sceneId) => {
      try {
        await invoke<unknown, { deleted: string }>("scene.manage", {
          action: "delete",
          scene_id: sceneId,
        });
        await get().loadScenes();
        notifyInfo(t("notice.scene.removed"), sceneId);
      } catch (e) {
        notifyInfo(t("notice.delete_failed"), messageOf(e));
      }
    },

    setSceneDefault: async (sceneId) => {
      try {
        await invoke<unknown, { default: string }>("scene.manage", {
          action: "set_default",
          scene_id: sceneId,
        });
        await get().loadScenes();
        const target = get().scenes.find((s) => s.id === sceneId) ?? null;
        if (target) set({ scene: target });
        notifyInfo(t("notice.scene.default_set"), target?.name ?? sceneId);
      } catch (e) {
        notifyInfo(t("notice.default_failed"), messageOf(e));
      }
    },

    sceneAiChat: async (input) => {
      try {
        const res = await invoke<unknown, SceneAiResult>("scene.ai", input);
        return res;
      } catch (e) {
        notifyInfo(t("notice.ai_failed"), messageOf(e));
        return null;
      }
    },

    clearError: () => set({ error: null }),
    setDraftText: (text) => {
      set({ draftText: text });
      saveDraft(text);
    },

    // ---- 工作台历史侧栏 ----
    loadHistory: async () => {
      set({ historyLoading: true, historyError: null });
      try {
        const res = await invoke<unknown, { items: HistoryItem[]; total: number }>("history.list", {
          limit: 30,
          offset: 0,
        });
        set({ historyItems: res.items ?? [], historyLoading: false });
      } catch (e) {
        set({ historyLoading: false, historyError: messageOf(e) });
      }
    },

    openHistoryTask: async (taskId) => {
      stopPolling();
      try {
        const snap = await invoke<unknown, TranslationSnapshot>("translation.snapshot", {
          task_id: taskId,
        });
        set({
          task: snap.task,
          segments: snap.segments, terms: snap.terms ?? [],
          checkpointSeq: snap.checkpoint_seq,
          progress: snap.progress ?? null,
          estimate: null,
          busy: false,
          error: null,
          mode: (snap.task.mode as TranslateMode) ?? "fluent",
        });
      } catch (e) {
        notifyInfo(t("notice.history_open_failed"), messageOf(e));
      }
    },

    // ---- 设置 → 调用历史 ----
    loadCalls: async (offset = 0, limit = 20) => {
      set({ callsLoading: true, callsError: null });
      try {
        const res = await invoke<unknown, { items: CallSummary[]; total: number }>("calls.list", {
          limit,
          offset,
        });
        const items = res.items ?? [];
        set({
          calls: items,
          callsTotal: res.total ?? 0,
          callsLoading: false,
        });
      } catch (e) {
        set({ callsLoading: false, callsError: messageOf(e) });
      }
    },

    openCall: async (callId) => {
      set({ callDetailLoading: true, callDetail: null });
      try {
        const detail = await invoke<unknown, CallDetail>("calls.get", { call_id: callId });
        set({ callDetail: detail, callDetailLoading: false });
      } catch (e) {
        set({ callDetailLoading: false });
        notifyInfo(t("notice.call_detail_failed"), messageOf(e));
      }
    },

    closeCallDetail: () => set({ callDetail: null }),

    // ---- 皮肤（V11） ----
    loadSkins: async () => {
      try {
        const list = await invoke<unknown, { active: string; items: SkinSummary[] }>(
          "skin.list",
          {},
        );
        const view = await invoke<unknown, SkinView>("skin.active", {});
        set({ skins: list.items ?? [], activeSkin: view, activeSkinId: view.id });
      } catch {
        // 桥不可达/皮肤服务异常时保持默认浅色（回退路径就是默认皮肤）
        set({ skins: [], activeSkin: null });
      }
    },

    selectSkin: async (skinId) => {
      set({ skinBusy: true });
      try {
        const view = await invoke<unknown, SkinView>("skin.select", { id: skinId });
        set({ activeSkin: view, activeSkinId: view.id, skinBusy: false });
        return true;
      } catch (e) {
        set({ skinBusy: false });
        notifyInfo(t("notice.skin.switch_failed"), messageOf(e));
        return false;
      }
    },

    importSkin: async (filename, data) => {
      set({ skinBusy: true });
      try {
        const res = await invoke<unknown, { skin: SkinSummary; updated: boolean }>("skin.import", {
          filename,
          data,
        });
        const list = await invoke<unknown, { active: string; items: SkinSummary[] }>("skin.list", {});
        set({ skins: list.items ?? [] });
        if (res.skin?.id) {
          const view = await invoke<unknown, SkinView>("skin.select", { id: res.skin.id });
          set({ activeSkin: view, activeSkinId: view.id });
        }
        set({ skinBusy: false });
        notifyInfo(
          res.updated ? t("notice.skin.updated") : t("notice.skin.imported"),
          res.skin?.name ?? filename,
        );
        return { ok: true, updated: !!res.updated };
      } catch (e) {
        set({ skinBusy: false });
        notifyInfo(t("notice.skin.import_failed"), messageOf(e));
        return { ok: false, updated: false };
      }
    },

    exportSkin: async (skinId) => {
      try {
        const res = await invoke<unknown, { filename: string; data: string }>("skin.export", {
          id: skinId,
        });
        const saved = await saveBinaryFile(res.filename, res.data);
        if (saved.cancelled) return false;
        if (saved.error) {
          notifyInfo(t("notice.skin.export_failed"), saved.error);
          return false;
        }
        notifyInfo(t("notice.skin.exported"), res.filename);
        return true;
      } catch (e) {
        notifyInfo(t("notice.skin.export_failed"), messageOf(e));
        return false;
      }
    },

    deleteSkin: async (skinId) => {
      try {
        await invoke<unknown, { deleted: string; active: string }>("skin.delete", { id: skinId });
        const list = await invoke<unknown, { active: string; items: SkinSummary[] }>("skin.list", {});
        const view = await invoke<unknown, SkinView>("skin.active", {});
        set({ skins: list.items ?? [], activeSkin: view, activeSkinId: view.id });
        notifyInfo(t("notice.skin.deleted"), skinId);
        return true;
      } catch (e) {
        notifyInfo(t("notice.skin.delete_failed"), messageOf(e));
        return false;
      }
    },

    // ---- 用量（V11） ----
    loadUsageStatus: async () => {
      try {
        const status = await invoke<unknown, UsageCallsStatus>("usage.calls.status", {});
        set({ usageStatus: status });
      } catch (e) {
        notifyInfo(t("notice.usage.status_failed"), messageOf(e));
      }
    },

    loadUsageStats: async () => {
      try {
        const stats = await invoke<unknown, UsageStats>("usage.stats", {});
        set({ usageStats: stats });
      } catch (e) {
        notifyInfo(t("notice.usage.stats_failed"), messageOf(e));
      }
    },

    saveUsageSettings: async (usage) => {
      try {
        const res = await invoke<
          unknown,
          { settings: AppSettings; removed: { calls: number }; calls: UsageCallsStatus }
        >("usage.settings.save", { usage });
        set({ settings: res.settings, usageStatus: res.calls });
        notifyInfo(
          t("notice.usage.saved"),
          res.removed.calls > 0
            ? t("notice.usage.trimmed").replace("{n}", String(res.removed.calls))
            : t("notice.usage.keep_all"),
        );
        await get().loadCalls(0, 20);
        return true;
      } catch (e) {
        notifyInfo(t("notice.usage.save_failed"), messageOf(e));
        return false;
      }
    },

    cleanupCalls: async (days) => {
      try {
        const res = await invoke<unknown, { removed: number; calls: UsageCallsStatus }>(
          "usage.calls.cleanup",
          { days },
        );
        set({ usageStatus: res.calls });
        notifyInfo(t("notice.usage.cleaned"), t("notice.usage.cleaned_detail")
          .replace("{n}", String(res.removed))
          .replace("{d}", String(days)));
        await get().loadCalls(0, 20);
      } catch (e) {
        notifyInfo(t("notice.usage.cleanup_failed"), messageOf(e));
      }
    },

    clearCalls: async () => {
      try {
        const res = await invoke<unknown, { removed: number; calls: UsageCallsStatus }>(
          "usage.calls.clear",
          {},
        );
        set({ usageStatus: res.calls });
        notifyInfo(t("notice.usage.cleared"), t("notice.usage.cleared_detail")
          .replace("{n}", String(res.removed)));
        await get().loadCalls(0, 20);
        await get().loadUsageSummary();
      } catch (e) {
        notifyInfo(t("notice.usage.clear_failed"), messageOf(e));
      }
    },
  };
});