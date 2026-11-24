import { useCallback } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import en from "./locales/en.json";
import zh from "./locales/zh.json";

/** NewUI's own words. They live here, not in src/locales: those two files are part of the first screen's bundle,
 *  these arrive with the NewUI chunk. The language itself is the app's (LocaleContext), so the switch is shared. */
const STR: Record<"zh" | "en", Record<string, string>> = { zh, en };

export type Vars = Record<string, string | number | null | undefined>;
export type NfT = (key: string, vars?: Vars) => string;

/** "{i} / {n}" + {i: 7, n: 140} → "7 / 140"; a variable that was not given leaves nothing behind. */
export function fill(text: string, vars?: Vars): string {
  return vars ? text.replace(/\{(\w+)\}/g, (_, k: string) => String(vars[k] ?? "")) : text.replace(/\{(\w+)\}/g, "");
}

/** The text of `key` in `locale`; Chinese when that language lacks it (the design's source language), else the key. */
export function nfT(locale: "zh" | "en", key: string, vars?: Vars): string {
  const text = STR[locale]?.[key] ?? STR.zh[key];
  return text === undefined ? key : fill(text, vars);
}

export function useNfT(): NfT {
  const { locale } = useLocale();
  return useCallback((key: string, vars?: Vars) => nfT(locale, key, vars), [locale]);
}
