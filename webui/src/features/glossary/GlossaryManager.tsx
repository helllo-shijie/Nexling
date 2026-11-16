// 术语库主界面（顶层「术语库」标签页）：选词库 / 搜索 / 查看 / 增删改 / 导入导出。
// 只读词库（readonly===1 或 scope!=='personal'）仅展示，隐藏新增/编辑/删除/导入。
import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
} from "react";
import { useAppStore } from "../../store/app";
import { entityLabel, t } from "../../i18n/ui";
import { invoke } from "../../api/laa";
import { downloadTextFile, saveTextFile } from "../../bridge/nativeSave";
import { notifyInfo } from "../../store/notice";
import type {
  GlossaryBank,
  GlossaryEntry,
  GlossaryEntryInput,
  GlossaryPackage,
} from "../../bridge/types";
import { MemoryManager } from "./MemoryManager";
import { TermDiscovery } from "./TermDiscovery";

function LibraryTabs({
  value,
  onChange,
  pending,
}: {
  value: "terms" | "memory" | "candidates";
  onChange: (v: "terms" | "memory" | "candidates") => void;
  pending?: number;
}) {
  return (
    <div className="tabs glossary__tabs" role="tablist">
      <button
        type="button"
        role="tab"
        aria-selected={value === "terms"}
        className={`tab${value === "terms" ? " tab--active" : ""}`}
        onClick={() => onChange("terms")}
      >
        {t("glossary.terms")}
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={value === "memory"}
        className={`tab${value === "memory" ? " tab--active" : ""}`}
        onClick={() => onChange("memory")}
      >
        {t("glossary.memory")}
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={value === "candidates"}
        className={`tab${value === "candidates" ? " tab--active" : ""}`}
        onClick={() => onChange("candidates")}
      >
        {t("term.tab")}
        {pending && pending > 0 ? (
          <span className="tab__badge" title={t("term.tab.badge", { n: String(pending) })}>
            {pending}
          </span>
        ) : null}
      </button>
    </div>
  );
}

function isReadonlyBank(bank: GlossaryBank): boolean {
  return bank.readonly === 1 || bank.scope !== "personal";
}

interface SceneVariantRow {
  scene_id: string;
  text: string;
}

interface TermForm {
  source_term: string;
  target_term: string;
  domain: string;
  forced: boolean;
  sceneVariants: SceneVariantRow[];
}

const EMPTY_TERM: TermForm = {
  source_term: "",
  target_term: "",
  domain: "",
  forced: false,
  sceneVariants: [],
};

function sceneVariantsToRecord(rows: SceneVariantRow[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const r of rows) {
    if (r.scene_id && r.text.trim()) out[r.scene_id] = r.text.trim();
  }
  return out;
}

function recordToRows(v: Record<string, string> | undefined): SceneVariantRow[] {
  return Object.entries(v ?? {}).map(([scene_id, text]) => ({ scene_id, text }));
}

interface BankForm {
  name: string;
  src_lang: string;
  tgt_lang: string;
  domain: string;
}

const EMPTY_BANK: BankForm = { name: "", src_lang: "", tgt_lang: "", domain: "" };

