import { useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import { useAnomaly } from "@/hooks/useAnomaly";
import { useAnomalyRca } from "@/hooks/useAnomalyRca";
import { useFixPlans, useApproveFixPlan, useRejectFixPlan, useExecuteFixPlan } from "@/hooks/useFixPlans";
import { useIssueTimeline } from "@/hooks/useIssueTimeline";
import { SeverityBadge } from "@/components/ui/SeverityBadge";
import { IssueStatusBadge } from "@/components/ui/IssueStatusBadge";
import { PipelineStepper } from "@/components/ui/PipelineStepper";
import { RiskLevelBadge } from "@/components/ui/RiskLevelBadge";
import { FixPlanStatusBadge } from "@/components/ui/FixPlanStatusBadge";
import { Spinner } from "@/components/ui/Spinner";
import { apiFetch } from "@/api/client";
import { formatFullDate, formatShortDate } from "@/lib/formatDate";
import { renderMarkdown } from "@/lib/renderMarkdown";
import { useLocale } from "@/i18n/LocaleContext";
import type { PipelineEvent, FixPlan } from "@/api/types";

interface Props {
  issueId: number | null;
  onClose: () => void;
}

/* ── Stage colors for timeline ──────────────────────────────────── */

const STAGE_COLORS: Record<string, string> = {
  detection: "bg-blue-500",
  rca: "bg-amber-500",
  planning: "bg-violet-500",
  approval: "bg-emerald-500",
  execution: "bg-orange-500",
  resolution: "bg-green-600",
  notification: "bg-muted-foreground/40",
};

const STATUS_ICONS: Record<string, string> = {
  completed: "check",
  started: "play",
  failed: "x",
  skipped: "minus",
};

export function ContextPanel({ issueId, onClose }: Props) {
  const { t } = useLocale();

  if (!issueId) return null;

  return (
    <div className="h-full flex flex-col bg-card border-l border-border">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          I#{issueId}
        </span>
        <button
          onClick={onClose}
          className="w-6 h-6 flex items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
          title={t("common.close")}
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Tabs content */}
      <ContextPanelBody issueId={issueId} />
    </div>
  );
}

