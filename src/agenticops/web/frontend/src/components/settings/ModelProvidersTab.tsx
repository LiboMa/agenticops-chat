import { useState } from "react";
import { List, Pencil, PlugZap, Plus, Trash2 } from "lucide-react";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Switch } from "@/components/ui/Switch";
import { IconButton } from "@/components/ui/IconButton";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { useLocale } from "@/i18n/LocaleContext";
import { ApiError } from "@/api/client";
import { formatFullDate } from "@/lib/formatDate";
import { refusalText, settingName } from "@/lib/modelRefs";
import {
  useDeleteProvider, useModelProviders, useSetBedrock, useTestProvider, useUpdateProvider, type ProviderRow,
} from "@/hooks/useModelProviders";
import { ProviderDialog } from "./ProviderDialog";
import { ProviderModelsDialog } from "./ProviderModelsDialog";
import { ProbeSteps } from "./ProbeSteps";

import { fillPlaceholders } from "@/lib/placeholders";
/** Settings → «Model providers» (MVP-2.9.0 N35): Amazon Bedrock (on / off, and what still points at it), then the
 *  providers beyond it — add one from a platform's preset, test it, look through its models, turn it off, delete it.
 *  Only an administrator changes anything here; a reader sees it all and changes nothing (`can_edit`). */
