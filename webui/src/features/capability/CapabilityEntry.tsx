// CapabilityEntry：能力入口组件。
// 硬性要求（§6.25）：占位入口与可用入口外观/文案完全一致 —— 从不加 disabled、
// 角标/红点/锁/虚线/"Beta"，点击占位入口只弹 FeatureNotice。
import type { KeyboardEvent, ReactNode } from "react";
import { useCapabilityGate } from "./useCapabilityGate";

export interface CapabilityEntryProps {
  capabilityId: string;
  onActivate?: () => void;
  className?: string;
  title?: string;
  icon?: ReactNode;
  children?: ReactNode;
  as?: "button" | "div";
}

export function CapabilityEntry({
  capabilityId,
  onActivate,
  className = "",
  title,
  icon,
  children,
  as = "button",
}: CapabilityEntryProps) {
  const { activate } = useCapabilityGate(capabilityId, onActivate);
  const classes = `cap-entry ${className}`.trim();
  const content = children ?? title;

  if (as === "div") {
    const handleKey = (e: KeyboardEvent<HTMLDivElement>): void => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        activate();
      }
    };
    return (
      <div className={classes} role="button" tabIndex={0} onClick={activate} onKeyDown={handleKey}>
        {icon}
        {content}
      </div>
    );
  }

  return (
    <button type="button" className={classes} onClick={activate}>
      {icon}
      {content}
    </button>
  );
}