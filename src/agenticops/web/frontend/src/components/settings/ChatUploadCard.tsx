import { useEffect, useMemo, useState } from "react";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useLocale } from "@/i18n/LocaleContext";
import { formatFullDate } from "@/lib/formatDate";
import {
  UploadConfigError, useChatUploadSettings, usePatchChatUpload, useResetChatUpload, type ChatUploadValues,
} from "@/hooks/useChatUploadSettings";

type NumberField = Exclude<keyof ChatUploadValues, "allowed_extensions">;

const GROUPS: { key: string; fields: NumberField[] }[] = [
  { key: "limits", fields: ["max_files", "max_file_mb", "max_total_mb"] },
  { key: "model", fields: ["text_max_chars", "turn_text_max_chars", "image_max_edge_px", "pdf_render_pages_max",
                           "native_media_max_mb"] },
  { key: "history", fields: ["history_text_max_chars", "history_images_max"] },
  { key: "staging", fields: ["staged_ttl_hours"] },
];
const KINDS = ["image", "pdf", "office", "text"] as const;

/** Settings → General → «Chat attachments»: the upload limits in force, editable by admins (audited server-side). */
export function ChatUploadCard() {
  const { t } = useLocale();
  const q = useChatUploadSettings();
  const patch = usePatchChatUpload();
  const reset = useResetChatUpload();
  const [form, setForm] = useState<ChatUploadValues | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  useEffect(() => { if (q.data) setForm(q.data.effective); }, [q.data]);

  const all = useMemo(() => (q.data ? KINDS.flatMap((k) => q.data!.supported[k] ?? []) : []), [q.data]);
  if (q.isLoading) return <Card><CardBody><Spinner /></CardBody></Card>;
  if (q.error) return <Card><CardBody><ErrorBanner message={q.error.message} onRetry={() => q.refetch()} /></CardBody></Card>;
  if (!q.data || !form) return null;

  const s = q.data;
  const editable = s.can_edit;
  const changed = (Object.keys(form) as (keyof ChatUploadValues)[]).filter(
    (k) => JSON.stringify(form[k]) !== JSON.stringify(s.effective[k]));
  const error = patch.error ?? reset.error;
  const badField = error instanceof UploadConfigError ? error.field : "";
  const allowed = form.allowed_extensions ?? all;
  const setAllowed = (exts: string[]) =>
    setForm({ ...form, allowed_extensions: exts.length === all.length ? null : [...exts].sort() });
  const save = () => patch.mutate(Object.fromEntries(changed.map((k) => [k, form[k]])) as Partial<ChatUploadValues>);
  const label = (ext: string) => ext || t("settings.chatUpload.noExtension");

  return (
    <Card>
      <CardHeader>
        <h2 className="text-lg font-semibold text-foreground">{t("settings.chatUpload.title")}</h2>
        <span className="text-xs text-muted-foreground">{t("settings.chatUpload.subtitle")}</span>
      </CardHeader>
      <CardBody>
        {!editable && (
          <p role="status" className="mb-3 rounded-md border border-border bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
            {t("settings.chatUpload.adminOnly")}
          </p>
        )}
        <fieldset disabled={!editable || patch.isPending || reset.isPending} className="m-0 min-w-0 space-y-5 border-0 p-0">
          {GROUPS.map((g) => (
            <section key={g.key}>
              <h3 className="mb-2 text-sm font-medium text-foreground">{t(`settings.chatUpload.group.${g.key}`)}</h3>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {g.fields.map((f) => {
                  const range = s.ranges[f];
                  return (
                    <label key={f} className="block text-xs">
                      <span className="flex items-center gap-1 text-foreground">
                        {t(`settings.chatUpload.field.${f}`)}
                        {s.overridden.includes(f) && (
                          <span title={t("settings.chatUpload.overridden")} className="h-1.5 w-1.5 rounded-full bg-primary" />
                        )}
                      </span>
                      <input type="number" value={form[f]} min={range?.[0]} max={range?.[1]}
                             onChange={(e) => setForm({ ...form, [f]: Number(e.target.value) })}
                             className={`mt-1 w-full rounded border px-2 py-1 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-60 ${
                               badField === f ? "border-red-500" : "border-border"}`} />
                      <span className="text-[11px] text-muted-foreground">
                        {range ? `${range[0]}–${range[1]}` : ""} · {t("settings.chatUpload.default")} {s.defaults[f]}
                      </span>
                      {badField === f && <span className="block text-[11px] text-red-600">{error?.message}</span>}
                    </label>
                  );
                })}
              </div>
            </section>
          ))}
          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-medium text-foreground">
              {t("settings.chatUpload.group.types")}
              {s.overridden.includes("allowed_extensions") && <span className="h-1.5 w-1.5 rounded-full bg-primary" />}
              <label className="ml-auto flex items-center gap-1 text-xs font-normal text-muted-foreground">
                <input type="checkbox" checked={form.allowed_extensions === null}
                       onChange={(e) => setForm({ ...form, allowed_extensions: e.target.checked ? null : [...all].sort() })} />
                {t("settings.chatUpload.allTypes")}
              </label>
            </h3>
            {badField === "allowed_extensions" && <p className="mb-1 text-[11px] text-red-600">{error?.message}</p>}
            <div className="space-y-2">
              {KINDS.map((k) => (
                <div key={k} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                  <span className="w-14 text-muted-foreground">{t(`settings.chatUpload.kind.${k}`)}</span>
                  {(s.supported[k] ?? []).map((ext) => (
                    <label key={ext || "none"} className="flex items-center gap-1 font-mono">
                      <input type="checkbox" checked={allowed.includes(ext)}
                             onChange={(e) => setAllowed(e.target.checked ? [...allowed, ext] : allowed.filter((x) => x !== ext))} />
                      {label(ext)}
                    </label>
                  ))}
                </div>
              ))}
            </div>
          </section>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <button type="button" onClick={save} disabled={changed.length === 0}
                    className="rounded-lg bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
              {t("settings.chatUpload.save")}
            </button>
            <button type="button" onClick={() => setConfirmReset(true)} disabled={s.overridden.length === 0}
                    className="rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-secondary disabled:opacity-50">
              {t("settings.chatUpload.reset")}
            </button>
            {error && !badField && <span className="text-xs text-red-600">{error.message}</span>}
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
        <ConfirmDialog title={t("settings.chatUpload.reset")} message={t("settings.chatUpload.resetConfirm")}
                       confirmText={t("settings.chatUpload.reset")} cancelText={t("common.cancel")}
                       onConfirm={() => { setConfirmReset(false); reset.mutate(); }}
                       onCancel={() => setConfirmReset(false)} />
      )}
    </Card>
  );
}
