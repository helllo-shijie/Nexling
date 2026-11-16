// LanguageSelect：目标语言选择。源语言一律自动识别，因此不出现"中译英"这类绑定源语言的选项。
// 控件为自定义下拉：标签与触发按钮始终同行不换行，窄窗口收成「图标 + 当前语言短码」。
import { useEffect, useRef, useState } from "react";
import { useAppStore } from "../../store/app";
import { t, uiLang } from "../../i18n/ui";
import { CheckIcon, ChevronDownIcon, GlobeIcon } from "../../components/icons";

interface TargetLang {
  value: string;
  label: string;
  short: string;
  labelEn?: string;
  shortEn?: string;
  group: "auto" | "common" | "more";
}

export const TARGET_LANGS: TargetLang[] = [
  { value: "auto", label: "自动（中文↔英文）", short: "自动", group: "auto" },
  { value: "zh-Hans", label: "中文（简体）", short: "中文", labelEn: "Chinese (Simplified)", shortEn: "ZH", group: "common" },
  { value: "en", label: "English", short: "EN", group: "common" },
  { value: "ja", label: "日本語", short: "JA", group: "more" },
  { value: "ko", label: "한국어", short: "KO", group: "more" },
  { value: "fr", label: "Français", short: "FR", group: "more" },
  { value: "de", label: "Deutsch", short: "DE", group: "more" },
  { value: "es", label: "Español", short: "ES", group: "more" },
  { value: "ru", label: "Русский", short: "RU", group: "more" },
];

const GROUPS: { id: TargetLang["group"]; key: string }[] = [
  { id: "auto", key: "lang.group.auto" },
  { id: "common", key: "lang.group.common" },
  { id: "more", key: "lang.group.more" },
];

/** 目标语言的显示名（随界面语言切换）。 */
export function targetLangLabel(value: string): string {
  if (value === "auto") return t("lang.auto");
  const hit = TARGET_LANGS.find((l) => l.value === value);
  if (!hit) return value;
  return uiLang() === "en" ? hit.labelEn ?? hit.label : hit.label;
}

/** 目标语言的短标签（历史列表等处使用）。 */
export function targetLangShort(value: string): string {
  if (value === "auto") return t("lang.auto.short");
  const hit = TARGET_LANGS.find((l) => l.value === value);
  if (!hit) return value;
  return uiLang() === "en" ? hit.shortEn ?? hit.short : hit.short;
}

export function LanguageSelect() {
  const targetLang = useAppStore((s) => s.targetLang);
  const setTargetLang = useAppStore((s) => s.setTargetLang);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // 点击外部或按 Esc 收起下拉
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent): void => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const pick = (value: string): void => {
    setTargetLang(value);
    setOpen(false);
  };

  return (
    <div className="langsel" ref={rootRef}>
      <span className="langsel__caption">{t("wb.target")}</span>
      <button
        type="button"
        className="langsel__btn"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={t("lang.menu")}
        onClick={() => setOpen((v) => !v)}
      >
        <GlobeIcon className="langsel__globe" />
        <span className="langsel__value">{targetLangLabel(targetLang)}</span>
        <span className="langsel__short">{targetLangShort(targetLang)}</span>
        <ChevronDownIcon className="langsel__chev" />
      </button>

      {open ? (
        <ul className="langsel__menu" role="listbox" aria-label={t("lang.menu")}>
          {GROUPS.map((g) => {
            const items = TARGET_LANGS.filter((l) => l.group === g.id);
            if (!items.length) return null;
            return (
              <li key={g.id} className="langsel__groupwrap">
                <div className="langsel__group" aria-hidden="true">
                  {t(g.key)}
                </div>
                <ul className="langsel__sublist" role="group" aria-label={t(g.key)}>
                  {items.map((l) => {
                    const active = l.value === targetLang;
                    return (
                      <li key={l.value}>
                        <button
                          type="button"
                          role="option"
                          aria-selected={active}
                          className={`langsel__option${active ? " langsel__option--active" : ""}`}
                          onClick={() => pick(l.value)}
                        >
                          {active ? (
                            <CheckIcon className="langsel__check" />
                          ) : (
                            <span className="langsel__check--placeholder" aria-hidden="true" />
                          )}
                          <span className="langsel__option-main">
                            <span>{targetLangLabel(l.value)}</span>
                            {l.value === "auto" ? (
                              <span className="langsel__option-note">{t("lang.note.auto")}</span>
                            ) : null}
                          </span>
                          <span className="langsel__option-code">{targetLangShort(l.value)}</span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
