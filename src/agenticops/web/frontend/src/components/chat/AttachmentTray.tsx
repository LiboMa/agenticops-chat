import { useLocale } from "@/i18n/LocaleContext";
import { humanSize, type AttachmentRules } from "@/lib/attachments";
import type { UploadItem } from "@/lib/attachmentUpload";
import { localPreviewUrl } from "@/hooks/useAttachmentBlob";
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
  // local previews of the images still in this browser (HEIC / TIFF: the server's thumbnail once processed); kept
  // by item id in one registry, so the sent message shows the same picture before the server's copy loads
  const urlFor = (i: UploadItem) => (i.file && PREVIEWABLE.test(i.file.type) ? localPreviewUrl(i.localId, i.file) : undefined);

  if (items.length === 0) return null;
  const used = items.reduce((sum, i) => sum + i.size, 0);
  return (
    <div className="mx-auto mb-2 max-w-[760px]">
      <div className="flex flex-wrap gap-2">
        {items.map((i) => (
          <AttachmentCard key={i.localId} item={i} thumbUrl={urlFor(i) ?? thumbFor?.(i)}
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
