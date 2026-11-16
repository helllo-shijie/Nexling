// SourceWithTones：原文渲染。模型识别出明显语气时，在对应片段前插入方括号语气标签（如 [讽刺]）。
// 没有语气标注时就是纯原文，不做任何多余装饰。
import type { ReactNode } from "react";
import type { SegmentView } from "../../bridge/types";
import { useAppStore } from "../../store/app";
import { t } from "../../i18n/ui";

export function SourceWithTones({ segment }: { segment: SegmentView }) {
  const showAnnotations = useAppStore((s) => s.showAnnotations);
  const text = segment.source_text ?? "";
  const tones = (segment.tones ?? [])
    .filter((t) => Array.isArray(t.span) && t.span.length >= 2)
    .slice()
    .sort((a, b) => a.span[0] - b.span[0]);

  if (!showAnnotations || tones.length === 0) return <>{text}</>;

  const nodes: ReactNode[] = [];
  let cursor = 0;
  tones.forEach((tone, i) => {
    const start = Math.max(0, Math.min(tone.span[0], text.length));
    const end = Math.max(start, Math.min(tone.span[1], text.length));
    if (start < cursor) return; // 重叠片段跳过
    if (start > cursor) nodes.push(<span key={`p${i}`}>{text.slice(cursor, start)}</span>);
    nodes.push(
      <span key={`t${i}`} className="tone-mark" title={t("tone.title", { label: tone.label })}>
        [{tone.label}]
      </span>,
    );
    nodes.push(
      <span key={`s${i}`} className="source-tone">
        {text.slice(start, end)}
      </span>,
    );
    cursor = end;
  });
  if (cursor < text.length) nodes.push(<span key="tail">{text.slice(cursor)}</span>);
  return <>{nodes}</>;
}