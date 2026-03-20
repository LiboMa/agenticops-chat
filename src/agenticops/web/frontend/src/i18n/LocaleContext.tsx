import { createContext, useContext, useState, useCallback, type ReactNode } from "react";
import en from "@/locales/en.json";
import zh from "@/locales/zh.json";

type Locale = "en" | "zh";
type Translations = Record<string, string>;

const TRANSLATIONS: Record<Locale, Translations> = { en, zh };

interface LocaleContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string) => string;
}

const LocaleContext = createContext<LocaleContextValue | null>(null);

function getInitialLocale(): Locale {
  if (typeof window === "undefined") return "en";
  const stored = localStorage.getItem("aiops_locale");
  if (stored === "en" || stored === "zh") return stored;
  return "en";
}

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(getInitialLocale);

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    localStorage.setItem("aiops_locale", l);
  }, []);

  const t = useCallback(
    (key: string): string => TRANSLATIONS[locale]?.[key] ?? TRANSLATIONS.en[key] ?? key,
    [locale],
  );

  return (
    <LocaleContext.Provider value={{ locale, setLocale, t }}>
      {children}
    </LocaleContext.Provider>
  );
}

export function useLocale() {
  const ctx = useContext(LocaleContext);
  if (!ctx) throw new Error("useLocale must be used within LocaleProvider");
  return ctx;
}
