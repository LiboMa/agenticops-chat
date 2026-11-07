import { describe, it, expect } from "vitest";
import en from "@/locales/en.json";
import zh from "@/locales/zh.json";
import { deliveryLabel, layoutAttachments, mergeDeliveries, THUMB_PX, GAP_PX } from "@/lib/messageAttachments";
import type { MessageAttachment } from "@/api/types";

const img = (id: string): MessageAttachment => ({ id, filename: `${id}.png`, size: 1, kind: "image" });
const doc = (id: string): MessageAttachment => ({ id, filename: `${id}.pdf`, size: 1, kind: "pdf" });

// every reason the server's delivery (chat/attachments/delivery.py) and processing can report
const REASONS = ["model_text_only", "model_no_documents", "model_no_images", "document_quota", "document_too_large",
  "image_quota", "media_budget", "text_budget", "scanned_needs_vision", "claude_only_format", "processing_failed",
  "file_missing", "encrypted", "archive_too_large", "image_too_large", "undecodable", "corrupt", "timeout",
  "worker_crashed", "unreadable", "unsupported_type", "not_found", "file_too_large", "content_mismatch", "binary_text"];

describe("message attachments (2026-11-07)", () => {
  it("reserves height for image grid", () => {
    expect(layoutAttachments([]).reservedHeight).toBe(0);
    expect(layoutAttachments([img("a")]).reservedHeight).toBe(THUMB_PX);
    const four = layoutAttachments([img("a"), img("b"), img("c"), img("d"), doc("e")]);
    expect(four.images.map((i) => i.id)).toEqual(["a", "b", "c", "d"]);
    expect(four.files.map((i) => i.id)).toEqual(["e"]);
    expect(four.reservedHeight).toBe(2 * THUMB_PX + GAP_PX);
    const many = layoutAttachments(Array.from({ length: 9 }, (_, i) => img(`i${i}`)));
    expect(many.images).toHaveLength(6);
    expect(many.overflow).toBe(3);
    expect(many.reservedHeight).toBe(2 * THUMB_PX + GAP_PX);
  });

  it("legacy attachments without id are files", () => {
    const out = layoutAttachments([{ filename: "old.png", size: 3 }, { filename: "old.txt", size: 3 }]);
    expect(out.images).toEqual([]);
    expect(out.files.map((f) => f.filename)).toEqual(["old.png", "old.txt"]);
  });

  it("delivery badge text per reason", () => {
    const t = (k: string) => (en as Record<string, string>)[k] ?? k;
    expect(deliveryLabel({ ...doc("a"), delivery: "native_document" }, t)).toBe(en["chat.attach.delivery.native"]);
    expect(deliveryLabel({ ...doc("a"), delivery: "text" }, t)).toBe(en["chat.attach.delivery.text"]);
    expect(deliveryLabel({ ...doc("a"), delivery: "text", reason: "document_quota" }, t))
      .toBe(`${en["chat.attach.delivery.text"]} (${en["chat.attach.reason.document_quota"]})`);
    expect(deliveryLabel({ ...doc("a"), delivery: "page_images", reason: "model_no_documents" }, t))
      .toContain(en["chat.attach.delivery.pages"]);
    expect(deliveryLabel({ ...doc("a") }, t)).toBeNull();
    for (const code of REASONS) {
      const label = deliveryLabel({ ...doc("a"), delivery: "notice", reason: code }, t)!;
      expect(label).toContain((en as Record<string, string>)[`chat.attach.reason.${code}`]);
    }
  });

  it("every reason code the server can send has an English and a Chinese text", () => {
    for (const code of REASONS) {
      expect((en as Record<string, string>)[`chat.attach.reason.${code}`], code).toBeTruthy();
      expect((zh as Record<string, string>)[`chat.attach.reason.${code}`], code).toBeTruthy();
    }
  });

  it("live deliveries from the stream label the message being answered", () => {
    const merged = mergeDeliveries([doc("a"), { filename: "legacy.txt", size: 1 }],
                                   [{ id: "a", filename: "a.pdf", delivery: "text", reason: "model_no_documents" }]);
    expect(merged[0]).toMatchObject({ id: "a", delivery: "text", reason: "model_no_documents" });
    expect(merged[1]).toEqual({ filename: "legacy.txt", size: 1 });
  });
});
