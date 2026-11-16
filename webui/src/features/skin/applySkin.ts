// 皮肤应用层：只把后端下发的声明式变量写到 :root，不改任何布局/字体。
// 未提供的变量会被移除，回落到 global.css 的默认浅色学术风（回退路径）。
import type { SkinView } from "../../bridge/types";

const applied = new Set<string>();

const SCRIM_ALPHA = { low: 0.55, medium: 0.72, high: 0.86 } as const;

export function applySkin(skin: SkinView | null): void {
  const root = document.documentElement;
  for (const key of applied) root.style.removeProperty(key);
  applied.clear();
  root.removeAttribute("data-skin-bg");
  root.dataset.skin = skin?.id ?? "default";
  root.dataset.skinMode = skin?.mode === "dark" ? "dark" : "light";
  root.dataset.skinGlass = skin?.effects?.glass === "on" ? "on" : "off";
  root.style.colorScheme = skin?.mode === "dark" ? "dark" : "light";
  if (!skin) return;
  for (const [key, value] of Object.entries(skin.vars ?? {})) {
    if (!key.startsWith("--") || typeof value !== "string") continue;
    root.style.setProperty(key, value);
    applied.add(key);
  }
  if (skin.background?.data_url) {
    const alpha = SCRIM_ALPHA[skin.background.scrim] ?? SCRIM_ALPHA.medium;
    const base = skin.mode === "dark" ? "8, 11, 16" : "250, 250, 252";
    root.style.setProperty("--skin-bg-image", `url("${skin.background.data_url}")`);
    root.style.setProperty("--skin-bg-scrim", `rgba(${base}, ${alpha})`);
    applied.add("--skin-bg-image");
    applied.add("--skin-bg-scrim");
    root.dataset.skinBg = "on";
  }
}
