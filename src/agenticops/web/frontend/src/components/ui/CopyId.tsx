import { useEffect, useState, type MouseEvent } from "react";
import { Check, Copy } from "lucide-react";
import { useLocale } from "@/i18n/LocaleContext";
import { copyText } from "@/lib/clipboard";
import { cn } from "@/lib/cn";

/** An identifier shown short — the tail of an ARN, the end of a long id — with the whole of it in the tooltip and a
 *  button that copies the whole of it (MVP-2.9.0 N24, the 2.8.0 spec's R09). The button sits above a row's stretched
 *  link and never follows it; what happened is said to a screen reader too. */
export function CopyId({ id, short, struck = false, className }: { id: string; short: string; struck?: boolean; className?: string }) {
  const { t } = useLocale();
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  useEffect(() => {
    if (state === "idle") return;
    const timer = window.setTimeout(() => setState("idle"), 1600);
    return () => window.clearTimeout(timer);
  }, [state]);
  const copy = async (e: MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setState((await copyText(id)) ? "copied" : "failed");
  };
  const said = state === "copied" ? t("common.copied") : state === "failed" ? t("common.copyFailed") : "";
  return (
    <span className={cn("inline-flex min-w-0 max-w-full items-center gap-0.5", className)}>
      <span title={id} className={cn("min-w-0 truncate font-mono text-xs text-muted-foreground", struck && "line-through opacity-60")}>{short}</span>
      <button type="button" onClick={copy} aria-label={t("common.copyId")} title={said || t("common.copyId")}
              className="relative z-10 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary max-[767px]:-my-2.5 max-[767px]:h-[44px] max-[767px]:w-[44px]">
        {state === "copied"
          ? <Check className="h-3.5 w-3.5 text-status-ok" aria-hidden="true" />
          : <Copy className={cn("h-3.5 w-3.5", state === "failed" && "text-status-danger")} aria-hidden="true" />}
      </button>
      <span role="status" className="sr-only">{said}</span>
    </span>
  );
}
