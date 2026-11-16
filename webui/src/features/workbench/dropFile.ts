// 拖入文件翻译：格式判定 / 编码识别 / BOM 清理（纯函数，便于测试）。
// V10 起不再在前端按长度截断：超过硬上限由提交前的估算明确提示，长文本交给后端分批处理。
export const SUPPORTED_EXTS = [".txt", ".md"] as const;
// 一次拖入过多文件时限制合并数量，避免误拖整个目录后卡死读取
export const MAX_DROPPED_FILES = 20;

export function isSupportedTextFile(name: string): boolean {
  const lower = name.toLowerCase();
  return SUPPORTED_EXTS.some((ext) => lower.endsWith(ext));
}

/** 去掉 UTF-8 BOM（\uFEFF），避免首个字符被当成正文。 */
export function stripBom(text: string): string {
  return text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
}

export interface DecodedText {
  text: string;
  encoding: "utf-8" | "utf-8-sig" | "utf-16le" | "utf-16be" | "gbk";
}

function tryDecode(bytes: Uint8Array, encoding: string): string {
  return new TextDecoder(encoding, { fatal: true }).decode(bytes);
}

/** 无 BOM 的 UTF-16：按 0 字节分布判断（ASCII 文本的奇数/偶数位会大量为 0）。 */
function sniffUtf16(bytes: Uint8Array): "utf-16le" | "utf-16be" | "" {
  const n = Math.min(bytes.length, 512);
  if (n < 4) return "";
  let evenZero = 0;
  let oddZero = 0;
  for (let i = 0; i < n; i += 1) {
    if (bytes[i] === 0) {
      if (i % 2 === 0) evenZero += 1;
      else oddZero += 1;
    }
  }
  const half = n / 2;
  if (oddZero > half * 0.3 && evenZero < half * 0.05) return "utf-16le";
  if (evenZero > half * 0.3 && oddZero < half * 0.05) return "utf-16be";
  return "";
}

/**
 * 按 BOM → UTF-8 → GBK 的顺序识别编码。
 * 全部失败时抛错，由调用方提示用户，而不是把乱码填进输入框。
 */
export function decodeTextBytes(bytes: Uint8Array): DecodedText {
  if (bytes.length >= 3 && bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
    return { text: stripBom(tryDecode(bytes.subarray(3), "utf-8")), encoding: "utf-8-sig" };
  }
  if (bytes.length >= 2 && bytes[0] === 0xff && bytes[1] === 0xfe) {
    return { text: stripBom(tryDecode(bytes.subarray(2), "utf-16le")), encoding: "utf-16le" };
  }
  if (bytes.length >= 2 && bytes[0] === 0xfe && bytes[1] === 0xff) {
    return { text: stripBom(tryDecode(bytes.subarray(2), "utf-16be")), encoding: "utf-16be" };
  }
  const utf16 = sniffUtf16(bytes);
  if (utf16) {
    try {
      return { text: stripBom(tryDecode(bytes, utf16)), encoding: utf16 };
    } catch {
      // 嗅探误判则继续按 UTF-8/GBK 尝试
    }
  }
  for (const encoding of ["utf-8", "gbk"] as const) {
    try {
      return { text: stripBom(tryDecode(bytes, encoding)), encoding };
    } catch {
      // 换下一种编码
    }
  }
  throw new Error("无法识别文件编码（支持 UTF-8 / UTF-16 / GBK）");
}

function readBytes(file: File): Promise<Uint8Array> {
  if (typeof file.arrayBuffer === "function") {
    return file.arrayBuffer().then((buf) => new Uint8Array(buf));
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer));
    reader.onerror = () => reject(reader.error ?? new Error("read failed"));
    reader.readAsArrayBuffer(file);
  });
}

/** 读取单个文本文件：自动识别 UTF-8 / UTF-16 / GBK。 */
export async function readTextFile(file: File): Promise<string> {
  return decodeTextBytes(await readBytes(file)).text;
}

export interface DroppedFilesResult {
  /** 合并后的正文（文件之间空一行）；不截断，超限由提交时明确提示 */
  text: string;
  /** 成功读取的文件名 */
  read: string[];
  /** 扩展名不支持而被跳过的文件名 */
  skipped: string[];
  /** 编码无法识别或读取失败的文件 */
  failed: { name: string; reason: string }[];
}

/**
 * 读取拖入的多个文件：格式不支持的跳过、编码失败的单条上报，其余按顺序合并。
 * 单个文件坏掉不会影响其它文件，也不会让整次拖入静默失败。
 */
export async function readDroppedFiles(files: File[]): Promise<DroppedFilesResult> {
  const skipped: string[] = [];
  const failed: { name: string; reason: string }[] = [];
  const read: string[] = [];
  const texts: string[] = [];

  for (const file of files.slice(0, MAX_DROPPED_FILES)) {
    if (!isSupportedTextFile(file.name)) {
      skipped.push(file.name);
      continue;
    }
    try {
      texts.push(await readTextFile(file));
      read.push(file.name);
    } catch (err) {
      failed.push({ name: file.name, reason: err instanceof Error ? err.message : String(err) });
    }
  }
  for (const file of files.slice(MAX_DROPPED_FILES)) {
    skipped.push(file.name);
  }

  const merged = texts.filter((t) => t.trim().length > 0).join("\n\n");
  return { text: merged, read, skipped, failed };
}
