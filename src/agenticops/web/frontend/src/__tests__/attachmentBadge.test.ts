import { describe, it, expect } from "vitest";
import { attachmentBadge } from "@/lib/attachmentBadge";

describe("attachmentBadge", () => {
  it("badges by type", () => {
    expect(attachmentBadge("Q3.PDF")).toEqual({ label: "PDF", tone: "pdf" });
    expect(attachmentBadge("m.xlsx").tone).toBe("sheet");
    expect(attachmentBadge("m.csv").tone).toBe("sheet");
    expect(attachmentBadge("a.docx").tone).toBe("doc");
    expect(attachmentBadge("s.pptx").tone).toBe("slide");
    expect(attachmentBadge("x.heic").tone).toBe("image");
    expect(attachmentBadge("app.log").tone).toBe("text");
    expect(attachmentBadge("b.zip").tone).toBe("archive");
    expect(attachmentBadge("setup.exe")).toEqual({ label: "EXE", tone: "other" });
    expect(attachmentBadge("README").label).toBe("FILE");
    expect(attachmentBadge("data.jsonl").label).toBe("JSON");
  });
});
