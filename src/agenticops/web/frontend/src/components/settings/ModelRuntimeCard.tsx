import { useEffect, useState } from "react";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useLocale } from "@/i18n/LocaleContext";
import { formatFullDate } from "@/lib/formatDate";
import {
  ModelRuntimeError, useModelRuntimeSettings, usePatchModelRuntime, useResetModelRuntime,
} from "@/hooks/useModelRuntimeSettings";

/** Settings → General → «Model connection» (2026-11-08): how long a model may send nothing before its stream is cut.
 *  Admins change it (audited server-side); the next turn of every chat uses it. */
export function ModelRuntimeCard() {
  const { t } = useLocale();
  const q = useModelRuntimeSettings();
  const patch = usePatchModelRuntime();
  const reset = useResetModelRuntime();
  const [value, setValue] = useState<number | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  useEffect(() => { if (q.data) setValue(q.data.effective.stream_read_timeout_seconds); }, [q.data]);

  if (q.isLoading) return <Card><CardBody><Spinner /></CardBody></Card>;
  if (q.error) return <Card><CardBody><ErrorBanner message={q.error.message} onRetry={() => q.refetch()} /></CardBody></Card>;
  if (!q.data || value === null) return null;

  const s = q.data;
  const range = s.ranges.stream_read_timeout_seconds;
  const error = patch.error ?? reset.error;
  const bad = error instanceof ModelRuntimeError && error.field === "stream_read_timeout_seconds";
  const changed = value !== s.effective.stream_read_timeout_seconds;

  return (
    <Card>
      <CardHeader>
        <h2 className="text-lg font-semibold text-foreground">{t("settings.modelRuntime.title")}</h2>
        <span className="text-xs text-muted-foreground">{t("settings.modelRuntime.subtitle")}</span>
      </CardHeader>
      <CardBody>
        {!s.can_edit && (
          <p role="status" className="mb-3 rounded-md border border-border bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
            {t("settings.chatUpload.adminOnly")}
          </p>
        )}
        <fieldset disabled={!s.can_edit || patch.isPending || reset.isPending} className="m-0 min-w-0 space-y-3 border-0 p-0">
          <label className="block max-w-sm text-xs">
            <span className="flex items-center gap-1 text-foreground">
              {t("settings.modelRuntime.readTimeout")}
              {s.overridden.includes("stream_read_timeout_seconds") && (
                <span title={t("settings.chatUpload.overridden")} className="h-1.5 w-1.5 rounded-full bg-primary" />
              )}
            </span>
            <input type="number" value={value} min={range?.[0]} max={range?.[1]}
                   onChange={(e) => setValue(Number(e.target.value))}
                   className={`mt-1 w-full rounded border px-2 py-1 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-60 ${
                     bad ? "border-red-500" : "border-border"}`} />
            <span className="text-[11px] text-muted-foreground">
              {range ? `${range[0]}–${range[1]}` : ""} · {t("settings.chatUpload.default")} {s.defaults.stream_read_timeout_seconds}
            </span>
            {bad && <span className="block text-[11px] text-red-600">{error?.message}</span>}
          </label>
          <p className="text-[11px] text-muted-foreground">{t("settings.modelRuntime.hint")}</p>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <button type="button" onClick={() => patch.mutate({ stream_read_timeout_seconds: value })} disabled={!changed}
                    className="rounded-lg bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
              {t("settings.chatUpload.save")}
            </button>
            <button type="button" onClick={() => setConfirmReset(true)} disabled={s.overridden.length === 0}
                    className="rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-secondary disabled:opacity-50">
              {t("settings.chatUpload.reset")}
            </button>
            {error && !bad && <span className="text-xs text-red-600">{error.message}</span>}
            {s.updated_by && (
              <span className="ml-auto text-[11px] text-muted-foreground">
                {t("settings.chatUpload.updated").replace("{who}", s.updated_by)
                  .replace("{when}", s.updated_at ? formatFullDate(s.updated_at) : "")}
              </span>
            )}
          </div>
        </fieldset>
      </CardBody>
      {confirmReset && (
        <ConfirmDialog title={t("settings.chatUpload.reset")} message={t("settings.modelRuntime.resetConfirm")}
                       confirmText={t("settings.chatUpload.reset")} cancelText={t("common.cancel")}
                       onConfirm={() => { setConfirmReset(false); reset.mutate(); }}
                       onCancel={() => setConfirmReset(false)} />
      )}
    </Card>
  );
}
