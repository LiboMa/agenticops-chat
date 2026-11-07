import { useState } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import { apiDownload } from "@/api/client";
import type { MessageAttachment } from "@/api/types";
import { extOf, humanSize } from "@/lib/attachments";
import { saveBlob } from "@/lib/download";
import { deliveryLabel, layoutAttachments, THUMB_PX, GAP_PX, COLS } from "@/lib/messageAttachments";
import { localPreview, useAttachmentBlob } from "@/hooks/useAttachmentBlob";
import { ImageLightbox } from "./ImageLightbox";

type Item = MessageAttachment & { localId?: string };

function Thumb({ item, onOpen, extra }: { item: Item; onOpen: () => void; extra?: number }) {
  const { url } = useAttachmentBlob(item.id, "thumb");
  const src = url ?? localPreview(item.localId);
  return (
    <button type="button" onClick={onOpen} title={item.filename}
            style={{ width: THUMB_PX, height: THUMB_PX }}
            className="relative overflow-hidden rounded-lg border border-primary-100 bg-muted">
      {src ? <img src={src} alt={item.filename} className="h-full w-full object-cover" />
        : <span className="text-[10px] text-muted-foreground">{(extOf(item.filename).slice(1) || "img").toUpperCase()}</span>}
      {extra ? <span className="absolute inset-0 flex items-center justify-center bg-black/50 text-sm font-semibold text-white">+{extra}</span> : null}
    </button>
  );
}

/** A message's attachments: a thumbnail grid (click → full size), and file cards (click → download). */
export function MessageAttachments({ attachments }: { attachments: Item[] }) {
  const { t } = useLocale();
  const [open, setOpen] = useState<number | null>(null);
  const { images, overflow, files, reservedHeight } = layoutAttachments(attachments);
  const allImages = attachments.filter((a) => a.id && a.kind === "image").map((a) => ({ id: a.id!, filename: a.filename }));
  const download = async (a: Item) => {
    const { blob, filename } = await apiDownload(`/chat/attachments/${a.id}/content?variant=original`);
    saveBlob(blob, filename ?? a.filename);
  };
  return (
    <div className="mb-1 space-y-1.5">
      {images.length > 0 && (
        <div className="grid" style={{ gridTemplateColumns: `repeat(${Math.min(COLS, images.length)}, ${THUMB_PX}px)`,
                                       gap: GAP_PX, height: reservedHeight }}>
          {images.map((img, i) => (
            <Thumb key={img.id} item={img} onOpen={() => setOpen(i)}
                   extra={i === images.length - 1 && overflow > 0 ? overflow : undefined} />
          ))}
        </div>
      )}
      {files.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {files.map((a, i) => {
            const label = deliveryLabel(a, t);
            const notice = a.delivery === "notice" || a.delivery === "failed";
            const body = (
              <>
                <span className="font-semibold text-[10px] text-primary-600">{(extOf(a.filename).slice(1) || "file").toUpperCase().slice(0, 4)}</span>
                <span className="truncate max-w-[14rem]">{a.filename}</span>
                <span className="text-primary-400">{humanSize(a.size)}</span>
                {label && <span className={`rounded px-1 ${notice ? "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
                  : "bg-primary-100 text-primary-700"}`}>{label}</span>}
              </>
            );
            const cls = "inline-flex items-center gap-1.5 rounded-lg border border-primary-100 bg-background px-2 py-1 text-xs";
            return a.id
              ? <button key={a.id} type="button" onClick={() => void download(a)} title={t("chat.attach.download")}
                        className={`${cls} hover:border-primary-300`}>{body}</button>
              : <span key={`${a.filename}-${i}`} className={cls}>{body}</span>;
          })}
        </div>
      )}
      {images.some((i) => i.delivery) && (
        <div className="text-[11px] text-primary-500">
          {[...new Set(images.map((i) => deliveryLabel(i, t)).filter(Boolean))].join(" · ")}
        </div>
      )}
      {open !== null && (
        <ImageLightbox images={allImages} index={open} onIndex={setOpen} onClose={() => setOpen(null)} />
      )}
    </div>
  );
}
