import { useLocale } from "@/i18n/LocaleContext";
import { attachmentReasonText, extOf, humanSize } from "@/lib/attachments";
import type { UploadItem } from "@/lib/attachmentUpload";

interface Props {
  item: UploadItem;
  /** an image preview: the local file's object URL, or the server's thumbnail */
  thumbUrl?: string;
  onRemove?: () => void;
  onRetry?: () => void;
}

/** One attachment in the composer: thumbnail or type badge, name, size, and where its upload stands. */
export function AttachmentCard({ item, thumbUrl, onRemove, onRetry }: Props) {
  const { t } = useLocale();
  const label = (extOf(item.name).slice(1) || "file").toUpperCase().slice(0, 4);
  const failed = item.state === "failed";
  const status = item.state === "uploading" ? t("chat.attach.uploading").replace("{p}", String(item.progress))
    : item.state === "queued" ? t("chat.attach.queued")
    : item.state === "processing" ? t("chat.attach.processing")
    : failed ? attachmentReasonText(item.reason, t) || t("chat.attach.failed")
    : t("chat.attach.ready");
  return (
    <div
      className={`relative flex w-56 items-center gap-2 rounded-lg border bg-background px-2 py-1.5 text-xs ${
        failed ? "border-red-300 dark:border-red-800" : "border-border"}`}
      title={item.name}
    >
      <div className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-md bg-muted">
        {thumbUrl ? <img src={thumbUrl} alt="" className="h-full w-full object-cover" />
          : <span className="font-semibold text-[10px] text-muted-foreground">{label}</span>}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium text-foreground">{item.name}</div>
        <div className={`truncate ${failed ? "text-red-600 dark:text-red-400" : "text-muted-foreground"}`}>
          {humanSize(item.size)} · {status}
        </div>
        {item.state === "uploading" && (
          <div className="mt-1 h-1 w-full overflow-hidden rounded bg-muted" aria-hidden>
            <div className="h-full bg-primary transition-[width]" style={{ width: `${item.progress}%` }} />
          </div>
        )}
      </div>
      {failed && onRetry && item.file && (
        <button type="button" onClick={onRetry} className="shrink-0 text-primary hover:underline">
          {t("chat.attach.retry")}
        </button>
      )}
      {onRemove && (
        <button type="button" onClick={onRemove} aria-label={t("chat.attach.remove")} title={t("chat.attach.remove")}
                className="shrink-0 px-1 text-muted-foreground hover:text-red-500">✕</button>
      )}
    </div>
  );
}