/** Inner body component that always receives a valid issueId */
function ContextPanelBody({ issueId }: { issueId: number }) {
  const { t } = useLocale();

  const anomaly = useAnomaly(issueId);
  const rca = useAnomalyRca(issueId);
  const fixPlans = useFixPlans({ health_issue_id: issueId });
  const timeline = useIssueTimeline(issueId);

  const [rcaLoading, setRcaLoading] = useState(false);
  const [fixPlanLoading, setFixPlanLoading] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const approveMut = useApproveFixPlan();
  const rejectMut = useRejectFixPlan();
  const executeMut = useExecuteFixPlan();

  const triggerRca = async () => {
    setRcaLoading(true);
    setActionMsg(null);
    try {
      await apiFetch<unknown>(`/issues/${issueId}/rca`, { method: "POST" });
      setActionMsg("RCA triggered. Results may take a minute.");
      setTimeout(() => rca.refetch(), 10000);
    } catch (e: any) {
      setActionMsg(`RCA failed: ${e.message}`);
    } finally {
      setRcaLoading(false);
    }
  };

  const triggerFixPlan = async () => {
    setFixPlanLoading(true);
    setActionMsg(null);
    try {
      await apiFetch<unknown>(`/issues/${issueId}/generate-fix-plan`, { method: "POST" });
      setActionMsg("Fix plan generation triggered.");
      setTimeout(() => fixPlans.refetch(), 10000);
    } catch (e: any) {
      setActionMsg(`Fix plan failed: ${e.message}`);
    } finally {
      setFixPlanLoading(false);
    }
  };

  if (anomaly.isLoading) return <Spinner label={t("common.loading")} />;
  if (anomaly.error) {
    return (
      <div className="p-4 text-sm text-destructive">
        {anomaly.error.message}
      </div>
    );
  }

  const a = anomaly.data!;

  return (
    <Tabs.Root defaultValue="issue" className="flex-1 flex flex-col min-h-0">
      <Tabs.List className="flex border-b border-border px-2 shrink-0">
        {(["issue", "fixPlan", "timeline"] as const).map((tab) => (
          <Tabs.Trigger
            key={tab}
            value={tab}
            className="px-3 py-2 text-xs font-medium text-muted-foreground transition-colors
              data-[state=active]:text-primary data-[state=active]:border-b-2 data-[state=active]:border-primary
              hover:text-foreground"
          >
            {t(`issues.tab.${tab}`)}
          </Tabs.Trigger>
        ))}
      </Tabs.List>

      {/* Action message */}
      {actionMsg && (
        <div className="mx-3 mt-2 px-2 py-1.5 rounded bg-primary/10 border border-primary/20 text-xs text-primary">
          {actionMsg}
        </div>
      )}

      {/* ── Issue Tab ──────────────────────────────────────────── */}
      <Tabs.Content value="issue" className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Title + badges */}
        <div>
          <div className="flex items-center gap-2 flex-wrap mb-2">
            <SeverityBadge severity={a.severity} />
            <IssueStatusBadge status={a.status} />
          </div>
          <h2 className="text-sm font-semibold text-foreground leading-snug">
            {a.title}
          </h2>
        </div>

        {/* Description */}
        <div
          className="text-xs text-muted-foreground report-content"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(a.description) }}
        />

        {/* Pipeline stepper */}
        <PipelineStepper status={a.status} />

        {/* Metadata grid */}
        <div className="grid grid-cols-2 gap-3 text-xs">
          <MetaField label={t("issues.resource")} value={a.resource_id} mono />
          <MetaField label={t("issues.region")} value={a.region} />
          <MetaField label={t("issues.account")} value={a.account_name ?? "-"} />
          <MetaField label={t("issues.detected")} value={formatShortDate(a.detected_at)} />
        </div>

        {/* Action buttons */}
        <div className="flex gap-2 pt-2">
          <button
            onClick={triggerRca}
            disabled={rcaLoading}
            className="flex-1 px-3 py-1.5 text-xs font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
          >
            {rcaLoading ? "..." : t("issues.runRca")}
          </button>
          <button
            onClick={triggerFixPlan}
            disabled={fixPlanLoading}
            className="flex-1 px-3 py-1.5 text-xs font-medium rounded-md bg-secondary text-foreground hover:bg-accent border border-border disabled:opacity-50 transition-colors"
          >
            {fixPlanLoading ? "..." : t("issues.createFixPlan")}
          </button>
        </div>

        {/* RCA results inline */}
        {rca.data && (
          <div className="space-y-2 pt-2 border-t border-border">
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              {t("issues.rcaResults")}
            </h3>
            <div className="flex items-center gap-2 text-xs">
              <span className="text-muted-foreground">Confidence</span>
              <div className="flex-1 h-1.5 bg-secondary rounded-full">
                <div
                  className="h-1.5 bg-primary rounded-full"
                  style={{ width: `${rca.data.confidence_score * 100}%` }}
                />
              </div>
              <span className="text-foreground font-medium">
                {Math.round(rca.data.confidence_score * 100)}%
              </span>
            </div>
            <div
              className="text-xs text-foreground report-content"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(rca.data.root_cause) }}
            />
            {rca.data.recommendations.length > 0 && (
              <ol className="list-decimal list-inside text-xs text-muted-foreground space-y-0.5">
                {rca.data.recommendations.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ol>
            )}
          </div>
        )}
      </Tabs.Content>

      {/* ── Fix Plan Tab ───────────────────────────────────────── */}
      <Tabs.Content value="fixPlan" className="flex-1 overflow-y-auto p-4 space-y-4">
        {fixPlans.isLoading ? (
          <Spinner label={t("common.loading")} />
        ) : !fixPlans.data || fixPlans.data.length === 0 ? (
          <div className="text-center py-8">
            <p className="text-xs text-muted-foreground">{t("issues.noFixPlan")}</p>
          </div>
        ) : (
          fixPlans.data.map((fp) => (
            <FixPlanCard
              key={fp.id}
              fp={fp}
              approveMut={approveMut}
              rejectMut={rejectMut}
              executeMut={executeMut}
            />
          ))
        )}
      </Tabs.Content>

      {/* ── Timeline Tab ───────────────────────────────────────── */}
      <Tabs.Content value="timeline" className="flex-1 overflow-y-auto p-4">
        {timeline.isLoading ? (
          <Spinner label={t("common.loading")} />
        ) : !timeline.data || timeline.data.length === 0 ? (
          <div className="text-center py-8">
            <p className="text-xs text-muted-foreground">{t("issues.noTimeline")}</p>
          </div>
        ) : (
          <MiniTimeline events={timeline.data} />
        )}
      </Tabs.Content>
    </Tabs.Root>
  );
}

/* ── Metadata field helper ──────────────────────────────────────── */

function MetaField({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <span className="text-muted-foreground block text-[10px] uppercase tracking-wider">
        {label}
      </span>
      <span className={`text-foreground ${mono ? "font-mono" : ""} break-all`}>
        {value}
      </span>
    </div>
  );
}

/* ── Fix Plan card ──────────────────────────────────────────────── */

