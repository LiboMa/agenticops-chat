import { useLocale } from "@/i18n/LocaleContext";
import { attachmentReasonText, humanSize } from "@/lib/attachments";
import type { UploadItem } from "@/lib/attachmentUpload";
import { BADGE_CLASS, attachmentBadge } from "@/lib/attachmentBadge";

/** A file the composer refused (type, size, count or total): shown in the box with the reason until removed. */
export interface RejectedFile { key: string; name: string; text: string }

interface Props {
  item?: UploadItem;
  rejected?: RejectedFile;
  /** the image's preview: the local file's object URL, or the server's thumbnail */
  thumbUrl?: string;
  onRemove: () => void;
  onRetry?: () => void;
  onOpen?: () => void;
}

const REMOVE = "flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px]";

/** One attachment inside the composer (2026-11-07): an image as a square thumbnail with its upload ring, a document
 *  as a card with its type colour and where it stands, a refused file in red with the reason. */
export function ComposerAttachment({ item, rejected, thumbUrl, onRemove, onRetry, onOpen }: Props) {
  const { t } = useLocale();
  const name = item?.name ?? rejected?.name ?? "";
  const badge = attachmentBadge(name);

  if (rejected) {
    return (
      <div className="flex min-w-[150px] max-w-[240px] shrink-0 items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-2.5 py-1.5 dark:border-red-900 dark:bg-red-950/40"
           title={rejected.text}>
        <span className="flex h-9 w-7 shrink-0 items-center justify-center rounded-md bg-gray-400 text-[9px] font-bold text-white">{badge.label}</span>
        <div className="min-w-0 flex-1 leading-tight">
          <div className="truncate text-[13px] font-medium text-red-800 dark:text-red-300">{name}</div>
          <div className="truncate text-[11px] text-red-700 dark:text-red-400">{rejected.text}</div>
        </div>
        <button type="button" onClick={onRemove} aria-label={t("chat.attach.remove")} title={t("chat.attach.remove")}
                className={`${REMOVE} text-red-700 hover:bg-red-100 dark:text-red-400 dark:hover:bg-red-900/40`}>✕</button>
      </div>
    );
  }
  if (!item) return null;

  const failed = item.state === "failed";
  const busy = item.state === "queued" || item.state === "uploading" || item.state === "processing";
  const reason = failed ? attachmentReasonText(item.reason, t) || t("chat.attach.failed") : "";

  if (item.kind === "image" && (thumbUrl || busy || failed)) {
    const pct = item.state === "uploading" ? item.progress : 0;
    return (
      <div className={`group relative h-[60px] w-[60px] shrink-0 overflow-hidden rounded-xl border ${failed ? "border-red-400" : "border-border"} bg-muted`}
           title={failed ? `${name} — ${reason}` : name}>
        {thumbUrl
          ? <button type="button" onClick={onOpen} disabled={!onOpen || item.state !== "ready"} className="h-full w-full disabled:cursor-default"
                    aria-label={t("chat.attach.preview")}>
              <img src={thumbUrl} alt="" className="h-full w-full object-cover" />
            </button>
          : <span className="flex h-full w-full items-center justify-center text-[10px] font-semibold text-muted-foreground">{badge.label}</span>}
        {busy && (
          <span className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/35" aria-hidden>
            <svg width="28" height="28" viewBox="0 0 36 36" className={item.state === "uploading" ? "" : "animate-spin"}>
              <circle cx="18" cy="18" r="15" fill="none" stroke="rgba(255,255,255,.35)" strokeWidth="3" />
              <circle cx="18" cy="18" r="15" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round"
                      strokeDasharray="94.2" strokeDashoffset={item.state === "uploading" ? 94.2 * (1 - pct / 100) : 66}
                      transform="rotate(-90 18 18)" />
            </svg>
          </span>
        )}
        {failed && (
          <span className="absolute inset-x-0 bottom-0 bg-red-600/85 px-1 py-0.5 text-center text-[10px] text-white">
            {onRetry && item.file
              ? <button type="button" onClick={onRetry} className="underline">{t("chat.attach.retry")}</button>
              : t("chat.attach.failed")}
          </span>
        )}
        <button type="button" onClick={onRemove} aria-label={t("chat.attach.remove")} title={t("chat.attach.remove")}
                className={`${REMOVE} absolute right-1 top-1 bg-gray-900/80 text-white opacity-0 group-hover:opacity-100 focus:opacity-100 [@media(pointer:coarse)]:opacity-100`}>✕</button>
      </div>
    );
  }

  const pages = typeof item.meta?.pages === "number" ? (item.meta.pages as number) : null;
  const status = item.state === "uploading" ? t("chat.attach.uploading").replace("{p}", String(item.progress))
    : item.state === "queued" ? t("chat.attach.queued")
    : item.state === "processing" ? t("chat.attach.processing")
    : failed ? reason
    : pages ? `${t("chat.attach.pages").replace("{n}", String(pages))} · ${humanSize(item.size)}`
    : humanSize(item.size);
  return (
    <div className={`flex min-w-[150px] max-w-[240px] shrink-0 items-center gap-2 rounded-xl border px-2.5 py-1.5 ${
      failed ? "border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/40" : "border-border bg-background"}`} title={name}>
      <span className={`flex h-9 w-7 shrink-0 items-center justify-center rounded-md text-[9px] font-bold text-white ${BADGE_CLASS[badge.tone]}`}>
        {badge.label}
      </span>
      <div className="min-w-0 flex-1 leading-tight">
        <div className="truncate text-[13px] font-medium text-foreground">{name}</div>
        <div className={`truncate text-[11px] ${failed ? "text-red-700 dark:text-red-400" : "text-muted-foreground"}`}>{status}</div>
      </div>
      {failed && onRetry && item.file && (
        <button type="button" onClick={onRetry} className="shrink-0 text-[11px] text-primary hover:underline">{t("chat.attach.retry")}</button>
      )}
      <button type="button" onClick={onRemove} aria-label={t("chat.attach.remove")} title={t("chat.attach.remove")}
              className={`${REMOVE} text-muted-foreground hover:bg-muted hover:text-foreground`}>✕</button>
    </div>
  );
}
