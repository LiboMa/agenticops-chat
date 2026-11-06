import { useEffect, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useLocale } from "@/i18n/LocaleContext";
import { usePublishReport } from "@/hooks/useNotifications";
import { ApiError } from "@/api/client";
import { destinationOf } from "@/lib/publish";
import type { NotificationChannel, ReportPublishResponse } from "@/api/types";

const FORMATS = ["html", "pdf", "docx", "markdown"] as const;

/** Publish one report version (MVP-2.7.0 S6): the real destination is shown before anything is sent, the version
 *  and language are pinned, and one Idempotency-Key per opening means a repeated click sends once. */
export function PublishDialog({ open, onOpenChange, reportId, version, language, channels }: {
  open: boolean; onOpenChange: (o: boolean) => void; reportId: number; version: number;
  language: "zh" | "en"; channels: NotificationChannel[];
}) {
  const { t } = useLocale();
  const publish = usePublishReport(reportId);
  const [channel, setChannel] = useState(channels[0]?.name ?? "");
  const [formats, setFormats] = useState<string[]>(["html"]);
  const [result, setResult] = useState<ReportPublishResponse | null>(null);
  const key = useRef<string>("");
  useEffect(() => {
    if (open) { key.current = crypto.randomUUID(); setResult(null); publish.reset(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const chosen = channels.find((c) => c.name === channel);
  const destination = destinationOf(chosen);
  const toggle = (f: string) => setFormats((cur) => (cur.includes(f) ? cur.filter((x) => x !== f) : [...cur, f]));
  const send = () => publish.mutate(
    { channel_name: channel, formats, version, language, idempotencyKey: key.current },
    { onSuccess: (r) => setResult(r) });
  const err = publish.error as ApiError | null;
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 grid items-start justify-items-center overflow-y-auto bg-black/30 px-[15px] pt-[10vh]">
          <Dialog.Content className="w-[min(520px,100%)] rounded-lg border border-border bg-card p-5 shadow-xl animate-[slideInRight_0.2s_ease-out]">
            <Dialog.Title className="text-lg font-semibold text-foreground">{t("reports.publish.title")}</Dialog.Title>
            <Dialog.Description className="mt-1 text-sm text-muted-foreground">
              {t("reports.export.what").replace("{ref}", `R#${reportId}`).replace("{version}", String(version))
                .replace("{language}", t(`reports.lang.${language}`))}
            </Dialog.Description>
            {result ? (
              <div className="mt-4 rounded-md border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-800 dark:text-emerald-300">
                <p>{t("reports.publish.done").replace("{destination}", destination)}</p>
                {Object.entries(result.download_urls).map(([f, url]) => (
                  <a key={f} href={url} target="_blank" rel="noopener noreferrer" className="block text-xs underline">{f.toUpperCase()}</a>
                ))}
              </div>
            ) : (
              <>
                <label className="mt-4 block text-xs font-medium text-muted-foreground">{t("reports.publish.channel")}
                  <select value={channel} onChange={(e) => setChannel(e.target.value)}
                          className="mt-1 w-full rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-foreground">
                    {channels.map((c) => <option key={c.name} value={c.name}>{c.name} ({c.channel_type})</option>)}
                  </select>
                </label>
                <div className="mt-3 rounded-md bg-secondary px-3 py-2 text-sm">
                  <span className="text-xs text-muted-foreground">{t("reports.publish.destination")}</span>
                  <p className="break-all font-mono text-xs text-foreground">{destination || t("reports.publish.noDestination")}</p>
                </div>
                <fieldset className="mt-3 flex flex-wrap gap-3">
                  <legend className="mb-1 w-full text-xs font-medium text-muted-foreground">{t("reports.export.format")}</legend>
                  {FORMATS.map((f) => (
                    <label key={f} className="flex items-center gap-1.5 text-sm text-foreground">
                      <input type="checkbox" checked={formats.includes(f)} onChange={() => toggle(f)} />{f.toUpperCase()}
                    </label>
                  ))}
                </fieldset>
                {err && <p role="alert" className="mt-3 text-sm text-red-600 dark:text-red-400">
                  {err.code ? t(`reports.error.${err.code}`) : err.message}</p>}
              </>
            )}
            <div className="mt-5 flex justify-end gap-2">
              <Dialog.Close className="rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent">
                {result ? t("common.close") : t("common.cancel")}
              </Dialog.Close>
              {!result && (
                <button type="button" onClick={send} disabled={!channel || !destination || formats.length === 0 || publish.isPending}
                        className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50">
                  {publish.isPending ? t("reports.publish.sending") : t("reports.publish.confirm")}
                </button>
              )}
            </div>
          </Dialog.Content>
        </Dialog.Overlay>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
