// SpanRenderer：按字符区间渲染译文，保证重叠标注不重复、不丢字。
// 术语 -> 点线；中文保留 -> 浅色细下划线；候选译法 -> 虚线下划线 + 点开气泡切换。
// 句子级情感 -> 句子左侧细色条（中性不着色），悬停看三项概率，点开看与段落结论的关系。
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { AnnotatedSpan, SegmentView, SentenceSentiment } from "../../bridge/types";
import { useAppStore } from "../../store/app";
import { LiteralWords } from "./LiteralWords";
import { t } from "../../i18n/ui";

const KIND_CLASS: Record<string, string> = {
  terminology_applied: "span span--term",
  alternate_translation: "span span--alt",
  common_translation: "span span--common",
  source_lang_kept: "span span--kept",
  literal_style: "span span--literal",
  risk_flag: "span span--risk",
  emotion_tag: "span span--emotion",
  qa_fixed: "span span--qa",
};

// 同一字符被多个标注覆盖时，数值大者胜出
const PRIORITY: Record<string, number> = {
  terminology_applied: 60,
  alternate_translation: 50,
  source_lang_kept: 40,
  risk_flag: 30,
  qa_fixed: 25,
  emotion_tag: 20,
  common_translation: 10,
  literal_style: 5,
};

function rank(kinds: string[]): number {
  return Math.max(0, ...kinds.map((k) => PRIORITY[k] ?? 0));
}

function spanClass(kinds: string[]): string {
  return kinds.map((k) => KIND_CLASS[k]).filter(Boolean).join(" ");
}

type Piece = { text: string; span: AnnotatedSpan | null };

function composePieces(text: string, spans: AnnotatedSpan[]): Piece[] {
  const n = text.length;
  const owner: number[] = new Array(n).fill(-1);
  const usable = spans.filter(
    (s) => Array.isArray(s.span) && s.span.length >= 2 && !s.kinds.includes("low_confidence"),
  );
  usable.forEach((s, i) => {
    const start = Math.max(0, Math.min(s.span[0], n));
    const end = Math.max(start, Math.min(s.span[1], n));
    for (let j = start; j < end; j += 1) {
      const cur = owner[j];
      if (cur < 0 || rank(usable[i].kinds) > rank(usable[cur].kinds)) owner[j] = i;
    }
  });

  const pieces: Piece[] = [];
  let i = 0;
  while (i < n) {
    const o = owner[i];
    let j = i + 1;
    while (j < n && owner[j] === o) j += 1;
    pieces.push({ text: text.slice(i, j), span: o >= 0 ? usable[o] : null });
    i = j;
  }
  return pieces;
}

/** 截取 [start, end) 区间内的 span 并换算成相对区间，供句子内复用同一套渲染。 */
function slicePieces(text: string, spans: AnnotatedSpan[], start: number, end: number): Piece[] {
  const local = spans
    .filter((s) => Array.isArray(s.span) && s.span[0] < end && s.span[1] > start)
    .map((s) => ({ ...s, span: [Math.max(s.span[0], start) - start, Math.min(s.span[1], end) - start] }));
  return composePieces(text.slice(start, end), local);
}

