// RoadmapPanel：路线图。原先散落在界面各处、点击只弹"开发中"的空壳能力，统一收到这里并标注状态。
import { useAppStore } from "../../store/app";
import { entityText, t } from "../../i18n/ui";

const STAGE_LABEL_KEY: Record<string, string> = {
  core: "roadmap.now",
  next: "roadmap.next",
  M4: "roadmap.m4",
  M5: "roadmap.m5",
  M6: "roadmap.later",
  later: "roadmap.later",
};

const GROUP_LABEL_KEY: Record<string, string> = {
  input: "roadmap.group.input",
  output: "roadmap.group.output",
  extend: "roadmap.group.extend",
  platform: "roadmap.group.platform",
};

function stageLabel(stage: string): string {
  const key = STAGE_LABEL_KEY[stage];
  return key ? t(key) : stage;
}

function groupLabel(group: string): string {
  const key = GROUP_LABEL_KEY[group];
  return key ? t(key) : group;
}

export function RoadmapPanel() {
  const capabilities = useAppStore((s) => s.capabilities);
  const items = capabilities.filter((c) => c.status === "roadmap");
  const groups = Array.from(new Set(items.map((c) => c.group)));

  return (
    <div className="roadmap">
      <p className="muted">{t("roadmap.desc")}</p>
      {items.length === 0 ? <p className="muted">{t("roadmap.empty")}</p> : null}
      {groups.map((g) => (
        <section key={g} className="roadmap__group">
          <h3 className="roadmap__group-title">{groupLabel(g)}</h3>
          <ul className="roadmap__list">
            {items
              .filter((c) => c.group === g)
              .map((c) => (
                <li key={c.id} className="roadmap__item">
                  <span className="roadmap__name">{entityText("cap", c.id, "", c.name)}</span>
                  <span className={`status status--${c.status}`}>
                    {stageLabel(c.stage)}
                  </span>
                </li>
              ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
