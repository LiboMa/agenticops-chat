/**
 * Mini 5-segment pipeline stepper: open → investigating → rca → fix → resolved
 * Completed/current segments = indigo, resolved = green, remaining = dark gray.
 */

interface Props {
  status: string;
  className?: string;
}

const STATUS_TO_PHASE: Record<string, number> = {
  open: 0,
  investigating: 1,
  acknowledged: 1,
  root_cause_identified: 2,
  fix_planned: 3,
  fix_approved: 3,
  fix_executing: 3,
  fix_executed: 3,
  resolved: 4,
};

export function PipelineStepper({ status, className = "" }: Props) {
  const currentPhase = STATUS_TO_PHASE[status] ?? 0;
  const isResolved = status === "resolved";
  const isDismissed = status === "dismissed";

  return (
    <div className={`flex gap-0.5 ${className}`}>
      {[0, 1, 2, 3, 4].map((i) => {
        let bg: string;
        if (isDismissed) bg = "bg-muted-foreground/30";
        else if (isResolved) bg = "bg-green-500";
        else if (i <= currentPhase) bg = "bg-primary";
        else bg = "bg-muted";
        return <div key={i} className={`h-[3px] flex-1 rounded-sm ${bg}`} />;
      })}
    </div>
  );
}
