import type { FixExecution } from "@/api/types";
import { ExecutionEvidence } from "@/components/plans/ExecutionEvidence";
import { RunningFor } from "@/components/workitem/RunningFor";
import { executionStatusLabel } from "@/lib/issueDetail";
import { formatFullDate } from "@/lib/formatDate";

/** Every run's evidence, one fold each, newest first and open; a run in flight shows how long it has been going.
 *  The run whose error_message the status line already shows does not repeat it (P3). */
export function RunList({ runs, quietRunId, t }: {
  runs: FixExecution[];          // newest first
  quietRunId: number | null;
  t: (key: string) => string;
}) {
  return (
    <div className="space-y-3">
      {runs.map((ex, i) => (
        <details key={ex.id} open={i === 0} className="rounded-lg border border-border p-3">
          <summary className="cursor-pointer text-sm font-semibold text-foreground">
            {t("issues.executionN").replace("{n}", String(ex.id))}
            <span className="ml-2 text-xs font-normal text-muted-foreground">
              {executionStatusLabel(ex.status, t)}{ex.started_at && ` · ${formatFullDate(ex.started_at)}`}
            </span>
          </summary>
          <div className="mt-3 space-y-3">
            {(ex.status === "pending" || ex.status === "running") && <RunningFor since={ex.started_at} t={t} />}
            <ExecutionEvidence execution={ex} showError={ex.id !== quietRunId} />
          </div>
        </details>
      ))}
    </div>
  );
}
