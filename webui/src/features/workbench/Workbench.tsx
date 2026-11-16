// Workbench：工作台 = 工具栏（场景 / 目标语言 / 模式）+ 输入区 + 原文-译文双栏对照 + 二级入口抽屉。
// 历史记录不占常驻栏位，改为需要时从工具栏打开。
import { useEffect, useState } from "react";
import { SceneSelector } from "./SceneSelector";
import { ModeControl } from "./ModeControl";
import { LanguageSelect } from "./LanguageSelect";
import { InputArea } from "./InputArea";
import { SegmentList } from "./SegmentList";
import { TermPanel } from "./TermPanel";
import { ProgressBar } from "./ProgressBar";
import { HistorySidebar } from "./HistorySidebar";
import { t } from "../../i18n/ui";
import { HistoryIcon } from "../../components/icons";

export function Workbench() {
  const [historyOpen, setHistoryOpen] = useState(false);

  // Esc 关闭抽屉
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") {
        setHistoryOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="workbench">
      <div className="workbench__main">
        <div className="workbench__toolbar">
          <SceneSelector />
          <LanguageSelect />
          <ModeControl />
          <span className="workbench__spacer" />
          <button
            type="button"
            className="toolbar-action toolbar-action--icon"
            onClick={() => setHistoryOpen(true)}
            title={t("wb.history")}
          >
            <HistoryIcon />
            {t("wb.history")}
          </button>
        </div>

        <InputArea />
        <ProgressBar />
        <SegmentList />
        <TermPanel />
      </div>

      {historyOpen ? (
        <div className="drawer-layer" role="dialog" aria-modal="true" aria-label={t("wb.history")} onClick={() => setHistoryOpen(false)}>
          <div className="drawer drawer--left" onClick={(e) => e.stopPropagation()}>
            <HistorySidebar onClose={() => setHistoryOpen(false)} />
          </div>
        </div>
      ) : null}
    </div>
  );
}
