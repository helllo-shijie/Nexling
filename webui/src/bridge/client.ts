// 桥接客户端：与后端 laa_core/bridge/http_server.py 通信。
// Base URL = 空字符串（同源）。
import type { InvokeErrorBody, InvokeOkBody, UiEvent } from "./types";

export interface BridgeErrorShape {
  code: string;
  message: string;
  retryable: boolean;
  details: Record<string, unknown>;
}

/** 命令失败时抛出的错误对象，暴露 { code, message, details } 供上层读取。 */
export class BridgeError extends Error implements BridgeErrorShape {
  code: string;
  details: Record<string, unknown>;
  retryable: boolean;

  constructor(code: string, message: string, retryable: boolean, details: Record<string, unknown>) {
    super(message);
    this.name = "BridgeError";
    this.code = code;
    this.details = details;
    this.retryable = retryable;
  }
}

const BASE_URL = "";

interface NativeBridgeApi {
  get_bridge_token?: () => Promise<string> | string;
}

interface PywebviewWindow {
  pywebview?: { api?: NativeBridgeApi };
}

let tokenPromise: Promise<string> | null = null;

function nativeApi(): NativeBridgeApi | undefined {
  return (window as unknown as PywebviewWindow).pywebview?.api;
}

async function readToken(): Promise<string> {
  const direct = nativeApi();
  if (direct?.get_bridge_token) {
    try {
      return String((await direct.get_bridge_token()) ?? "");
    } catch {
      return "";
    }
  }
  // 开发态（Vite 代理）没有原生桥：直接不带 token，由后端按 Origin 校验。
  if (import.meta.env.DEV) return "";
  // 生产态：pywebview 在页面 load 之后才注入 api。监听一次 pywebviewready，
  // 同时轮询兜底，避免事件早于脚本执行时永远拿不到 token。
  return new Promise<string>((resolve) => {
    let settled = false;
    let timer = 0;
    const done = (value: string): void => {
      if (settled) return;
      settled = true;
      window.clearInterval(timer);
      resolve(value);
    };
    const attempt = (): void => {
      const api = nativeApi();
      if (!api?.get_bridge_token) return;
      void Promise.resolve(api.get_bridge_token())
        .then((value) => done(String(value ?? "")))
        .catch(() => done(""));
    };
    window.addEventListener("pywebviewready", attempt, { once: true });
    timer = window.setInterval(attempt, 120);
    attempt();
    window.setTimeout(() => done(""), 5000);
  });
}

/** 本地桥 token：只从原生桥（pywebview js_api）获取，页面源码里不存在。 */
export function bridgeToken(): Promise<string> {
  if (!tokenPromise) tokenPromise = readToken();
  return tokenPromise;
}

async function bridgeHeaders(extra?: Record<string, string>): Promise<Record<string, string>> {
  const token = await bridgeToken();
  return { ...(token ? { "X-NexLing-Token": token } : {}), ...(extra ?? {}) };
}

function unexpected(status: number): BridgeError {
  return new BridgeError("LAA-1001", `HTTP ${status}`, false, {});
}

/**
 * 调用命令：POST /api/invoke，请求体 { cmd, payload, request_id? }。
 * 成功返回响应 data；失败抛 BridgeError（含 code/message/details）。
 */
export async function invoke<T, R>(cmd: string, payload: T): Promise<R> {
  let res: Response;
  try {
    res = await fetch(`${BASE_URL}/api/invoke`, {
      method: "POST",
      headers: await bridgeHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ cmd, payload }),
    });
  } catch {
    throw new BridgeError("LAA-1001", "无法连接后端服务", false, { cmd });
  }

  let body: InvokeOkBody<R> | InvokeErrorBody;
  try {
    body = (await res.json()) as InvokeOkBody<R> | InvokeErrorBody;
  } catch {
    throw unexpected(res.status);
  }

  if (!res.ok || body.ok === false) {
    const err = (body as InvokeErrorBody).error;
    throw new BridgeError(
      err?.code ?? "LAA-1001",
      err?.message ?? `HTTP ${res.status}`,
      err?.retryable ?? false,
      err?.details ?? {},
    );
  }

  return (body as InvokeOkBody<R>).data;
}

/** 事件轮询：GET /api/events?task_id=<id>&from_seq=<n>。 */
export async function pollEvents(
  taskId: string,
  fromSeq: number,
): Promise<{ events: UiEvent[]; next_seq: number }> {
  const url = `${BASE_URL}/api/events?task_id=${encodeURIComponent(taskId)}&from_seq=${fromSeq}`;
  let res: Response;
  try {
    res = await fetch(url, { headers: await bridgeHeaders() });
  } catch {
    throw new BridgeError("LAA-1001", "无法连接后端服务", false, { task_id: taskId });
  }
  if (!res.ok) {
    throw unexpected(res.status);
  }
  return (await res.json()) as { events: UiEvent[]; next_seq: number };
}