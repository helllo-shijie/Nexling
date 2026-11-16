// 设置 → 界面 → 皮肤：内置两套 + 已导入外置包。
// 只改视觉变量：可切换、导入、导出、删除外置包；内置不可删，切回默认即可恢复。
import { useRef, useState } from "react";
import { useAppStore } from "../../store/app";
import { t } from "../../i18n/ui";

function readBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("read failed"));
    reader.onload = () => {
      const text = String(reader.result ?? "");
      const comma = text.indexOf(",");
      resolve(comma >= 0 ? text.slice(comma + 1) : text);
    };
    reader.readAsDataURL(file);
  });
}

export function SkinPanel() {
  const skins = useAppStore((s) => s.skins);
  const activeSkin = useAppStore((s) => s.activeSkin);
  const activeId = useAppStore((s) => s.activeSkinId);
  const busy = useAppStore((s) => s.skinBusy);
  const selectSkin = useAppStore((s) => s.selectSkin);
  const importSkin = useAppStore((s) => s.importSkin);
  const exportSkin = useAppStore((s) => s.exportSkin);
  const deleteSkin = useAppStore((s) => s.deleteSkin);

  const inputRef = useRef<HTMLInputElement>(null);
  const [importError, setImportError] = useState<string | null>(null);

  const onPick = async (file: File | null): Promise<void> => {
    if (!file) return;
    setImportError(null);
    if (file.size > 5 * 1024 * 1024) {
      setImportError(t("skin.import.too_large"));
      return;
    }
    try {
      const data = await readBase64(file);
      await importSkin(file.name, data);
    } catch {
      setImportError(t("skin.import.read_failed"));
    }
  };

  const swatches = activeSkin
    ? [
        activeSkin.vars["--bg"] || "#f7f8fa",
        activeSkin.vars["--surface"] || "#ffffff",
        activeSkin.vars["--accent"] || "#3b5c8f",
        activeSkin.vars["--text"] || "#1b2430",
      ]
    : [];

  return (
    <div className="skin">
      <div className="skin__head">
        <div>
          <p className="muted">{t("skin.desc")}</p>
          {activeSkin ? (
            <p className="skin__current">
              {t("skin.current")}：<strong>{activeSkin.name}</strong>
              <span className={`skin-badge skin-badge--${activeSkin.mode}`}>
                {activeSkin.mode === "dark" ? t("skin.mode.dark") : t("skin.mode.light")}
              </span>
              {activeSkin.builtin ? <span className="skin-badge">{t("skin.builtin")}</span> : null}
              <span className="skin-swatches" aria-hidden="true">
                {swatches.map((c) => (
                  <i key={c} style={{ background: c }} />
                ))}
              </span>
            </p>
          ) : null}
        </div>
        <div className="skin__actions">
          <input
            ref={inputRef}
            type="file"
            accept=".nxlskin"
            hidden
            onChange={(e) => {
              void onPick(e.target.files?.[0] ?? null);
              e.target.value = "";
            }}
          />
          <button
            type="button"
            className="btn btn--primary"
            disabled={busy}
            onClick={() => inputRef.current?.click()}
          >
            {t("skin.import")}
          </button>
        </div>
      </div>

      {importError ? <p className="usage-status__warn">{importError}</p> : null}

      <ul className="skin-list">
        {skins.map((skin) => {
          const active = skin.id === activeId;
          return (
            <li key={skin.id} className={`skin-item${active ? " skin-item--active" : ""}`}>
              <div className="skin-item__main">
                <div className="skin-item__title">
                  <strong>{skin.name}</strong>
                  <span className={`skin-badge skin-badge--${skin.mode}`}>
                    {skin.mode === "dark" ? t("skin.mode.dark") : t("skin.mode.light")}
                  </span>
                  {skin.builtin ? <span className="skin-badge">{t("skin.builtin")}</span> : (
                    <span className="skin-badge skin-badge--external">{t("skin.external")}</span>
                  )}
                  {skin.effects?.glass === "on" ? (
                    <span className="skin-badge">{t("skin.glass")}</span>
                  ) : null}
                  {skin.has_background ? <span className="skin-badge">{t("skin.background")}</span> : null}
                  {active ? <span className="skin-badge skin-badge--active">{t("skin.active")}</span> : null}
                </div>
                <p className="muted skin-item__desc">{skin.description || "—"}</p>
                <p className="skin-item__meta muted">
                  {skin.id}
                  {skin.author ? ` · ${skin.author}` : ""}
                  {skin.updated_at ? ` · ${skin.updated_at.slice(0, 10)}` : ""}
                </p>
              </div>
              <div className="skin-item__actions">
                <button
                  type="button"
                  className="btn btn--sm"
                  disabled={busy || active}
                  onClick={() => void selectSkin(skin.id)}
                >
                  {active ? t("skin.in_use") : t("skin.use")}
                </button>
                <button
                  type="button"
                  className="btn btn--sm"
                  disabled={busy}
                  onClick={() => void exportSkin(skin.id)}
                >
                  {t("skin.export")}
                </button>
                {skin.builtin ? null : (
                  <button
                    type="button"
                    className="btn btn--sm btn--danger"
                    disabled={busy}
                    onClick={() => {
                      if (window.confirm(t("skin.delete_confirm").replace("{name}", skin.name))) {
                        void deleteSkin(skin.id);
                      }
                    }}
                  >
                    {t("skin.delete")}
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      <div className="skin__notes">
        <p className="muted">{t("skin.note.vars")}</p>
        <p className="muted">{t("skin.note.limit")}</p>
        <p className="muted">{t("skin.note.screenshot")}</p>
        <p className="muted">{t("skin.note.fallback")}</p>
      </div>
    </div>
  );
}
