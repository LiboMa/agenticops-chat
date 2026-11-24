import { forwardRef, type MouseEvent, type ReactNode } from "react";
import * as Tooltip from "@radix-ui/react-tooltip";

/** An icon-only button (MVP-2.8.0, owner 2026-11-10: «尽可能使用Icon化的按钮»). `label` is both the tooltip shown on
 *  hover / keyboard focus and the accessible name, so they can never differ; a touch screen never shows a tooltip,
 *  so the label must stand on its own. 40 px on phones, 32 px from 768 px; a visible focus ring; `danger` is red.
 *  The tooltip is portalled above the modal overlay (z-50), so it shows inside dialogs too. */
export const IconButton = forwardRef<HTMLButtonElement, {
  label: string;
  icon: ReactNode;
  onClick: (e: MouseEvent<HTMLButtonElement>) => void;
  tone?: "default" | "danger";
  disabled?: boolean;
  className?: string;
}>(function IconButton({ label, icon, onClick, tone = "default", disabled = false, className = "" }, ref) {
  const tones = tone === "danger"
    ? "border-status-danger/40 text-status-danger hover:bg-status-danger/5"
    : "border-border text-foreground/80 hover:bg-accent hover:text-foreground";
  return (
    <Tooltip.Provider delayDuration={300}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <button ref={ref} type="button" aria-label={label} onClick={onClick} disabled={disabled}
                  className={`inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md border bg-card md:h-8 md:w-8 ${tones} focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-not-allowed disabled:opacity-50 ${className}`}>
            {icon}
          </button>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content side="top" sideOffset={6}
                           className="z-[60] max-w-[240px] rounded-md bg-foreground px-2 py-1 text-xs text-background shadow-md">
            {label}
            <Tooltip.Arrow className="fill-foreground" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
});
