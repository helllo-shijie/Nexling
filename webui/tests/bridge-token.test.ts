// 本地桥 token 只从原生桥（pywebview js_api）读取，页面 meta/源码里不应存在。
import { beforeEach, describe, expect, it, vi } from "vitest";

interface PywebviewWindow {
  pywebview?: { api?: { get_bridge_token?: () => Promise<string> } };
}

describe("bridge token", () => {
  beforeEach(() => {
    vi.resetModules();
    document.head.innerHTML = "";
    delete (window as unknown as PywebviewWindow).pywebview;
  });

  it("reads the token from the native bridge", async () => {
    (window as unknown as PywebviewWindow).pywebview = {
      api: { get_bridge_token: () => Promise.resolve("from-native") },
    };
    // 即便有人往页面里塞 meta，也不能覆盖原生桥来源
    document.head.innerHTML = '<meta name="nexling-token" content="from-meta">';
    const { bridgeToken } = await import("../src/bridge/client");
    expect(await bridgeToken()).toBe("from-native");
  });

  it("returns an empty token in dev when no native bridge exists", async () => {
    const { bridgeToken } = await import("../src/bridge/client");
    expect(await bridgeToken()).toBe("");
  });
});
