// ModeControl：模式分段控件（流畅 / 直译），默认流畅。
import { useAppStore } from "../../store/app";
import type { TranslateMode } from "../../bridge/types";
import { t } from "../../i18n/ui";

const MODES: { value: TranslateMode; key: string }[] = [
  { value: "fluent", key: "mode.fluent" },
  { value: "literal", key: "mode.literal" },
];

export function ModeControl() {
  const mode = useAppStore((s) => s.mode);
  const setMode = useAppStore((s) => s.setMode);

  return (
    <div className="mode-control" role="radiogroup" aria-label={t("mode.aria")}>
      {MODES.map((m) => (
        <button
          key={m.value}
          type="button"
          role="radio"
          aria-checked={mode === m.value}
          className={`mode-control__option${
            mode === m.value ? " mode-control__option--active" : ""
          }`}
          onClick={() => void setMode(m.value)}
        >
          {t(m.key)}
        </button>
      ))}
    </div>
  );
}
