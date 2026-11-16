// 供应商管理面板（设置 → 模型分区），替换原静态 ProviderTable。
// 交互全部走 store 里的 loadProviders/saveProvider/testProvider/deleteProvider（内部 invoke）。
import { useEffect, useState } from "react";
import { useAppStore } from "../../store/app";
import { notifyInfo } from "../../store/notice";
import { t } from "../../i18n/ui";
import type { ProviderProfile } from "../../bridge/types";

const CUSTOM = "custom";

interface PresetDef {
  id: string;
  name: string;
  base_url: string;
  model: string;
}

const PRESETS: PresetDef[] = [
  { id: "deepseek", name: "DeepSeek", base_url: "https://api.deepseek.com/v1", model: "deepseek-chat" },
  { id: "openai", name: "OpenAI", base_url: "https://api.openai.com/v1", model: "gpt-4o-mini" },
  { id: "claude", name: "Claude", base_url: "https://api.anthropic.com/v1", model: "claude-3-5-sonnet-20241022" },
];

/** 由名称生成稳定 id（自定义预设时用作 provider_id）。 */
function stableProviderId(name: string): string {
  const slug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  if (slug) return `custom-${slug}`;
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return `custom-${h.toString(36)}`;
}

interface FormState {
  preset: string;
  name: string;
  base_url: string;
  model: string;
  api_key: string;
  is_default: boolean;
  allow_custom: boolean;
}

const EMPTY_FORM: FormState = {
  preset: "deepseek",
  name: "DeepSeek",
  base_url: "https://api.deepseek.com/v1",
  model: "deepseek-chat",
  api_key: "",
  is_default: false,
  allow_custom: false,
};

