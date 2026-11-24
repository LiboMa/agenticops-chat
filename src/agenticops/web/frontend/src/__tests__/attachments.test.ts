import { describe, it, expect } from "vitest";
import {
  filesFromPaste,
  filesFromDrop,
  validateFiles,
  fileKey,
  FALLBACK_POLICY,
  attachmentRules,
  attachmentErrorText,
  normalizePastedName,
  type UploadPolicy,
} from "@/lib/attachments";

function file(name: string, size: number, type = ""): File {
  return new File([new Uint8Array(size)], name, { type });
}

const MB = 1024 * 1024;
const rules = attachmentRules(FALLBACK_POLICY);

describe("attachments (2026-11-07: any common file, limits from the server)", () => {
  it("non-image paste is accepted", () => {
    const pdf = file("report.pdf", 10, "application/pdf");
    const xlsx = file("q3.xlsx", 10);
    const out = filesFromPaste({ items: [
      { kind: "string", type: "text/plain", getAsFile: () => null },
      { kind: "file", type: "application/pdf", getAsFile: () => pdf },
      { kind: "file", type: "", getAsFile: () => xlsx },
    ] });
    expect(out.map((f) => f.name)).toEqual(["report.pdf", "q3.xlsx"]);
  });

  it("filesFromPaste returns [] when no items; filesFromDrop returns the dropped files", () => {
    expect(filesFromPaste({})).toEqual([]);
    expect(filesFromDrop({ files: [file("a.log", 1), file("b.json", 1)] }).map((f) => f.name)).toEqual(["a.log", "b.json"]);
  });

  it("pasted files get a dated name before dedupe; user-named files keep theirs", () => {
    const now = new Date(2026, 10, 7, 9, 5, 3);
    expect(normalizePastedName(file("image.png", 5, "image/png"), now, 1).name).toBe("pasted-20261107-090503-1.png");
    expect(normalizePastedName(file("", 5, "image/jpeg"), now, 2).name).toBe("pasted-20261107-090503-2.jpg");
    expect(normalizePastedName(file("Pasted Graphic 3.tiff", 5, "image/tiff"), now, 3).name)
      .toBe("pasted-20261107-090503-3.tiff");
    expect(normalizePastedName(file("blob", 5, "application/pdf"), now, 4).name).toBe("pasted-20261107-090503-4.pdf");
    expect(normalizePastedName(file("clipboard", 5, ""), now, 5).name).toBe("pasted-20261107-090503-5.bin");
    expect(normalizePastedName(file("imagery-report.pdf", 5, "application/pdf"), now, 6).name).toBe("imagery-report.pdf");
    expect(normalizePastedName(file("q3.xlsx", 5), now, 7).name).toBe("q3.xlsx");
    const renamed = normalizePastedName(file("image.png", 7, "image/png"), now, 1);
    expect([renamed.size, renamed.type]).toEqual([7, "image/png"]);
  });

  it("pasted files with the same name and size are both kept", () => {
    const now = new Date(2026, 10, 7, 9, 5, 3);
    const a = normalizePastedName(file("image.png", 100, "image/png"), now, 1);
    const b = normalizePastedName(file("image.png", 100, "image/png"), now, 2);
    const r = validateFiles([a], [b], rules);
    expect(r.accepted).toHaveLength(1);
  });

  it("accepts every common type the server supports, refuses others", () => {
    for (const name of ["a.txt", "a.md", "a.html", "a.htm", "a.pdf", "a.docx", "a.doc", "a.xlsx", "a.xlsm", "a.xls",
                        "a.csv", "a.tsv", "a.pptx", "a.jpg", "a.png", "a.gif", "a.webp", "a.bmp", "a.tiff", "a.heic",
                        "a.json", "a.log", "deploy.sh", "Makefile"]) {
      expect(rules.accepted(name)).toBe(true);
    }
    expect(rules.accepted("setup.exe")).toBe(false);
    expect(rules.accepted("logo.svg")).toBe(false);
    expect(rules.kindOf("A.HEIC")).toBe("image");
    expect(rules.kindOf("q.xlsx")).toBe("office");
  });

  it("an extensionless type allowed means no accept filter (the picker would hide Makefile)", () => {
    expect(rules.accept).toBe("");
    const pdfOnly = attachmentRules({ ...FALLBACK_POLICY, extensions: [".pdf", ".png"] });
    expect(pdfOnly.accept).toBe(".pdf,.png");
    expect(pdfOnly.accepted("Makefile")).toBe(false);
  });

  it("validateFiles: type, per-file size, count, then total size", () => {
    const small: UploadPolicy = { ...FALLBACK_POLICY, max_files: 3, max_file_bytes: 2 * MB, max_total_bytes: 3 * MB };
    const r = attachmentRules(small);
    expect(validateFiles([], [file("bad.exe", 1)], r).errors).toEqual([{ kind: "type", name: "bad.exe" }]);
    expect(validateFiles([], [file("big.pdf", 3 * MB)], r).errors).toEqual([{ kind: "size", name: "big.pdf", limit: 2 * MB }]);
    const total = validateFiles([file("a.pdf", 2 * MB)], [file("b.pdf", 2 * MB)], r);
    expect(total.accepted).toEqual([]);
    expect(total.errors).toEqual([{ kind: "total", limit: 3 * MB }]);
    const count = validateFiles([file("1.png", 1), file("2.png", 1)], [file("3.png", 1), file("4.png", 1)], r);
    expect(count.accepted.map((f) => f.name)).toEqual(["3.png"]);
    expect(count.errors).toEqual([{ kind: "count", limit: 3 }]);
  });

  it("existing entries need only a name and a size (restored uploads have no File)", () => {
    const r = validateFiles([{ name: "a.pdf", size: 10 }], [file("a.pdf", 10), file("b.pdf", 10)], rules);
    expect(r.accepted.map((f) => f.name)).toEqual(["b.pdf"]);
  });

  it("dedups within the batch, same name with another size is not a duplicate", () => {
    expect(validateFiles([], [file("a.png", 100), file("a.png", 100)], rules).accepted).toHaveLength(1);
    expect(validateFiles([file("a.log", 100)], [file("a.log", 200)], rules).accepted).toHaveLength(1);
    expect(fileKey(file("x.png", 42))).toBe("x.png:42");
  });

  it("a smaller max from the server is honoured", () => {
    const two = attachmentRules({ ...FALLBACK_POLICY, max_files: 2 });
    const r = validateFiles([], [file("1.png", 1), file("2.png", 1), file("3.png", 1)], two);
    expect(r.accepted).toHaveLength(2);
    expect(r.errors).toEqual([{ kind: "count", limit: 2 }]);
  });

  it("error text goes through the locale", () => {
    const t = (k: string) => ({ "chat.attach.type": "{name}: type", "chat.attach.size": "{name}: max {limit}",
                                "chat.attach.count": "max {limit}", "chat.attach.total": "total {limit}" } as
                                Record<string, string>)[k] ?? k;
    expect(attachmentErrorText({ kind: "size", name: "a.log", limit: 50 * MB }, t)).toBe("a.log: max 50 MB");
    expect(attachmentErrorText({ kind: "count", limit: 20 }, t)).toBe("max 20");
    expect(attachmentErrorText({ kind: "total", limit: 200 * MB }, t)).toBe("total 200 MB");
  });
});

