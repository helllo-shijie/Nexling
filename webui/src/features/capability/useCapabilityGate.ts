// useCapabilityGate：能力门控 hook。
// available -> 调用 onActivate；否则仅弹统一 FeatureNotice（零后端调用）。
import { useCallback } from "react";
import { useAppStore } from "../../store/app";
import type { CapabilityStatus } from "../../bridge/types";
import { notifyFeature } from "../../store/notice";

export interface CapabilityGate {
  status: CapabilityStatus | "unknown";
  available: boolean;
  activate: () => void;
}

export function useCapabilityGate(
  capabilityId: string,
  onActivate?: () => void,
): CapabilityGate {
  const capabilities = useAppStore((s) => s.capabilities);
  const cap = capabilities.find((c) => c.id === capabilityId);
  const status: CapabilityStatus | "unknown" = cap?.status ?? "unknown";
  const available = status === "available";

  const activate = useCallback(() => {
    if (available) {
      onActivate?.();
      return;
    }
    const key = cap?.message_key || `capability.${capabilityId}.in_development`;
    notifyFeature(key);
  }, [available, cap, capabilityId, onActivate]);

  return { status, available, activate };
}