export function ProviderManager() {
  const providers = useAppStore((s) => s.providers);
  const loadProviders = useAppStore((s) => s.loadProviders);
  const saveProvider = useAppStore((s) => s.saveProvider);
  const testProvider = useAppStore((s) => s.testProvider);
  const deleteProvider = useAppStore((s) => s.deleteProvider);

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    void loadProviders();
  }, [loadProviders]);

  const patch = (partial: Partial<FormState>): void =>
    setForm((prev) => ({ ...prev, ...partial }));

  const effectiveId = (f: FormState): string =>
    f.preset === CUSTOM ? stableProviderId(f.name) : f.preset;

  const applyPreset = (presetId: string): void => {
    if (presetId === CUSTOM) {
      patch({ preset: presetId, name: "", base_url: "", model: "", allow_custom: true });
      return;
    }
    const p = PRESETS.find((x) => x.id === presetId);
    patch({
      preset: presetId,
      name: p?.name ?? "",
      base_url: p?.base_url ?? "",
      model: p?.model ?? "",
      allow_custom: false,
    });
  };

  const startCreate = (): void => {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setFormOpen(true);
  };

  const startEdit = (p: ProviderProfile): void => {
    setEditingId(p.id);
    setForm({
      preset: PRESETS.some((x) => x.id === p.preset) ? p.preset : CUSTOM,
      name: p.name,
      base_url: p.base_url,
      model: p.model,
      api_key: "",
      is_default: p.default,
      allow_custom: p.custom_endpoint,
    });
    setFormOpen(true);
  };

  const closeForm = (): void => {
    setFormOpen(false);
    setEditingId(null);
    setForm(EMPTY_FORM);
  };

  const handleTest = async (): Promise<void> => {
    if (testing || saving) return;
    if (!form.base_url.trim() || !form.model.trim()) {
      notifyInfo(t("common.cannot_test"), t("provider.err.base_url_model"));
      return;
    }
    const provider_id = editingId ?? effectiveId(form);
    setTesting(true);
    await testProvider({
      provider_id,
      base_url: form.base_url.trim(),
      model: form.model.trim(),
      api_key: form.api_key,
      allow_custom_endpoint: form.allow_custom,
    });
    setTesting(false);
  };

  const handleSave = async (): Promise<void> => {
    if (testing || saving) return;
    if (!form.name.trim()) {
      notifyInfo(t("common.cannot_save"), t("provider.err.name"));
      return;
    }
    if (!form.base_url.trim() || !form.model.trim()) {
      notifyInfo(t("common.cannot_save"), t("provider.err.base_url_model"));
      return;
    }
    const id = editingId ?? effectiveId(form);
    setSaving(true);
    const ok = await saveProvider(
      {
        id,
        name: form.name.trim(),
        kind: form.preset === CUSTOM ? "custom" : form.preset,
        base_url: form.base_url.trim(),
        model: form.model.trim(),
        is_default: form.is_default,
        enabled: true,
        allow_custom_endpoint: form.allow_custom,
      },
      form.api_key,
    );
    setSaving(false);
    if (ok) closeForm();
  };

  const handleTestRow = async (p: ProviderProfile): Promise<void> => {
    if (busyId) return;
    setBusyId(`test:${p.id}`);
    await testProvider({
      provider_id: p.id,
      base_url: p.base_url,
      model: p.model,
      api_key: "",
      allow_custom_endpoint: p.custom_endpoint,
    });
    setBusyId(null);
  };

  /** 旧库非法地址：用户显式确认后落库 custom_endpoint，才重新进入路由。 */
  const handleConfirmEndpoint = async (p: ProviderProfile): Promise<void> => {
    if (busyId) return;
    setBusyId(`confirm:${p.id}`);
    await saveProvider(
      {
        id: p.id,
        name: p.name,
        kind: p.preset || p.kind || "translate",
        base_url: p.base_url,
        model: p.model,
        is_default: p.default,
        enabled: true,
        allow_custom_endpoint: true,
      },
      "",
    );
    setBusyId(null);
  };

  const handleSetDefault = async (p: ProviderProfile): Promise<void> => {
    if (busyId || p.default) return;
    setBusyId(`default:${p.id}`);
    await saveProvider(
      {
        id: p.id,
        name: p.name,
        kind: p.preset || p.kind || "translate",
        base_url: p.base_url,
        model: p.model,
        is_default: true,
        enabled: true,
        allow_custom_endpoint: p.custom_endpoint,
      },
      "",
    );
    setBusyId(null);
  };

  const handleDelete = async (p: ProviderProfile): Promise<void> => {
    if (busyId) return;
    setBusyId(`delete:${p.id}`);
    await deleteProvider(p.id);
    setBusyId(null);
  };

  return (
    <div className="provider-manager">
      <ul className="provider-list">
        <li className="provider-row provider-row--builtin">
          <div className="provider-row__main">
            <span className="provider-row__name">{t("provider.offline")}</span>
            <span className="provider-row__meta">{t("provider.offline.meta")}</span>
          </div>
          <div className="provider-row__flags">
            {providers.some((p) => p.default) ? null : (
              <span className="flag flag--default">{t("common.default")}</span>
            )}
          </div>
        </li>

        {providers.map((p) => (
          <li className="provider-row" key={p.id}>
            <div className="provider-row__main">
              <span className="provider-row__name">{p.name || p.id}</span>
              <span className="provider-row__meta">
                {p.base_url} · {p.model}
              </span>
            </div>
            <div className="provider-row__flags">
              {p.configured ? (
                <span className="flag flag--ok">{t("provider.configured")}</span>
              ) : (
                <span className="flag flag--muted">{t("provider.unconfigured")}</span>
              )}
              {p.default ? <span className="flag flag--default">{t("common.default")}</span> : null}
              {p.custom_endpoint ? (
                <span className="flag flag--muted">{t("provider.custom_endpoint.flag")}</span>
              ) : null}
              {p.blocked ? <span className="flag flag--warn">{t("provider.blocked")}</span> : null}
              {!p.enabled ? <span className="flag flag--muted">{t("provider.disabled")}</span> : null}
            </div>
            {p.blocked ? <p className="provider-row__warn muted">{t("provider.blocked.hint")}</p> : null}
            <div className="provider-row__actions">
              {p.blocked ? (
                <button
                  type="button"
                  className="link-btn"
                  onClick={() => void handleConfirmEndpoint(p)}
                >
                  {busyId === `confirm:${p.id}`
                    ? t("common.saving")
                    : t("provider.confirm_endpoint")}
                </button>
              ) : (
                <button type="button" className="link-btn" onClick={() => void handleTestRow(p)}>
                  {busyId === `test:${p.id}` ? t("provider.testing") : t("provider.test")}
                </button>
              )}
              <button type="button" className="link-btn" onClick={() => void handleSetDefault(p)}>
                {p.default ? t("common.is_default") : t("common.set_default")}
              </button>
              <button type="button" className="link-btn" onClick={() => startEdit(p)}>
                {t("common.edit")}
              </button>
              <button
                type="button"
                className="link-btn link-btn--danger"
                onClick={() => void handleDelete(p)}
              >
                {busyId === `delete:${p.id}` ? t("common.deleting") : t("common.delete")}
              </button>
            </div>
          </li>
        ))}
      </ul>

      {providers.length === 0 ? <p className="muted">{t("provider.empty")}</p> : null}

      {!formOpen ? (
        <button type="button" className="btn" onClick={startCreate}>
          {t("provider.create")}
        </button>
      ) : (
        <div className="provider-form">
          <h3 className="provider-form__title">{editingId ? t("provider.edit") : t("provider.create")}</h3>

          <label className="field">
            <span className="field__label">{t("provider.preset")}</span>
            <select
              className="field__control"
              value={form.preset}
              onChange={(e) => applyPreset(e.target.value)}
            >
              {PRESETS.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
              <option value={CUSTOM}>{t("provider.custom")}</option>
            </select>
          </label>

          <label className="field">
            <span className="field__label">{t("common.name")}</span>
            <input
              className="field__control"
              value={form.name}
              onChange={(e) => patch({ name: e.target.value })}
              placeholder={t("provider.name.placeholder")}
            />
          </label>

          <label className="field">
            <span className="field__label">Base URL</span>
            <input
              className="field__control"
              value={form.base_url}
              onChange={(e) => patch({ base_url: e.target.value })}
              placeholder="https://api.example.com/v1"
            />
          </label>

          <label className="field field--inline">
            <input
              type="checkbox"
              checked={form.allow_custom}
              onChange={(e) => patch({ allow_custom: e.target.checked })}
            />
            <span>{t("provider.custom_endpoint")}</span>
          </label>
          <p className="provider-form__hint muted">{t("provider.custom_endpoint.hint")}</p>

          <label className="field">
            <span className="field__label">Model</span>
            <input
              className="field__control"
              value={form.model}
              onChange={(e) => patch({ model: e.target.value })}
              placeholder="model-name"
            />
          </label>

          <label className="field">
            <span className="field__label">API Key</span>
            <input
              className="field__control"
              type="password"
              value={form.api_key}
              onChange={(e) => patch({ api_key: e.target.value })}
              placeholder="sk-..."
              autoComplete="off"
            />
          </label>

          <label className="field field--inline">
            <input
              type="checkbox"
              checked={form.is_default}
              onChange={(e) => patch({ is_default: e.target.checked })}
            />
            <span>{t("common.set_default")}</span>
          </label>

          <div className="provider-form__actions">
            <button type="button" className="btn" onClick={() => void handleTest()}>
              {testing ? t("provider.testing") : t("provider.test_connection")}
            </button>
            <button type="button" className="btn btn--primary" onClick={() => void handleSave()}>
              {saving ? t("common.saving") : t("common.save")}
            </button>
            <button type="button" className="btn btn--ghost" onClick={closeForm}>
              {t("common.cancel")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}