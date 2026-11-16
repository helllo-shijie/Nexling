// 原生「另存为」：通过桥接命令 file.save_dialog 让桌面程序弹系统保存对话框。
// 非桌面模式（浏览器）降级到 File System Access API；都不支持时退回普通下载。
import { invoke } from "../api/laa";

export interface SaveTextResult {
  saved?: boolean;
  cancelled?: boolean;
  path?: string;
  error?: string;
  unsupported?: boolean;
}

interface SavePickerWritable {
  write: (data: string) => Promise<void>;
  close: () => Promise<void>;
}

interface SavePickerHandle {
  name: string;
  createWritable: () => Promise<SavePickerWritable>;
}

type SavePicker = (options: {
  suggestedName?: string;
  types?: { description?: string; accept: Record<string, string[]> }[];
}) => Promise<SavePickerHandle>;

/** 三种导出格式的 MIME 与文件选择器描述（.txt/.md/.json）。 */
function formatOf(name: string): { ext: string; mime: string; label: string } {
  const dot = name.lastIndexOf(".");
  const ext = dot >= 0 ? name.slice(dot).toLowerCase() : ".json";
  if (ext === ".md") return { ext, mime: "text/markdown;charset=utf-8", label: "Markdown 文件" };
  if (ext === ".txt") return { ext, mime: "text/plain;charset=utf-8", label: "文本文件" };
  return { ext: ".json", mime: "application/json", label: "JSON 文件" };
}

/**
 * 把文本保存到用户选择的路径，返回保存结果。
 * 流程：桌面桥接命令（弹系统对话框）→ 浏览器文件选择器 → 普通下载。
 */
export async function saveTextFile(defaultName: string, content: string): Promise<SaveTextResult> {
  // 1) 桌面程序：通过 bridge 命令触发 Python 侧的系统保存对话框
  try {
    const res = await invoke<unknown, SaveTextResult>("file.save_dialog", {
      suggested_name: defaultName,
      content,
    });
    // bridge 返回 unsupported 时说明不在桌面模式，继续降级
    if (!res.unsupported) return res;
  } catch {
    // bridge 完全不可达时（如浏览器直接打开 dist），降级
  }

  // 2) 浏览器：File System Access API（可在基于 Chromium 的现代浏览器里选路径）
  const picker = (window as unknown as { showSaveFilePicker?: SavePicker }).showSaveFilePicker;
  if (picker) {
    const fmt = formatOf(defaultName);
    try {
      const handle = await picker({
        suggestedName: defaultName,
        types: [{ description: fmt.label, accept: { [fmt.mime]: [fmt.ext] } }],
      });
      const writable = await handle.createWritable();
      await writable.write(content);
      await writable.close();
      return { saved: true, path: handle.name };
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return { cancelled: true };
      return { error: e instanceof Error ? e.message : String(e) };
    }
  }

  return { unsupported: true };
}

/** 按扩展名给出下载 MIME（浏览器兜底用）。 */
export function mimeForName(name: string): string {
  return formatOf(name).mime;
}

/**
 * 保存二进制内容（如皮肤包 .nxlskin）：桌面走系统对话框，浏览器降级为下载。
 * 内容以 base64 传入，避免在前端与桥之间做字节数组序列化。
 */
export async function saveBinaryFile(
  defaultName: string,
  base64: string,
): Promise<SaveTextResult> {
  try {
    const res = await invoke<unknown, SaveTextResult>("file.save_dialog", {
      suggested_name: defaultName,
      content: base64,
      base64_encoded: true,
    });
    if (!res.unsupported) return res;
  } catch {
    // 继续降级
  }
  try {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    const blob = new Blob([bytes], { type: "application/octet-stream" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = defaultName;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    return { saved: true, path: defaultName };
  } catch (e) {
    return { error: e instanceof Error ? e.message : String(e) };
  }
}

/** 兜底：普通浏览器下载（保存位置取决于浏览器设置）。 */
export function downloadTextFile(defaultName: string, content: string, mime = "application/json"): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = defaultName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}