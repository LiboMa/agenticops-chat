import React from "react";
import type { IssueStatus } from "@/api/types";

const STEPS: { key: IssueStatus; label: string }[] = [
  { key: "open", label: "Open" },
  { key: "investigating", label: "Investigate" },
  { key: "root_cause_identified", label: "RCA" },
  { key: "fix_planned", label: "Plan" },
  { key: "fix_approved", label: "Approve" },
  { key: "fix_executed", label: "Execute" },
  { key: "resolved", label: "Resolved" },
];

function stepIndex(status: IssueStatus): number {
  if (status === "dismissed") return -1;
  const idx = STEPS.findIndex((s) => s.key === status);
  // "acknowledged" maps to "investigating"
  if (idx === -1 && status === "acknowledged") return 1;
  return idx === -1 ? 0 : idx;
}

export const IssueStatusStepper = React.memo(function IssueStatusStepper({
  status,
}: {
  status: IssueStatus;
}) {
  const current = stepIndex(status);
  const isDismissed = status === "dismissed";

  if (isDismissed) {
    return (
      <div className="flex items-center justify-center gap-2 py-2 text-sm text-slate-500">
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
        </svg>
        <span className="font-medium">Dismissed</span>
      </div>
    );
  }

  return (
    <div className="flex items-center w-full">
      {STEPS.map((step, i) => {
        const isCompleted = i < current;
        const isCurrent = i === current;

        return (
          <React.Fragment key={step.key}>
            {/* Connector line (before each step except the first) */}
            {i > 0 && (
              <div
                className={`flex-1 h-0.5 ${
                  i <= current ? "bg-primary" : "bg-muted"
                }`}
              />
            )}

            {/* Step circle + label */}
            <div className="flex flex-col items-center">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold shrink-0 ${
                  isCompleted
                    ? "bg-primary text-primary-foreground"
                    : isCurrent
                      ? "bg-primary text-primary-foreground ring-4 ring-primary/20"
                      : "bg-muted text-muted-foreground"
                }`}
              >
                {isCompleted ? (
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                  </svg>
                ) : (
                  i + 1
                )}
              </div>
              <span
                className={`mt-1.5 text-[10px] leading-tight text-center whitespace-nowrap ${
                  isCompleted || isCurrent
                    ? "text-primary font-medium"
                    : "text-muted-foreground"
                }`}
              >
                {step.label}
              </span>
            </div>
          </React.Fragment>
        );
      })}
    </div>
  );
});
