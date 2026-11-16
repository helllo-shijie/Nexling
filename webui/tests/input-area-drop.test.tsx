// 输入区拖拽的组件级回归（.tsx 用例，验证 vitest 配置确实收集）：
// 拖入高亮、多文件合并、文件夹与不支持格式的明确提示。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react-dom/test-utils";
import { InputArea } from "../src/features/workbench/InputArea";
import { useAppStore } from "../src/store/app";
import { useNoticeStore } from "../src/store/notice";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

function composer(): HTMLElement {
  const el = container.querySelector("section.composer");
  if (!el) throw new Error("composer not rendered");
  return el as HTMLElement;
}

function drag(type: string, files: File[] = [], items: unknown[] = []): void {
  const ev = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperty(ev, "dataTransfer", {
    value: { types: ["Files"], files, items },
  });
  act(() => {
    composer().dispatchEvent(ev);
  });
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  useNoticeStore.setState({ notices: [] });
  // busy 状态：拖入只填输入框，不触发真实翻译请求
  useAppStore.setState({ busy: true, draftText: "" });
  act(() => {
    root.render(<InputArea />);
  });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("InputArea drop", () => {
  it("highlights the drop zone while dragging files", () => {
    drag("dragenter");
    expect(composer().className).toContain("composer--drop");
    drag("dragleave");
    expect(composer().className).not.toContain("composer--drop");
  });

  it("merges multiple dropped files into the draft", async () => {
    drag("drop", [
      new File(["Hello"], "a.txt", { type: "text/plain" }),
      new File(["World"], "b.md", { type: "text/markdown" }),
    ]);
    await vi.waitFor(() => {
      expect(useAppStore.getState().draftText).toBe("Hello\n\nWorld");
    });
    const notices = useNoticeStore.getState().notices;
    expect(notices.some((n) => n.title.includes("合并"))).toBe(true);
  });

  it("rejects folders with an explicit hint", async () => {
    drag("drop", [new File([""], "folder")], [
      { webkitGetAsEntry: () => ({ isDirectory: true }) },
    ]);
    await vi.waitFor(() => {
      expect(useNoticeStore.getState().notices.some((n) => n.title.includes("文件夹"))).toBe(true);
    });
    expect(useAppStore.getState().draftText).toBe("");
  });

  it("rejects unsupported formats with an explicit hint", async () => {
    drag("drop", [new File(["%PDF"], "paper.pdf", { type: "application/pdf" })]);
    await vi.waitFor(() => {
      expect(useNoticeStore.getState().notices.some((n) => n.title.includes("仅支持") ||
        n.title.includes("格式"))).toBe(true);
    });
    expect(useAppStore.getState().draftText).toBe("");
  });
});