function FixPlanCard({
  fp,
  approveMut,
  rejectMut,
  executeMut,
}: {
  fp: FixPlan;
  approveMut: ReturnType<typeof useApproveFixPlan>;
  rejectMut: ReturnType<typeof useRejectFixPlan>;
  executeMut: ReturnType<typeof useExecuteFixPlan>;
}) {
  const { t } = useLocale();

  return (
    <div className="rounded-lg border border-border bg-secondary/30 p-3 space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2 flex-wrap">
        <RiskLevelBadge level={fp.risk_level} />
        <FixPlanStatusBadge status={fp.status} />
      </div>
      <h3 className="text-xs font-semibold text-foreground">{fp.title}</h3>
      <p className="text-[11px] text-muted-foreground">{fp.summary}</p>

      {/* Steps */}
      {Array.isArray(fp.steps) && fp.steps.length > 0 && (
        <div>
          <h4 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">
            {t("issues.steps")}
          </h4>
          <ol className="list-decimal list-inside text-[11px] text-muted-foreground space-y-0.5">
            {fp.steps.map((step, i) => (
              <li key={i}>
                {typeof step === "object" && step !== null
                  ? String(
                      (step as Record<string, unknown>).description ??
                      (step as Record<string, unknown>).title ??
                      JSON.stringify(step),
                    )
                  : String(step)}
              </li>
            ))}
          </ol>
        </div>
      )}

      {/* Approval info */}
      {fp.approved_by && (
        <p className="text-[10px] text-muted-foreground">
          Approved by {fp.approved_by}
          {fp.approved_at ? ` on ${formatShortDate(fp.approved_at)}` : ""}
        </p>
      )}

      {/* Action buttons */}
      <div className="flex gap-2">
        {fp.status === "pending_approval" && (
          <>
            <button
              onClick={() =>
                approveMut.mutate({ id: fp.id, approved_by: "web-user" })
              }
              disabled={approveMut.isPending}
              className="flex-1 px-2 py-1 text-[11px] font-medium rounded-md bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 transition-colors"
            >
              {t("issues.approve")}
            </button>
            <button
              onClick={() => rejectMut.mutate(fp.id)}
              disabled={rejectMut.isPending}
              className="flex-1 px-2 py-1 text-[11px] font-medium rounded-md bg-secondary text-foreground hover:bg-accent border border-border disabled:opacity-50 transition-colors"
            >
              {t("issues.reject")}
            </button>
          </>
        )}
        {fp.status === "approved" && (
          <button
            onClick={() => executeMut.mutate(fp.id)}
            disabled={executeMut.isPending}
            className="flex-1 px-2 py-1 text-[11px] font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
          >
            {t("issues.execute")}
          </button>
        )}
      </div>
    </div>
  );
}

/* ── Mini Timeline ──────────────────────────────────────────────── */

function MiniTimeline({ events }: { events: PipelineEvent[] }) {
  return (
    <div className="relative">
      {/* Vertical line */}
      <div className="absolute left-[9px] top-1 bottom-1 w-0.5 bg-muted" />
      <div className="space-y-2.5">
        {events.map((ev, i) => {
          const color = STAGE_COLORS[ev.stage] || "bg-muted-foreground/40";
          const iconKey = STATUS_ICONS[ev.status] || "dot";
          const isFailed = ev.status === "failed";
          return (
            <div key={ev.id ?? i} className="relative flex items-start gap-2.5">
              {/* Dot */}
              <div
                className={`
                  relative z-10 flex-shrink-0 w-[19px] h-[19px] rounded-full
                  flex items-center justify-center text-white text-[9px] font-bold
                  ${color} ${isFailed ? "ring-2 ring-red-300" : ""}
                `}
              >
                {iconKey === "check" && (
                  <svg className="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                  </svg>
                )}
                {iconKey === "play" && (
                  <svg className="w-2.5 h-2.5" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M8 5v14l11-7z" />
                  </svg>
                )}
                {iconKey === "x" && (
                  <svg className="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                )}
                {iconKey === "minus" && (
                  <svg className="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 12h14" />
                  </svg>
                )}
                {iconKey === "dot" && <span>{"\u2022"}</span>}
              </div>

              {/* Content */}
              <div className="flex-1 min-w-0 pb-0.5">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className="text-[11px] font-medium text-foreground">
                    {ev.event_type.replace(/_/g, " ")}
                  </span>
                  <span
                    className={`inline-flex items-center px-1 py-0 rounded text-[9px] font-medium uppercase tracking-wide ${
                      isFailed
                        ? "bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400"
                        : ev.status === "started"
                          ? "bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-400"
                          : ev.status === "skipped"
                            ? "bg-secondary text-muted-foreground"
                            : "bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400"
                    }`}
                  >
                    {ev.status}
                  </span>
                  {ev.duration_ms != null && ev.duration_ms > 0 && (
                    <span className="text-[9px] text-muted-foreground">
                      {ev.duration_ms >= 1000
                        ? `${(ev.duration_ms / 1000).toFixed(1)}s`
                        : `${ev.duration_ms}ms`}
                    </span>
                  )}
                </div>
                {/* Detail chips */}
                {ev.detail && (
                  <div className="flex flex-wrap gap-0.5 mt-0.5">
                    {Object.entries(ev.detail).map(([k, v]) =>
                      v != null ? (
                        <span
                          key={k}
                          className="inline-flex items-center px-1 py-0 rounded bg-secondary text-[9px] text-muted-foreground font-mono"
                        >
                          {k}: {typeof v === "object" ? JSON.stringify(v) : String(v).slice(0, 60)}
                        </span>
                      ) : null,
                    )}
                  </div>
                )}
                <div className="text-[9px] text-muted-foreground mt-0.5">
                  {ev.actor !== "system" && <span className="mr-1.5">{ev.actor}</span>}
                  {formatFullDate(ev.created_at)}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
