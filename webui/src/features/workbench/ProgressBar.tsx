// ProgressBar：长文本分批翻译的任务级进度（V10）。
// 显示总片段 / 已完成 / 失败 / 取消 / 剩余、计划批次数、提交前估算与实际调用/花费；
// 有失败片段时提供“重试失败片段”（只重跑未完成部分）。
import { useAppStore } from "../../store/app";
import { t } from "../../i18n/ui";

function pct(done: number, total: number): number {
  if (total <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((done / total) * 100)));
}

export function ProgressBar() {
  const progress = useAppStore((s) => s.progress);
  const estimate = useAppStore((s) => s.estimate);
  const task = useAppStore((s) => s.task);
  const busy = useAppStore((s) => s.busy);
  const retryFailed = useAppStore((s) => s.retryFailed);

  if (!progress || progress.total <= 0) return null;

  const { total, done, failed, cancelled, remaining, batch_total, calls, cost } = progress;
  const tokens = progress.input_tokens + progress.output_tokens;
  const finished = done + failed + cancelled >= total;
  const showBar = !finished || failed > 0;

  const hasUnfinished = remaining > 0 || failed > 0 || cancelled > 0;
  const canRetry = !busy && (failed > 0 || cancelled > 0 || task?.status === "paused");

  return (
    <section className="progress" aria-live="polite" aria-label={t("wb.progress.title")}>
      <div className="progress__head">
        <span className="progress__title">{t("wb.progress.title")}</span>
        <span className="progress__summary">
          {t("wb.progress.summary", { done: String(done), total: String(total) })}
        </span>
        <span className="progress__spacer" />
        {failed > 0 ? (
          <span className="progress__stat progress__stat--bad">
            {t("wb.progress.failed", { n: String(failed) })}
          </span>
        ) : null}
        {cancelled > 0 ? (
          <span className="progress__stat">{t("wb.progress.cancelled", { n: String(cancelled) })}</span>
        ) : null}
        {remaining > 0 ? (
          <span className="progress__stat">{t("wb.progress.remaining", { n: String(remaining) })}</span>
        ) : null}
        {batch_total > 0 ? (
          <span className="progress__stat">
            {t("wb.progress.batch_total", { n: String(batch_total) })}
          </span>
        ) : null}
        {calls > 0 ? (
          <span className="progress__stat">{t("wb.progress.calls", { n: String(calls) })}</span>
        ) : estimate?.est_calls ? (
          <span className="progress__stat">
            {t("wb.progress.estimate", { n: String(estimate.est_calls) })}
          </span>
        ) : null}
        {tokens > 0 ? (
          <span className="progress__stat">
            {t("wb.progress.tokens", {
              input: String(progress.input_tokens),
              output: String(progress.output_tokens),
            })}
          </span>
        ) : null}
        {calls > 0 && cost > 0 ? (
          <span className="progress__stat">{t("wb.progress.cost", { cost: cost.toFixed(6) })}</span>
        ) : null}
        {canRetry && hasUnfinished ? (
          <button type="button" className="btn btn--ghost progress__retry" onClick={() => void retryFailed()}>
            {t("wb.retry.failed")}
          </button>
        ) : null}
      </div>
      {showBar ? (
        <div
          className="progress__track"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct(done, total)}
        >
          <span className="progress__fill" style={{ width: `${pct(done, total)}%` }} />
          {failed > 0 ? (
            <span className="progress__fill progress__fill--bad" style={{ width: `${pct(failed, total)}%` }} />
          ) : null}
          {cancelled > 0 ? (
            <span
              className="progress__fill progress__fill--muted"
              style={{ width: `${pct(cancelled, total)}%` }}
            />
          ) : null}
        </div>
      ) : null}
      {task?.status === "paused" ? <p className="progress__note">{t("wb.progress.paused")}</p> : null}
    </section>
  );
}
