// SceneSelector：场景档案选择器（位于工作台顶部工具栏）。
import { useAppStore } from "../../store/app";
import { entityLabel, t } from "../../i18n/ui";

export function SceneSelector() {
  const scenes = useAppStore((s) => s.scenes);
  const scene = useAppStore((s) => s.scene);
  const setScene = useAppStore((s) => s.setScene);

  return (
    <label className="scene-selector">
      <span className="scene-selector__label">{t("scene.label")}</span>
      <select
        className="scene-selector__select"
        value={scene?.id ?? ""}
        onChange={(e) => setScene(e.target.value)}
      >
        {scenes.map((s) => (
          <option key={s.id} value={s.id}>
            {entityLabel("scene", s.id, s.name)}
          </option>
        ))}
      </select>
    </label>
  );
}