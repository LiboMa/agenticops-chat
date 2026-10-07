/**
 * The report page's view logic (MVP-2.7.0 S6): which papers are shown, what each says while its language is not
 * ready, and whether what is shown can be exported. Never mixes languages silently. Pure, so node can test it.
 */
import type { ContentRendering, RenderingStatus, Report } from "@/api/types";

export type ViewMode = "current" | "both";
export type Lang = "zh" | "en";
export type PaperState = "ready" | "preparing" | "failed" | "notPrepared" | "stale";

export const papersFor = (mode: ViewMode, uiLang: Lang): Lang[] => (mode === "both" ? ["zh", "en"] : [uiLang]);

export const exportLanguage = (mode: ViewMode, uiLang: Lang): "zh" | "en" | "zh-en" => (mode === "both" ? "zh-en" : uiLang);

const STATE: Record<RenderingStatus, PaperState> = {
  ready: "ready", pending: "preparing", missing: "notPrepared", failed: "failed", stale: "stale",
};

export function paperState(r: Pick<ContentRendering, "status"> | undefined): PaperState {
  return r ? STATE[r.status] ?? "notPrepared" : "preparing";
}

export function canExport(mode: ViewMode, uiLang: Lang, renderings: Partial<Record<Lang, Pick<ContentRendering, "status">>>): boolean {
  return papersFor(mode, uiLang).every((l) => renderings[l]?.status === "ready");
}

/** The list row's language badges: zh then en; the source language is always ready. */
export function languageBadges(report: Pick<Report, "source_language" | "language_status">): { lang: Lang; state: PaperState }[] {
  const source = report.source_language ?? "en";
  return (["zh", "en"] as Lang[]).map((lang) => ({
    lang,
    state: lang === source ? "ready" : paperState({ status: report.language_status?.[lang] ?? "missing" }),
  }));
}
