import { describe, it, expect } from "vitest";
import {
  filesFromPaste,
  filesFromDrop,
  validateFiles,
  maxSizeForFile,
  acceptAttr,
  fileKey,
  MAX_ATTACHMENTS,
} from "@/lib/attachments";

function file(name: string, size: number): File {
  // node File global accepts (bits, name); override size via a small Blob slice trick.
  const f = new File([new Uint8Array(size)], name);
  return f;
}

describe("attachments", () => {
  it("filesFromPaste extracts image items and ignores text items", () => {
    const img = file("shot.png", 10);
    const clipboard = {
      items: [
        { kind: "string", type: "text/plain", getAsFile: () => null },
        { kind: "file", type: "image/png", getAsFile: () => img },
      ],
    };
    const out = filesFromPaste(clipboard);
    expect(out).toHaveLength(1);
    expect(out[0].name).toBe("shot.png");
  });

  it("filesFromPaste returns [] when no items", () => {
    expect(filesFromPaste({})).toEqual([]);
  });

  it("filesFromDrop returns dropped files", () => {
    const a = file("a.log", 10);
    const b = file("b.json", 10);
    expect(filesFromDrop({ files: [a, b] }).map((f) => f.name)).toEqual(["a.log", "b.json"]);
  });

  it("validateFiles accepts supported types under the size cap", () => {
    const r = validateFiles([], [file("ok.png", 100), file("ok.log", 100)]);
    expect(r.accepted.map((f) => f.name)).toEqual(["ok.png", "ok.log"]);
    expect(r.errors).toEqual([]);
  });

  it("validateFiles rejects unsupported extension", () => {
    const r = validateFiles([], [file("bad.exe", 10)]);
    expect(r.accepted).toEqual([]);
    expect(r.errors[0]).toContain("type not supported");
  });

  it("validateFiles rejects oversize per-type (text 512KB, image 5MB)", () => {
    const bigLog = validateFiles([], [file("big.log", 600 * 1024)]); // > 512KB text cap
    expect(bigLog.accepted).toEqual([]);
    expect(bigLog.errors[0]).toContain("too large");

    const okImg = validateFiles([], [file("pic.png", 600 * 1024)]); // fine under 5MB
    expect(okImg.accepted).toHaveLength(1);
  });

  it("validateFiles caps total at MAX_ATTACHMENTS across existing + incoming", () => {
    const existing = [file("1.png", 10), file("2.png", 10), file("3.png", 10)];
    const incoming = [file("4.png", 10), file("5.png", 10), file("6.png", 10)];
    const r = validateFiles(existing, incoming);
    expect(r.accepted).toHaveLength(MAX_ATTACHMENTS - existing.length); // 2
    expect(r.errors.some((e) => e.includes("too many"))).toBe(true);
  });

  it("maxSizeForFile classifies by extension (matches backend routing)", () => {
    expect(maxSizeForFile("x.png")).toBe(5 * 1024 * 1024);   // image
    expect(maxSizeForFile("x.pdf")).toBe(5 * 1024 * 1024);   // document
    expect(maxSizeForFile("x.txt")).toBe(5 * 1024 * 1024);   // document server-side, NOT 512KB
    expect(maxSizeForFile("x.csv")).toBe(5 * 1024 * 1024);   // document
    expect(maxSizeForFile("x.log")).toBe(512 * 1024);        // else/text branch
    expect(maxSizeForFile("x.json")).toBe(512 * 1024);       // else/text branch
    expect(maxSizeForFile("x.unknown")).toBe(512 * 1024);    // default → smallest
  });

  it("acceptAttr is a dotted comma list", () => {
    expect(acceptAttr).toContain(".png");
    expect(acceptAttr).toContain(".log");
    expect(acceptAttr.startsWith(".")).toBe(true);
  });

  it("validateFiles dedups against existing selection (name+size), silently", () => {
    const existing = [file("shot.png", 100)];
    const r = validateFiles(existing, [file("shot.png", 100), file("other.png", 100)]);
    expect(r.accepted.map((f) => f.name)).toEqual(["other.png"]); // dup skipped
    expect(r.errors).toEqual([]); // no error noise for dedup
  });

  it("validateFiles dedups within the incoming batch", () => {
    const r = validateFiles([], [file("a.png", 100), file("a.png", 100)]);
    expect(r.accepted).toHaveLength(1);
  });

  it("same name but different size is NOT a duplicate", () => {
    const r = validateFiles([file("a.log", 100)], [file("a.log", 200)]);
    expect(r.accepted).toHaveLength(1);
  });

  it("fileKey combines name and size", () => {
    expect(fileKey(file("x.png", 42))).toBe("x.png:42");
  });
});
