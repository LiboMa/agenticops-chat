import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useLocale } from "@/i18n/LocaleContext";
import { useBootstrap } from "@/hooks/useBootstrap";
import { ApiError, apiDownload } from "@/api/client";
import { saveBlob } from "@/lib/download";

const FORMATS = ["html", "pdf", "docx"] as const;

/** Export one report version (MVP-2.7.0 S6): the language is what the page shows; formats the server cannot make
 *  are greyed out. An authenticated download — the token never goes in a URL. Never publishes. */
export function ExportDialog({ open, onOpenChange, reportId, version, language }: {
  open: boolean; onOpenChange: (o: boolean) => void; reportId: number; version: number; language: "zh" | "en" | "zh-en";
}) {
  const { t } = useLocale();
  const available = useBootstrap().data?.report_export_formats ?? ["html"];
  const [format, setFormat] = useState<(typeof FORMATS)[number]>("html");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const download = async () => {
    setBusy(true); setError(null);
    try {
      const { blob, filename } = await apiDownload(`/reports/${reportId}/export?version=${version}&language=${language}&format=${format}`);
      saveBlob(blob, filename ?? `AgenticOps_R${reportId}_v${version}_${language}.${format}`);
      onOpenChange(false);
    } catch (e) {
      setError(e instanceof ApiError && e.code ? t(`reports.error.${e.code}`) : String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 grid items-start justify-items-center overflow-y-auto bg-black/30 px-[15px] pt-[12vh]">
          <Dialog.Content className="w-[min(440px,100%)] rounded-lg border border-border bg-card p-5 shadow-xl animate-[slideInRight_0.2s_ease-out]">
            <Dialog.Title className="text-lg font-semibold text-foreground">{t("reports.export.title")}</Dialog.Title>
            <Dialog.Description className="mt-1 text-sm text-muted-foreground">
              {t("reports.export.what").replace("{ref}", `R#${reportId}`).replace("{version}", String(version))
                .replace("{language}", t(`reports.lang.${language}`))}
            </Dialog.Description>
            <fieldset className="mt-4 space-y-1.5">
              <legend className="mb-1 text-xs font-medium text-muted-foreground">{t("reports.export.format")}</legend>
              {FORMATS.map((f) => {
                const ok = available.includes(f);
                return (
                  <label key={f} className={`flex items-center gap-2 text-sm ${ok ? "text-foreground" : "text-muted-foreground/60"}`}>
                    <input type="radio" name="format" value={f} checked={format === f} disabled={!ok} onChange={() => setFormat(f)} />
                    {f.toUpperCase()} {!ok && <span className="text-xs">· {t("reports.export.unavailable")}</span>}
                  </label>
                );
              })}
            </fieldset>
            {error && <p role="alert" className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
            <div className="mt-5 flex justify-end gap-2">
              <Dialog.Close className="rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent">{t("common.cancel")}</Dialog.Close>
              <button type="button" onClick={download} disabled={busy}
                      className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50">
                {busy ? t("common.loading") : t("reports.export.download")}
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Overlay>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
