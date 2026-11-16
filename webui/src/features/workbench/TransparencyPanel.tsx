// TransparencyPanel：译文下方的「透明化」区域。
// 一眼可见区（brief）：置信度、风险、情感倾向与概率分布、命中术语——不用展开就能看到；
// 展开区只放细节（情感概率条、风险原因、术语说明、翻译记忆、情绪标注）。
import { useState } from "react";
import type { AnnotatedSpan, MemoryHit, SegmentView } from "../../bridge/types";
import { invoke } from "../../api/laa";
import { useAppStore } from "../../store/app";
import { notifyInfo } from "../../store/notice";
import { t } from "../../i18n/ui";

const BAND_KEY: Record<string, string> = {
  high: "band.high",
  medium: "band.medium",
  low: "band.low",
  unknown: "band.unknown",
};

const MATCH_KEY: Record<string, string> = {
  exact: "match.exact",
  fuzzy: "match.fuzzy",
  keyword: "match.keyword",
};

function bandLabel(band: string): string {
  const key = BAND_KEY[band];
  return key ? t(key) : band;
}

function matchLabel(kind: string): string {
  const key = MATCH_KEY[kind];
  return key ? t(key) : kind;
}

function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

function SentimentBars({ segment }: { segment: SegmentView }) {
  const s = segment.sentiment;
  if (!s) {
    return <p className="tp__hint">{t("tp.no_sentiment")}</p>;
  }
  const rows: { key: "positive" | "negative" | "neutral"; label: string; cls: string }[] = [
    { key: "positive", label: t("sentiment.positive"), cls: "bar--pos" },
    { key: "negative", label: t("sentiment.negative"), cls: "bar--neg" },
    { key: "neutral", label: t("sentiment.neutral"), cls: "bar--neu" },
  ];
  const top = ["positive", "negative", "neutral"].reduce((a, b) =>
    (s[a as "positive"] ?? 0) >= (s[b as "positive"] ?? 0) ? a : b,
  ) as "positive" | "negative" | "neutral";
  const topLabel = { positive: t("sentiment.positive"), negative: t("sentiment.negative"), neutral: t("sentiment.neutral") }[top];

  return (
    <div className="tp__sentiment">
      <div className="tp__sentiment-head">
        <span>{t("wb.sentiment")}</span>
        {segment.channel === "offline" ? (
          <span className="chip chip--warn">{t("tp.offline_estimate")}</span>
        ) : null}
        <span className="muted">
          {t("tp.top", { label: topLabel, pct: pct(s[top]) })}
        </span>
      </div>
      {rows.map((r) => (
        <div key={r.key} className="bar">
          <span className="bar__label">{r.label}</span>
          <span className="bar__track">
            <span className={`bar__fill ${r.cls}`} style={{ width: pct(s[r.key] ?? 0) }} />
          </span>
          <span className="bar__value">{pct(s[r.key] ?? 0)}</span>
        </div>
      ))}
      {s.needs_review ? <p className="tp__warn">{t("wb.recheck")}</p> : null}
    </div>
  );
}

