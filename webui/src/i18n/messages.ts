// 占位入口与错误文案的单一映射（message_key -> 文案）。
// 文案以 "/" 分割为「标题/正文」，FeatureNotice 据此渲染标题与正文。
// 约束（§6.25）：不得出现"敬请期待"、不加状态后缀、不做 disabled/角标/红点/锁。

export const MESSAGES: Record<string, string> = {
  "capability.voice.input.in_development":
    "语音输入正在开发中/我们正在打磨实时听写与断句，完成后会在此处直接可用。",
  "capability.voice.output.in_development":
    "语音朗读正在开发中/我们正在打磨发音与音色合成，完成后会在此处直接可用。",
  "capability.document.in_development":
    "文档翻译正在开发中/我们正在打磨文档解析与排版还原，完成后会在此处直接可用。",
  "capability.plugin.in_development":
    "插件正在开发中/我们正在打磨插件宿主与权限体系，完成后会在此处直接可用。",
  "capability.platform.multi.in_development":
    "多端使用正在开发中/我们正在打磨跨设备同步与状态续传，完成后会在此处直接可用。",
  "capability.model.local.in_development":
    "本地能力正在开发中/我们正在打磨离线引擎与本地隐私方案，完成后会在此处直接可用。",
  "error.LAA-2005": "正在开发中/该能力暂不可用，我们正在完善。",
};

export interface NoticeMessage {
  title: string;
  body: string;
}

export function getMessage(key: string): NoticeMessage {
  const raw = MESSAGES[key];
  if (!raw) {
    return { title: key, body: "" };
  }
  const idx = raw.indexOf("/");
  if (idx === -1) {
    return { title: raw, body: "" };
  }
  return { title: raw.slice(0, idx), body: raw.slice(idx + 1) };
}