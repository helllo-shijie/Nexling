// V10 前端交互：任务级进度展示、失败重试入口与取消后的状态刷新。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react-dom/test-utils";
import type { TaskProgress, TranslationSnapshot, TranslationTask } from "../src/bridge/types";
import { ProgressBar } from "../src/features/workbench/ProgressBar";
import { useAppStore } from "../src/store/app";
import { useNoticeStore } from "../src/store/notice";

const invokeMock = vi.fn();
vi.mock("../src/bridge/client", () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  pollEvents: vi.fn(async () => ({ events: [], next_seq: 0 })),
}));

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

const PROGRESS: TaskProgress = {
  total: 10,
  done: 6,
  failed: 2,
  cancelled: 0,
  remaining: 2,
  batch_total: 5,
  calls: 4,
  input_tokens: 1200,
  output_tokens: 800,
  cost: 0.0021,
};

function task(overrides: Partial<TranslationTask> = {}): TranslationTask {
  return { id: "t1", status: "running", ...overrides } as unknown as TranslationTask;
}

function snapshot(overrides: Partial<TranslationSnapshot> = {}): TranslationSnapshot {
  return {
    task: task(),
    segments: [],
    checkpoint_seq: 0,
    progress: PROGRESS,
    ...overrides,
  };
}

beforeEach(() => {
  invokeMock.mockReset();
  useNoticeStore.setState({ notices: [] });
  useAppStore.setState({
    task: task(),
    segments: [],
    progress: PROGRESS,
    estimate: null,
    busy: true,
    error: null,
  });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("ProgressBar", () => {
  it("shows done / total, failed and remaining from task progress", () => {
    act(() => {
      root.render(<ProgressBar />);
    });
    const text = container.textContent ?? "";
    expect(text).toContain("已完成 6 / 10 段");
    expect(text).toContain("失败 2");
    expect(text).toContain("剩余 2");
    expect(text).toContain("计划 5 批");
    expect(text).toContain("实际调用 4 次");
    expect(text).toContain("token 入 1200 / 出 800");
    const bar = container.querySelector('[role="progressbar"]');
    expect(bar?.getAttribute("aria-valuenow")).toBe("60");
  });

  it("keeps the bar in sync when a task.progress event arrives", () => {
    act(() => root.render(<ProgressBar />));
    act(() => {
      useAppStore.getState().applyEvent({
        topic: "task.progress",
        seq: 7,
        payload: {
          total: 10,
          done: 9,
          failed: 1,
          cancelled: 0,
          remaining: 0,
          batch_total: 5,
          batch: 5,
          status: "running",
        },
      } as never);
    });
    const bar = container.querySelector('[role="progressbar"]');
    expect(bar?.getAttribute("aria-valuenow")).toBe("90");
    expect(container.textContent ?? "").toContain("已完成 9 / 10 段");
  });

  it("offers retry for failed segments and only asks the backend to retry unfinished ones", async () => {
    // 运行中不允许重试；任务结束后 failed > 0 才出现入口
    useAppStore.setState({ busy: false, task: task({ status: "failed" }) });
    act(() => root.render(<ProgressBar />));
    const btn = [...container.querySelectorAll("button")].find((b) =>
      (b.textContent ?? "").includes("重试失败片段"),
    );
    expect(btn).toBeTruthy();
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === "translation.retry") return { task_id: "t1", queued: true, segment_count: 3 };
      if (cmd === "translation.snapshot") return snapshot({ task: task({ status: "running" }) });
      throw new Error(`unexpected cmd ${cmd}`);
    });
    await act(async () => {
      btn?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await vi.waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith("translation.retry", { task_id: "t1" });
    });
    expect(useNoticeStore.getState().notices.some((n) => n.body.includes("3"))).toBe(true);
    useAppStore.setState({ busy: false });
  });

  it("lets a paused (restarted) task continue from where it stopped", () => {
    useAppStore.setState({
      busy: false,
      task: task({ status: "paused" }),
      progress: { ...PROGRESS, done: 4, failed: 0, cancelled: 0, remaining: 6 },
    });
    act(() => root.render(<ProgressBar />));
    const text = container.textContent ?? "";
    expect(text).toContain("任务已暂停");
    expect(text).toContain("重试失败片段");
  });

  it("shows the pre-submit estimate before real calls are backfilled", () => {
    useAppStore.setState({
      progress: { ...PROGRESS, calls: 0, cost: 0 },
      estimate: { chars: 5000, max_chars: 200000, over_limit: false, segments: 10, batches: 5, est_calls: 5 },
    });
    act(() => root.render(<ProgressBar />));
    expect(container.textContent ?? "").toContain("预计 5 次调用");
  });
});

describe("cancel", () => {
  it("cancels, then refreshes the snapshot so finished segments stay usable", async () => {
    const doneSegment = {
      id: "s1",
      index: 0,
      source_text: "Hello",
      target_text: "你好",
      span: [0, 5],
      confidence: null,
      terms: [],
      status: "done",
    };
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === "translation.cancel") return { cancelled: true };
      if (cmd === "translation.snapshot") {
        return snapshot({
          task: task({ status: "cancelled" }),
          segments: [doneSegment],
          progress: { ...PROGRESS, done: 6, cancelled: 2, remaining: 0 },
        } as Partial<TranslationSnapshot>);
      }
      throw new Error(`unexpected cmd ${cmd}`);
    });
    await act(async () => {
      await useAppStore.getState().cancel();
    });
    expect(invokeMock).toHaveBeenCalledWith("translation.cancel", { task_id: "t1" });
    const state = useAppStore.getState();
    expect(state.busy).toBe(false);
    expect(state.task?.status).toBe("cancelled");
    expect(state.segments).toHaveLength(1);
    expect(state.progress?.cancelled).toBe(2);
  });
});
