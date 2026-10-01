/**
 * Pull connectors (MVP-2.6.1 spec §3.E.5): each connector's switch, whether it is running, its discovery
 * schedule, the newest runs with their counts, and a Run-now button (POST /api/connectors/{name}/run).
 * The switch itself lives in config/settings.yaml — the card shows it, it does not flip it.
 */
import { useEffect, useRef } from "react";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { Badge } from "@/components/ui/Badge";
import { useConnectors, useRunConnector } from "@/hooks/useConnectors";
import { useLocale } from "@/i18n/LocaleContext";
import { COUNT_KEYS, countParts, runBlocker } from "@/lib/connectors";
import { formatShortDate } from "@/lib/formatDate";
import type { ConnectorRunStatus, ConnectorStatus } from "@/api/types";

const KNOWN_COUNTS: readonly string[] = COUNT_KEYS;

const RUN_BADGE: Record<ConnectorRunStatus, string> = {
  complete: "bg-green-100 text-green-700",
  partial: "bg-amber-100 text-amber-700",
  failed: "bg-red-100 text-red-700",
};

export function ConnectorsCard() {
  const { t } = useLocale();
  const q = useConnectors();

  return (
    <Card>
      <CardHeader>
        <h2 className="text-lg font-semibold text-foreground">{t("connectors.title")}</h2>
        <span className="text-xs text-muted-foreground">{t("connectors.subtitle")}</span>
      </CardHeader>
      <CardBody>
        {q.isLoading ? <Spinner />
          : q.error ? <ErrorBanner message={(q.error as Error).message} onRetry={() => q.refetch()} />
          : <div className="space-y-6">{q.data?.connectors.map((c) => <ConnectorRow key={c.name} c={c} />)}</div>}
      </CardBody>
    </Card>
  );
}

function ConnectorRow({ c }: { c: ConnectorStatus }) {
  const { t } = useLocale();
  const run = useRunConnector();
  const blocker = runBlocker(c);
  const { reset } = run;
  const wasRunning = useRef(c.running);

  // A run that has finished retires this row's "accepted" line and any 409 it caused.
  useEffect(() => {
    if (wasRunning.current && !c.running) reset();
    wasRunning.current = c.running;
  }, [c.running, reset]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-foreground">{c.name}</span>
        <Badge className={c.enabled ? "bg-green-100 text-green-700" : "bg-secondary text-muted-foreground"}>
          {t(c.enabled ? "connectors.on" : "connectors.off")}
        </Badge>
        {c.running && <Badge className="bg-blue-100 text-blue-700">{t("connectors.running")}</Badge>}
        <span className="text-xs text-muted-foreground">
          {t("connectors.schedule")}:{" "}
          {c.schedule
            ? <><code>{c.schedule.cron_expression}</code> · {t(c.schedule.is_enabled ? "connectors.on" : "connectors.off")}</>
            : t("connectors.noSchedule")}
        </span>
        <button
          className="ml-auto px-3 py-1.5 text-xs rounded-md bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
          disabled={blocker != null || run.isPending}
          title={blocker ? t(`connectors.blocked.${blocker}`) : undefined}
          onClick={() => run.mutate(c.name)}
        >
          {t("connectors.runNow")}
        </button>
      </div>
      {!c.enabled && <p className="text-xs text-muted-foreground">{t("connectors.offHint")}</p>}
      {run.isError && <p className="text-xs text-destructive">{(run.error as Error).message}</p>}
      {run.isSuccess && !c.running && <p className="text-xs text-muted-foreground">{t("connectors.accepted")}</p>}

      {c.recent_runs.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("connectors.noRuns")}</p>
      ) : (
        <table className="w-full text-xs">
          <thead className="text-left text-muted-foreground">
            <tr>
              <th className="py-1 pr-3">{t("connectors.col.started")}</th>
              <th className="pr-3">{t("connectors.col.target")}</th>
              <th className="pr-3">{t("connectors.col.trigger")}</th>
              <th className="pr-3">{t("connectors.col.status")}</th>
              <th>{t("connectors.col.counts")}</th>
            </tr>
          </thead>
          <tbody>
            {c.recent_runs.map((r) => (
              <tr key={r.id} className="border-t align-top">
                <td className="py-1.5 pr-3 whitespace-nowrap">{formatShortDate(r.started_at)}</td>
                <td className="pr-3">{r.account ?? "—"}{r.scope ? ` / ${r.scope}` : ""}</td>
                <td className="pr-3">{t(`connectors.trigger.${r.trigger}`)}</td>
                <td className="pr-3">
                  <Badge className={RUN_BADGE[r.status] ?? "bg-secondary text-muted-foreground"}>
                    {t(`connectors.status.${r.status}`)}
                  </Badge>
                </td>
                <td>
                  {countParts(r.counts)
                    .map(([k, n]) => `${KNOWN_COUNTS.includes(k) ? t(`connectors.count.${k}`) : k} ${n}`)
                    .join(" · ") || "—"}
                  {r.error && <p className="mt-0.5 text-destructive break-words">{r.error}</p>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
