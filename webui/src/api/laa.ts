// 传输抽象：默认走真实桥接（bridge/client），置 VITE_MOCK=1 时切到开发演示数据。
import { invoke as realInvoke, pollEvents as realPollEvents } from "../bridge/client";
import type { UiEvent } from "../bridge/types";
import { mockInvoke, mockPollEvents } from "../mock/mock";

const useMock = import.meta.env.VITE_MOCK === "1";

export function invoke<T, R>(cmd: string, payload: T): Promise<R> {
  return useMock ? mockInvoke<T, R>(cmd, payload) : realInvoke<T, R>(cmd, payload);
}

export function pollEvents(
  taskId: string,
  fromSeq: number,
): Promise<{ events: UiEvent[]; next_seq: number }> {
  return useMock ? mockPollEvents(taskId, fromSeq) : realPollEvents(taskId, fromSeq);
}