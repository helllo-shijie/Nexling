// FeatureNotice：占位入口点击后的统一 toast。
// 文案取 message_key（见 i18n/messages.ts），3 秒自动消失。
import { useEffect } from "react";
import { useNoticeStore, type Notice } from "../../store/notice";

const AUTO_DISMISS_MS = 3000;

function NoticeToast({ notice }: { notice: Notice }) {
  const dismiss = useNoticeStore((s) => s.dismiss);
  const { id, title, body } = notice;

  useEffect(() => {
    const timer = setTimeout(() => dismiss(id), AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [id, dismiss]);

  return (
    <div className="feature-notice" role="status">
      <strong className="feature-notice__title">{title}</strong>
      {body ? <span className="feature-notice__body">{body}</span> : null}
    </div>
  );
}

export function FeatureNotice() {
  const notices = useNoticeStore((s) => s.notices);
  if (notices.length === 0) return null;
  return (
    <div className="feature-notice-host" aria-live="polite" aria-atomic="false">
      {notices.map((n) => (
        <NoticeToast key={n.id} notice={n} />
      ))}
    </div>
  );
}