function MemoryBlock({ segment }: { segment: SegmentView }) {
  const task = useAppStore((s) => s.task);
  const targetLang = useAppStore((s) => s.targetLang);
  const overrideTarget = useAppStore((s) => s.overrideTarget);
  // 后端已随视图下发召回命中：默认直接展示，不再要求用户手动点「查询」
  const [hits, setHits] = useState<MemoryHit[] | null>(segment.tm_hits ?? null);
  const [loading, setLoading] = useState(false);

  const lookup = async (): Promise<void> => {
    setLoading(true);
    try {
      const items = await invoke<unknown, MemoryHit[]>("memory.lookup", {
        source_text: segment.source_text,
        src_lang: task?.src_lang ?? task?.detected_lang ?? "auto",
        tgt_lang: task?.tgt_lang ?? targetLang,
        domain: task?.domain ?? "general",
      });
      setHits(items ?? []);
    } catch (e) {
      notifyInfo(t("tp.memory.failed"), e instanceof Error ? e.message : t("common.unknown_error"));
      setHits([]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="tp__cell tp__cell--wide">
      <span className="tp__k">{t("tp.memory")}</span>
      {hits === null ? (
        <button type="button" className="link-btn" onClick={() => void lookup()} disabled={loading}>
          {loading ? t("tp.memory.loading") : t("tp.memory.lookup")}
        </button>
      ) : hits.length === 0 ? (
        <span className="tp__v muted">{t("tp.memory.empty")}</span>
      ) : (
        <>
          <button type="button" className="link-btn tp__refresh" onClick={() => void lookup()} disabled={loading}>
            {loading ? t("tp.memory.loading") : t("tp.memory.refresh")}
          </button>
          <ul className="tm-list">
            {hits.map((h) => (
              <li key={h.entry_id} className="tm-item">
                <div className="tm-item__head">
                  <span className={`tm-kind tm-kind--${h.match_kind}`}>
                    {matchLabel(h.match_kind)}
                  </span>
                  <span className="muted">{pct(h.score)}</span>
                  <button
                    type="button"
                    className="link-btn tm-item__apply"
                    onClick={() => void overrideTarget(segment.segment_id, h.target_text, "tm_apply", h.entry_id)}
                  >
                    {t("tp.memory.apply")}
                  </button>
                </div>
                <p className="tm-item__text">{h.target_text}</p>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

export function TransparencyPanel({
  segment,
  onTermFocus,
}: {
  segment: SegmentView;
  onTermFocus?: (term: string) => void;
}) {
  const confidence = segment.confidence;
  const band = confidence?.band ?? null;
  const score = confidence?.score;
  const terms = (segment.spans ?? []).filter((s: AnnotatedSpan) =>
    s.kinds.includes("terminology_applied"),
  );
  const sentiment = segment.sentiment;
  const topSentiment = sentiment
    ? ["positive", "negative", "neutral"].reduce((a, b) =>
        (sentiment[a as "positive"] ?? 0) >= (sentiment[b as "positive"] ?? 0) ? a : b,
      )
    : null;
  const sentimentText = topSentiment
    ? {
        positive: t("sentiment.positive"),
        negative: t("sentiment.negative"),
        neutral: t("sentiment.neutral"),
      }[topSentiment as "positive" | "negative" | "neutral"]
    : "—";

  return (
    <div className="tp">
      <div className="tp__brief">
        <span className={`tp__badge tp__badge--${band ?? "unknown"}`}>
          <span className="tp__badge-k">{t("wb.confidence")}</span>
          <span className="tp__badge-v">
            {score != null ? pct(score) : band ? bandLabel(band) : "—"}
          </span>
        </span>
        <span className={`tp__badge tp__badge--risk${segment.risk?.tier && segment.risk.tier !== "L0" ? " tp__badge--risk-high" : ""}`}>
          <span className="tp__badge-k">{t("wb.risk")}</span>
          <span className="tp__badge-v">{segment.risk?.tier ?? "L0"}</span>
        </span>

        {sentiment ? (
          <span className="tp__mini" title={`${t("wb.sentiment")}：${sentimentText} ${pct(sentiment[topSentiment as "positive"] ?? 0)}`}>
            <span className="tp__mini-track" aria-hidden="true">
              <i className="tp__mini-pos" style={{ flex: Math.max(sentiment.positive ?? 0, 0.02) }} />
              <i className="tp__mini-neg" style={{ flex: Math.max(sentiment.negative ?? 0, 0.02) }} />
              <i className="tp__mini-neu" style={{ flex: Math.max(sentiment.neutral ?? 0, 0.02) }} />
            </span>
            <em>
              {sentimentText} {pct(sentiment[topSentiment as "positive"] ?? 0)}
            </em>
          </span>
        ) : null}

        {terms.slice(0, 3).map((s) => (
          <button
            key={s.id}
            type="button"
            className="chip chip--term"
            onClick={() => onTermFocus?.(s.text)}
            title={t("tp.highlight")}
          >
            {s.text}
          </button>
        ))}
        {terms.length > 3 ? (
          <button
            type="button"
            className="chip chip--more"
            onClick={() => onTermFocus?.(terms[3].text)}
            title={t("tp.highlight")}
          >
            +{terms.length - 3}
          </button>
        ) : null}
        {terms.length === 0 ? <span className="chip chip--muted">{t("tp.no_terms_short")}</span> : null}
        {segment.emotions?.length ? (
          <span className="chip chip--muted">
            {t("tp.emotions")} {segment.emotions.length}
          </span>
        ) : null}
        {segment.tm_hits?.length ? (
          <span className="chip chip--muted" title={t("tp.memory")}>
            {t("tp.memory")} {segment.tm_hits.length}
          </span>
        ) : null}
      </div>

      <details className="tp__details">
        <summary className="tp__summary">
          <span className="tp__more">{t("tp.details")}</span>
        </summary>
        <div className="tp__body">
          <SentimentBars segment={segment} />
          <div className="tp__grid">
            <div className="tp__cell">
              <span className="tp__k">{t("wb.confidence")}</span>
              <span className="tp__v">
                {score != null ? pct(score) : "—"}
                {band ? ` · ${bandLabel(band)}` : ""}
              </span>
            </div>
            <div className="tp__cell">
              <span className="tp__k">{t("wb.risk")}</span>
              <span className="tp__v">{segment.risk?.tier ?? "L0"}</span>
              {segment.risk?.reason ? <span className="tp__note">{segment.risk.reason}</span> : null}
            </div>
            <div className="tp__cell tp__cell--wide">
              <span className="tp__k">{t("wb.terms")}</span>
              {terms.length === 0 ? (
                <span className="tp__v muted">{t("tp.no_terms")}</span>
              ) : (
                <ul className="tp__terms">
                  {terms.map((s) => (
                    <li key={s.id}>
                      <button
                        type="button"
                        className="link-btn"
                        onClick={() => onTermFocus?.(s.text)}
                        title={t("tp.highlight")}
                      >
                        <b>{s.text}</b>
                      </button>
                      {s.note ? <span className="muted"> — {s.note}</span> : null}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <MemoryBlock segment={segment} />
            {segment.emotions?.length ? (
              <div className="tp__cell tp__cell--wide">
                <span className="tp__k">{t("tp.emotions")}</span>
                <div className="emotions">
                  {segment.emotions.map((e, i) => (
                    <span
                      key={`${e.segment_id}-${i}`}
                      className={`emotion emotion--${e.emotion}${
                        e.align_status !== "matched" ? " emotion--misaligned" : ""
                      }`}
                      title={e.evidence || e.note || undefined}
                    >
                      {e.emotion}
                      {e.intensity > 0 ? ` +${e.intensity}` : ""}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </details>
    </div>
  );
}
