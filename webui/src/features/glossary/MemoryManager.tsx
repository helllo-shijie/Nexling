// 翻译记忆（TM）管理：列出复用过的句对，支持关键词/语言对过滤与删除。
// 数据来自后端 memory.list / memory.delete，空库时给明确空状态，不假装有数据。
import { useCallback, useEffect, useState } from "react";
import { invoke } from "../../api/laa";
import { notifyInfo } from "../../store/notice";
import { t } from "../../i18n/ui";

interface MemoryRow {
  entry_id: string;
  source_text: string;
  target_text: string;
  lang_pair: string;
  domain: string;
  approved: boolean;
  quality: number;
  stale: boolean;
  use_count: number;
  last_used_at: string;
}

interface MemoryListResult {
  items: MemoryRow[];
  total: number;
  pairs?: string[];
  stale_total?: number;
}

export function MemoryManager() {
  const [items, setItems] = useState<MemoryRow[]>([]);
  const [total, setTotal] = useState(0);
  const [staleTotal, setStaleTotal] = useState(0);
  const [pairs, setPairs] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [langPair, setLangPair] = useState("");
  const [includeStale, setIncludeStale] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const load = useCallback(async (): Promise<void> => {
    setLoading(true);
    try {
      const res = await invoke<unknown, MemoryListResult>("memory.list", {
        query: query.trim() || undefined,
        lang_pair: langPair || undefined,
        include_stale: includeStale,
        limit: 200,
      });
      setItems(res.items ?? []);
      setTotal(res.total ?? 0);
      setPairs(res.pairs ?? []);
      setStaleTotal(res.stale_total ?? 0);
    } catch (e) {
      notifyInfo(t("memory.load_failed"), e instanceof Error ? e.message : t("common.unknown_error"));
    } finally {
      setLoading(false);
    }
  }, [query, langPair, includeStale]);

  useEffect(() => {
    const timer = setTimeout(() => void load(), 220);
    return () => clearTimeout(timer);
  }, [load]);

  const remove = async (entryId: string): Promise<void> => {
    setBusyId(entryId);
    try {
      const res = await invoke<unknown, { deleted: boolean }>("memory.delete", {
        entry_id: entryId,
      });
      if (res.deleted) {
        setItems((prev) => prev.filter((i) => i.entry_id !== entryId));
        setTotal((n) => Math.max(0, n - 1));
        notifyInfo(t("memory.deleted"), entryId.slice(0, 8));
      } else {
        notifyInfo(t("memory.delete_failed"), t("memory.gone"));
      }
    } catch (e) {
      notifyInfo(t("memory.delete_failed"), e instanceof Error ? e.message : t("common.unknown_error"));
    } finally {
      setBusyId(null);
      setConfirmId(null);
    }
  };

  const restore = async (entryId: string): Promise<void> => {
    setBusyId(entryId);
    try {
      const res = await invoke<unknown, { restored: boolean }>("memory.restore", {
        entry_id: entryId,
      });
      if (res.restored) {
        notifyInfo(t("memory.restored"), entryId.slice(0, 8));
        await load();
      } else {
        notifyInfo(t("memory.restore_failed"), t("memory.gone"));
      }
    } catch (e) {
      notifyInfo(t("memory.restore_failed"), e instanceof Error ? e.message : t("common.unknown_error"));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="memory" aria-label={t("memory.title")}>
      <div className="memory__toolbar">
        <input
          className="field__control memory__search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("memory.search")}
        />
        <select
          className="field__control"
          value={langPair}
          onChange={(e) => setLangPair(e.target.value)}
        >
          <option value="">{t("memory.all_pairs")}</option>
          {pairs.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={includeStale}
            onChange={(e) => setIncludeStale(e.target.checked)}
          />
          <span>{t("memory.include_stale")}</span>
        </label>
        <span className="memory__count muted">
          {loading ? t("memory.loading") : t("memory.count", { n: String(total) })}
        </span>
        {!includeStale && staleTotal > 0 ? (
          <button type="button" className="link-btn" onClick={() => setIncludeStale(true)}>
            {t("memory.stale_total", { n: String(staleTotal) })} · {t("memory.show_stale")}
          </button>
        ) : null}
      </div>

      {!loading && items.length === 0 ? (
        <div className="memory__empty">
          <p>{t("memory.empty.title")}</p>
          <p className="muted">{t("memory.empty.hint")}</p>
        </div>
      ) : (
        <ul className="memory__list">
          {items.map((row) => (
            <li key={row.entry_id} className={`memory__row${row.stale ? " memory__row--stale" : ""}`}>
              <div className="memory__texts">
                <p className="memory__source">{row.source_text}</p>
                <p className="memory__target">{row.target_text}</p>
              </div>
              <div className="memory__meta">
                <span className="chip">{row.lang_pair}</span>
                {row.approved ? <span className="chip chip--ok">{t("memory.approved")}</span> : null}
                {row.stale ? <span className="chip chip--warn">{t("memory.stale")}</span> : null}
                <span className="muted">{t("memory.uses", { n: String(row.use_count) })}</span>
                {row.stale ? (
                  <button
                    type="button"
                    className="btn btn--sm"
                    disabled={busyId === row.entry_id}
                    onClick={() => void restore(row.entry_id)}
                  >
                    {t("memory.restore")}
                  </button>
                ) : null}
                {confirmId === row.entry_id ? (
                  <>
                    <button
                      type="button"
                      className="btn btn--danger btn--sm"
                      disabled={busyId === row.entry_id}
                      onClick={() => void remove(row.entry_id)}
                    >
                      {t("memory.delete_confirm")}
                    </button>
                    <button
                      type="button"
                      className="btn btn--sm"
                      onClick={() => setConfirmId(null)}
                    >
                      {t("memory.cancel")}
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className="btn btn--sm"
                    onClick={() => setConfirmId(row.entry_id)}
                  >
                    {t("memory.delete")}
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
