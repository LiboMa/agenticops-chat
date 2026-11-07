import { useEffect, useRef } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import { apiDownload } from "@/api/client";
import { saveBlob } from "@/lib/download";
import { useAttachmentBlob } from "@/hooks/useAttachmentBlob";

export interface LightboxImage { id: string; filename: string }

interface Props {
  images: LightboxImage[];
  index: number;
  onIndex: (i: number) => void;
  onClose: () => void;
}

/** A sent image at full size (house rule: slides in, ESC closes); ←/→ step through the message's images. */
export function ImageLightbox({ images, index, onIndex, onClose }: Props) {
  const { t } = useLocale();
  const current = images[index];
  const { url } = useAttachmentBlob(current?.id, "preview");
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    box.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowLeft" && index > 0) onIndex(index - 1);
      else if (e.key === "ArrowRight" && index < images.length - 1) onIndex(index + 1);
      else if (e.key === "Tab" && box.current) {   // keep focus inside the dialog
        const focusable = box.current.querySelectorAll<HTMLElement>("button:not([disabled])");
        if (focusable.length === 0) return;
        const first = focusable[0], last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, images.length, onClose, onIndex]);

  if (!current) return null;
  const download = async () => {
    const { blob, filename } = await apiDownload(`/chat/attachments/${current.id}/content?variant=original`);
    saveBlob(blob, filename ?? current.filename);
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70" onClick={onClose}>
      <div ref={box} tabIndex={-1} role="dialog" aria-modal="true" aria-label={current.filename}
           onClick={(e) => e.stopPropagation()}
           className="relative flex max-h-[90vh] max-w-[90vw] flex-col rounded-lg bg-background p-3 shadow-xl outline-none animate-[slideInRight_0.2s_ease-out]">
        <div className="mb-2 flex items-center gap-2 text-sm">
          <span className="min-w-0 flex-1 truncate font-medium text-foreground">{current.filename}</span>
          <span className="text-xs text-muted-foreground">{index + 1}/{images.length}</span>
          <button type="button" onClick={() => void download()} className="rounded px-2 py-1 text-primary hover:bg-muted">
            {t("chat.attach.download")}
          </button>
          <button type="button" onClick={onClose} aria-label={t("chat.attach.close")}
                  className="rounded px-2 py-1 text-muted-foreground hover:bg-muted">✕</button>
        </div>
        <div className="relative flex min-h-[200px] min-w-[300px] items-center justify-center">
          {url ? <img src={url} alt={current.filename} className="max-h-[78vh] max-w-[86vw] object-contain" />
            : <span className="text-sm text-muted-foreground">…</span>}
          {index > 0 && (
            <button type="button" onClick={() => onIndex(index - 1)} aria-label={t("chat.attach.previous")}
                    className="absolute left-1 rounded-full bg-black/40 px-3 py-2 text-white hover:bg-black/60">‹</button>
          )}
          {index < images.length - 1 && (
            <button type="button" onClick={() => onIndex(index + 1)} aria-label={t("chat.attach.next")}
                    className="absolute right-1 rounded-full bg-black/40 px-3 py-2 text-white hover:bg-black/60">›</button>
          )}
        </div>
      </div>
    </div>
  );
}
