import { useEffect, useMemo } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import { humanSize, type AttachmentRules } from "@/lib/attachments";
import type { UploadItem } from "@/lib/attachmentUpload";
import { AttachmentCard } from "./AttachmentCard";

interface Props {
  items: UploadItem[];
  rules: AttachmentRules;
  onRemove: (localId: string) => void;
  onRetry: (localId: string) => void;
  /** the thumbnail of an upload restored from a draft (no local file to preview) */
  thumbFor?: (item: UploadItem) => string | undefined;
}

const PREVIEWABLE = /^image\/(png|jpeg|gif|webp|bmp)$/;

/** The composer's attachments above the text box, with how many and how much of the message's allowance. */
export function AttachmentTray({ items, rules, onRemove, onRetry, thumbFor }: Props) {
  const { t } = useLocale();
  // local previews for the images still in this browser (HEIC / TIFF: the server's thumbnail once processed)
  const urls = useMemo(() => {
    const out = new Map<string, string>();
    for (const i of items) if (i.file && PREVIEWABLE.test(i.file.type)) out.set(i.localId, URL.createObjectURL(i.file));
    return out;
  }, [items.map((i) => i.localId).join(",")]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => urls.forEach((u) => URL.revokeObjectURL(u)), [urls]);

  if (items.length === 0) return null;
  const used = items.reduce((sum, i) => sum + i.size, 0);
  return (
    <div className="mx-auto mb-2 max-w-[760px]">
      <div className="flex flex-wrap gap-2">
        {items.map((i) => (
          <AttachmentCard key={i.localId} item={i} thumbUrl={urls.get(i.localId) ?? thumbFor?.(i)}
                          onRemove={() => onRemove(i.localId)} onRetry={() => onRetry(i.localId)} />
        ))}
      </div>
      <div className="mt-1 text-[11px] text-muted-foreground">
        {t("chat.attach.counter").replace("{n}", String(items.length)).replace("{max}", String(rules.max))
          .replace("{used}", humanSize(used)).replace("{total}", humanSize(rules.maxTotalBytes))}
      </div>
    </div>
  );
}