function VariantPiece({ piece, segment }: { piece: Piece; segment: SegmentView }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number; placement: "top" | "bottom" } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const bubbleRef = useRef<HTMLDivElement>(null);
  const pickVariant = useAppStore((s) => s.pickVariant);
  const span = piece.span;

  // 气泡挂到 body 上（portal），避免被祖先的 overflow / 层叠上下文裁切
  useLayoutEffect(() => {
    if (!open) {
      setPos(null);
      return;
    }
    const place = (): void => {
      const trigger = triggerRef.current;
      const bubble = bubbleRef.current;
      if (!trigger || !bubble) return;
      const rect = trigger.getBoundingClientRect();
      const width = bubble.offsetWidth;
      const height = bubble.offsetHeight;
      const gap = 8;
      const margin = 8;
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const left = Math.min(Math.max(margin, rect.left), Math.max(margin, vw - width - margin));
      const below = rect.bottom + gap;
      const above = rect.top - gap - height;
      if (below + height > vh - margin && above >= margin) {
        setPos({ top: above, left, placement: "top" });
      } else {
        const top = below + height > vh - margin
          ? Math.max(margin, vh - margin - height)
          : below;
        setPos({ top, left, placement: "bottom" });
      }
    };
    place();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(place) : null;
    if (observer && bubbleRef.current) observer.observe(bubbleRef.current);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus({ preventScroll: true });
      }
    };
    window.addEventListener("keydown", onKey);
    const first = bubbleRef.current?.querySelector<HTMLButtonElement>(".variant__opt");
    first?.focus({ preventScroll: true });
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent): void => {
      const target = e.target as Node;
      if (bubbleRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      // 点击外部关闭与 Esc 一致：焦点回到触发元素（遮罩会在 mousedown 时先被卸载）
      setOpen(false);
      triggerRef.current?.focus({ preventScroll: true });
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  if (!span) return <>{piece.text}</>;
  const variants = span.variants ?? [];

  return (
    <span className="variant">
      <button
        type="button"
        ref={triggerRef}
        className={`span span--alt variant__trigger${open ? " variant__trigger--open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        title={t("wb.alternates")}
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        {piece.text}
      </button>
      {open
        ? createPortal(
            <>
              <div
                className="variant__scrim"
                aria-hidden="true"
                onClick={() => {
                  setOpen(false);
                  triggerRef.current?.focus({ preventScroll: true });
                }}
              />
              <div
                ref={bubbleRef}
                className={`variant__bubble variant__bubble--${pos?.placement ?? "bottom"}`}
                role="dialog"
                aria-label={t("wb.alternates")}
                style={{
                  top: pos?.top ?? 0,
                  left: pos?.left ?? 0,
                  visibility: pos ? "visible" : "hidden",
                }}
              >
                <span className="variant__bubble-title">{t("wb.alternates")}</span>
                {variants.map((v) => {
                  const current = v.text === piece.text;
                  return (
                    <button
                      key={v.id}
                      type="button"
                      className={`variant__opt${current ? " variant__opt--current" : ""}`}
                      onClick={() => {
                        setOpen(false);
                        if (!current) {
                          void pickVariant(segment.segment_id, span.span, v.text || v.label);
                        }
                      }}
                    >
                      {v.text || v.label}
                      {current ? <span className="variant__tag">{t("variant.current")}</span> : null}
                    </button>
                  );
                })}
                <span className="variant__hint">{t("variant.hint")}</span>
              </div>
            </>,
            document.body,
          )
        : null}
    </span>
  );
}

function pct(v: number | undefined): number {
  return Math.round((v ?? 0) * 100);
}

function sentLabel(label: SentenceSentiment["label"]): string {
  return t(`sent.label.${label}`);
}

/** 句子级情感：左侧细色条 + 悬停概率；点开显示三项概率与段落结论的关系。 */
function SentenceMark({
  sentence,
  paragraph,
  children,
}: {
  sentence: SentenceSentiment;
  paragraph: { positive: number; negative: number; neutral: number };
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number; placement: "top" | "bottom" } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const bubbleRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  const hover = t("sent.title", {
    pos: String(pct(sentence.positive)),
    neg: String(pct(sentence.negative)),
    neu: String(pct(sentence.neutral)),
  });
  const paragraphLabel = pct(paragraph.positive) >= pct(paragraph.negative)
    && pct(paragraph.positive) >= pct(paragraph.neutral)
    ? "positive"
    : pct(paragraph.negative) >= pct(paragraph.neutral) ? "negative" : "neutral";
  const same = paragraphLabel === sentence.label;

  useLayoutEffect(() => {
    if (!open) {
      setPos(null);
      return;
    }
    const place = (): void => {
      const trigger = triggerRef.current;
      const bubble = bubbleRef.current;
      if (!trigger || !bubble) return;
      const rect = trigger.getBoundingClientRect();
      const width = bubble.offsetWidth;
      const height = bubble.offsetHeight;
      const gap = 8;
      const margin = 8;
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const left = Math.min(Math.max(margin, rect.left), Math.max(margin, vw - width - margin));
      const below = rect.bottom + gap;
      const above = rect.top - gap - height;
      if (below + height > vh - margin && above >= margin) {
        setPos({ top: above, left, placement: "top" });
      } else {
        setPos({
          top: below + height > vh - margin ? Math.max(margin, vh - margin - height) : below,
          left,
          placement: "bottom",
        });
      }
    };
    place();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(place) : null;
    if (observer && bubbleRef.current) observer.observe(bubbleRef.current);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus({ preventScroll: true });
      }
    };
    window.addEventListener("keydown", onKey);
    closeRef.current?.focus({ preventScroll: true });
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent): void => {
      const target = e.target as Node;
      if (bubbleRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      // 点击外部关闭与 Esc 一致：焦点回到触发元素
      setOpen(false);
      triggerRef.current?.focus({ preventScroll: true });
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  return (
    <span className={`sent sent--${sentence.label}`} title={hover}>
      <button
        type="button"
        ref={triggerRef}
        className={`sent__mark sent__mark--${sentence.label}`}
        aria-label={`${sentLabel(sentence.label)} · ${hover}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      />
      <span className="sent__text">{children}</span>
      {open
        ? createPortal(
            <>
              <div
                className="variant__scrim"
                aria-hidden="true"
                onClick={() => {
                  setOpen(false);
                  triggerRef.current?.focus({ preventScroll: true });
                }}
              />
              <div
                ref={bubbleRef}
                className={`sent__bubble sent__bubble--${pos?.placement ?? "bottom"}`}
                role="dialog"
                aria-label={t("sent.label")}
                style={{
                  top: pos?.top ?? 0,
                  left: pos?.left ?? 0,
                  visibility: pos ? "visible" : "hidden",
                }}
              >
                <div className="sent__bubble-head">
                  <span>{t("sent.label")}</span>
                  <button
                    type="button"
                    ref={closeRef}
                    className="sent__bubble-close"
                    onClick={() => {
                      setOpen(false);
                      triggerRef.current?.focus({ preventScroll: true });
                    }}
                    aria-label={t("sent.close")}
                  >
                    ×
                  </button>
                </div>
                <p className="sent__quote">{sentence.text}</p>
                {(["positive", "negative", "neutral"] as const).map((key) => (
                  <div key={key} className="sent__row">
                    <span className="sent__row-label">{t(`sent.label.${key}`)}</span>
                    <span className="sent__bar">
                      <span
                        className={`sent__bar-fill sent__bar-fill--${key}`}
                        style={{ width: `${pct(sentence[key])}%` }}
                      />
                    </span>
                    <span className="sent__row-num">{pct(sentence[key])}%</span>
                  </div>
                ))}
                <p className="sent__paragraph">
                  {t("sent.paragraph", {
                    pos: String(pct(paragraph.positive)),
                    neg: String(pct(paragraph.negative)),
                    neu: String(pct(paragraph.neutral)),
                  })}
                </p>
                <p className={`sent__relation${same ? "" : " sent__relation--diff"}`}>
                  {same
                    ? t("sent.relation.same", { label: sentLabel(sentence.label) })
                    : t("sent.relation.different", {
                        label: sentLabel(sentence.label),
                        paragraph: sentLabel(paragraphLabel as SentenceSentiment["label"]),
                      })}
                </p>
                {sentence.needs_review ? (
                  <p className="sent__review">{t("sent.needs_review")}</p>
                ) : null}
              </div>
            </>,
            document.body,
          )
        : null}
    </span>
  );
}

/** 校验并裁剪句子区间：非法/重叠/越界的句子直接丢弃，绝不猜测位置。 */
function usableSentences(segment: SegmentView): SentenceSentiment[] {
  const n = (segment.target_text ?? "").length;
  const raw = segment.sentiment?.sentences ?? [];
  const out: SentenceSentiment[] = [];
  raw
    .slice()
    .sort((a, b) => (a.span?.[0] ?? 0) - (b.span?.[0] ?? 0))
    .forEach((s) => {
      const [start, end] = s.span;
      if (!Number.isInteger(start) || !Number.isInteger(end)) return;
      if (start < 0 || end <= start || end > n) return;
      if ((segment.target_text ?? "").slice(start, end) !== s.text) return;
      if (out.some((o) => !(end <= o.span[0] || start >= o.span[1]))) return;
      out.push(s);
    });
  return out;
}

export function SpanRenderer({
  segment,
  activeTerm,
}: {
  segment: SegmentView;
  activeTerm?: string | null;
}) {
  const spans = segment.spans ?? [];
  const words = segment.words ?? [];
  const text = segment.target_text ?? "";
  const showAnnotations = useAppStore((s) => s.showAnnotations);

  // 直译模式且拿到逐词对齐：走可点选义的逐词渲染（逐词对齐是功能本体，不受标注开关影响）
  if (segment.mode === "literal" && words.length > 0) {
    return <LiteralWords segment={segment} />;
  }

  if (!text) return null;

  const isLiteral =
    segment.mode === "literal" || spans.some((s) => s.kinds.includes("literal_style"));

  if (!showAnnotations) {
    return <span className="span-plain">{text}</span>;
  }

  const renderPiece = (p: Piece, key: string) =>
    p.span && p.span.kinds.includes("alternate_translation") ? (
      <VariantPiece key={key} piece={p} segment={segment} />
    ) : p.span ? (
      <span
        key={key}
        className={`${spanClass(p.span.kinds)}${
          activeTerm &&
          p.span.kinds.includes("terminology_applied") &&
          p.text.includes(activeTerm)
            ? " span--term-active"
            : ""
        }`}
        title={p.span.note || undefined}
      >
        {p.text}
      </span>
    ) : (
      <span key={key}>{p.text}</span>
    );

  const sentences = usableSentences(segment);
  const paragraph = segment.sentiment && typeof segment.sentiment.positive === "number"
    ? segment.sentiment
    : { positive: 0, negative: 0, neutral: 1 };

  if (sentences.length === 0) {
    return (
      <>
        {composePieces(text, spans).map((p, i) => renderPiece(p, `${p.span?.id ?? "plain"}-${i}`))}
        {isLiteral ? <span className="span span--literal-mark">[AI TRANSLATED]</span> : null}
      </>
    );
  }

  const nodes: React.ReactNode[] = [];
  let cursor = 0;
  sentences.forEach((s, idx) => {
    if (s.span[0] > cursor) {
      const gapText = text.slice(cursor, s.span[0]);
      nodes.push(<span key={`gap-${idx}`}>{gapText}</span>);
    }
    nodes.push(
      <SentenceMark key={`sent-${idx}-${s.span[0]}`} sentence={s} paragraph={paragraph}>
        {slicePieces(text, spans, s.span[0], s.span[1]).map((p, i) =>
          renderPiece(p, `${p.span?.id ?? "plain"}-${idx}-${i}`),
        )}
      </SentenceMark>,
    );
    cursor = s.span[1];
  });
  if (cursor < text.length) {
    nodes.push(<span key="tail">{text.slice(cursor)}</span>);
  }

  return (
    <>
      {nodes}
      {isLiteral ? <span className="span span--literal-mark">[AI TRANSLATED]</span> : null}
    </>
  );
}
