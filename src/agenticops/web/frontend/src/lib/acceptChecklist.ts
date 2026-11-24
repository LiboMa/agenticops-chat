import type { RunSummary } from "@/lib/runSummary";

export interface ChecklistItem { id: string | null; label: string }

/** What a person confirms before accepting a run (MVP-2.8.0 S2): one box per declared check still to verify — no
 *  result («待核对») or a warning — then one overall confirmation. The ticked declared ids go with the acceptance. */
export function checklistItems(summary: RunSummary, t: (k: string) => string): ChecklistItem[] {
  const toVerify = summary.checks.filter((c) => c.state === "pending" || c.state === "warning");
  return [
    ...toVerify.map((c) => ({
      id: c.id,
      label: t(c.state === "warning" ? "accept.checklist.warning" : "accept.checklist.pending").replace("{check}", c.label),
    })),
    { id: null, label: t("accept.checklist.overall") },
  ];
}

export const canAccept = (items: ChecklistItem[], ticked: ReadonlySet<number>) => items.every((_, i) => ticked.has(i));

export function confirmedIds(items: ChecklistItem[], ticked: ReadonlySet<number>): string[] {
  return items.flatMap((item, i) => (item.id && ticked.has(i) ? [item.id] : []));
}

/** The acceptance's reason (the API needs 1–2000 characters): the person's note, else what was checked — the
 *  declared checks only (the overall confirmation carries no id), and with none, the overall confirmation in words. */
export function acceptReason(note: string, items: ChecklistItem[], t: (k: string) => string): string {
  const own = note.trim().slice(0, 2000);
  if (own) return own;
  const checks = items.filter((item) => item.id !== null).length;
  return checks > 0 ? t("accept.checklist.reason").replace("{n}", String(checks)) : t("accept.checklist.reasonOverall");
}
