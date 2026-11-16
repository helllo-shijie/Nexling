// TermPanel：本文术语一致性入口。
// 列出任务内出现过的术语与当前译法，用户可指定统一译法；只重译译法不一致的片段。
import { useEffect, useState } from "react";
import { useAppStore } from "../../store/app";
import { t } from "../../i18n/ui";
import type { TaskTerm } from "../../bridge/types";

const RUNNING = new Set(["queued", "preparing", "running", "cancelling", "finalizing"]);

function OriginTag({ origin }: { origin: string }) {
  const key =
    origin === "user"
      ? "term.panel.origin.user"
      : origin === "glossary"
        ? "term.panel.origin.glossary"
        : "term.panel.origin.model";
  return <span className={`term-panel__origin term-panel__origin--${origin}`}>{t(key)}</span>;
}

function Row({ term, busy }: { term: TaskTerm; busy: boolean }) {
  const setTaskTerm = useAppStore((s) => s.setTaskTerm);
  const [value, setValue] = useState(term.target_term);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setValue(term.target_term);
  }, [term.target_term]);

  const changed = value.trim() !== "" && value.trim() !== term.target_term;

  const save = async (): Promise<void> => {
    if (!changed || saving) return;
    setSaving(true);
    await setTaskTerm(term.source_term, value.trim());
    setSaving(false);
  };

  return (
    <div className="term-panel__row">
      <span className="term-panel__src" title={term.source_term}>
        {term.source_term}
      </span>
      <input
        className="term-panel__input"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") void save();
        }}
        disabled={busy || saving}
        aria-label={`${term.source_term} → ${t("term.panel.col.target")}`}
      />
      <OriginTag origin={term.origin} />
      <button
        type="button"
        className="btn btn--ghost term-panel__save"
        onClick={() => void save()}
        disabled={busy || saving || !changed}
      >
        {t("term.panel.save")}
      </button>
    </div>
  );
}

export function TermPanel() {
  const terms = useAppStore((s) => s.terms);
  const task = useAppStore((s) => s.task);
  const [open, setOpen] = useState(false);

  if (terms.length === 0) return null;
  const busy = RUNNING.has(task?.status ?? "");

  return (
    <section className={`term-panel${open ? " term-panel--open" : ""}`}>
      <button
        type="button"
        className="term-panel__head"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="term-panel__title">{t("term.panel.title")}</span>
        <span className="term-panel__count">{terms.length}</span>
        <span className="term-panel__spacer" />
        <span className="term-panel__chevron" aria-hidden="true">
          {open ? "▾" : "▸"}
        </span>
      </button>
      {open ? (
        <div className="term-panel__body">
          <p className="term-panel__hint">{busy ? t("term.panel.busy") : t("term.panel.hint")}</p>
          <div className="term-panel__cols">
            <span>{t("term.panel.col.term")}</span>
            <span>{t("term.panel.col.target")}</span>
            <span>{t("term.panel.col.origin")}</span>
            <span />
          </div>
          <div className="term-panel__rows">
            {terms.map((term) => (
              <Row key={term.source_term} term={term} busy={busy} />
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
