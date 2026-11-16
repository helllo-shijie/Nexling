// 拖入文件翻译：格式判定、编码识别与 BOM 兼容；V10 起不再在前端截断。
import { describe, expect, it } from "vitest";
import {
  decodeTextBytes,
  isSupportedTextFile,
  readDroppedFiles,
  readTextFile,
  stripBom,
} from "../src/features/workbench/dropFile";

function bytes(...values: number[]): Uint8Array {
  return new Uint8Array(values);
}

function utf8(text: string): Uint8Array {
  return new TextEncoder().encode(text);
}

describe("drop file", () => {
  it("accepts only .txt / .md", () => {
    expect(isSupportedTextFile("notes.txt")).toBe(true);
    expect(isSupportedTextFile("README.MD")).toBe(true);
    expect(isSupportedTextFile("paper.pdf")).toBe(false);
    expect(isSupportedTextFile("doc.txt.bak")).toBe(false);
  });

  it("strips UTF-8 BOM", () => {
    expect(stripBom("\uFEFFhello")).toBe("hello");
    expect(stripBom("hello")).toBe("hello");
  });

  it("keeps long content intact instead of truncating", async () => {
    const long = "a".repeat(250_000);
    const result = await readDroppedFiles([new File([long], "long.txt", { type: "text/plain" })]);
    // V10：超上限交给提交前的估算明确提示，前端不再静默截断
    expect(result.text.length).toBe(250_000);
    expect(result.read).toEqual(["long.txt"]);
  });

  it("reads a BOM-prefixed file as UTF-8", async () => {
    const file = new File(["\uFEFF技术文档"], "notes.txt", { type: "text/plain" });
    expect(await readTextFile(file)).toBe("技术文档");
  });

  it("decodes UTF-8 with BOM", () => {
    const raw = new Uint8Array([0xef, 0xbb, 0xbf, ...utf8("技术文档")]);
    const out = decodeTextBytes(raw);
    expect(out.text).toBe("技术文档");
    expect(out.encoding).toBe("utf-8-sig");
  });

  it("decodes UTF-16 LE / BE with BOM", () => {
    const text = "技术文档";
    const le: number[] = [0xff, 0xfe];
    const be: number[] = [0xfe, 0xff];
    for (const ch of text) {
      const code = ch.charCodeAt(0);
      le.push(code & 0xff, code >> 8);
      be.push(code >> 8, code & 0xff);
    }
    expect(decodeTextBytes(new Uint8Array(le))).toEqual({ text, encoding: "utf-16le" });
    expect(decodeTextBytes(new Uint8Array(be))).toEqual({ text, encoding: "utf-16be" });
  });

  it("decodes BOM-less UTF-16 LE", () => {
    const raw: number[] = [];
    for (const ch of "Hello") {
      const code = ch.charCodeAt(0);
      raw.push(code & 0xff, 0);
    }
    expect(decodeTextBytes(new Uint8Array(raw))).toEqual({ text: "Hello", encoding: "utf-16le" });
  });

  it("falls back to GBK for non-UTF-8 Chinese", () => {
    // “中文测试” 的 GBK 编码
    const out = decodeTextBytes(bytes(0xd6, 0xd0, 0xce, 0xc4, 0xb2, 0xe2, 0xca, 0xd4));
    expect(out.text).toBe("中文测试");
    expect(out.encoding).toBe("gbk");
  });

  it("reports unrecognizable bytes instead of mojibake", () => {
    expect(() => decodeTextBytes(bytes(0x81))).toThrow();
  });

  it("merges multiple files and reports skipped ones", async () => {
    const result = await readDroppedFiles([
      new File(["Hello"], "a.txt", { type: "text/plain" }),
      new File(["World"], "b.md", { type: "text/markdown" }),
      new File(["binary"], "c.pdf", { type: "application/pdf" }),
    ]);
    expect(result.text).toBe("Hello\n\nWorld");
    expect(result.read).toEqual(["a.txt", "b.md"]);
    expect(result.skipped).toEqual(["c.pdf"]);
    expect(result.failed).toEqual([]);
  });
});
