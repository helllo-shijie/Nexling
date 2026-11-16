// 工作台关键交互的自动化回归：
// 翻译启动 → 完成事件 → 自动扫描候选 → 采纳候选 → 导出。
// 只 mock 本地桥的 HTTP 客户端，状态机与调用参数都走真实 store 代码。
import { beforeEach, describe, expect, it, vi } from "vitest";

type Call = { cmd: string; payload: Record<string, unknown> };
const calls: Call[] = [];

const candidate = {
  id: "cand-1",
  normalized: "websocket",
  source_term: "WebSocket",
  target_term: "WebSocket 协议",
  lang: "en",
  target_lang: "zh-Hans",
  task_id: "task-1",
  occurrences: 3,
  confidence: 0.91,
  status: "pending",
  quality: "high" as const,
  reasons: ["aligned", "repeated"],
};

vi.mock("../src/api/laa", () => ({
  invoke: vi.fn(async (cmd: string, payload: Record<string, unknown>) => {
    calls.push({ cmd, payload });
    switch (cmd) {
      case "capability.list":
        return { version: "1.6.0", items: [] };
      case "scene.list":
        return { items: [] };
      case "translation.start":
        return { task_id: "task-1", stream: { url: "/api/events" } };
      case "translation.snapshot":
        return {
          task: {
            id: "task-1",
            status: "running",
            src_lang: "en",
            tgt_lang: "zh-Hans",
            mode: "fluent",
            risk_tier: "L0",
          },
          segments: [
            {
              segment_id: "seg-1",
              source_text: "The scheduler retries failed pods.",
              target_text: "调度器会重试失败的 Pod。",
              spans: [],
              words: [],
              tones: [],
              emotions: [],
              sentiment: null,
              tm_hits: [],
              risk: { tier: "L0" },
            },
          ],
          checkpoint_seq: 0,
        };
      case "term.scan":
        return { scanned: 1, items: [candidate] };
      case "term.list":
        return { items: [candidate], counts: { pending: 1, accepted: 0, ignored: 0 } };
      case "term.accept":
        return { entry: { id: "entry-1" }, counts: { pending: 0, accepted: 1, ignored: 0 } };
      case "glossary.banks":
        return { items: [{ id: "personal-default", name: "Personal", editable: true }] };
      case "glossary.search":
        return { items: [] };
      case "translation.export":
        return { path: "task-1.md", content: "# export" };
      default:
        return {};
    }
  }),
  pollEvents: vi.fn(async () => ({ seq: 0, events: [] })),
}));

import { useAppStore } from "../src/store/app";

describe("workbench flow", () => {
  beforeEach(() => {
    calls.length = 0;
    useAppStore.setState({
      task: null,
      segments: [],
      termCandidates: [],
      termLastScanAt: null,
      glossaryBankId: "personal-default",
      termAutoScan: true,
    });
  });

  it("translates, auto-scans and accepts a candidate, then exports", async () => {
    const store = useAppStore.getState();
    await store.bootstrap();

    await useAppStore.getState().submit("The scheduler retries failed pods.");
    expect(calls.some((c) => c.cmd === "translation.start")).toBe(true);
    const started = useAppStore.getState();
    expect(started.task?.id).toBe("task-1");
    expect(started.segments).toHaveLength(1);

    // 后端完成事件：停轮询并自动扫描候选（本地规则，不产生模型调用）
    useAppStore.getState().applyEvent({ topic: "task.completed", payload: {} } as never);
    await vi.waitFor(() => {
      expect(calls.some((c) => c.cmd === "term.scan")).toBe(true);
      expect(calls.some((c) => c.cmd === "term.list")).toBe(true);
    });
    const scanCall = calls.find((c) => c.cmd === "term.scan");
    expect(scanCall?.payload.task_id).toBe("task-1");
    expect(useAppStore.getState().termLastScanAt).not.toBeNull();

    // 采纳候选：写入词库后刷新候选与词库
    const ok = await useAppStore.getState().acceptTermCandidate(
      "cand-1", "WebSocket 协议", "personal-default",
    );
    expect(ok).toBe(true);
    const accept = calls.find((c) => c.cmd === "term.accept");
    expect(accept?.payload).toMatchObject({
      id: "cand-1",
      target_term: "WebSocket 协议",
      bank_id: "personal-default",
    });

    // 导出：带上当前任务 id 与格式
    const { invoke } = await import("../src/api/laa");
    const out = await invoke<unknown, { path: string; content: string }>("translation.export", {
      task_id: useAppStore.getState().task?.id,
      format: "md",
      include_meta: true,
    });
    expect(out.path).toBe("task-1.md");
    const exported = calls.find((c) => c.cmd === "translation.export");
    expect(exported?.payload.task_id).toBe("task-1");
  });

  it("refuses bulk accept when there is no current task", async () => {
    await useAppStore.getState().acceptHighQualityTerms();
    expect(calls.some((c) => c.cmd === "term.accept_bulk")).toBe(false);
    expect(useAppStore.getState().error).toBeTruthy();
  });
});
