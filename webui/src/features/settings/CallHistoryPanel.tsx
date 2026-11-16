// CallHistoryPanel：设置 → 调用历史。
// 列出每次模型调用的提示词 / 回复 / token / 花费；点行展开详情。
// 提示词默认只显示用户原始输入，点「展开完整提示词」后才显示实际发给模型的完整 messages。
import { Fragment, useEffect, useState } from "react";
import { useAppStore } from "../../store/app";
import { t } from "../../i18n/ui";

function fmtUsd(n: number): string {
  return `$${(n ?? 0).toFixed(4)}`;
}

function fmtCount(n: number): string {
  return (n ?? 0).toLocaleString("zh-CN");
}

function fmtTime(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (x: number): string => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function CallHistoryPanel() {
  const calls = useAppStore((s) => s.calls);
  const total = useAppStore((s) => s.callsTotal);
  const loading = useAppStore((s) => s.callsLoading);
  const error = useAppStore((s) => s.callsError);
  const loadCalls = useAppStore((s) => s.loadCalls);
  const detail = useAppStore((s) => s.callDetail);
  const detailLoading = useAppStore((s) => s.callDetailLoading);
  const openCall = useAppStore((s) => s.openCall);
  const closeCallDetail = useAppStore((s) => s.closeCallDetail);

  const [showFullPrompt, setShowFullPrompt] = useState(false);
  // 分页：调用历史可能上千条，一屏无限拉长会卡；固定每页 20 条
  const PAGE = 20;
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(total / PAGE));

  useEffect(() => {
    void loadCalls(page * PAGE, PAGE);
    // 翻页时收起已展开的详情，避免显示上一页的记录
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  const handleRow = (callId: string): void => {
    setShowFullPrompt(false);
    if (detail?.id === callId) {
      closeCallDetail();
      return;
    }
    void openCall(callId);
  };

  const goPage = (next: number): void => {
    const bounded = Math.max(0, Math.min(pages - 1, next));
    if (bounded === page) return;
    closeCallDetail();
    setPage(bounded);
  };

  return (
    <div className="settings-panel">
      <h2 className="settings-panel__title">{t("calls.title")}</h2>
      <p className="muted">{t("calls.desc")}</p>

      <div className="calls-toolbar">
        <button
          type="button"
          className="btn btn--ghost"
          onClick={() => (page === 0 ? void loadCalls(0, PAGE) : goPage(0))}
        >
          {loading ? t("app.loading") : t("common.refresh")}
        </button>
        <span className="muted">{t("calls.total", { n: String(total) })}</span>
      </div>

      {error ? <p className="muted">{t("calls.load_failed", { error })}</p> : null}
      {!loading && calls.length === 0 ? <p className="muted">{t("calls.empty")}</p> : null}

      {calls.length > 0 ? (
        <table className="billing-table calls-table">
          <thead>
            <tr>
              <th>{t("common.time")}</th>
              <th>{t("calls.provider_model")}</th>
              <th>{t("common.purpose")}</th>
              <th>{t("common.input")}</th>
              <th>{t("common.output")}</th>
              <th>{t("calls.cost")}</th>
              <th>{t("calls.preview")}</th>
            </tr>
          </thead>
          <tbody>
            {calls.map((c) => {
              const expanded = detail?.id === c.id;
              return (
                <Fragment key={c.id}>
                  <tr
                    className={`calls-row${expanded ? " calls-row--active" : ""}`}
                    onClick={() => handleRow(c.id)}
                  >
                    <td>{fmtTime(c.created_at)}</td>
                    <td>
                      {c.provider}
                      {c.model ? ` · ${c.model}` : ""}
                    </td>
                    <td>{c.purpose}</td>
                    <td>{fmtCount(c.input_tokens)}</td>
                    <td>{fmtCount(c.output_tokens)}</td>
                    <td>{fmtUsd(c.amount)}</td>
                    <td className="calls-preview">{c.user_input || c.response_preview || "—"}</td>
                  </tr>
                  {expanded ? (
                    <tr className="calls-detail-row">
                      <td colSpan={7}>
                        {detailLoading ? (
                          <p className="muted">{t("calls.detail_loading")}</p>
                        ) : detail ? (
                          <div className="calls-detail">
                            <div className="calls-detail__meta">
                              <span>{t("calls.field.provider", { v: detail.provider })}</span>
                              <span>{t("calls.field.model", { v: detail.model || "—" })}</span>
                              <span>{t("calls.field.purpose", { v: detail.purpose })}</span>
                              <span>{t("calls.field.time", { v: fmtTime(detail.created_at) })}</span>
                              <span>{t("calls.field.latency", { v: String(detail.latency_ms) })}</span>
                              <span>
                                {t("calls.field.tokens", {
                                  in: fmtCount(detail.input_tokens),
                                  out: fmtCount(detail.output_tokens),
                                })}
                              </span>
                              <span>{t("calls.field.cost", { v: fmtUsd(detail.amount) })}</span>
                            </div>

                            <div className="calls-detail__section">
                              <div className="calls-detail__label">{t("calls.prompt")}</div>
                              {showFullPrompt ? (
                                <div className="calls-prompt">
                                  {detail.prompt.messages.length === 0 ? (
                                    <p className="muted">{t("calls.no_prompt")}</p>
                                  ) : (
                                    detail.prompt.messages.map((m, i) => (
                                      <div key={`${m.role}-${i}`} className="calls-prompt__msg">
                                        <div className="calls-prompt__role">{m.role}</div>
                                        <pre className="calls-pre">{m.content}</pre>
                                      </div>
                                    ))
                                  )}
                                </div>
                              ) : (
                                <pre className="calls-pre calls-pre--input">{detail.user_input || t("calls.no_input")}</pre>
                              )}
                              <button
                                type="button"
                                className="link-btn"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setShowFullPrompt((v) => !v);
                                }}
                              >
                                {showFullPrompt ? t("calls.prompt.collapse") : t("calls.prompt.expand")}
                              </button>
                            </div>

                            <div className="calls-detail__section">
                              <div className="calls-detail__label">{t("calls.response")}</div>
                              <pre className="calls-pre">{detail.response || t("calls.empty_response")}</pre>
                            </div>
                          </div>
                        ) : null}
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      ) : null}

      {total > 0 ? (
        <div className="calls-pager">
          <button type="button" className="btn btn--sm" disabled={page <= 0 || loading} onClick={() => goPage(page - 1)}>
            {t("calls.page.prev")}
          </button>
          <span className="muted">
            {t("calls.page.info", { page: String(page + 1), pages: String(pages) })}
          </span>
          <button
            type="button"
            className="btn btn--sm"
            disabled={page >= pages - 1 || loading}
            onClick={() => goPage(page + 1)}
          >
            {t("calls.page.next")}
          </button>
        </div>
      ) : null}
    </div>
  );
}