import { PipelineStepper } from "./PipelineStepper";
import { SeverityBadge } from "./SeverityBadge";
import { formatShortDate } from "@/lib/formatDate";
import type { Anomaly } from "@/api/types";

interface Props {
  issue: Anomaly;
  onClick: (issue: Anomaly) => void;
}

const STATUS_LABELS: Record<string, string> = {
  open: "open",
  investigating: "investigating",
  acknowledged: "acknowledged",
  root_cause_identified: "rca_done",
  fix_planned: "fix_planned",
  fix_approved: "approved",
  fix_executing: "executing",
  fix_executed: "executed",
  resolved: "resolved",
  dismissed: "dismissed",
};

export function IssueRow({ issue, onClick }: Props) {
  const isResolved = issue.status === "resolved";
  const isDismissed = issue.status === "dismissed";
  const isCritical = issue.severity === "critical" && !isResolved && !isDismissed;

  return (
    <div
      onClick={() => onClick(issue)}
      className={`flex items-center gap-3 px-4 py-3 border-b border-border/50 cursor-pointer transition-colors hover:bg-accent ${
        isResolved || isDismissed ? "opacity-50" : ""
      } ${isCritical ? "bg-red-500/5" : ""}`}
    >
      <SeverityBadge severity={issue.severity} />
      <div className="flex-1 min-w-0">
        <div className="text-sm text-foreground">
          <span className="text-muted-foreground font-mono">#{issue.id}</span>{" "}
          {issue.title}
        </div>
        <div className="text-xs text-muted-foreground mt-0.5">
          {issue.region} · {issue.resource_type}/{issue.resource_id?.slice(0, 20)} · {formatShortDate(issue.detected_at)}
        </div>
      </div>
      <PipelineStepper status={issue.status} className="w-20 flex-shrink-0" />
      <span className={`text-xs w-16 text-right flex-shrink-0 ${
        isResolved ? "text-green-500" : isDismissed ? "text-slate-400" : "text-primary"
      }`}>
        {STATUS_LABELS[issue.status] ?? issue.status}
        {isResolved && " \u2713"}
      </span>
    </div>
  );
}
