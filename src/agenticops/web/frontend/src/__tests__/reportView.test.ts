import { describe, it, expect } from "vitest";
import { canExport, exportLanguage, languageBadges, paperState, papersFor } from "@/lib/reportView";
import type { ContentRendering, Report } from "@/api/types";

const r = (status: ContentRendering["status"], language: "zh" | "en" = "zh") => ({ status, language }) as ContentRendering;

describe("report view (MVP-2.7.0 S6)", () => {
  it("current shows the UI language; both shows zh then en", () => {
    expect(papersFor("current", "en")).toEqual(["en"]);
    expect(papersFor("current", "zh")).toEqual(["zh"]);
    expect(papersFor("both", "en")).toEqual(["zh", "en"]);
  });
  it("export follows what is shown", () => {
    expect(exportLanguage("current", "zh")).toBe("zh");
    expect(exportLanguage("both", "en")).toBe("zh-en");
  });
  it("paper states: missing reads as not prepared, pending as preparing", () => {
    expect(paperState(r("ready"))).toBe("ready");
    expect(paperState(r("pending"))).toBe("preparing");
    expect(paperState(r("missing"))).toBe("notPrepared");
    expect(paperState(r("failed"))).toBe("failed");
    expect(paperState(r("stale"))).toBe("stale");
    expect(paperState(undefined)).toBe("preparing");   // still loading
  });
  it("export needs every shown paper ready", () => {
    expect(canExport("current", "en", { en: r("ready", "en") })).toBe(true);
    expect(canExport("both", "en", { en: r("ready", "en"), zh: r("pending") })).toBe(false);
    expect(canExport("both", "en", { en: r("ready", "en"), zh: r("ready") })).toBe(true);
  });
  it("badges: the source language is always ready; the other from its status", () => {
    const rep = { source_language: "en", language_status: { zh: "missing" } } as unknown as Report;
    expect(languageBadges(rep)).toEqual([{ lang: "zh", state: "notPrepared" }, { lang: "en", state: "ready" }]);
    const zhRep = { source_language: "zh", language_status: { en: "pending" } } as unknown as Report;
    expect(languageBadges(zhRep)).toEqual([{ lang: "zh", state: "ready" }, { lang: "en", state: "preparing" }]);
    expect(languageBadges({ source_language: "en" } as unknown as Report)[0]).toEqual({ lang: "zh", state: "notPrepared" });
  });
});
