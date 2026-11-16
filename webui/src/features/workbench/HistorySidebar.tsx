// HistorySidebar：历史记录浮层（从工作台工具栏打开，不再常驻占宽）。
import { useEffect } from "react";
import { useAppStore } from "../../store/app";
import type { HistoryItem } from "../../bridge/types";
import { CloseIcon } from "../../components/icons";
import { targetLangShort } from "./LanguageSelect";
import { t } from "../../i18n/ui";

function langLabel(code: string): string {
  return targetLangShort(code);
}

function formatTime(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (x: number): string => String(x).padStart(2, "0");
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  if (sameDay) return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function HistoryRow({
  item,
  active,
  onOpen,
}: {
  item: HistoryItem;
  active: boolean;
  onOpen: () => void;
}) {
  const failed = item.status !== "succeeded";
  return (
    <button
      type="button"
      className={`history__item${active ? " history__item--active" : ""}`}
      onClick={onOpen}
      title={item.source_text}
    >
      <span className="history__snippet">{item.source_text || t("history.no_source")}</span>
      <span className="history__meta">
        <span className={`mode-tag${item.mode === "literal" ? "" : " mode-tag--fluent"}`}>
          {item.mode === "literal" ? t("mode.literal") : t("mode.fluent")}
        </span>
        <span className="history__lang">{langLabel(item.tgt_lang)}</span>
        {failed ? <span className="history__status">{item.status}</span> : null}
        <span className="history__time">{formatTime(item.created_at)}</span>
      </span>
    </button>
  );
}

export function HistorySidebar({ onClose }: { onClose?: () => void }) {
  const items = useAppStore((s) => s.historyItems);
  const loading = useAppStore((s) => s.historyLoading);
  const error = useAppStore((s) => s.historyError);
  const loadHistory = useAppStore((s) => s.loadHistory);
  const openHistoryTask = useAppStore((s) => s.openHistoryTask);
  const currentTaskId = useAppStore((s) => s.task?.id ?? null);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory, currentTaskId]);

  return (
    <aside className="history">
      <header className="history__head">
        <span className="history__title">{t("history.title")}</span>
        <span className="history__spacer" />
        <button type="button" className="link-btn" onClick={() => void loadHistory()}>
          {loading ? t("common.refreshing") : t("common.refresh")}
        </button>
        {onClose ? (
          <button
            type="button"
            className="icon-btn icon-btn--only"
            onClick={onClose}
            title={t("common.close")}
          >
            <CloseIcon />
          </button>
        ) : null}
      </header>
      {error ? <p className="history__hint">{error}</p> : null}
      {!loading && items.length === 0 ? <p className="history__hint">{t("history.empty")}</p> : null}
      <ul className="history__list">
        {items.map((item) => (
          <li key={item.task_id}>
            <HistoryRow
              item={item}
              active={item.task_id === currentTaskId}
              onOpen={() => {
                void openHistoryTask(item.task_id);
                onClose?.();
              }}
            />
          </li>
        ))}
      </ul>
    </aside>
  );
}