export function ModelProvidersTab() {
  const { t } = useLocale();
  const q = useModelProviders();
  const setBedrock = useSetBedrock();
  const update = useUpdateProvider();
  const remove = useDeleteProvider();
  const test = useTestProvider();
  const { confirm, dialog } = useConfirm();
  const [editing, setEditing] = useState<ProviderRow | "new" | null>(null);
  const [models, setModels] = useState<ProviderRow | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (q.isLoading) return <Card><CardBody><Spinner /></CardBody></Card>;
  if (q.error) return <Card><CardBody><ErrorBanner message={(q.error as Error).message} onRetry={() => q.refetch()} /></CardBody></Card>;
  if (!q.data) return null;
  const page = q.data;
  const canEdit = page.can_edit;
  const fail = (e: unknown) => setError(e instanceof ApiError ? refusalText(t, e) : String(e));
  const names = (refs: string[]) => refs.map((r) => settingName(t, r)).join(", ");

  async function toggleBedrock(on: boolean) {
    setError(null);
    if (!on && page.bedrock.references.length
        && !(await confirm(fillPlaceholders(t("settings.providers.bedrockOffConfirm"), { refs: names(page.bedrock.references) }),
                           { title: t("settings.providers.bedrockOffTitle"), variant: "destructive" }))) return;
    setBedrock.mutate(on, { onError: fail });
  }

  async function toggle(row: ProviderRow, enabled: boolean) {
    setError(null);
    update.mutate({ name: row.name, body: { enabled } }, { onError: fail });
  }

  async function del(row: ProviderRow) {
    setError(null);
    const ok = await confirm(fillPlaceholders(t("settings.providers.deleteConfirm"), { name: row.name, n: String(row.models_count) }),
                             { title: t("settings.providers.deleteTitle"), variant: "destructive", confirmText: t("common.delete") });
    if (ok) remove.mutate(row.name, { onError: fail });
  }

  async function runTest(row: ProviderRow) {
    setError(null);
    setTesting(row.name);
    try { await test.mutateAsync({ name: row.name }); }
    catch (e) { fail(e instanceof ApiError && e.code === "no_model" ? new ApiError(422, t("settings.providers.noModelYet")) : e); }
    finally { setTesting(null); }
  }

  return (
    <div className="space-y-6">
      {dialog}
      <Card>
        <CardHeader>
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-foreground">{t("settings.providers.title")}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{t("settings.providers.subtitle")}</p>
          </div>
        </CardHeader>
        <CardBody className="space-y-4">
          <p className="text-sm text-muted-foreground">{t("settings.providers.dataNotice")}</p>
          {!canEdit && <p className="text-sm text-muted-foreground">{t("settings.providers.adminOnly")}</p>}
          {page.credential_backend === "plaintext" && (
            <p role="note" className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
              {t("settings.providers.plaintext")}
            </p>
          )}
          <div className="flex flex-wrap items-start gap-3 rounded-lg border border-border p-3">
            <Switch checked={page.bedrock.enabled} onCheckedChange={(v) => void toggleBedrock(v)}
                    disabled={!canEdit || setBedrock.isPending} labelledBy="pv-bedrock-name" describedBy="pv-bedrock-desc" />
            <div className="min-w-0 flex-1">
              <p id="pv-bedrock-name" className="text-sm font-semibold text-foreground">{t("settings.providers.bedrock")}</p>
              <p id="pv-bedrock-desc" className="text-xs text-muted-foreground">
                {page.bedrock.enabled
                  ? fillPlaceholders(t("settings.providers.bedrockOn"), { region: page.bedrock.region })
                  : t("settings.providers.bedrockOff")}
              </p>
              {page.bedrock.references.length > 0 && (
                <p className={`mt-1 text-xs ${page.bedrock.enabled ? "text-muted-foreground" : "text-destructive"}`}>
                  {fillPlaceholders((page.bedrock.enabled ? t("settings.providers.bedrockUsedBy") : t("settings.providers.bedrockStillUsedBy")), { refs: names(page.bedrock.references) })}
                </p>
              )}
            </div>
          </div>
          {error && <p role="alert" className="text-sm text-destructive [overflow-wrap:anywhere]">{error}</p>}
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-foreground">{t("settings.providers.others")}</h3>
            {canEdit && (
              <button type="button" onClick={() => setEditing("new")}
                      className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">
                <Plus className="h-4 w-4" aria-hidden />{t("settings.providers.add")}
              </button>
            )}
          </div>
          {page.providers.length === 0 ? (
            <p className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">{t("settings.providers.none")}</p>
          ) : (
            // relative: the screen-reader-only labels inside are absolutely placed — without a positioned box they
            // escape the scroll box and widen the whole page on a phone (N35 E2E: 634 px in a 390 px window)
            <div className="relative overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="whitespace-nowrap py-2 pr-3 font-medium">{t("settings.providers.col.name")}</th>
                    <th className="whitespace-nowrap py-2 pr-3 font-medium">{t("settings.providers.col.address")}</th>
                    <th className="whitespace-nowrap py-2 pr-3 font-medium">{t("settings.providers.col.models")}</th>
                    <th className="whitespace-nowrap py-2 pr-3 font-medium">{t("settings.providers.col.lastTest")}</th>
                    <th className="whitespace-nowrap py-2 pr-3 font-medium">{t("settings.providers.col.enabled")}</th>
                    <th className="py-2 font-medium"><span className="sr-only">{t("settings.providers.col.actions")}</span></th>
                  </tr>
                </thead>
                <tbody>
                  {page.providers.map((row) => (
                    <tr key={row.name} className={`border-b border-border align-top ${row.enabled ? "" : "opacity-60"}`}>
                      <td className="max-w-[16rem] py-2 pr-3">
                        <span className="block font-medium text-foreground">{row.display_name || row.name}</span>
                        <span className="block font-mono text-xs text-muted-foreground">{row.name}</span>
                        <span className="block text-xs text-muted-foreground">{t(`settings.providers.kind.${row.kind}`)}{row.has_api_key ? ` · ${t("settings.providers.hasKey")}` : ""}</span>
                        {row.references.length > 0 && (
                          <span className="mt-0.5 block text-xs text-muted-foreground">{fillPlaceholders(t("settings.providers.usedBy"), { refs: names(row.references) })}</span>
                        )}
                      </td>
                      <td className="min-w-[13rem] max-w-[18rem] py-2 pr-3 font-mono text-xs text-foreground [overflow-wrap:anywhere]">{row.base_url}</td>
                      <td className="py-2 pr-3">
                        <button type="button" onClick={() => setModels(row)} className="text-primary hover:underline">{row.models_count}</button>
                      </td>
                      <td className="min-w-[11rem] py-2 pr-3">
                        {testing === row.name ? <span className="text-xs text-muted-foreground">{t("settings.providers.testing")}</span>
                          : row.last_test ? (
                            <div>
                              <ProbeSteps result={row.last_test} compact />
                              <span className="block text-[11px] text-muted-foreground">{formatFullDate(row.last_test.at)}</span>
                            </div>
                          ) : <span className="text-xs text-muted-foreground">{t("settings.providers.neverTested")}</span>}
                      </td>
                      <td className="py-2 pr-3">
                        <Switch checked={row.enabled} onCheckedChange={(v) => void toggle(row, v)} disabled={!canEdit}
                                label={`${t("settings.providers.enabled")}: ${row.name}`} />
                      </td>
                      <td className="py-2">
                        <div className="flex justify-end gap-1.5">
                          {canEdit && <IconButton label={t("settings.providers.test")} icon={<PlugZap className="h-4 w-4" />}
                                                  onClick={() => void runTest(row)} disabled={testing !== null} />}
                          <IconButton label={t("settings.providers.models")} icon={<List className="h-4 w-4" />} onClick={() => setModels(row)} />
                          {canEdit && <IconButton label={t("common.edit")} icon={<Pencil className="h-4 w-4" />} onClick={() => setEditing(row)} />}
                          {canEdit && <IconButton label={t("common.delete")} icon={<Trash2 className="h-4 w-4" />} tone="danger" onClick={() => void del(row)} />}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardBody>
      </Card>
      {editing && (
        <ProviderDialog presets={page.presets} row={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} />
      )}
      {models && <ProviderModelsDialog provider={models} canEdit={canEdit} onClose={() => setModels(null)} />}
    </div>
  );
}
