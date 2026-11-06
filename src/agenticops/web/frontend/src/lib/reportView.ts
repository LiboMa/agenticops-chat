/**
 * The report page's view logic (MVP-2.7.0 S6): the page shows one language at a time — a 中文 / English toggle, never
 * the two side by side (owner, 2026-10-08) — what the paper says while that language is not ready, and whether it
 * can be exported. Never mixes languages silently. Pure, so node can test it.
 */
import type { ContentRendering, RenderingStatus, Report } from "@/api/types";

export type Lang = "zh" | "en";
export type PaperState = "ready" | "preparing" | "failed" | "notPrepared" | "stale";

/** The toggle's two choices, in this order. */
export const LANGS: Lang[] = ["zh", "en"];

const STATE: Record<RenderingStatus, PaperState> = {
  ready: "ready", pending: "preparing", missing: "notPrepared", failed: "failed", stale: "stale",
};

export function paperState(r: Pick<ContentRendering, "status"> | undefined): PaperState {
  return r ? STATE[r.status] ?? "notPrepared" : "preparing";
}

export function canExport(lang: Lang, renderings: Partial<Record<Lang, Pick<ContentRendering, "status">>>): boolean {
  return renderings[lang]?.status === "ready";
}

/** The list row's language badges: zh then en; the source language is always ready. */
export function languageBadges(report: Pick<Report, "source_language" | "language_status">): { lang: Lang; state: PaperState }[] {
  const source = report.source_language ?? "en";
  return LANGS.map((lang) => ({
    lang,
    state: lang === source ? "ready" : paperState({ status: report.language_status?.[lang] ?? "missing" }),
  }));
}
