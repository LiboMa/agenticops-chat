import { useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useLocale } from "@/i18n/LocaleContext";
import { StatusText } from "@/components/ui/StatusText";
import { acceptReason, canAccept, checklistItems, confirmedIds } from "@/lib/acceptChecklist";
import { returnFocusTo } from "@/lib/focusReturn";
import type { RunSummary } from "@/lib/runSummary";

/** Accept a run by ticking what you checked (MVP-2.8.0 S2, design «验收本次执行»): the plan version and whether it
 *  still matches its approval, one box per check still to verify plus one overall confirmation, an optional note.
 *  Confirm stays off until every box is ticked; the ticked declared ids go with the acceptance. Rejecting keeps
 *  its own reason dialog. Radix: slide-in, ESC, focus kept inside; focus goes back to the button that opened it
 *  (mounted on open, so the element focused at the first render is the opener). */
export function AcceptDialog({ summary, busy, error, onConfirm, onClose }: {
  summary: RunSummary;
  busy: boolean;
  error: string | null;
  onConfirm: (args: { reason: string; confirmedChecks: string[] }) => void;
  onClose: () => void;
}) {
  const { t } = useLocale();
  const items = checklistItems(summary, t);
  const [ticked, setTicked] = useState<Set<number>>(new Set());
  const [note, setNote] = useState("");
  const openerRef = useRef<HTMLElement | null>(
    typeof document !== "undefined" && document.activeElement instanceof HTMLElement && document.activeElement !== document.body
      ? document.activeElement : null,
  );
  const toggle = (i: number) => setTicked((prev) => {
    const next = new Set(prev);
    if (next.has(i)) next.delete(i); else next.add(i);
    return next;
  });
  const ready = canAccept(items, ticked) && !busy;
  return (
    <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
      <Dialog.Portal>
        {/* centred by the overlay, not by a translate: the slideInRight keyframe owns `transform` */}
        <Dialog.Overlay className="fixed inset-0 z-50 grid items-start justify-items-center overflow-y-auto bg-black/30 px-4 pt-[12vh]">
          <Dialog.Content onCloseAutoFocus={(e) => returnFocusTo(openerRef.current, e)}
                          className="w-[min(560px,100%)] rounded-lg border border-border bg-card p-5 shadow-xl animate-[slideInRight_0.2s_ease-out]">
            <div className="flex items-start justify-between gap-3">
              <Dialog.Title className="text-lg font-semibold text-foreground">{t("accept.dialog.title")}</Dialog.Title>
              <Dialog.Close aria-label={t("common.close")} className="rounded px-2 text-lg text-muted-foreground hover:text-foreground">×</Dialog.Close>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
              {summary.planId != null && (
                <span className="rounded bg-selected px-2 py-0.5 font-mono text-primary">Plan #{summary.planId} · v{summary.version}</span>
              )}
              {summary.matchesApproved != null && (
                <StatusText tone={summary.matchesApproved ? "ok" : "danger"}>
                  {t(summary.matchesApproved ? "plan.hashMatches" : "plan.hashDrifted")}
                </StatusText>
              )}
            </div>
            <Dialog.Description className="mt-3 text-sm text-muted-foreground">{t("accept.dialog.intro")}</Dialog.Description>
            <ul className="mt-3 space-y-2">
              {items.map((item, i) => (
                <li key={`${item.id ?? "overall"}-${i}`}>
                  <label className="flex cursor-pointer items-start gap-2.5 rounded-md px-1 py-1 text-sm text-foreground hover:bg-accent">
                    <input type="checkbox" checked={ticked.has(i)} onChange={() => toggle(i)} className="mt-0.5 h-4 w-4 shrink-0 accent-[hsl(var(--primary))]" />
                    <span className="min-w-0 [overflow-wrap:anywhere]">
                      {item.id && <span className="mr-1.5 font-mono text-xs text-muted-foreground">{item.id}</span>}
                      {item.label}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
            <label className="mt-4 block text-xs font-medium text-muted-foreground" htmlFor="accept-note">{t("accept.dialog.note")}</label>
            <textarea id="accept-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} rows={3}
                      placeholder={t("accept.dialog.notePlaceholder")}
                      className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-[16px] sm:text-sm" />
            {error && <p role="alert" className="mt-2 text-sm text-status-danger">{error}</p>}
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
              <span className="text-xs text-muted-foreground">{t("accept.dialog.binding")}</span>
              <button type="button" disabled={!ready}
                      onClick={() => onConfirm({ reason: acceptReason(note, items.length, t), confirmedChecks: confirmedIds(items, ticked) })}
                      className="min-h-[40px] rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50">
                {t("accept.dialog.confirm")}
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Overlay>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
