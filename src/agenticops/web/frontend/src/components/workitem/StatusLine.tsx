import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useLocale } from "@/i18n/LocaleContext";
import { Card, CardBody } from "@/components/ui/Card";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { cn } from "@/lib/cn";
import { nextMenuIndex, type MenuKey } from "@/lib/menuNav";

export interface StatusLineAction {
  key: string; label: string; run: () => void; disabled?: boolean; variant?: "default" | "destructive";
  title?: string;                    // a menu item's hover note
}
export interface StatusLineProps {
  refLabel: string;                 // "I#1" / "C#1"
  title: string;
  badges?: React.ReactNode;          // severity / risk / change type chips
  statusLabel: string;               // localized sub-state, e.g. 根因待复核
  tone: "info" | "warn" | "bad" | "ok";
  reason?: string | null;            // at most two lines; the page's ONLY copy of a failure sentence
  waiting?: string | null;           // localized "等你：…" / "等执行器"
  primary?: StatusLineAction | null; // the page's ONE primary button
  menu?: StatusLineAction[];         // the "⋯" menu (secondary actions)
  error?: string | null;             // a 409/403 message, shown in an ErrorBanner under the line
  onDismissError?: () => void;
  errorActionLabel?: string;         // the banner's button; default "Close" (a failed fetch passes "Retry")
  backTo: string; backLabel: string;
}

const DOT: Record<StatusLineProps["tone"], string> = {
  info: "bg-blue-500", warn: "bg-amber-500", bad: "bg-red-500", ok: "bg-emerald-500",
};

/** The work item's one status indicator: where it is, why, who moves it next, and the one primary button. */
export function StatusLine({
  refLabel, title, badges, statusLabel, tone, reason, waiting, primary, menu, error, onDismissError, errorActionLabel,
  backTo, backLabel,
}: StatusLineProps) {
  const { t } = useLocale();
  const [expanded, setExpanded] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const items = menu ?? [];

  // ESC (focus back on ⋯) and a click outside close the menu; bound only while it is open. Opening it focuses its
  // first enabled item, so the arrow keys work at once.
  useEffect(() => {
    if (!menuOpen) return;
    const first = nextMenuIndex(-1, "Home", items.map((a) => !!a.disabled));
    if (first >= 0) itemRefs.current[first]?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setMenuOpen(false);
      triggerRef.current?.focus();
    };
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
    };
    // the items are read once per opening; a poll that re-renders them must not steal the focus back
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [menuOpen]);

  const onMenuKey = (e: React.KeyboardEvent) => {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
    e.preventDefault();
    const current = itemRefs.current.findIndex((el) => el === document.activeElement);
    const next = nextMenuIndex(current, e.key as MenuKey, items.map((a) => !!a.disabled));
    if (next >= 0) itemRefs.current[next]?.focus();
  };
  return (
    <div className="space-y-2">
      <Card>
        <CardBody className="space-y-3">
          <Link to={backTo} className="text-sm text-muted-foreground hover:text-foreground transition-colors">
            ← {backLabel}
          </Link>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs px-2 py-0.5 rounded bg-secondary text-muted-foreground">{refLabel}</span>
            {badges}
            <h1 className="text-2xl font-semibold text-foreground">{title}</h1>
          </div>
          <div className="flex flex-wrap items-start gap-3">
            <div className="min-w-0 flex-1 space-y-1">
              <div className="flex items-center gap-2">
                <span className={`h-2 w-2 shrink-0 rounded-full ${DOT[tone]}`} />
                <span className="font-medium text-foreground">{statusLabel}</span>
              </div>
              {reason && (
                // a button, so the keyboard expands the clamped sentence too
                <button type="button" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}
                        className={cn("w-full text-left text-sm text-foreground/80 break-words cursor-pointer",
                                      expanded ? "block" : "line-clamp-2")}>
                  {reason}
                </button>
              )}
              {waiting && <p className="text-sm text-muted-foreground">{waiting}</p>}
            </div>
            {(primary || items.length > 0) && (
              <div ref={menuRef} className="relative ml-auto shrink-0 whitespace-nowrap flex items-center gap-2">
                {primary && (
                  <button
                    onClick={primary.run}
                    disabled={primary.disabled}
                    className={cn(
                      "px-4 py-2 text-sm font-medium rounded-lg transition-colors disabled:opacity-50",
                      primary.variant === "destructive"
                        ? "bg-red-600 text-white hover:bg-red-700"
                        : "bg-primary text-primary-foreground hover:bg-primary/90",
                    )}
                  >
                    {primary.label}
                  </button>
                )}
                {items.length > 0 && (
                  <button
                    ref={triggerRef}
                    onClick={() => setMenuOpen(!menuOpen)}
                    aria-haspopup="menu"
                    aria-expanded={menuOpen}
                    aria-label={t("workitem.menu")}
                    title={t("workitem.menu")}
                    className="px-2.5 py-2 text-sm rounded-lg border border-border hover:bg-accent transition-colors"
                  >
                    ⋯
                  </button>
                )}
                {menuOpen && items.length > 0 && (
                  <div role="menu" aria-label={t("workitem.menu")} onKeyDown={onMenuKey}
                       className="absolute right-0 top-full mt-1 z-20 min-w-48 rounded-lg border bg-popover shadow-lg py-1 animate-[slideInRight_0.2s_ease-out]">
                    {items.map((a, i) => (
                      <button
                        key={a.key}
                        ref={(el) => { itemRefs.current[i] = el; }}
                        role="menuitem"
                        tabIndex={-1}
                        title={a.title}
                        disabled={a.disabled}
                        onClick={() => { setMenuOpen(false); a.run(); }}
                        className={cn(
                          "block w-full text-left px-3 py-2 text-sm hover:bg-accent focus:bg-accent focus:outline-none transition-colors disabled:opacity-50",
                          a.variant === "destructive" ? "text-red-500" : "text-popover-foreground",
                        )}
                      >
                        {a.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </CardBody>
      </Card>
      {error && <ErrorBanner message={error} onRetry={onDismissError} actionLabel={errorActionLabel ?? t("common.close")} />}
    </div>
  );
}
