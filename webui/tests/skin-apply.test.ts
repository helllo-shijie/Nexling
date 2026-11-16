import { afterEach, describe, expect, it } from "vitest";

import type { SkinView } from "../src/bridge/types";
import { applySkin } from "../src/features/skin/applySkin";

function skin(over: Partial<SkinView> = {}): SkinView {
  return {
    id: "night",
    name: "深空夜色",
    mode: "dark",
    builtin: false,
    has_background: true,
    effects: { glass: "off" },
    vars: { "--bg": "#0f141b", "--text": "#e8eef6" },
    background: { data_url: "data:image/png;base64,QUJD", scrim: "high" },
    ...over,
  } as SkinView;
}

const root = document.documentElement;

afterEach(() => applySkin(null));

describe("applySkin", () => {
  it("写入变量、模式与玻璃标记", () => {
    applySkin(skin({ effects: { glass: "on" } }));
    expect(root.dataset.skin).toBe("night");
    expect(root.dataset.skinMode).toBe("dark");
    expect(root.dataset.skinGlass).toBe("on");
    expect(root.style.getPropertyValue("--bg")).toBe("#0f141b");
    expect(root.style.getPropertyValue("--text")).toBe("#e8eef6");
  });

  it("背景图只写根变量并带遮罩", () => {
    applySkin(skin());
    expect(root.dataset.skinBg).toBe("on");
    expect(root.style.getPropertyValue("--skin-bg-image")).toContain("data:image/png");
    expect(root.style.getPropertyValue("--skin-bg-scrim")).toContain("0.86");
    expect(root.style.getPropertyValue("--skin-bg-scrim")).toContain("8, 11, 16");
  });

  it("切回默认会清掉上次变量与背景标记", () => {
    applySkin(skin());
    applySkin(null);
    expect(root.dataset.skin).toBe("default");
    expect(root.dataset.skinMode).toBe("light");
    expect(root.dataset.skinGlass).toBe("off");
    expect(root.dataset.skinBg).toBeUndefined();
    expect(root.style.getPropertyValue("--bg")).toBe("");
    expect(root.style.getPropertyValue("--skin-bg-image")).toBe("");
  });
});