describe("attachmentReasonText", () => {
  it("words a server reason code in the user's language, and shows an unknown code as is", async () => {
    const { attachmentReasonText } = await import("@/lib/attachments");
    const t = (k: string) => ({ "chat.attach.reason.encrypted": "password-protected" } as Record<string, string>)[k] ?? k;
    expect(attachmentReasonText("encrypted", t)).toBe("password-protected");
    expect(attachmentReasonText("brand_new_code", t)).toBe("brand_new_code");
    expect(attachmentReasonText(undefined, t)).toBe("");
  });
});

import { attachmentErrorReason, pagesLabel } from "@/lib/attachments";
describe("composer card copy (2026-11-07)", () => {
  it("a refused file's reason without its name (the card shows the name)", () => {
    const en = (k: string) => (k === "chat.attach.type" ? "{name}: this file type cannot be attached" : k);
    const zh = (k: string) => (k === "chat.attach.type" ? "{name}：不支持这种文件类型" : k);
    expect(attachmentErrorReason({ kind: "type", name: "setup.exe" }, en)).toBe("this file type cannot be attached");
    expect(attachmentErrorReason({ kind: "type", name: "setup.exe" }, zh)).toBe("不支持这种文件类型");
  });
  it("one page, n pages", () => {
    const t = (k: string) => (k === "chat.attach.page" ? "1 page" : "{n} pages");
    expect(pagesLabel(1, t)).toBe("1 page");
    expect(pagesLabel(12, t)).toBe("12 pages");
  });
});
