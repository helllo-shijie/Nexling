// 设置 → 用量：四个子页签（账单 / 调用历史 / 统计概览 / 设置）。
// 账单与统计都读 usage 账本；调用历史读 calls 表，裁剪历史不会影响账单数字。
import { useEffect, useState, type ReactNode } from "react";
import { useAppStore } from "../../store/app";
import { t } from "../../i18n/ui";
import { CallHistoryPanel } from "./CallHistoryPanel";
import type { UsageAggRow, UsageRecord, UsageSummary } from "../../bridge/types";

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="settings-panel">
      <h2 className="settings-panel__title">{title}</h2>
      {children}
    </div>
  );
}

function fmtUsd(usd: number): string {
  const v = Number(usd) || 0;
  return `$${v.toFixed(6)}`;
}

function fmtCount(n: number): string {
  return (Number(n) || 0).toLocaleString("en-US");
}

type UsageTab = "billing" | "calls" | "stats" | "settings";

const TABS: { id: UsageTab; key: string }[] = [
  { id: "billing", key: "usage.tab.billing" },
  { id: "calls", key: "usage.tab.calls" },
  { id: "stats", key: "usage.tab.stats" },
  { id: "settings", key: "usage.tab.settings" },
];

function BillingTab() {
  const loadUsageSummary = useAppStore((s) => s.loadUsageSummary);
  const loadUsageList = useAppStore((s) => s.loadUsageList);

  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [records, setRecords] = useState<UsageRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [provider, setProvider] = useState("");
  const [loading, setLoading] = useState(true);
  const [moreLoading, setMoreLoading] = useState(false);

  const refresh = async (p: string): Promise<void> => {
    setLoading(true);
    const [s, l] = await Promise.all([
      loadUsageSummary(),
      loadUsageList({ limit: 50, provider: p || undefined }),
    ]);
    if (s) setSummary(s);
    if (l) {
      setRecords(l.items);
      setTotal(l.total);
    }
    setLoading(false);
  };

  useEffect(() => {
    void refresh("");
    // 仅首次进入时加载一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleProvider = (p: string): void => {
    setProvider(p);
    void refresh(p);
  };

  const loadMore = async (): Promise<void> => {
    if (moreLoading || records.length >= total) return;
    setMoreLoading(true);
    const l = await loadUsageList({
      limit: 50,
      offset: records.length,
      provider: provider || undefined,
    });
    if (l) {
      setRecords((prev) => [...prev, ...l.items]);
      setTotal(l.total);
    }
    setMoreLoading(false);
  };

  const totals = summary?.totals;
  const byProvider: UsageAggRow[] = summary?.by_provider ?? [];
  const byDay: UsageAggRow[] = summary?.by_day ?? [];

  return (
    <Panel title={t("usage.title")}>
      <p className="muted">{t("usage.desc")}</p>

      <div className="billing-cards">
        <div className="billing-card">
          <div className="billing-card__label">{t("usage.total_cost")}</div>
          <div className="billing-card__value">{fmtUsd(totals?.amount ?? 0)}</div>
        </div>
        <div className="billing-card">
          <div className="billing-card__label">{t("usage.input_tokens")}</div>
          <div className="billing-card__value">{fmtCount(totals?.input_tokens ?? 0)}</div>
        </div>
        <div className="billing-card">
          <div className="billing-card__label">{t("usage.output_tokens")}</div>
          <div className="billing-card__value">{fmtCount(totals?.output_tokens ?? 0)}</div>
        </div>
        <div className="billing-card">
          <div className="billing-card__label">{t("usage.calls")}</div>
          <div className="billing-card__value">{fmtCount(totals?.calls ?? 0)}</div>
        </div>
      </div>

      {!loading && (totals?.calls ?? 0) === 0 ? (
        <p className="muted">{t("usage.empty")}</p>
      ) : (
        <>
          {byProvider.length > 0 && (
            <>
              <h3 className="billing-subtitle">{t("usage.by_provider")}</h3>
              <table className="billing-table">
                <thead>
                  <tr>
                    <th>{t("common.provider")}</th>
                    <th>{t("common.amount")}</th>
                    <th>{t("usage.input_tokens")}</th>
                    <th>{t("usage.output_tokens")}</th>
                    <th>{t("usage.calls_short")}</th>
                  </tr>
                </thead>
                <tbody>
                  {byProvider.map((r) => (
                    <tr key={r.k}>
                      <td>{r.k}</td>
                      <td>{fmtUsd(r.amount)}</td>
                      <td>{fmtCount(r.input_tokens)}</td>
                      <td>{fmtCount(r.output_tokens)}</td>
                      <td>{fmtCount(r.n)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          {byDay.length > 0 && (
            <>
              <h3 className="billing-subtitle">{t("usage.by_day")}</h3>
              <table className="billing-table">
                <thead>
                  <tr>
                    <th>{t("common.date")}</th>
                    <th>{t("common.amount")}</th>
                    <th>{t("usage.input_tokens")}</th>
                    <th>{t("usage.output_tokens")}</th>
                    <th>{t("usage.calls_short")}</th>
                  </tr>
                </thead>
                <tbody>
                  {byDay.map((r) => (
                    <tr key={r.k}>
                      <td>{r.k}</td>
                      <td>{fmtUsd(r.amount)}</td>
                      <td>{fmtCount(r.input_tokens)}</td>
                      <td>{fmtCount(r.output_tokens)}</td>
                      <td>{fmtCount(r.n)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          <div className="billing-list-head">
            <h3 className="billing-subtitle">{t("usage.detail")}</h3>
            <label className="field billing-filter">
              <span className="field__label">{t("common.provider")}</span>
              <select
                className="field__control"
                value={provider}
                onChange={(e) => handleProvider(e.target.value)}
              >
                <option value="">{t("usage.all")}</option>
                {byProvider.map((r) => (
                  <option key={r.k} value={r.k}>
                    {r.k}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <table className="billing-table">
            <thead>
              <tr>
                <th>{t("common.time")}</th>
                <th>{t("common.provider")}</th>
                <th>{t("common.model")}</th>
                <th>{t("common.purpose")}</th>
                <th>{t("common.input")}</th>
                <th>{t("common.output")}</th>
                <th>{t("common.amount")}</th>
              </tr>
            </thead>
            <tbody>
              {records.map((r) => (
                <tr key={r.id}>
                  <td>{r.created_at ? r.created_at.replace("T", " ").slice(0, 19) : "-"}</td>
                  <td>{r.provider}</td>
                  <td>{r.model}</td>
                  <td>{r.purpose}</td>
                  <td>{fmtCount(r.input_tokens)}</td>
                  <td>{fmtCount(r.output_tokens)}</td>
                  <td>{fmtUsd(r.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="billing-foot">
            <span className="muted">
              {loading
                ? t("app.loading")
                : t("usage.shown", { shown: String(records.length), total: String(total) })}
            </span>
            {records.length < total && (
              <button type="button" className="btn btn--ghost" onClick={() => void loadMore()}>
                {moreLoading ? t("app.loading") : t("common.load_more")}
              </button>
            )}
          </div>
        </>
      )}
    </Panel>
  );
}

function StatsTab() {
  const stats = useAppStore((s) => s.usageStats);
  const loadStats = useAppStore((s) => s.loadUsageStats);
  const settings = useAppStore((s) => s.settings);
  const [loading, setLoading] = useState(true);

  const refresh = async (): Promise<void> => {
    setLoading(true);
    await loadStats();
    setLoading(false);
  };

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const enabled = settings?.usage?.stats_enabled ?? stats?.enabled ?? true;
  const totals = stats?.totals;
  // 只取最近 14 天做趋势图，避免长表把页面撑高
  const days = (stats?.by_day ?? []).slice(-14);
  const max = Math.max(1e-9, ...days.map((d) => d.amount));

  return (
    <Panel title={t("usage.stats.title")}>
      <p className="muted">{t("usage.stats.desc")}</p>
      {stats && !stats.include_offline ? (
        <p className="muted">{t("usage.stats.offline_excluded")}</p>
      ) : null}
      <div className="stats-toolbar">
        <button type="button" className="btn btn--ghost" onClick={() => void refresh()}>
          {loading ? t("app.loading") : t("common.refresh")}
        </button>
      </div>

      {!enabled ? (
        <p className="muted">{t("usage.stats.disabled")}</p>
      ) : (
        <>
          <div className="billing-cards">
            <div className="billing-card">
              <div className="billing-card__label">{t("usage.total_cost")}</div>
              <div className="billing-card__value">{fmtUsd(totals?.amount ?? 0)}</div>
            </div>
            <div className="billing-card">
              <div className="billing-card__label">{t("usage.stats.total_tokens")}</div>
              <div className="billing-card__value">
                {fmtCount((totals?.input_tokens ?? 0) + (totals?.output_tokens ?? 0))}
              </div>
            </div>
            <div className="billing-card">
              <div className="billing-card__label">{t("usage.calls")}</div>
              <div className="billing-card__value">{fmtCount(totals?.calls ?? 0)}</div>
            </div>
          </div>

          <h3 className="billing-subtitle">{t("usage.stats.trend")}</h3>
          {days.length === 0 ? (
            <p className="muted">{t("usage.empty")}</p>
          ) : (
            <div className="stats-chart" role="img" aria-label={t("usage.stats.trend")}>
              {days.map((d) => (
                <div key={d.day} className="stats-chart__col" title={`${d.day} · ${fmtUsd(d.amount)} · ${d.calls} calls`}>
                  <div
                    className="stats-chart__bar"
                    style={{ height: `${Math.max(4, (d.amount / max) * 100)}%` }}
                  />
                  <span className="stats-chart__label">{d.day.slice(5)}</span>
                </div>
              ))}
            </div>
          )}

          {stats && stats.by_purpose.length > 0 ? (
            <>
              <h3 className="billing-subtitle">{t("usage.stats.by_purpose")}</h3>
              <table className="billing-table">
                <thead>
                  <tr>
                    <th>{t("common.purpose")}</th>
                    <th>{t("usage.calls_short")}</th>
                    <th>{t("usage.input_tokens")}</th>
                    <th>{t("usage.output_tokens")}</th>
                    <th>{t("common.amount")}</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.by_purpose.map((r) => (
                    <tr key={r.purpose || "n/a"}>
                      <td>{r.purpose || "—"}</td>
                      <td>{fmtCount(r.calls)}</td>
                      <td>{fmtCount(r.input_tokens)}</td>
                      <td>{fmtCount(r.output_tokens)}</td>
                      <td>{fmtUsd(r.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : null}
        </>
      )}
    </Panel>
  );
}

function UsageSettingsTab() {
  const settings = useAppStore((s) => s.settings);
  const loadSettings = useAppStore((s) => s.loadSettings);
  const status = useAppStore((s) => s.usageStatus);
  const loadStatus = useAppStore((s) => s.loadUsageStatus);
  const saveUsageSettings = useAppStore((s) => s.saveUsageSettings);
  const cleanupCalls = useAppStore((s) => s.cleanupCalls);
  const clearCalls = useAppStore((s) => s.clearCalls);

  const [retention, setRetention] = useState("2000");
  const [unlimited, setUnlimited] = useState(false);
  const [ageDays, setAgeDays] = useState(0);
  const [statsEnabled, setStatsEnabled] = useState(true);
  const [includeOffline, setIncludeOffline] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    void loadSettings();
    void loadStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (dirty || !settings?.usage) return;
    const u = settings.usage;
    setRetention(String(u.calls_retention));
    setUnlimited(!!u.calls_unlimited);
    setAgeDays(u.calls_max_age_days || 0);
    setStatsEnabled(u.stats_enabled !== false);
    setIncludeOffline(u.stats_include_offline !== false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings]);

  const mark = (): void => setDirty(true);

  const save = async (): Promise<void> => {
    if (unlimited && retention === "0") setRetention("2000");
    setSaving(true);
    const ok = await saveUsageSettings({
      calls_retention: Number(retention) || 2000,
      calls_unlimited: unlimited,
      calls_max_age_days: ageDays,
      stats_enabled: statsEnabled,
      stats_include_offline: includeOffline,
    });
    setSaving(false);
    if (ok) setDirty(false);
  };

  const over = status?.over_limit ?? false;
  // 0 = 不按天数清理：不能借“立即清理”按钮默认删 30 天，必须由用户明确选 30/90。
  const canCleanup = ageDays === 30 || ageDays === 90;

  return (
    <Panel title={t("usage.tab.settings")}>
      <p className="muted">{t("usage.settings.desc")}</p>

      <div className="usage-status">
        <span>
          {t("usage.settings.current", {
            n: String(status?.count ?? 0),
            limit: status?.unlimited ? t("usage.settings.unlimited") : String(status?.limit ?? 0),
          })}
        </span>
        {over ? (
          <span className="usage-status__warn">
            {t("usage.settings.over", { limit: String(status?.limit ?? 0) })}
          </span>
        ) : null}
      </div>

      <div className="usage-form">
        <label className="field">
          <span className="field__label">{t("usage.settings.retention")}</span>
          <input
            className="field__control usage-input"
            type="number"
            min={100}
            max={200000}
            step={100}
            value={retention}
            disabled={unlimited}
            onChange={(e) => {
              setRetention(e.target.value);
              mark();
            }}
          />
          <span className="muted">{t("usage.settings.records")}</span>
        </label>
        <label className="usage-check">
          <input
            type="checkbox"
            checked={unlimited}
            onChange={(e) => {
              setUnlimited(e.target.checked);
              mark();
            }}
          />
          {t("usage.settings.unlimited_switch")}
        </label>

        <label className="field">
          <span className="field__label">{t("usage.settings.age")}</span>
          <select
            className="field__control"
            value={ageDays}
            onChange={(e) => {
              setAgeDays(Number(e.target.value) || 0);
              mark();
            }}
          >
            <option value={0}>{t("usage.settings.age_off")}</option>
            <option value={30}>{t("usage.settings.age_30")}</option>
            <option value={90}>{t("usage.settings.age_90")}</option>
          </select>
        </label>

        <label className="usage-check">
          <input
            type="checkbox"
            checked={statsEnabled}
            onChange={(e) => {
              setStatsEnabled(e.target.checked);
              mark();
            }}
          />
          {t("usage.settings.stats_enabled")}
        </label>
        <label className="usage-check">
          <input
            type="checkbox"
            checked={includeOffline}
            onChange={(e) => {
              setIncludeOffline(e.target.checked);
              mark();
            }}
          />
          {t("usage.settings.include_offline")}
        </label>
      </div>

      <p className="muted">{t("usage.settings.note")}</p>

      <div className="usage-actions">
        <button type="button" className="btn btn--primary" disabled={saving} onClick={() => void save()}>
          {saving ? t("app.loading") : t("usage.settings.save")}
        </button>
        <button
          type="button"
          className="btn btn--ghost"
          disabled={!canCleanup}
          title={canCleanup ? undefined : t("usage.settings.cleanup_off")}
          onClick={() => {
            if (window.confirm(t("usage.settings.cleanup_confirm", { days: String(ageDays) }))) {
              void cleanupCalls(ageDays);
            }
          }}
        >
          {t("usage.settings.cleanup_now")}
        </button>
        <button
          type="button"
          className="btn btn--danger"
          onClick={() => {
            if (window.confirm(t("usage.settings.clear_confirm"))) void clearCalls();
          }}
        >
          {t("usage.settings.clear")}
        </button>
      </div>
      {!canCleanup ? <p className="muted">{t("usage.settings.cleanup_off")}</p> : null}
    </Panel>
  );
}

export function UsagePanel() {
  const [tab, setTab] = useState<UsageTab>("billing");
  return (
    <div className="usage">
      <div className="tabs usage-tabs">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`tab${tab === item.id ? " tab--active" : ""}`}
            onClick={() => setTab(item.id)}
          >
            {t(item.key)}
          </button>
        ))}
      </div>
      {tab === "billing" ? <BillingTab /> : null}
      {tab === "calls" ? <CallHistoryPanel /> : null}
      {tab === "stats" ? <StatsTab /> : null}
      {tab === "settings" ? <UsageSettingsTab /> : null}
    </div>
  );
}
