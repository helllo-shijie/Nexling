// SegmentList：原文 / 译文双栏对照。
// 左栏原文（含语气标注），右栏译文（含术语、中文保留、候选译法），透明化信息收进段落下方的折叠区。
import { useState } from "react";
import type { SegmentView } from "../../bridge/types";
import { useAppStore } from "../../store/app";
import { invoke } from "../../api/laa";
import { downloadTextFile, mimeForName, saveTextFile } from "../../bridge/nativeSave";
import { notifyInfo } from "../../store/notice";
import { CheckIcon, CopyIcon, PlusIcon } from "../../components/icons";
import { SpanRenderer } from "./SpanRenderer";
import { SourceWithTones } from "./SourceWithTones";
import { TransparencyPanel } from "./TransparencyPanel";
import { t } from "../../i18n/ui";

function Row({
  segment,
  index,
  activeTerm,
  onTermFocus,
}: {
  segment: SegmentView;
  index: number;
  activeTerm: string | null;
  onTermFocus: (term: string) => void;
}) {
  const retranslate = useAppStore((s) => s.retranslate);
  const memoryAdd = useAppStore((s) => s.memoryAdd);
  const memoryRemove = useAppStore((s) => s.memoryRemove);
  const [copied, setCopied] = useState(false);
  const [memBusy, setMemBusy] = useState(false);
  const low = segment.confidence?.band === "low";
  // 已加入记忆的判定：同一原文存在精确命中且译文与当前一致（刷新/重启后仍可撤回）
  const storedHit = (segment.tm_hits ?? []).find(
    (h) => h.match_kind === "exact" && !h.stale && h.target_text === segment.target_text,
  );
  const memoryBlocked = segment.channel === "offline" || segment.channel === "fake";

  const toggleMemory = async (): Promise<void> => {
    if (memBusy) return;
    setMemBusy(true);
    if (storedHit) await memoryRemove(storedHit.entry_id, segment.segment_id);
    else await memoryAdd(segment.segment_id);
    setMemBusy(false);
  };

  const handleCopy = (): void => {
    const text = segment.target_text ?? "";
    if (!text) return;
    void navigator.clipboard?.writeText(text).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1400);
      },
      () => setCopied(false),
    );
  };

  return (
    <article className={`row${low ? " row--low" : ""}`}>
      <div className="row__src">
        <div className="row__meta">
          <span className="row__no">{String(index + 1).padStart(2, "0")}</span>
          <span className={`mode-tag${segment.mode === "literal" ? "" : " mode-tag--fluent"}`}>
            {segment.mode === "literal" ? t("mode.literal") : t("mode.fluent")}
          </span>
          {segment.tones?.length ? (
            <span className="row__tone">{t("wb.tones", { n: String(segment.tones.length) })}</span>
          ) : null}
          {segment.forced ? (
            <span className="row__forced" title={t("wb.forced")}>
              {t("wb.forced.short")}
            </span>
          ) : null}
        </div>
        <p className="row__text row__text--src">
          <SourceWithTones segment={segment} />
        </p>
      </div>

      <div className="row__tgt">
        <div className="row__actions">
          <button type="button" className="icon-btn" onClick={handleCopy} title={t("wb.copy")}>
            <CopyIcon />
            <span>{copied ? t("wb.copied") : t("wb.copy")}</span>
          </button>
          <button
            type="button"
            className="icon-btn"
            onClick={() => void retranslate([segment.segment_id])}
          >
            {t("wb.retranslate")}
          </button>
          <button
            type="button"
            className={`icon-btn icon-btn--memory${storedHit ? " icon-btn--memory-on" : ""}`}
            onClick={() => void toggleMemory()}
            disabled={memBusy || (!storedHit && (memoryBlocked || !segment.target_text))}
            aria-label={storedHit ? t("wb.memory.undo_hint") : t("wb.memory.add")}
            title={
              !storedHit && memoryBlocked
                ? t("wb.memory.offline")
                : storedHit
                  ? t("wb.memory.undo_hint")
                  : t("wb.memory.add")
            }
          >
            {storedHit ? <CheckIcon /> : <PlusIcon />}
          </button>
        </div>
        <p className="row__text row__text--tgt">
          {segment.target_text ? (
            <SpanRenderer segment={segment} activeTerm={activeTerm} />
          ) : (
            <span className={`row__status row__status--${segment.status ?? "pending"}`}>
              {segment.status === "failed"
                ? t("wb.status.failed")
                : segment.status === "cancelled"
                  ? t("wb.status.cancelled")
                  : t("wb.status.pending")}
            </span>
          )}
        </p>
        <TransparencyPanel segment={segment} onTermFocus={onTermFocus} />
      </div>
    </article>
  );
}

