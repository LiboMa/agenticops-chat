// A message's attachments (2026-11-07): images as a thumbnail grid of fixed squares (the virtualized list keeps its
// row height while they load), other files as cards with how each reached the model.
import type { MessageAttachment } from "@/api/types";
import type { AttachmentDelivery } from "@/lib/chatStream";
import { attachmentReasonText } from "@/lib/attachments";

export const THUMB_PX = 96;
export const GAP_PX = 8;
export const COLS = 3;
export const MAX_THUMBS = 6;

export interface AttachmentLayout {
  images: MessageAttachment[];   // shown as thumbnails (≤ MAX_THUMBS)
  overflow: number;              // more images than shown
  files: MessageAttachment[];
  reservedHeight: number;        // px of the thumbnail grid
}

export function layoutAttachments(items: MessageAttachment[]): AttachmentLayout {
  const images = items.filter((a) => a.id && a.kind === "image");
  const files = items.filter((a) => !(a.id && a.kind === "image"));
  const shown = images.slice(0, MAX_THUMBS);
  const rows = Math.ceil(shown.length / COLS);
  return { images: shown, overflow: images.length - shown.length, files,
           reservedHeight: rows ? rows * THUMB_PX + (rows - 1) * GAP_PX : 0 };
}

/** How the file reached the model, in the user's language; null before the server said. */
export function deliveryLabel(a: MessageAttachment, t: (k: string) => string): string | null {
  const reason = attachmentReasonText(a.reason, t);
  switch (a.delivery) {
    case "native_document":
    case "native_image":
      return t("chat.attach.delivery.native");
    case "text":
    case "page_images": {
      const base = t(a.delivery === "text" ? "chat.attach.delivery.text" : "chat.attach.delivery.pages");
      return reason ? `${base} (${reason})` : base;
    }
    case "notice":
    case "failed":
      return t("chat.attach.delivery.unreadable").replace("{reason}", reason);
    default:
      return null;
  }
}

/** The stream's `attachments` frame labels the message being answered until the history reload brings the stored
 *  labels. */
export function mergeDeliveries(items: MessageAttachment[], live: AttachmentDelivery[]): MessageAttachment[] {
  if (live.length === 0) return items;
  const byId = new Map(live.map((d) => [d.id, d]));
  return items.map((a) => {
    const d = a.id ? byId.get(a.id) : undefined;
    return d ? { ...a, delivery: d.delivery, reason: d.reason } : a;
  });
}
