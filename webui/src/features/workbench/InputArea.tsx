// InputArea：输入区。支持拖入 .txt / .md 文件读取内容并直接开始翻译。
import { useEffect, useRef, useState, type DragEvent } from "react";
import { useAppStore } from "../../store/app";
import { SendIcon } from "../../components/icons";
import { t } from "../../i18n/ui";
import { notifyInfo } from "../../store/notice";
import { mark } from "../../perf/marks";
import { isSupportedTextFile, readDroppedFiles } from "./dropFile";

export function InputArea() {
  const text = useAppStore((s) => s.draftText);
  const setDraftText = useAppStore((s) => s.setDraftText);
  const submit = useAppStore((s) => s.submit);
  const cancel = useAppStore((s) => s.cancel);
  const busy = useAppStore((s) => s.busy);
  const [dragging, setDragging] = useState(false);
  const dragDepth = useRef(0);
  const reading = useRef(false);

  // 输入区挂载即可输入：自动聚焦，并记一次「可输入」里程碑（性能实测用）
  useEffect(() => {
    mark("workbench_input_ready");
  }, []);

  const canSend = text.trim().length > 0 && !busy;
  const handleSend = (): void => {
    if (canSend) void submit(text);
  };

  const hasFiles = (e: DragEvent<HTMLElement>): boolean =>
    Array.from(e.dataTransfer?.types ?? []).includes("Files");

  /** 文件夹拖入（DataTransferItem 的 filesystem entry）单独识别，给出比「格式不支持」更准确的提示。 */
  const hasDirectory = (e: DragEvent<HTMLElement>): boolean =>
    Array.from(e.dataTransfer?.items ?? []).some((item) => {
      const entry = typeof item.webkitGetAsEntry === "function" ? item.webkitGetAsEntry() : null;
      return Boolean(entry?.isDirectory);
    });

  const handleDragEnter = (e: DragEvent<HTMLElement>): void => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    dragDepth.current += 1;
    setDragging(true);
  };

  const handleDragOver = (e: DragEvent<HTMLElement>): void => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    if (!dragging) setDragging(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLElement>): void => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragging(false);
  };

  const handleDrop = async (e: DragEvent<HTMLElement>): Promise<void> => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    if (reading.current) return;
    const files = Array.from(e.dataTransfer.files ?? []);
    if (!files.length) return;
    if (hasDirectory(e)) {
      notifyInfo(t("wb.drop.folder"), "");
      return;
    }
    const supported = files.filter((f) => isSupportedTextFile(f.name));
    if (!supported.length) {
      notifyInfo(t("wb.drop.unsupported"), files.map((f) => f.name).join("、"));
      return;
    }
    reading.current = true;
    try {
      const result = await readDroppedFiles(files);
      if (result.skipped.length) {
        notifyInfo(t("wb.drop.unsupported"), result.skipped.join("、"));
      }
      if (result.failed.length) {
        notifyInfo(
          t("wb.drop.encoding_failed"),
          result.failed.map((f) => f.name).join("、"),
        );
      }
      const full = result.text;
      if (!full.trim()) {
        notifyInfo(t("wb.drop.empty"), result.read.join("、"));
        return;
      }
      setDraftText(full);
      if (result.read.length > 1) {
        notifyInfo(t("wb.drop.multi", { n: String(result.read.length) }), "");
      }
      // 当前没有进行中的任务时直接开始翻译；忙时只填入，交由用户决定。
      // 长度不在这里截断：submit 先估算，超硬上限时给出明确提示，长文本则分批处理。
      if (!useAppStore.getState().busy) await submit(full);
    } catch (err) {
      notifyInfo(
        t("wb.drop.read_failed"),
        err instanceof Error ? err.message : "",
      );
    } finally {
      reading.current = false;
    }
  };

  return (
    <section
      className={`composer${dragging ? " composer--drop" : ""}`}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={(e) => void handleDrop(e)}
    >
      <textarea
        className="composer__text"
        value={text}
        onChange={(e) => setDraftText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            handleSend();
          }
        }}
        placeholder={t("wb.input.placeholder")}
        autoFocus
        rows={5}
      />
      {dragging ? (
        <div className="composer__drop" aria-hidden="true">
          <span className="composer__drop-text">{t("wb.drop.active")}</span>
        </div>
      ) : null}
      <div className="composer__foot">
        <span className="composer__hint">
          {text.trim().length > 0
            ? t("wb.input.chars", { n: String(text.trim().length) })
            : t("wb.input.hint")}
        </span>
        <span className="composer__spacer" />
        {busy ? (
          <button type="button" className="btn" onClick={() => void cancel()}>
            {t("wb.cancel")}
          </button>
        ) : null}
        <button
          type="button"
          className="btn btn--primary"
          onClick={handleSend}
          disabled={!canSend}
        >
          <SendIcon />
          {t("wb.submit")}
        </button>
      </div>
    </section>
  );
}
