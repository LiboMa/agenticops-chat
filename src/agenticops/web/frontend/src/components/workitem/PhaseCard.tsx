import { useState } from "react";
import type { PhaseState } from "@/lib/issuePhases";
import { cn } from "@/lib/cn";

export interface PhaseCardProps { id: string; index: number; title: string; state: PhaseState; summary?: string | null;
  futureHint?: string | null; badge?: React.ReactNode; open?: boolean; onToggle?: (open: boolean) => void; children?: React.ReactNode }

const MARK: Record<PhaseState, string> = {
  done: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
  current: "bg-primary text-primary-foreground",
  failed: "bg-red-500/15 text-red-500",
  future: "bg-secondary text-muted-foreground",
};

/** One phase of a work item. Controlled (`open` + `onToggle`) or, uncontrolled, open while current or failed; a
 *  future phase never opens and only says what will happen there. */
export function PhaseCard({ id, index, title, state, summary, futureHint, badge, open, onToggle, children }: PhaseCardProps) {
  const [inner, setInner] = useState(state === "current" || state === "failed");
  const future = state === "future";
  const isOpen = !future && (open ?? inner);
  const toggle = () => {
    const next = !isOpen;
    if (open === undefined) setInner(next);
    onToggle?.(next);
  };

  const head = (
    <>
      <span className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm font-semibold", MARK[state])}>
        {state === "done" ? "✓" : state === "failed" ? "!" : index}
      </span>
      <span className="min-w-0 flex-1">
        <span className={cn("block font-semibold", future ? "text-muted-foreground" : "text-foreground")}>{title}</span>
        {!isOpen && summary && (state === "done" || state === "failed") && (
          <span className="block truncate text-sm text-muted-foreground" title={summary}>{summary}</span>
        )}
      </span>
      {badge && <span className="ml-auto shrink-0">{badge}</span>}
    </>
  );

  return (
    <section id={id} className="scroll-mt-4">
      <div className={cn("bg-card text-card-foreground border rounded-lg",
                         state === "failed" && "border-red-500/40", state === "current" && "border-primary/40")}>
        {future ? (
          <div className="px-5 py-3.5">
            <div className="flex items-center gap-3">{head}</div>
            {futureHint && <p className="mt-1 pl-10 text-xs text-muted-foreground">{futureHint}</p>}
          </div>
        ) : (
          <button type="button" aria-expanded={isOpen} aria-controls={`${id}-body`} onClick={toggle}
                  className="flex w-full items-center gap-3 px-5 py-3.5 text-left">
            {head}
            <svg className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", isOpen && "rotate-90")}
                 fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
        )}
        {isOpen && <div id={`${id}-body`} className="border-t px-5 py-4">{children}</div>}
      </div>
    </section>
  );
}
