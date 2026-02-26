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
                  i <= current ? "bg-primary-500" : "bg-slate-200"
                }`}
              />
            )}

            {/* Step circle + label */}
            <div className="flex flex-col items-center">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold shrink-0 ${
                  isCompleted
                    ? "bg-primary-500 text-white"
                    : isCurrent
                      ? "bg-primary-500 text-white ring-4 ring-primary-100"
                      : "bg-slate-200 text-slate-500"
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
                    ? "text-primary-700 font-medium"
                    : "text-slate-400"
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
