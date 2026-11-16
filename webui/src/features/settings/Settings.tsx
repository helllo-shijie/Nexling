// 设置页：模型 / 用量 / 术语 / 翻译场景 / 路线图 / 关于。
// 计费与调用历史合并为「用量」；空壳能力统一收进路线图。
import { useEffect, useState, type ReactNode } from "react";
import { useAppStore } from "../../store/app";
import { entityLabel, entityText, t } from "../../i18n/ui";
import { notifyInfo } from "../../store/notice";
import { invoke } from "../../api/laa";
import { ProviderManager } from "./ProviderManager";
import { UsagePanel } from "./UsagePanel";
import { SkinPanel } from "./SkinPanel";
import { RoadmapPanel } from "./RoadmapPanel";
import type {
  AppSettings,
  ChatTurn,
  LongTextSettings,
  SceneProfileSummary,
  TermCandidateLimits,
} from "../../bridge/types";

type SectionId = "general" | "model" | "longtext" | "usage" | "glossary" | "scene" | "roadmap" | "about";

const SECTIONS: { id: SectionId; key: string }[] = [
  { id: "general", key: "settings.ui" },
  { id: "model", key: "settings.model" },
  { id: "longtext", key: "settings.longtext" },
  { id: "usage", key: "settings.usage" },
  { id: "glossary", key: "settings.glossary" },
  { id: "scene", key: "settings.scene" },
  { id: "roadmap", key: "settings.roadmap" },
  { id: "about", key: "settings.about" },
];

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="settings-panel">
      <h2 className="settings-panel__title">{title}</h2>
      {children}
    </div>
  );
}

type SceneForm = {
  name: string;
  description: string;
  register: "formal" | "semiformal" | "informal";
  mode_default: "fluent" | "literal";
  descriptors: string;
  dos: string;
  donts: string;
};

const EMPTY_SCENE: SceneForm = {
  name: "",
  description: "",
  register: "semiformal",
  mode_default: "fluent",
  descriptors: "",
  dos: "",
  donts: "",
};

function splitLines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
}

