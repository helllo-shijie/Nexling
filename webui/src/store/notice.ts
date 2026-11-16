// 全局 toast 通知状态（FeatureNotice 使用）。
import { create } from "zustand";
import { getMessage } from "../i18n/messages";

export interface Notice {
  id: string;
  title: string;
  body: string;
}

interface NoticeState {
  notices: Notice[];
  push: (title: string, body: string) => void;
  dismiss: (id: string) => void;
}

let noticeSeq = 0;

export const useNoticeStore = create<NoticeState>((set) => ({
  notices: [],
  push: (title, body) =>
    set((s) => ({ notices: [...s.notices, { id: `n-${++noticeSeq}`, title, body }] })),
  dismiss: (id) => set((s) => ({ notices: s.notices.filter((n) => n.id !== id) })),
}));

/** 按 message_key 弹出一条统一 FeatureNotice。 */
export function notifyFeature(messageKey: string): void {
  const { title, body } = getMessage(messageKey);
  useNoticeStore.getState().push(title, body);
}

/** 可用能力的普通提示（与占位入口的 FeatureNotice 区分，不涉及状态后缀）。 */
export function notifyInfo(title: string, body: string): void {
  useNoticeStore.getState().push(title, body);
}