import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export type StatusTone = "ok" | "warn" | "danger" | "info" | "neutral";

const TONE: Record<StatusTone, string> = {
  ok: "text-status-ok",
  warn: "text-status-warn",
  danger: "text-status-danger",
  info: "text-primary",
  neutral: "text-muted-foreground",
};

/** A state said in words, the colour only helping (MVP-2.8.0): a small dot in the tone's colour + the text. */
export function StatusText({ tone, children, className }: { tone: StatusTone; children: ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap", TONE[tone], className)}>
      <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" />
      {children}
    </span>
  );
}