export function GlossaryManager() {
  const banks = useAppStore((s) => s.banks);
  const entries = useAppStore((s) => s.glossaryEntries);
  const glossaryBankId = useAppStore((s) => s.glossaryBankId);
  const glossaryLoading = useAppStore((s) => s.glossaryLoading);
  const loadBanks = useAppStore((s) => s.loadBanks);
  const setGlossaryBankId = useAppStore((s) => s.setGlossaryBankId);
  const searchGlossary = useAppStore((s) => s.searchGlossary);
  const addGlossaryEntry = useAppStore((s) => s.addGlossaryEntry);
  const updateGlossaryEntry = useAppStore((s) => s.updateGlossaryEntry);
  const deleteGlossaryEntry = useAppStore((s) => s.deleteGlossaryEntry);
  const importGlossaryPackage = useAppStore((s) => s.importGlossaryPackage);
  const createGlossaryBank = useAppStore((s) => s.createGlossaryBank);
  const scenes = useAppStore((s) => s.scenes);
  const loadScenes = useAppStore((s) => s.loadScenes);

  const [query, setQuery] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<TermForm>(EMPTY_TERM);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [detailEntry, setDetailEntry] = useState<GlossaryEntry | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importMode, setImportMode] = useState<"merge" | "append">("merge");
  const [importTarget, setImportTarget] = useState("personal-default");
  const [importText, setImportText] = useState("");
  const [importFileName, setImportFileName] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [dragging, setDragging] = useState(false);
  const dragCounter = useRef(0);
  const [bankOpen, setBankOpen] = useState(false);
  const [bankForm, setBankForm] = useState<BankForm>(EMPTY_BANK);
  const [bankSaving, setBankSaving] = useState(false);
  const [tab, setTab] = useState<"terms" | "memory" | "candidates">("terms");
  const termPending = useAppStore((s) => s.termCounts.pending);
  const refreshTermCounts = useAppStore((s) => s.refreshTermCounts);
  const taskId = useAppStore((s) => s.task?.id ?? "");

  useEffect(() => {
    void refreshTermCounts();
  }, [refreshTermCounts, taskId]);

  const selectedBank: GlossaryBank | null = banks.find((b) => b.id === glossaryBankId) ?? null;
  const readonly: boolean = selectedBank ? isReadonlyBank(selectedBank) : false;
  const personalBanks: GlossaryBank[] = banks.filter((b) => !isReadonlyBank(b));

  useEffect(() => {
    void loadBanks();
  }, [loadBanks]);

  // 场景档案为空时补拉一次（通常 bootstrap 已加载；兜底供详情/编辑映射场景名）。
  useEffect(() => {
    if (scenes.length === 0) void loadScenes();
  }, [scenes.length, loadScenes]);

  // 词库切换或搜索词变化时去抖刷新（初始选中也在 glossaryBankId 变化后触发）。
  useEffect(() => {
    if (!glossaryBankId) return;
    const t = setTimeout(() => {
      void searchGlossary(glossaryBankId, query);
    }, 220);
    return () => clearTimeout(t);
  }, [glossaryBankId, query, searchGlossary]);

  const patch = (partial: Partial<TermForm>): void =>
    setForm((prev) => ({ ...prev, ...partial }));

  const patchSceneVariant = (idx: number, partial: Partial<SceneVariantRow>): void =>
    setForm((prev) => ({
      ...prev,
      sceneVariants: prev.sceneVariants.map((r, i) => (i === idx ? { ...r, ...partial } : r)),
    }));

  const addSceneVariant = (): void =>
    setForm((prev) => ({
      ...prev,
      sceneVariants: [...prev.sceneVariants, { scene_id: "", text: "" }],
    }));

  const removeSceneVariant = (idx: number): void =>
    setForm((prev) => ({
      ...prev,
      sceneVariants: prev.sceneVariants.filter((_, i) => i !== idx),
    }));

  const sceneName = (sid: string): string => {
    const scene = scenes.find((s) => s.id === sid);
    return scene ? entityLabel("scene", scene.id, scene.name) : sid;
  };

  const defaultSceneId: string =
    scenes.find((s) => s.is_default)?.id ?? scenes[0]?.id ?? "";

  const openCreate = (): void => {
    setEditingId(null);
    setForm({ ...EMPTY_TERM, domain: defaultSceneId });
    setFormOpen(true);
  };

  const openEdit = (e: GlossaryEntry): void => {
    setEditingId(e.id);
    setForm({
      source_term: e.source_term,
      target_term: e.target_term,
      domain: e.domain || defaultSceneId,
      forced: e.forced === 1,
      sceneVariants: recordToRows(e.scene_variants),
    });
    setFormOpen(true);
  };

  const closeForm = (): void => {
    setFormOpen(false);
    setEditingId(null);
    setForm(EMPTY_TERM);
  };

  const handleSave = async (): Promise<void> => {
    if (saving) return;
    if (!form.source_term.trim() || !form.target_term.trim()) {
      notifyInfo(t("common.cannot_save"), t("glossary.err.required"));
      return;
    }
    const payload: GlossaryEntryInput = {
      source_term: form.source_term.trim(),
      target_term: form.target_term.trim(),
      domain: form.domain.trim() || "general",
      forced: form.forced,
      scene_variants: sceneVariantsToRecord(form.sceneVariants),
    };
    setSaving(true);
    const ok = editingId
      ? await updateGlossaryEntry(editingId, payload)
      : await addGlossaryEntry(glossaryBankId, payload);
    setSaving(false);
    if (ok) closeForm();
  };

  const handleDelete = async (e: GlossaryEntry): Promise<void> => {
    if (busyId) return;
    setBusyId(`delete:${e.id}`);
    await deleteGlossaryEntry(e.id);
    setBusyId(null);
  };

  const openCreateBank = (): void => {
    setBankForm({ ...EMPTY_BANK, domain: defaultSceneId });
    setBankOpen(true);
  };

  const closeCreateBank = (): void => {
    setBankOpen(false);
    setBankForm(EMPTY_BANK);
  };

  const handleCreateBank = async (): Promise<void> => {
    if (bankSaving) return;
    if (!bankForm.name.trim()) {
      notifyInfo(t("common.cannot_create"), t("glossary.err.bank_name"));
      return;
    }
    setBankSaving(true);
    const bank = await createGlossaryBank({
      name: bankForm.name.trim(),
      src_lang: bankForm.src_lang.trim() || undefined,
      tgt_lang: bankForm.tgt_lang.trim() || undefined,
      domain: bankForm.domain.trim() || defaultSceneId,
    });
    setBankSaving(false);
    if (bank) closeCreateBank();
  };

  const openImport = (): void => {
    let target = "personal-default";
    const cur = banks.find((b) => b.id === glossaryBankId);
    if (cur && !isReadonlyBank(cur)) target = cur.id;
    else if (personalBanks.length > 0) target = personalBanks[0].id;
    setImportOpen(true);
    setImportMode("merge");
    setImportTarget(target);
    setImportText("");
    setImportFileName(null);
  };

  const readTermFile = (file: File): void => {
    setImportFileName(file.name);
    const reader = new FileReader();
    reader.onload = () => setImportText(String(reader.result ?? ""));
    reader.onerror = () => notifyInfo(t("glossary.err.read_failed"), t("glossary.err.read_file"));
    reader.readAsText(file);
  };

  const isJsonFile = (file: File): boolean =>
    /\.json$/i.test(file.name) || file.type === "application/json";

  const handleImportFile = (e: ChangeEvent<HTMLInputElement>): void => {
    const file = e.target.files?.[0];
    if (file) readTermFile(file);
  };

  const handleMainDrop = (e: DragEvent<HTMLDivElement>): void => {
    e.preventDefault();
    dragCounter.current = 0;
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (!file) return;
    if (!isJsonFile(file)) {
      notifyInfo(t("glossary.err.json_only"), t("glossary.err.drop_json"));
      return;
    }
    openImport();
    readTermFile(file);
  };

  const handleModalDrop = (e: DragEvent<HTMLDivElement>): void => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current = 0;
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (!file) return;
    if (!isJsonFile(file)) {
      notifyInfo(t("glossary.err.json_only"), t("glossary.err.drop_json"));
      return;
    }
    readTermFile(file);
  };

  const handleDragEnter = (e: DragEvent<HTMLDivElement>): void => {
    e.preventDefault();
    if (!e.dataTransfer?.types?.includes("Files")) return;
    dragCounter.current += 1;
    setDragging(true);
  };

  const handleDragOver = (e: DragEvent<HTMLDivElement>): void => {
    e.preventDefault();
  };

  const handleDragLeave = (): void => {
    dragCounter.current -= 1;
    if (dragCounter.current <= 0) {
      dragCounter.current = 0;
      setDragging(false);
    }
  };

  const handleImport = async (): Promise<void> => {
    if (importing) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(importText);
    } catch {
      notifyInfo(t("glossary.err.invalid_package"), t("glossary.err.json_parse"));
      return;
    }
    const entries = (parsed as { entries?: unknown } | null)?.entries;
    if (!Array.isArray(entries) || entries.length === 0) {
      notifyInfo(t("glossary.err.invalid_package"), t("glossary.err.no_entries"));
      return;
    }
    setImporting(true);
    const res = await importGlossaryPackage(parsed as GlossaryPackage, {
      mode: importMode,
      target_bank_id: importTarget,
    });
    setImporting(false);
    if (res) {
      setImportOpen(false);
      setImportText("");
      setImportFileName(null);
    }
  };

  const handleExport = async (): Promise<void> => {
    if (!selectedBank) return;
    if (busyId) return;
    setBusyId(`export:${selectedBank.id}`);
    try {
      const pkg = await invoke<unknown, unknown>("glossary.export", {
        bank_id: selectedBank.id,
      });
      const content = JSON.stringify(pkg, null, 2);
      const fileName = `glossary-${selectedBank.id}.json`;
      const res = await saveTextFile(fileName, content);
      if (res.unsupported) {
        downloadTextFile(fileName, content);
        notifyInfo(t("wb.export.saved"), t("wb.export.downloaded"));
      } else if (res.cancelled) {
        notifyInfo(t("wb.export.cancelled"), selectedBank.name);
      } else if (res.error) {
        notifyInfo(t("wb.export.failed"), res.error);
      } else {
        notifyInfo(t("wb.export.saved"), res.path || selectedBank.name);
      }
    } catch (e) {
      notifyInfo(t("wb.export.failed"), e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  if (tab === "memory") {
    return (
      <div className="glossary">
        <LibraryTabs value={tab} onChange={setTab} pending={termPending} />
        <MemoryManager />
      </div>
    );
  }

  if (tab === "candidates") {
    return (
      <div className="glossary">
        <LibraryTabs value={tab} onChange={setTab} pending={termPending} />
        <TermDiscovery />
      </div>
    );
  }

  return (
    <div
      className={`glossary${dragging ? " glossary--dragging" : ""}`}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleMainDrop}
    >
      <LibraryTabs value={tab} onChange={setTab} pending={termPending} />
      <header className="glossary__toolbar">
        <label className="field field--inline">
          <span className="field__label">{t("glossary.bank")}</span>
          <select
            className="field__control"
            value={glossaryBankId}
            onChange={(e) => setGlossaryBankId(e.target.value)}
          >
            {banks.map((b) => (
              <option key={b.id} value={b.id}>
                {entityLabel("bank", b.id, b.name)}
                {isReadonlyBank(b) ? t("glossary.bank.readonly_suffix") : ""}
              </option>
            ))}
          </select>
        </label>

        <input
          className="field__control glossary__search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("glossary.search")}
        />

        {selectedBank ? (
          <span className="muted">
            {t("glossary.bank_meta", {
              n: String(selectedBank.entry_count),
              src: selectedBank.src_lang,
              tgt: selectedBank.tgt_lang,
            })}
          </span>
        ) : null}
      </header>

      {banks.length === 0 ? (
        <p className="muted">{t("glossary.no_banks")}</p>
      ) : null}

      {readonly ? <p className="muted">{t("glossary.readonly_note")}</p> : null}

      <div className="glossary__actions">
        {banks.length > 0 ? (
          <button type="button" className="btn" onClick={openCreateBank}>
            {t("glossary.bank.create")}
          </button>
        ) : null}
        {!readonly && banks.length > 0 ? (
          <>
            <button type="button" className="btn" onClick={openCreate}>
              {t("glossary.entry.create")}
            </button>
            <button type="button" className="btn" onClick={openImport}>
              {t("glossary.import")}
            </button>
          </>
        ) : null}
        {banks.length > 0 ? (
          <button type="button" className="btn" onClick={() => void handleExport()}>
            {busyId === `export:${selectedBank?.id}` ? t("glossary.exporting") : t("glossary.export")}
          </button>
        ) : null}
      </div>

      <ul className="glossary-list">
        {glossaryLoading ? <li className="muted glossary-list__state">{t("app.loading")}</li> : null}
        {!glossaryLoading && entries.length === 0 ? (
          <li className="muted glossary-list__state">{t("glossary.entry.empty")}</li>
        ) : null}
        {entries.map((e) => (
          <li key={e.id} className="glossary-row">
            <div className="glossary-row__terms">
              <span className="glossary-row__source">{e.source_term}</span>
              <span className="glossary-row__arrow">→</span>
              <span className="glossary-row__target">{e.target_term}</span>
            </div>
            <div className="glossary-row__meta">
              <span className="flag">{sceneName(e.domain) || t("glossary.no_scene")}</span>
              {e.forced === 1 ? <span className="flag flag--default">{t("glossary.forced")}</span> : null}
              <span className="muted">
                v{e.version} · {e.origin || "manual"}
              </span>
            </div>
            <div className="glossary-row__actions">
              <button type="button" className="link-btn" onClick={() => setDetailEntry(e)}>
                {t("glossary.detail")}
              </button>
              {!readonly ? (
                <>
                  <button type="button" className="link-btn" onClick={() => openEdit(e)}>
                    {t("common.edit")}
                  </button>
                  <button
                    type="button"
                    className="link-btn link-btn--danger"
                    onClick={() => void handleDelete(e)}
                  >
                    {busyId === `delete:${e.id}` ? t("common.deleting") : t("common.delete")}
                  </button>
                </>
              ) : null}
            </div>
          </li>
        ))}
      </ul>

      {formOpen ? (
        <div className="modal-overlay" onClick={closeForm}>
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal__header">
              <h3 className="modal__title">{editingId ? t("glossary.entry.edit") : t("glossary.entry.create")}</h3>
              <button
                type="button"
                className="modal__close"
                onClick={closeForm}
                aria-label={t("common.close")}
              >
                ×
              </button>
            </div>

            <div className="modal__body">
              <label className="field">
                <span className="field__label">{t("glossary.field.source")}</span>
                <input
                  className="field__control"
                  value={form.source_term}
                  onChange={(e) => patch({ source_term: e.target.value })}
                  placeholder={t("glossary.field.source.placeholder")}
                />
              </label>

              <label className="field">
                <span className="field__label">{t("glossary.field.target")}</span>
                <input
                  className="field__control"
                  value={form.target_term}
                  onChange={(e) => patch({ target_term: e.target.value })}
                  placeholder={t("glossary.field.target.placeholder")}
                />
              </label>

              <label className="field">
                <span className="field__label">{t("glossary.field.scene")}</span>
                <select
                  className="field__control"
                  value={form.domain}
                  onChange={(e) => patch({ domain: e.target.value })}
                >
                  {scenes.map((s) => (
                    <option key={s.id} value={s.id}>
                      {entityLabel("scene", s.id, s.name)}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field field--inline">
                <input
                  type="checkbox"
                  checked={form.forced}
                  onChange={(e) => patch({ forced: e.target.checked })}
                />
                <span>{t("glossary.field.forced")}</span>
              </label>

              <div className="scene-variants-editor">
                <div className="scene-variants-editor__title">{t("glossary.field.variants")}</div>
                {form.sceneVariants.map((row, idx) => (
                  <div className="scene-variant-row" key={idx}>
                    <select
                      className="field__control"
                      value={row.scene_id}
                      onChange={(e) => patchSceneVariant(idx, { scene_id: e.target.value })}
                    >
                      <option value="">{t("glossary.select_scene")}</option>
                      {scenes.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.name}
                        </option>
                      ))}
                    </select>
                    <input
                      className="field__control"
                      value={row.text}
                      onChange={(e) => patchSceneVariant(idx, { text: e.target.value })}
                      placeholder={t("glossary.variant.placeholder")}
                    />
                    <button
                      type="button"
                      className="link-btn link-btn--danger"
                      onClick={() => removeSceneVariant(idx)}
                    >
                      {t("common.delete")}
                    </button>
                  </div>
                ))}
                <button type="button" className="link-btn" onClick={addSceneVariant}>
                  {t("glossary.variant.add")}
                </button>
              </div>

              <div className="glossary-form__actions">
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

      {detailEntry ? (
        <div className="modal-overlay" onClick={() => setDetailEntry(null)}>
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal__header">
              <h3 className="modal__title">{t("glossary.entry.detail")}</h3>
              <button
                type="button"
                className="modal__close"
                onClick={() => setDetailEntry(null)}
                aria-label={t("common.close")}
              >
                ×
              </button>
            </div>

            <div className="modal__body">
              <div className="detail-grid">
                <div className="detail-row">
                  <span className="detail-row__label">{t("glossary.field.source")}</span>
                  <span>{detailEntry.source_term}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-row__label">{t("glossary.field.target_default")}</span>
                  <span>{detailEntry.target_term}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-row__label">{t("glossary.field.scene")}</span>
                  <span>{sceneName(detailEntry.domain) || t("glossary.no_scene")}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-row__label">{t("glossary.forced")}</span>
                  <span>{detailEntry.forced === 1 ? t("common.yes") : t("common.no")}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-row__label">{t("glossary.field.version")}</span>
                  <span>v{detailEntry.version}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-row__label">{t("glossary.field.origin")}</span>
                  <span>{detailEntry.origin || "manual"}</span>
                </div>
                {detailEntry.part_of_speech ? (
                  <div className="detail-row">
                    <span className="detail-row__label">{t("glossary.field.pos")}</span>
                    <span>{detailEntry.part_of_speech}</span>
                  </div>
                ) : null}
                {detailEntry.definition ? (
                  <div className="detail-row">
                    <span className="detail-row__label">{t("glossary.field.definition")}</span>
                    <span>{detailEntry.definition}</span>
                  </div>
                ) : null}
              </div>

              <div className="detail-variants">
                <div className="detail-variants__title">{t("glossary.field.variants")}</div>
                {Object.keys(detailEntry.scene_variants ?? {}).length === 0 ? (
                  <p className="muted">{t("glossary.variants.empty")}</p>
                ) : (
                  <ul className="detail-variants__list">
                    {Object.entries(detailEntry.scene_variants).map(([sid, text]) => (
                      <li key={sid}>
                        <span className="detail-variants__scene">{sceneName(sid)}</span>
                        <span className="detail-variants__arrow">→</span>
                        <span>{text}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="modal__actions">
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => setDetailEntry(null)}
                >
                  {t("common.close")}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {importOpen ? (
        <div
          className="modal-overlay"
          onClick={() => setImportOpen(false)}
          onDragOver={handleDragOver}
          onDrop={handleModalDrop}
        >
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal__header">
              <h3 className="modal__title">{t("glossary.import")}</h3>
              <button
                type="button"
                className="modal__close"
                onClick={() => setImportOpen(false)}
                aria-label={t("common.close")}
              >
                ×
              </button>
            </div>

            <div className="modal__body">
              <label className="field">
                <span className="field__label">{t("glossary.import.file")}</span>
                <input
                  type="file"
                  accept=".json,application/json"
                  onChange={handleImportFile}
                />
              </label>
              {importFileName ? (
                <span className="muted">{t("glossary.import.selected", { name: importFileName })}</span>
              ) : null}

              <label className="field">
                <span className="field__label">{t("glossary.import.paste")}</span>
                <textarea
                  className="field__control glossary-import__textarea"
                  value={importText}
                  onChange={(e) => {
                    setImportText(e.target.value);
                    setImportFileName(null);
                  }}
                  placeholder={t("glossary.import.placeholder")}
                />
              </label>

              <label className="field field--inline">
                <span className="field__label">{t("glossary.import.mode")}</span>
                <select
                  className="field__control"
                  value={importMode}
                  onChange={(e) => setImportMode(e.target.value as "merge" | "append")}
                >
                  <option value="merge">{t("glossary.import.mode.merge")}</option>
                  <option value="append">{t("glossary.import.mode.append")}</option>
                </select>
              </label>

              <label className="field">
                <span className="field__label">{t("glossary.import.target")}</span>
                <select
                  className="field__control"
                  value={importTarget}
                  onChange={(e) => setImportTarget(e.target.value)}
                >
                  {personalBanks.map((b) => (
                    <option key={b.id} value={b.id}>
                      {entityLabel("bank", b.id, b.name)}
                    </option>
                  ))}
                  {personalBanks.length === 0 ? (
                    <option value="personal-default">personal-default</option>
                  ) : null}
                </select>
              </label>
              {readonly ? (
                <p className="muted">{t("glossary.import.readonly_note")}</p>
              ) : null}

              <div className="glossary-form__actions">
                <button
                  type="button"
                  className="btn btn--primary"
                  onClick={() => void handleImport()}
                >
                  {importing ? t("glossary.importing") : t("glossary.import.action")}
                </button>
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => setImportOpen(false)}
                >
                  {t("common.cancel")}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {bankOpen ? (
        <div className="modal-overlay" onClick={closeCreateBank}>
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal__header">
              <h3 className="modal__title">{t("glossary.bank.create")}</h3>
              <button
                type="button"
                className="modal__close"
                onClick={closeCreateBank}
                aria-label={t("common.close")}
              >
                ×
              </button>
            </div>

            <div className="modal__body">
              <label className="field">
                <span className="field__label">{t("glossary.bank.name")}</span>
                <input
                  className="field__control"
                  value={bankForm.name}
                  onChange={(e) => setBankForm({ ...bankForm, name: e.target.value })}
                  placeholder={t("glossary.bank.name.placeholder")}
                />
              </label>

              <label className="field">
                <span className="field__label">{t("glossary.bank.src_lang")}</span>
                <input
                  className="field__control"
                  value={bankForm.src_lang}
                  onChange={(e) => setBankForm({ ...bankForm, src_lang: e.target.value })}
                  placeholder={t("glossary.bank.src_lang.placeholder")}
                />
              </label>

              <label className="field">
                <span className="field__label">{t("glossary.bank.tgt_lang")}</span>
                <input
                  className="field__control"
                  value={bankForm.tgt_lang}
                  onChange={(e) => setBankForm({ ...bankForm, tgt_lang: e.target.value })}
                  placeholder={t("glossary.bank.tgt_lang.placeholder")}
                />
              </label>

              <label className="field">
                <span className="field__label">{t("glossary.field.scene")}</span>
                <select
                  className="field__control"
                  value={bankForm.domain}
                  onChange={(e) => setBankForm({ ...bankForm, domain: e.target.value })}
                >
                  {scenes.map((s) => (
                    <option key={s.id} value={s.id}>
                      {entityLabel("scene", s.id, s.name)}
                    </option>
                  ))}
                </select>
              </label>

              <p className="muted">{t("glossary.bank.note")}</p>

              <div className="glossary-form__actions">
                <button
                  type="button"
                  className="btn btn--primary"
                  onClick={() => void handleCreateBank()}
                >
                  {bankSaving ? t("glossary.bank.creating") : t("glossary.bank.create_action")}
                </button>
                <button type="button" className="btn btn--ghost" onClick={closeCreateBank}>
                  {t("common.cancel")}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {dragging ? (
        <div className="glossary-drop-hint">
          <div className="glossary-drop-hint__inner">{t("glossary.drop_hint")}</div>
        </div>
      ) : null}
    </div>
  );
}