// 候选术语：术语发现的闭环入口（扫描 → 候选列表 → 采纳写入术语库 / 忽略）。
// 全部走本地规则抽取，不产生 API 调用。
import { useEffect, useState } from "react";
import { useAppStore } from "../../store/app";
import { t } from "../../i18n/ui";

const FILTERS: { value: "pending" | "accepted" | "ignored"; key: string }[] = [
  { value: "pending", key: "term.filter.pending" },
  { value: "accepted", key: "term.filter.accepted" },
  { value: "ignored", key: "term.filter.ignored" },
];

function pct(v: number): string {
  return `${Math.round((v || 0) * 100)}%`;
}

export function TermDiscovery() {
  const candidates = useAppStore((s) => s.termCandidates);
  const counts = useAppStore((s) => s.termCounts);
  const status = useAppStore((s) => s.termStatus);
  const loading = useAppStore((s) => s.termLoading);
  const scanning = useAppStore((s) => s.termScanning);
  const task = useAppStore((s) => s.task);
  const load = useAppStore((s) => s.loadTermCandidates);
  const scan = useAppStore((s) => s.scanTerms);
  const accept = useAppStore((s) => s.acceptTermCandidate);
  const ignore = useAppStore((s) => s.ignoreTermCandidates);
  const autoScan = useAppStore((s) => s.termAutoScan);
  const lastScanAt = useAppStore((s) => s.termLastScanAt);
  const setAutoScan = useAppStore((s) => s.setTermAutoScan);
  const acceptHigh = useAppStore((s) => s.acceptHighQualityTerms);
  const bulkFailures = useAppStore((s) => s.termBulkFailures);
  const banks = useAppStore((s) => s.banks);
  const loadBanks = useAppStore((s) => s.loadBanks);
  const settings = useAppStore((s) => s.settings);
  const loadSettings = useAppStore((s) => s.loadSettings);
  const clearColumn = useAppStore((s) => s.clearTermColumn);
  const autoReview = useAppStore((s) => s.termAutoReview);
  const autoBusy = useAppStore((s) => s.termAutoReviewBusy);
  const autoLast = useAppStore((s) => s.termAutoReviewLast);
  const loadAutoReview = useAppStore((s) => s.loadTermAutoReview);
  const runAutoReview = useAppStore((s) => s.runTermAutoReview);
  const undoAutoReview = useAppStore((s) => s.undoTermAutoReview);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [targetBank, setTargetBank] = useState("");
  const [confirmClear, setConfirmClear] = useState(false);

  useEffect(() => {
    void load(status);
    void loadAutoReview();
    // 语言或任务切换后重新拉取即可，status 变化由筛选按钮驱动
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, task?.id]);

  useEffect(() => {
    if (!settings) void loadSettings();
  }, [settings, loadSettings]);

  useEffect(() => {
    setConfirmClear(false);
  }, [status]);

  useEffect(() => {
    if (banks.length === 0) void loadBanks();
  }, [banks.length, loadBanks]);

  // 可写入的库：只列个人库（内置库只读，写了也会被后端拒绝）
  const writableBanks = banks.filter((b) => b.readonly !== 1 && b.scope === "personal");
  const writableIds = new Set(writableBanks.map((b) => b.id));
  const bankName = (id: string): string => writableBanks.find((b) => b.id === id)?.name ?? id;
  const effectiveBankOf = (c: { bank_id?: string }): string =>
    targetBank || (writableIds.has(c.bank_id ?? "") ? (c.bank_id ?? "") : "");

  const emptyHint =
    status === "accepted"
      ? t("term.empty.accepted")
      : status === "ignored"
        ? t("term.empty.ignored")
        : t("term.empty.pending");
  const highPending = candidates.filter(
    (c) => c.quality === "high" && (c.target_term ?? "").trim().length > 0,
  );
  const bulkMissingBank = highPending.filter((c) => !effectiveBankOf(c)).length;
  const lastScanLabel = lastScanAt
    ? t("term.last_scan", { t: new Date(lastScanAt).toLocaleTimeString() })
    : t("term.never_scan");
  const limit = settings?.term_candidate_limits?.[status] ?? 0;
  const count = counts[status] ?? 0;
  const canUndo = Boolean(autoLast?.batch_id || autoReview?.last_batch?.id);

  const handleClear = (): void => {
    if (!confirmClear) {
      setConfirmClear(true);
      return;
    }
    setConfirmClear(false);
    void clearColumn(status);
  };

  return (
    <section className="discovery">
      <header className="discovery__head">
        <div className="discovery__intro">
          <h2 className="discovery__title">{t("term.title")}</h2>
          <p className="discovery__desc">{t("term.desc")}</p>
        </div>
        <div className="discovery__actions">
          <label className="switch" title={t("term.autoscan")}>
            <input
              type="checkbox"
              checked={autoScan}
              onChange={(e) => setAutoScan(e.target.checked)}
            />
            <span className="switch__track" aria-hidden="true" />
            <span className="switch__label">{t("term.autoscan")}</span>
          </label>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => void scan()}
            disabled={!task || scanning}
            title={!task ? t("term.need_task") : undefined}
          >
            {scanning ? t("term.scanning") : task ? t("term.scan") : t("term.rescan")}
          </button>
        </div>
      </header>

      <div className="discovery__filters" role="tablist">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            role="tab"
            aria-selected={status === f.value}
            className={`chip-btn${status === f.value ? " chip-btn--active" : ""}`}
            onClick={() => void load(f.value)}
          >
            {t(f.key)}
            <span className="chip-btn__count">{counts[f.value] ?? 0}</span>
          </button>
        ))}
        <span className="discovery__stamp">{lastScanLabel}</span>
        <span className="discovery__limit muted" title={t("term.limit.hint")}>
          {limit > 0 ? t("term.limit", { n: String(limit) }) : t("term.unlimited")}
        </span>
        <button
          type="button"
          className="btn btn--ghost btn--sm discovery__clear"
          onClick={handleClear}
          onBlur={() => setConfirmClear(false)}
          disabled={count === 0}
          title={t("term.clear.hint")}
        >
          {confirmClear ? t("term.clear.confirm") : t("term.clear")}
        </button>
        {status === "pending" && highPending.length > 0 ? (
          <button
            type="button"
            className="btn btn--secondary btn--sm discovery__bulk"
            onClick={() => void acceptHigh(targetBank || undefined)}
            disabled={bulkMissingBank > 0 && !targetBank}
            title={bulkMissingBank > 0 && !targetBank ? t("term.target_bank.pick") : undefined}
          >
            {t("term.bulk.accept", { n: String(highPending.length) })}
          </button>
        ) : null}
      </div>

      {autoReview ? (
        <div className="discovery__auto" role="status">
          <div className="discovery__auto-main">
            <span className="discovery__auto-title">{t("term.auto.title")}</span>
            <span className="muted">
              {autoReview.enabled
                ? t("term.auto.threshold_hint", { n: String(autoReview.threshold) })
                : t("term.auto.off_hint")}
            </span>
            {autoReview.available ? null : (
              <span className="discovery__auto-warn">
                {autoReview.reason || t("term.auto.need_model")}
              </span>
            )}
          </div>
          <div className="discovery__auto-actions">
            {autoReview.allow_manual ? (
              <button
                type="button"
                className="btn btn--secondary btn--sm"
                onClick={() => void runAutoReview()}
                disabled={autoBusy || !autoReview.available || autoReview.pending === 0}
                title={
                  !autoReview.available
                    ? autoReview.reason || t("term.auto.need_model")
                    : autoReview.pending === 0
                      ? t("term.empty.pending")
                      : undefined
                }
              >
                {autoBusy ? t("term.auto.running") : t("term.auto.run")}
              </button>
            ) : null}
            {canUndo ? (
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={() => void undoAutoReview()}
              >
                {t("term.auto.undo")}
              </button>
            ) : null}
          </div>
          {autoLast && autoLast.available !== false ? (
            <>
              <p className="discovery__auto-result">
                {t("term.auto.summary", {
                  n: String(autoLast.processed),
                  accepted: String(autoLast.accepted_count),
                  ignored: String(autoLast.ignored_count),
                  failed: String(autoLast.failed_count),
                })}
              </p>
              {autoLast.failed.length > 0 ? (
                <ul className="discovery__failed-list">
                  {autoLast.failed.map((f) => (
                    <li key={f.id}>
                      <span className="discovery__failed-term">{f.source_term || f.id}</span>
                      <span className="discovery__failed-reason">{f.reason}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
              {autoLast.needs_bank?.length ? (
                <>
                  <p className="discovery__auto-result muted">
                    {t("term.auto.needs_bank", { n: String(autoLast.needs_bank_count) })}
                  </p>
                  <ul className="discovery__failed-list">
                    {autoLast.needs_bank.map((n) => (
                      <li key={n.id}>
                        <span className="discovery__failed-term">{n.source_term || n.id}</span>
                        <span className="discovery__failed-reason">{n.reason}</span>
                      </li>
                    ))}
                  </ul>
                </>
              ) : null}
            </>
          ) : null}
          {!autoLast && autoReview.last_batch?.id ? (
            <p className="discovery__auto-result muted">
              {t("term.auto.last", {
                accepted: String(autoReview.last_batch.counts?.accepted ?? 0),
                t: autoReview.last_batch.created_at ?? "",
              })}
            </p>
          ) : null}
        </div>
      ) : null}

      {status === "pending" ? (
        <div className="discovery__target">
          <label className="field field--inline">
            <span className="field__label">{t("term.target_bank")}</span>
            <select
              className="field__control"
              value={targetBank}
              onChange={(e) => setTargetBank(e.target.value)}
            >
              <option value="">{t("term.target_bank.auto")}</option>
              {writableBanks.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </label>
          <span className="discovery__target-hint muted">
            {targetBank
              ? bankName(targetBank)
              : bulkMissingBank > 0
                ? t("term.target_bank.pick")
                : t("term.target_bank.auto")}
          </span>
        </div>
      ) : null}

      {status === "pending" && bulkFailures.length > 0 ? (
        <div className="discovery__failed" role="status">
          <p className="discovery__failed-title">
            {t("term.bulk.failed", { n: String(bulkFailures.length) })}
          </p>
          <ul className="discovery__failed-list">
            {bulkFailures.map((f) => (
              <li key={f.id}>
                <span className="discovery__failed-term">{f.source_term}</span>
                <span className="discovery__failed-bank">
                  {t("term.target_bank")}：
                  {f.bank_id ? bankName(f.bank_id) : t("term.target_bank.none")}
                </span>
                <span className="discovery__failed-reason">{f.error}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {loading ? <p className="discovery__hint">{t("app.loading")}</p> : null}
      {!loading && candidates.length === 0 ? (
        <p className="discovery__empty">{emptyHint}</p>
      ) : null}

      <ul className="discovery__list">
        {candidates.map((c) => {
          const draft = drafts[c.id] ?? c.target_term ?? "";
          const effBank = effectiveBankOf(c);
          return (
            <li key={c.id} className="cand">
              <div className="cand__main">
                <div className="cand__term">
                  <span className="cand__source">{c.source_term}</span>
                  {status === "pending" ? (
                    <input
                      className="cand__input"
                      value={draft}
                      placeholder={t("term.target.placeholder")}
                      onChange={(e) => setDrafts((d) => ({ ...d, [c.id]: e.target.value }))}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && draft.trim() && effBank) {
                          void accept(c.id, draft, effBank);
                        }
                      }}
                    />
                  ) : (
                    <span className="cand__target">{c.target_term || "—"}</span>
                  )}
                </div>
                <div className="cand__meta">
                  {c.quality ? (
                    <span className={`cand__quality cand__quality--${c.quality}`}>
                      {t(`term.quality.${c.quality}`)}
                    </span>
                  ) : null}
                  <span className="cand__badge">{t("term.occurrences", { n: String(c.occurrences) })}</span>
                  <span className="cand__badge">{t("term.confidence", { p: pct(c.confidence) })}</span>
                  {(c.reasons ?? []).map((r) => (
                    <span key={r} className="cand__badge cand__badge--reason">
                      {t(`term.reason.${r}`)}
                    </span>
                  ))}
                  {c.target_term && status === "pending" ? (
                    <span className="cand__hint">{t("term.suggested")}</span>
                  ) : null}
                  {status === "pending" ? (
                    effBank ? (
                      <span className="cand__badge">
                        {t("term.target_bank")}：{bankName(effBank)}
                      </span>
                    ) : (
                      <span className="cand__badge cand__badge--warn">
                        {t("term.target_bank.none")}
                      </span>
                    )
                  ) : null}
                </div>
                {c.context ? (
                  <p className="cand__context" title={c.context}>
                    <span className="cand__contextLabel">{t("term.context")}</span>
                    {c.context}
                  </p>
                ) : null}
              </div>
              {status === "pending" ? (
                <div className="cand__actions">
                  <button
                    type="button"
                    className="btn btn--primary btn--sm"
                    onClick={() => void accept(c.id, draft, effBank || undefined)}
                    disabled={!draft.trim() || !effBank}
                    title={!effBank ? t("term.need_bank") : undefined}
                  >
                    {t("term.accept")}
                  </button>
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    onClick={() => void ignore([c.id])}
                  >
                    {t("term.ignore")}
                  </button>
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
