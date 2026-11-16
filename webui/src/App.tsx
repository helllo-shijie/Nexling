// App：NexLing 外壳。顶级导航只保留工作台 / 术语库 / 设置；空壳能力收进「设置 → 路线图」。
import { lazy, Suspense, useEffect } from "react";
import { useAppStore } from "./store/app";
import { FeatureNotice } from "./features/capability/FeatureNotice";
import { Workbench } from "./features/workbench/Workbench";
import { applySkin } from "./features/skin/applySkin";
import { t } from "./i18n/ui";

// 设置与术语库按需加载，缩小首屏包体
const Settings = lazy(() =>
  import("./features/settings/Settings").then((m) => ({ default: m.Settings })),
);
const GlossaryManager = lazy(() =>
  import("./features/glossary/GlossaryManager").then((m) => ({ default: m.GlossaryManager })),
);

const NAV: { id: "workbench" | "glossary" | "settings"; key: string }[] = [
  { id: "workbench", key: "nav.workbench" },
  { id: "glossary", key: "nav.glossary" },
  { id: "settings", key: "nav.settings" },
];

function BrandMark() {
  return (
    <svg className="brand__mark" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="3" y="4" width="13" height="3.4" rx="1.7" fill="currentColor" opacity="0.35" />
      <rect x="6" y="10.3" width="13" height="3.4" rx="1.7" fill="currentColor" opacity="0.65" />
      <rect x="9" y="16.6" width="12" height="3.4" rx="1.7" fill="currentColor" />
    </svg>
  );
}

export default function App() {
  const bootstrap = useAppStore((s) => s.bootstrap);
  const busy = useAppStore((s) => s.busy);
  const view = useAppStore((s) => s.view);
  const setView = useAppStore((s) => s.setView);
  const uiLang = useAppStore((s) => s.uiLang);
  const activeSkin = useAppStore((s) => s.activeSkin);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  // 皮肤切换即时生效：只写 CSS 变量与少量数据属性，不重建页面
  useEffect(() => {
    applySkin(activeSkin);
  }, [activeSkin]);

  useEffect(() => {
    document.documentElement.lang = uiLang === "en" ? "en" : "zh-CN";
  }, [uiLang]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <BrandMark />
          <span className="brand__name">{t("app.brand")}</span>
          <span className="brand__tag">{t("app.tagline")}</span>
        </div>
        <nav className="topbar__nav">
          {NAV.map((n) => (
            <button
              key={n.id}
              type="button"
              className={`topbar__nav-item${view === n.id ? " topbar__nav-item--active" : ""}`}
              onClick={() => setView(n.id)}
            >
              {t(n.key)}
            </button>
          ))}
        </nav>
        <span className="topbar__spacer" />
        {busy ? (
          <span className="topbar__busy">
            <span className="dot-pulse" />
            {t("nav.busy")}
          </span>
        ) : null}
      </header>

      <main className="main" key={uiLang}>
        <Suspense fallback={<div className="page-loading">{t("app.loading")}</div>}>
          {view === "workbench" ? (
            <Workbench />
          ) : view === "settings" ? (
            <Settings />
          ) : (
            <GlossaryManager />
          )}
        </Suspense>
      </main>

      <FeatureNotice />
    </div>
  );
}