function ScenePanel() {
  const scenes = useAppStore((s) => s.scenes);
  const scene = useAppStore((s) => s.scene);
  const setScene = useAppStore((s) => s.setScene);
  const createScene = useAppStore((s) => s.createScene);
  const saveScene = useAppStore((s) => s.saveScene);
  const deleteScene = useAppStore((s) => s.deleteScene);
  const setSceneDefault = useAppStore((s) => s.setSceneDefault);
  const sceneAiChat = useAppStore((s) => s.sceneAiChat);

  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<SceneForm>(EMPTY_SCENE);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatTurn[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [aiThinking, setAiThinking] = useState(false);

  const patch = (partial: Partial<SceneForm>): void =>
    setForm((prev) => ({ ...prev, ...partial }));

  const openCreate = (): void => {
    setEditingId(null);
    setForm(EMPTY_SCENE);
    setChatMessages([]);
    setChatInput("");
    setAiThinking(false);
    setFormOpen(true);
  };

  const openEdit = (s: SceneProfileSummary): void => {
    setEditingId(s.id);
    setForm({
      name: s.name,
      description: s.description ?? "",
      register: s.register ?? "semiformal",
      mode_default: s.mode_default ?? "fluent",
      descriptors: (s.descriptors ?? []).join("\n"),
      dos: (s.do ?? []).join("\n"),
      donts: (s.dont ?? []).join("\n"),
    });
    setChatMessages([]);
    setChatInput("");
    setAiThinking(false);
    setFormOpen(true);
  };

  const closeForm = (): void => {
    setFormOpen(false);
    setEditingId(null);
    setForm(EMPTY_SCENE);
  };

  const handleSave = async (): Promise<void> => {
    if (saving) return;
    if (!form.name.trim()) {
      notifyInfo(t("common.cannot_save"), t("scene.err.name_required"));
      return;
    }
    setSaving(true);
    const input = {
      name: form.name.trim(),
      description: form.description.trim() || undefined,
      register: form.register,
      mode_default: form.mode_default,
      descriptors: splitLines(form.descriptors),
      do: splitLines(form.dos),
      dont: splitLines(form.donts),
    };
    const ok = editingId
      ? await saveScene({ ...input, id: editingId })
      : await createScene(input);
    setSaving(false);
    if (ok) closeForm();
  };

  const handleDelete = async (s: SceneProfileSummary): Promise<void> => {
    if (busyId) return;
    setBusyId(`delete:${s.id}`);
    await deleteScene(s.id);
    setBusyId(null);
  };

  const handleSetDefault = async (s: SceneProfileSummary): Promise<void> => {
    if (busyId || s.is_default) return;
    setBusyId(`default:${s.id}`);
    await setSceneDefault(s.id);
    setBusyId(null);
  };

  const handleAiSend = async (): Promise<void> => {
    const text = chatInput.trim();
    if (!text || aiThinking) return;

    const userTurn: ChatTurn = { role: "user", content: text };
    const history = [...chatMessages, userTurn];
    setChatMessages(history);
    setChatInput("");
    setAiThinking(true);

    const scene_profile: Record<string, unknown> = {
      name: form.name.trim(),
      description: form.description.trim(),
      register: form.register,
      mode_default: form.mode_default,
      descriptors: splitLines(form.descriptors),
      do: splitLines(form.dos),
      dont: splitLines(form.donts),
    };

    const res = await sceneAiChat({ message: text, scene_profile, history });
    setAiThinking(false);
    if (!res) return;

    setForm({
      name: res.scene_profile.name,
      description: res.scene_profile.description,
      register: res.scene_profile.register,
      mode_default: res.scene_profile.mode_default,
      descriptors: res.scene_profile.descriptors.join("\n"),
      dos: res.scene_profile.do.join("\n"),
      donts: res.scene_profile.dont.join("\n"),
    });

    setChatMessages((prev) => [...prev, { role: "assistant", content: res.reply }]);
  };

  return (
    <Panel title={t("settings.scene.title")}>
      <div className="scene-toolbar">
        <button type="button" className="btn" onClick={openCreate}>
          {t("scene.create")}
        </button>
      </div>

      {scenes.length === 0 ? (
        <p className="muted">{t("scene.loading")}</p>
      ) : (
        <ul className="settings-list">
          {scenes.map((s) => (
            <li key={s.id} className="settings-list__item scene-row">
              <div className="scene-row__main">
                <span className={s.id === scene?.id ? "scene-row__name scene-active" : "scene-row__name"}>
                  {entityLabel("scene", s.id, s.name)}
                </span>
                <span className="muted">{entityText("scene", s.id, ".desc", s.description)}</span>
                <span className="muted scene-row__summary">
                  {s.register ?? "semiformal"} · {s.mode_default}
                </span>
              </div>
              <div className="scene-row__flags">
                {s.is_builtin ? <span className="flag">{t("scene.builtin")}</span> : null}
                {s.is_default ? <span className="flag flag--default">{t("common.default")}</span> : null}
                {scene?.id === s.id ? <span className="flag flag--ok">{t("scene.active")}</span> : null}
              </div>
              <div className="scene-row__actions">
                <button type="button" className="link-btn" onClick={() => setScene(s.id)}>
                  {t("scene.use")}
                </button>
                <button
                  type="button"
                  className="link-btn"
                  onClick={() => void handleSetDefault(s)}
                >
                  {s.is_default ? t("common.is_default") : t("common.set_default")}
                </button>
                {!s.is_builtin ? (
                  <button type="button" className="link-btn" onClick={() => openEdit(s)}>
                    {t("common.edit")}
                  </button>
                ) : null}
                {!s.is_builtin && !s.is_default ? (
                  <button
                    type="button"
                    className="link-btn link-btn--danger"
                    onClick={() => void handleDelete(s)}
                  >
                    {busyId === `delete:${s.id}` ? t("common.deleting") : t("common.delete")}
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}

      {formOpen ? (
        <div className="modal-overlay" onClick={closeForm}>
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal__header">
              <h3 className="modal__title">{editingId ? t("scene.edit") : t("scene.create")}</h3>
              <button type="button" className="modal__close" onClick={closeForm} aria-label={t("common.close")}>
                ×
              </button>
            </div>

            <div className="modal__body">
              <div className="scene-ai">
                <div className="scene-ai__header">
                  <span className="scene-ai__title">{t("scene.ai.title")}</span>
                  <span className="muted">{t("scene.ai.hint")}</span>
                </div>

                {chatMessages.length > 0 ? (
                  <div className="scene-ai__log">
                    {chatMessages.map((m, i) => (
                      <div key={i} className={`scene-ai__bubble scene-ai__bubble--${m.role}`}>
                        {m.content}
                      </div>
                    ))}
                  </div>
                ) : null}

                <div className="scene-ai__input">
                  <input
                    className="field__control"
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        void handleAiSend();
                      }
                    }}
                    placeholder={t("scene.ai.hint")}
                  />
                  <button
                    type="button"
                    className="btn btn--primary"
                    onClick={() => void handleAiSend()}
                  >
                    {aiThinking ? t("scene.ai.generating") : t("common.send")}
                  </button>
                </div>
              </div>

              <label className="field">
                <span className="field__label">{t("common.name")}</span>
                <input
                  className="field__control"
                  value={form.name}
                  onChange={(e) => patch({ name: e.target.value })}
                  placeholder={t("scene.name.placeholder")}
                />
              </label>

              <label className="field">
                <span className="field__label">{t("common.description")}</span>
                <input
                  className="field__control"
                  value={form.description}
                  onChange={(e) => patch({ description: e.target.value })}
                  placeholder={t("scene.description.placeholder")}
                />
              </label>

              <div className="field-row">
                <label className="field">
                  <span className="field__label">{t("scene.register")}</span>
                  <select
                    className="field__control"
                    value={form.register}
                    onChange={(e) => patch({ register: e.target.value as SceneForm["register"] })}
                  >
                    <option value="formal">{t("scene.register.formal")}</option>
                    <option value="semiformal">{t("scene.register.semiformal")}</option>
                    <option value="informal">{t("scene.register.informal")}</option>
                  </select>
                </label>
                <label className="field">
                  <span className="field__label">{t("scene.mode_default")}</span>
                  <select
                    className="field__control"
                    value={form.mode_default}
                    onChange={(e) => patch({ mode_default: e.target.value as SceneForm["mode_default"] })}
                  >
                    <option value="fluent">{t("scene.mode.fluent")}</option>
                    <option value="literal">{t("scene.mode.literal")}</option>
                  </select>
                </label>
              </div>

              <label className="field">
                <span className="field__label">{t("scene.descriptors")}</span>
                <textarea
                  className="field__control scene-textarea"
                  value={form.descriptors}
                  onChange={(e) => patch({ descriptors: e.target.value })}
                />
              </label>

              <label className="field">
                <span className="field__label">{t("scene.dos")}</span>
                <textarea
                  className="field__control scene-textarea"
                  value={form.dos}
                  onChange={(e) => patch({ dos: e.target.value })}
                />
              </label>

              <label className="field">
                <span className="field__label">{t("scene.donts")}</span>
                <textarea
                  className="field__control scene-textarea"
                  value={form.donts}
                  onChange={(e) => patch({ donts: e.target.value })}
                />
              </label>

              <div className="modal__actions">
                <button
                  type="button"
                  className="btn btn--primary"
                  onClick={() => void handleSave()}
                >
                  {saving ? t("common.saving") : t("common.save")}
                </button>
                <button type="button" className="btn btn--ghost" onClick={closeForm}>
                  {t("common.cancel")}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </Panel>
  );
}

function AboutPanel() {
  return (
    <Panel title={t("settings.about")}>
      <p className="muted">{t("about.line1")}</p>
      <p className="muted">{t("about.line2")}</p>
      <p className="muted">{t("about.line3")}</p>
    </Panel>
  );
}

function UiPanel() {
  const uiLang = useAppStore((s) => s.uiLang);
  const setUiLang = useAppStore((s) => s.setUiLang);
  const [tab, setTab] = useState<"language" | "skin">("language");
  return (
    <Panel title={t("settings.ui")}>
      <div className="tabs">
        <button
          type="button"
          className={`tab${tab === "language" ? " tab--active" : ""}`}
          onClick={() => setTab("language")}
        >
          {t("settings.language")}
        </button>
        <button
          type="button"
          className={`tab${tab === "skin" ? " tab--active" : ""}`}
          onClick={() => setTab("skin")}
        >
          {t("settings.skin")}
        </button>
      </div>

      {tab === "language" ? (
        <>
          <div className="field">
            <span className="field__label">{t("settings.language")} / Language</span>
            <div className="tabs">
              <button
                type="button"
                className={`tab${uiLang === "zh" ? " tab--active" : ""}`}
                onClick={() => setUiLang("zh")}
              >
                {t("lang.zh")}
              </button>
              <button
                type="button"
                className={`tab${uiLang === "en" ? " tab--active" : ""}`}
                onClick={() => setUiLang("en")}
              >
                {t("lang.en")}
              </button>
            </div>
          </div>
          <p className="muted">{t("settings.language.note")}</p>
        </>
      ) : (
        <SkinPanel />
      )}
    </Panel>
  );
}

const LIMIT_STATUSES: (keyof TermCandidateLimits)[] = ["pending", "accepted", "ignored"];
const LIMIT_DEFAULT: TermCandidateLimits = { pending: 200, accepted: 100, ignored: 100 };
const LIMIT_KEYS = ["pending", "accepted", "ignored", "memory"] as const;
type LimitKey = (typeof LIMIT_KEYS)[number];

function GlossarySettingsPanel() {
  const settings = useAppStore((s) => s.settings);
  const saving = useAppStore((s) => s.settingsSaving);
  const loadSettings = useAppStore((s) => s.loadSettings);
  const saveSettings = useAppStore((s) => s.saveSettings);
  const [draft, setDraft] = useState<AppSettings | null>(settings);
  const [memoryTotal, setMemoryTotal] = useState<number | null>(null);
  const [termTotals, setTermTotals] = useState<Record<string, number> | null>(null);
  const [limitText, setLimitText] = useState<Record<string, string>>({});
  const [thresholdText, setThresholdText] = useState("20");
  const [limitError, setLimitError] = useState<string | null>(null);

  useEffect(() => {
    if (!settings) void loadSettings();
  }, [settings, loadSettings]);

  useEffect(() => {
    if (settings) {
      setDraft({
        ...settings,
        term_auto_review: settings.term_auto_review ?? {
          enabled: false,
          threshold: 20,
          allow_manual: true,
        },
      });
    }
  }, [settings]);

  useEffect(() => {
    if (!settings) return;
    setLimitText({
      pending: String(settings.term_candidate_limits.pending),
      accepted: String(settings.term_candidate_limits.accepted),
      ignored: String(settings.term_candidate_limits.ignored),
      memory: String(settings.memory_limit),
    });
    setThresholdText(String(settings.term_auto_review?.threshold ?? 20));
  }, [settings]);

  useEffect(() => {
    invoke<unknown, { total: number }>("memory.list", { limit: 1, include_stale: true })
      .then((r) => setMemoryTotal(typeof r?.total === "number" ? r.total : null))
      .catch(() => setMemoryTotal(null));
    invoke<unknown, { counts: Record<string, number> }>("term.list", { status: "pending" })
      .then((r) => setTermTotals(r?.counts ?? null))
      .catch(() => setTermTotals(null));
  }, [settings]);

  if (!draft) {
    return (
      <Panel title={t("settings.glossary")}>
        <p className="muted">{t("app.loading")}</p>
      </Panel>
    );
  }

  const auto = draft.term_auto_review ?? { enabled: false, threshold: 20, allow_manual: true };

  const applyLimit = (key: LimitKey, value: number): void => {
    if (key === "memory") {
      setDraft({ ...draft, memory_limit: value });
      return;
    }
    setDraft({
      ...draft,
      term_candidate_limits: { ...draft.term_candidate_limits, [key]: value },
    });
  };

  const isUnlimited = (key: LimitKey): boolean =>
    key === "memory" ? draft.memory_limit === 0 : draft.term_candidate_limits[key] === 0;

  const onLimitInput = (key: LimitKey, raw: string): void => {
    setLimitError(null);
    setLimitText((prev) => ({ ...prev, [key]: raw }));
    if (raw.trim() === "") return;
    const n = Number(raw);
    if (!Number.isFinite(n) || n < 0) return;
    const cap = key === "memory" ? 1000000 : 100000;
    applyLimit(key, Math.min(cap, Math.floor(n)));
  };

  const toggleUnlimited = (status: keyof TermCandidateLimits, unlimited: boolean): void => {
    const next = unlimited ? 0 : LIMIT_DEFAULT[status];
    setLimitError(null);
    setLimitText((prev) => ({ ...prev, [status]: String(next) }));
    applyLimit(status, next);
  };

  const setMemoryUnlimited = (unlimited: boolean): void => {
    const next = unlimited ? 0 : 500;
    setLimitError(null);
    setLimitText((prev) => ({ ...prev, memory: String(next) }));
    setDraft({ ...draft, memory_limit: next });
  };

  const save = async (): Promise<void> => {
    const invalid = LIMIT_KEYS.some((key) => {
      if (isUnlimited(key)) return false;
      return !/^\d+$/.test((limitText[key] ?? "").trim());
    });
    if (invalid) {
      setLimitError(t("settings.limit.invalid"));
      return;
    }
    const threshold = Number(thresholdText.trim());
    if (!/^\d+$/.test(thresholdText.trim()) || threshold < 1 || threshold > 100000) {
      setLimitError(t("settings.auto.invalid"));
      return;
    }
    setLimitError(null);
    const saved = await saveSettings({
      ...draft,
      term_auto_review: { ...(draft.term_auto_review ?? { enabled: false, allow_manual: true }), threshold },
    });
    if (saved) setDraft(saved);
  };

  const renderLimitInput = (
    key: LimitKey,
    unlimited: boolean,
    max: number,
    onToggle: (unlimited: boolean) => void,
  ): ReactNode => (
    <>
      {unlimited ? (
        <input
          type="text"
          className="field__control settings-limit__input"
          value={t("common.unlimited")}
          disabled
          readOnly
        />
      ) : (
        <input
          type="number"
          className="field__control settings-limit__input"
          min={0}
          max={max}
          value={limitText[key] ?? ""}
          onChange={(e) => onLimitInput(key, e.target.value)}
        />
      )}
      <label className="settings-check">
        <input type="checkbox" checked={unlimited} onChange={(e) => onToggle(e.target.checked)} />
        {t("common.unlimited")}
      </label>
    </>
  );

  return (
    <Panel title={t("settings.glossary")}>
      <p className="muted">{t("settings.glossary.desc")}</p>

      <h3 className="settings-subtitle">{t("settings.glossary.candidates")}</h3>
      {LIMIT_STATUSES.map((status) => {
        const unlimited = draft.term_candidate_limits[status] === 0;
        return (
          <div className="field field--inline settings-limit" key={status}>
            <span className="field__label settings-limit__label">{t(`term.filter.${status}`)}</span>
            {renderLimitInput(status, unlimited, 100000, (v) => toggleUnlimited(status, v))}
            <span className="muted settings-limit__count">
              {t("settings.glossary.current", { n: String(termTotals?.[status] ?? 0) })}
            </span>
          </div>
        );
      })}

      <div className="field settings-field">
        <span className="field__label">{t("settings.glossary.cleanup")}</span>
        <select
          className="field__control"
          value={draft.term_candidate_cleanup}
          onChange={(e) =>
            setDraft({
              ...draft,
              term_candidate_cleanup: e.target.value === "manual" ? "manual" : "auto",
            })
          }
        >
          <option value="auto">{t("settings.glossary.cleanup.auto")}</option>
          <option value="manual">{t("settings.glossary.cleanup.manual")}</option>
        </select>
        <span className="muted settings-hint">{t("settings.glossary.cleanup.hint")}</span>
      </div>

      <h3 className="settings-subtitle">{t("settings.auto.title")}</h3>
      <p className="muted settings-hint">{t("settings.auto.desc")}</p>
      <label className="settings-check">
        <input
          type="checkbox"
          checked={auto.enabled}
          onChange={(e) =>
            setDraft({ ...draft, term_auto_review: { ...auto, enabled: e.target.checked } })
          }
        />
        {t("settings.auto.enabled")}
      </label>
      <label className="settings-check">
        <input
          type="checkbox"
          checked={auto.allow_manual}
          onChange={(e) =>
            setDraft({ ...draft, term_auto_review: { ...auto, allow_manual: e.target.checked } })
          }
        />
        {t("settings.auto.allow_manual")}
      </label>
      <div className="field field--inline settings-limit">
        <span className="field__label settings-limit__label">{t("settings.auto.threshold")}</span>
        <input
          type="number"
          className="field__control settings-limit__input"
          min={1}
          max={100000}
          value={thresholdText}
          onChange={(e) => {
            setLimitError(null);
            setThresholdText(e.target.value);
            const n = Number(e.target.value);
            if (Number.isFinite(n) && n >= 1 && n <= 100000) {
              setDraft({ ...draft, term_auto_review: { ...auto, threshold: Math.floor(n) } });
            }
          }}
        />
        <span className="muted settings-limit__count">
          {t("settings.auto.threshold_hint", { n: thresholdText || "—" })}
        </span>
      </div>
      <p className="muted settings-hint">{t("settings.auto.model_hint")}</p>

      <h3 className="settings-subtitle">{t("settings.memory.capacity")}</h3>
      <div className="field field--inline settings-limit">
        <span className="field__label settings-limit__label">{t("settings.memory.limit")}</span>
        {renderLimitInput("memory", draft.memory_limit === 0, 1000000, setMemoryUnlimited)}
        <span className="muted settings-limit__count">
          {memoryTotal === null ? "" : t("settings.memory.current", { n: String(memoryTotal) })}
        </span>
      </div>
      <p className="muted settings-hint">{t("settings.memory.hint")}</p>

      {limitError ? (
        <p className="settings-error" role="alert">
          {limitError}
        </p>
      ) : null}

      <div className="settings-actions">
        <button
          type="button"
          className="btn btn--primary"
          onClick={() => void save()}
          disabled={saving}
        >
          {saving ? t("common.saving") : t("common.save")}
        </button>
      </div>
    </Panel>
  );
}

const LONG_FIELDS: {
  key: keyof LongTextSettings;
  min: number;
  max: number;
  label: string;
  hint: string;
}[] = [
  { key: "max_chars", min: 1000, max: 5_000_000, label: "settings.long.max_chars", hint: "settings.long.max_chars.hint" },
  { key: "batch_chars", min: 200, max: 20_000, label: "settings.long.batch_chars", hint: "settings.long.batch_chars.hint" },
  { key: "batch_segments", min: 1, max: 50, label: "settings.long.batch_segments", hint: "settings.long.batch_segments.hint" },
  { key: "retries", min: 0, max: 5, label: "settings.long.retries", hint: "settings.long.retries.hint" },
  { key: "throttle_ms", min: 0, max: 5000, label: "settings.long.throttle_ms", hint: "settings.long.throttle_ms.hint" },
];

function LongTextPanel() {
  const settings = useAppStore((s) => s.settings);
  const saving = useAppStore((s) => s.settingsSaving);
  const loadSettings = useAppStore((s) => s.loadSettings);
  const saveSettings = useAppStore((s) => s.saveSettings);
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!settings) void loadSettings();
  }, [settings, loadSettings]);

  useEffect(() => {
    if (!settings) return;
    const cfg = settings.long_text;
    setTexts({
      max_chars: String(cfg.max_chars),
      batch_chars: String(cfg.batch_chars),
      batch_segments: String(cfg.batch_segments),
      retries: String(cfg.retries),
      throttle_ms: String(cfg.throttle_ms),
    });
  }, [settings]);

  if (!settings) {
    return (
      <Panel title={t("settings.long.title")}>
        <p className="muted">{t("app.loading")}</p>
      </Panel>
    );
  }

  const save = async (): Promise<void> => {
    const next = {} as LongTextSettings;
    for (const field of LONG_FIELDS) {
      const raw = (texts[field.key] ?? "").trim();
      const n = Number(raw);
      if (!/^\d+$/.test(raw) || n < field.min || n > field.max) {
        setError(t("settings.long.invalid"));
        return;
      }
      next[field.key] = n;
    }
    setError(null);
    await saveSettings({ ...settings, long_text: next });
  };

  return (
    <Panel title={t("settings.long.title")}>
      <p className="muted">{t("settings.long.desc")}</p>
      {LONG_FIELDS.map((field) => (
        <div className="field settings-field" key={field.key}>
          <label className="field__label" htmlFor={`long-${field.key}`}>
            {t(field.label)}
          </label>
          <input
            id={`long-${field.key}`}
            type="number"
            className="field__control settings-number"
            min={field.min}
            max={field.max}
            value={texts[field.key] ?? ""}
            onChange={(e) => {
              setError(null);
              setTexts((prev) => ({ ...prev, [field.key]: e.target.value }));
            }}
          />
          <span className="muted settings-hint">{t(field.hint)}</span>
        </div>
      ))}
      {error ? (
        <p className="settings-error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="settings-actions">
        <button type="button" className="btn btn--primary" onClick={() => void save()} disabled={saving}>
          {saving ? t("common.saving") : t("common.save")}
        </button>
      </div>
    </Panel>
  );
}

export function Settings() {
  const [active, setActive] = useState<SectionId>("general");

  return (
    <div className="settings">
      <nav className="settings__nav">
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            type="button"
            className={`settings__nav-item${active === s.id ? " settings__nav-item--active" : ""}`}
            onClick={() => setActive(s.id)}
          >
            {t(s.key)}
          </button>
        ))}
      </nav>

      <div className="settings__content">
        {active === "general" && <UiPanel />}

        {active === "model" && (
          <Panel title={t("settings.model")}>
            <ProviderManager />
          </Panel>
        )}

        {active === "longtext" && <LongTextPanel />}

        {active === "usage" && <UsagePanel />}

        {active === "glossary" && <GlossarySettingsPanel />}

        {active === "scene" && <ScenePanel />}

        {active === "roadmap" && (
          <Panel title={t("settings.roadmap")}>
            <RoadmapPanel />
          </Panel>
        )}

        {active === "about" && <AboutPanel />}
      </div>
    </div>
  );
}