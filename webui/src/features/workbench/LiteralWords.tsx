// LiteralWords：直译模式的逐词渲染。
// 每个词可点击，弹出气泡列出该词的候选义项（默认义项 + 其他义项）；
// 选择后调用 segment.word.pick 重建成句并保存为新版本。
// V8 定版修复：气泡改用 portal + fixed 定位，避免被祖先 overflow 裁切，并做视口翻转/夹紧。
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { SegmentView } from "../../bridge/types";
import { useAppStore } from "../../store/app";
import { t } from "../../i18n/ui";

export function LiteralWords({ segment }: { segment: SegmentView }) {
  const pickWord = useAppStore((s) => s.pickWord);
  const [open, setOpen] = useState<number | null>(null);
  const [pos, setPos] = useState<{ top: number; left: number; placement: "top" | "bottom" } | null>(null);
  const triggerRefs = useRef<Record<number, HTMLButtonElement | null>>({});
  const bubbleRef = useRef<HTMLSpanElement>(null);
  const words = segment.words ?? [];

  // 气泡挂到 body 上（portal），避免 .doc__rows 等祖先 overflow 裁切
  useLayoutEffect(() => {
    if (open === null) {
      setPos(null);
      return;
    }
    const place = (): void => {
      const trigger = triggerRefs.current[open];
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
        setOpen(null);
        triggerRefs.current[open]?.focus({ preventScroll: true });
      }
    };
    window.addEventListener("keydown", onKey);
    const first = bubbleRef.current?.querySelector<HTMLButtonElement>(".literal-opt");
    first?.focus({ preventScroll: true });
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  useEffect(() => {
    if (open === null) return;
    const onDown = (e: MouseEvent): void => {
      const target = e.target as Node;
      if (bubbleRef.current?.contains(target) || triggerRefs.current[open]?.contains(target)) return;
      setOpen(null);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const close = (): void => {
    const i = open;
    setOpen(null);
    if (i !== null) triggerRefs.current[i]?.focus({ preventScroll: true });
  };

  const word = open === null ? null : words[open];
  // 候选顺序由后端固化（推荐项在首位）；选中只改当前采用项，不重排、不改推荐标记。
  const options = word
    ? (word.options && word.options.length
        ? word.options
        : Array.from(new Set([word.target, ...word.alternatives].filter(Boolean))))
    : [];
  const recommended = word ? (word.recommended || options[0] || word.target) : "";

  return (
    <>
      <span className="literal-sentence">
        {words.map((w, i) => {
          const hasChoices = w.alternatives.length > 0;
          return (
            <span key={`${segment.segment_id}-${i}`} className="literal-word-wrap">
              <button
                type="button"
                ref={(el) => {
                  triggerRefs.current[i] = el;
                }}
                className={`literal-word${open === i ? " literal-word--open" : ""}${
                  hasChoices ? " literal-word--alt" : ""
                }`}
                onClick={() => setOpen(open === i ? null : i)}
                title={w.src ? t("literal.src_title", { src: w.src }) : t("literal.click_hint")}
                aria-haspopup="dialog"
                aria-expanded={open === i}
              >
                {w.target}
              </button>
            </span>
          );
        })}
      </span>
      <span className="span span--literal-mark">[AI TRANSLATED]</span>
      {word && open !== null
        ? createPortal(
            <>
              <span className="literal-scrim" aria-hidden="true" onClick={close} />
              <span
                ref={bubbleRef}
                className={`literal-bubble literal-bubble--${pos?.placement ?? "bottom"}`}
                role="dialog"
                aria-label={t("literal.click_hint")}
                style={{
                  top: pos?.top ?? 0,
                  left: pos?.left ?? 0,
                  visibility: pos ? "visible" : "hidden",
                }}
              >
                <span className="literal-bubble__src">{word.src || t("literal.no_src")}</span>
                <span className="literal-bubble__opts">
                  {options.map((opt, idx) => (
                    <button
                      key={`${idx}-${opt}`}
                      type="button"
                      className={`literal-opt${opt === word.target ? " literal-opt--current" : ""}`}
                      onClick={() => {
                        const i = open;
                        setOpen(null);
                        triggerRefs.current[i]?.focus({ preventScroll: true });
                        if (opt !== word.target) void pickWord(segment.segment_id, i, opt);
                      }}
                    >
                      <span className="literal-opt__text">{opt}</span>
                      <span className={`literal-opt__tag${opt === recommended ? "" : " literal-opt__tag--alt"}`}>
                        {opt === recommended ? t("literal.recommended") : t("literal.alternate")}
                      </span>
                    </button>
                  ))}
                </span>
                <span className="literal-bubble__hint">{t("literal.hint")}</span>
              </span>
            </>,
            document.body,
          )
        : null}
    </>
  );
}
