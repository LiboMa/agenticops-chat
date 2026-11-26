import { useId, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useLocale } from "@/i18n/LocaleContext";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ModalFrame } from "@/components/ui/ModalFrame";
import { StatusText } from "@/components/ui/StatusText";
import { Switch } from "@/components/ui/Switch";
import { useBootstrap } from "@/hooks/useBootstrap";
import { useUpdateSettings, type AppSettings } from "@/hooks/useSettings";
import { formatShortDate } from "@/lib/formatDate";
import { HIGH_IMPACT, canEditHigh, heldVar, highKeys, pending, shown, sourceOf, stage, type HighKey, type Staged } from "@/lib/settingsPage";

import { fillPlaceholders } from "@/lib/placeholders";
type T = (key: string) => string;
const onOff = (t: T, on: boolean) => t(on ? "settings.high.on" : "settings.high.off");

/** The six high-impact switches (MVP-2.9.0 N25 — the 2.8.0 spec's S8, R18): the executor, the auto-fix pipeline,
 *  L0 / L1 auto-approval, the executor's step-by-step confirmation, standard-change auto-approval, permission
 *  enforcement. A click only STAGES a value; «preview and save» lists each change — from → to, and what it affects —
 *  and one confirmation saves them in one request. Each row says the value in force and where it comes from. With
 *  sign-in on, only an administrator changes them (the server's rule; here the switches are just disabled). */
export function AutomationCard({ s }: { s: AppSettings }) {
  const { t } = useLocale();
  const boot = useBootstrap();
  const update = useUpdateSettings();
  const qc = useQueryClient();
  const [staged, setStaged] = useState<Staged>({});
  const [preview, setPreview] = useState(false);
  const [saved, setSaved] = useState(false);
  const id = useId();

  const keys = highKeys(s);
  const inForce = Object.fromEntries(HIGH_IMPACT.map((key) => [key, s[key] === true])) as Record<HighKey, boolean>;
  const changes = pending(inForce, staged, keys);
  const canEdit = canEditHigh(boot.data);
  const info = s.execution_switches;

  const click = (key: HighKey, value: boolean) => { setSaved(false); update.reset(); setStaged((now) => stage(inForce, now, key, value, info)); };
  const save = () => update.mutate(Object.fromEntries(changes.map((c) => [c.key, c.to])), {
    onSuccess: () => { setStaged({}); setPreview(false); setSaved(true); },
    // a request that failed part-way may have saved some of it: read what is in force again
    onError: () => void qc.invalidateQueries({ queryKey: ["settings"] }),
  });

  return (
    <Card>
      <CardHeader className="flex-wrap gap-2">
        <h3 className="text-lg font-semibold text-foreground">{t("settings.high.title")}</h3>
        <span className="text-xs text-muted-foreground">{t("settings.high.subtitle")}</span>
      </CardHeader>
      <CardBody>
        {!canEdit && <p role="status" className="mb-2 text-xs text-status-warn">{t("settings.high.adminOnly")}</p>}
        <div>
          {keys.map((key) => {
            const source = sourceOf(key, info);
            const held = heldVar(key, info);                 // this process's environment holds it: not changeable here
            const waiting = staged[key] !== undefined && staged[key] !== inForce[key];
            return (
              <div key={key} className="flex items-start justify-between gap-4 border-b border-border/50 py-3 last:border-b-0">
                <div className="min-w-0">
                  <span id={`${id}-${key}-name`} className="text-sm font-medium text-foreground">{t(`settings.high.${key}`)}</span>
                  <p id={`${id}-${key}-desc`} className="mt-0.5 text-xs text-muted-foreground">{t(`settings.high.${key}.desc`)}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">{t("settings.high.affects")}</span> {t(`settings.high.${key}.affects`)}
                  </p>
                  <p className="mt-1 flex flex-wrap items-center gap-x-2 text-xs">
                    <StatusText tone={inForce[key] ? "ok" : "neutral"} className="text-xs">
                      {t("settings.high.inForce")}{onOff(t, inForce[key])}
                    </StatusText>
                    <span className={held ? "text-status-warn" : "text-muted-foreground"}>{fillPlaceholders(t(`settings.high.source.${source}`), { var: held ?? "" })}</span>
                    {waiting && <StatusText tone="warn" className="text-xs">{fillPlaceholders(t("settings.high.staged"), { value: onOff(t, staged[key] as boolean) })}</StatusText>}
                  </p>
                </div>
                <Switch checked={shown(inForce, staged, key)} onCheckedChange={(v) => click(key, v)} disabled={!canEdit || update.isPending || held !== null}
                        labelledBy={`${id}-${key}-name`} describedBy={`${id}-${key}-desc`} />
              </div>
            );
          })}
        </div>

        {info?.updated_at && (
          <p className="mt-3 text-xs text-muted-foreground">
            {fillPlaceholders(t("settings.high.lastChange"), { time: formatShortDate(info.updated_at), by: (info.updated_by ?? "—").replace(/^user:/, "") })}
          </p>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-2" role="status">
          {changes.length > 0 ? (
            <>
              <span className="text-sm text-status-warn">{fillPlaceholders(t("settings.high.pending"), { n: String(changes.length) })}</span>
              <button type="button" onClick={() => setPreview(true)}
                      className="min-h-[44px] rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary-hover sm:min-h-9">
                {t("settings.high.preview")}
              </button>
              <button type="button" onClick={() => setStaged({})}
                      className="min-h-[44px] rounded-md border border-border px-3 text-sm text-foreground hover:bg-accent sm:min-h-9">
                {t("settings.high.discard")}
              </button>
            </>
          ) : saved ? <StatusText tone="ok" className="text-sm">{t("settings.high.saved")}</StatusText> : null}
        </div>
      </CardBody>

      {preview && (
        <ModalFrame title={t("settings.high.preview")} onClose={() => setPreview(false)} width="w-[min(560px,100%)]">
          <p className="mt-2 text-sm text-muted-foreground">{t("settings.high.previewIntro")}</p>
          <ul className="mt-3 space-y-3">
            {changes.map((c) => (
              <li key={c.key} className="rounded-md border border-border bg-background p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-sm font-medium text-foreground">{t(`settings.high.${c.key}`)}</span>
                  <span className="font-mono text-sm text-foreground">{onOff(t, c.from)} → <strong>{onOff(t, c.to)}</strong></span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">{t("settings.high.affects")}</span> {t(`settings.high.${c.key}.affects`)}
                </p>
                <p className="mt-0.5 text-xs text-muted-foreground">{t(`settings.high.${c.key}.${c.to ? "onMeans" : "offMeans"}`)}</p>
              </li>
            ))}
          </ul>
          {update.isError && <p role="alert" className="mt-3 text-sm text-status-danger">{t("settings.high.failed")} {update.error instanceof Error ? update.error.message : ""}</p>}
          <div className="mt-4 flex flex-wrap justify-end gap-2 border-t border-border pt-3">
            <button type="button" onClick={() => setPreview(false)}
                    className="min-h-[44px] rounded-md border border-border px-3 text-sm text-foreground hover:bg-accent sm:min-h-9">{t("common.cancel")}</button>
            <button type="button" onClick={save} disabled={update.isPending || changes.length === 0}
                    className="min-h-[44px] rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-60 sm:min-h-9">
              {update.isPending ? t("settings.high.saving") : fillPlaceholders(t("settings.high.confirm"), { n: String(changes.length) })}
            </button>
          </div>
        </ModalFrame>
      )}
    </Card>
  );
}