function EmptyState() {
  const setDraftText = useAppStore((s) => s.setDraftText);
  const submit = useAppStore((s) => s.submit);
  const busy = useAppStore((s) => s.busy);
  const error = useAppStore((s) => s.error);
  const samples = [t("wb.empty.1"), t("wb.empty.2"), t("wb.empty.3")];

  const run = (text: string): void => {
    setDraftText(text);
    void submit(text);
  };

  return (
    <section className="empty">
      <div className="empty__lead">
        <h2 className="empty__title">{busy ? t("nav.busy") : t("wb.empty.title")}</h2>
        <p className="empty__hint">{error ?? t("wb.empty.hint")}</p>
        <ol className="empty__steps">
          {[t("wb.empty.step1"), t("wb.empty.step2"), t("wb.empty.step3")].map((line, i) => (
            <li key={i} className="empty__step">
              <span className="empty__step-no">{i + 1}</span>
              <span>
                {i === 1 ? (
                  <>
                    {line.split("Ctrl+Enter")[0]}
                    <kbd className="empty__kbd">Ctrl</kbd> + <kbd className="empty__kbd">Enter</kbd>
                    {line.split("Ctrl+Enter")[1]}
                  </>
                ) : (
                  line
                )}
              </span>
            </li>
          ))}
        </ol>
      </div>
      <div className="empty__samples">
        <div className="empty__samples-title">{t("wb.empty.samples_title")}</div>
        {samples.map((s, i) => (
          <button key={i} type="button" className="sample" onClick={() => run(s)}>
            <span className="sample__text">{s}</span>
            <span className="sample__go">→</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function ExportMenu() {
  const task = useAppStore((s) => s.task);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const run = async (format: "txt" | "md" | "json"): Promise<void> => {
    if (!task) return;
    setBusy(true);
    setOpen(false);
    try {
      const res = await invoke<unknown, { path: string; content: string }>("translation.export", {
        task_id: task.id,
        format,
        include_meta: format !== "txt",
      });
      const saved = await saveTextFile(res.path, res.content);
      if (saved.unsupported) {
        downloadTextFile(res.path, res.content, mimeForName(res.path));
        notifyInfo(t("wb.export.downloaded"), res.path);
      } else if (saved.cancelled) {
        notifyInfo(t("wb.export.cancelled"), res.path);
      } else if (saved.error) {
        notifyInfo(t("wb.export.failed"), saved.error);
      } else {
        notifyInfo(t("wb.export.saved"), saved.path ?? res.path);
      }
    } catch (e) {
      notifyInfo(t("wb.export.failed"), e instanceof Error ? e.message : t("common.unknown_error"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className="export">
      <button
        type="button"
        className="btn btn--ghost export__trigger"
        onClick={() => setOpen((v) => !v)}
        disabled={busy}
      >
        {busy ? t("wb.exporting") : t("wb.export")}
      </button>
      {open ? (
        <span className="export__menu" role="menu">
          <button type="button" role="menuitem" onClick={() => void run("txt")}>
            {t("wb.export.txt")}
          </button>
          <button type="button" role="menuitem" onClick={() => void run("md")}>
            {t("wb.export.md")}
          </button>
          <button type="button" role="menuitem" onClick={() => void run("json")}>
            {t("wb.export.json")}
          </button>
        </span>
      ) : null}
    </span>
  );
}

function AnnotationToggle() {
  const show = useAppStore((s) => s.showAnnotations);
  const setShow = useAppStore((s) => s.setShowAnnotations);
  return (
    <button
      type="button"
      className={`btn btn--ghost doc__toggle${show ? "" : " doc__toggle--off"}`}
      aria-pressed={show}
      title={show ? t("wb.annotations") : t("wb.annotations.off")}
      onClick={() => setShow(!show)}
    >
      {t("wb.annotations")}
    </button>
  );
}

export function SegmentList() {
  const segments = useAppStore((s) => s.segments);
  const [focus, setFocus] = useState<{ segmentId: string; term: string } | null>(null);

  if (segments.length === 0) return <EmptyState />;

  const allOffline = segments.every((s) => s.channel === "offline");

  return (
    <section className="doc">
      {allOffline ? <div className="offline-banner">{t("wb.offline")}</div> : null}
      <div className="doc__head">
        <span>{t("wb.source")}</span>
        <span>{t("wb.result")}</span>
        <div className="doc__tools">
          <AnnotationToggle />
          <ExportMenu />
        </div>
      </div>
      <div className="doc__rows">
        {segments.map((seg, i) => (
          <Row
            key={seg.segment_id}
            segment={seg}
            index={i}
            activeTerm={focus?.segmentId === seg.segment_id ? focus.term : null}
            onTermFocus={(term) =>
              setFocus((cur) =>
                cur && cur.segmentId === seg.segment_id && cur.term === term
                  ? null
                  : { segmentId: seg.segment_id, term },
              )
            }
          />
        ))}
      </div>
    </section>
  );
}
