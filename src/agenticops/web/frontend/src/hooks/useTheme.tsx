import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

type Theme = "light" | "dark";
export type FontSize = "small" | "medium" | "large";

export const FONT_SIZES: Record<FontSize, string> = {
  small: "13px",
  medium: "15px",
  large: "17px",
};

/** First visit is light (the blue/white workspace, MVP-2.7.0); a stored choice wins. The system dark
 *  preference is not followed — index.html applies the same rule before the first paint. */
function getInitialTheme(): Theme {
  if (typeof window === "undefined") return "light";
  return localStorage.getItem("theme") === "dark" ? "dark" : "light";
}

function getInitialFontSize(): FontSize {
  if (typeof window === "undefined") return "medium";
  const stored = localStorage.getItem("fontSize");
  if (stored === "small" || stored === "medium" || stored === "large") return stored;
  return "medium";
}

interface ThemeValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggle: () => void;
  fontSize: FontSize;
  setFontSize: (size: FontSize) => void;
}

const ThemeContext = createContext<ThemeValue | null>(null);

/** One theme + font-size state for the whole app (the login page included), applied to <html>. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(getInitialTheme);
  const [fontSize, setFontSizeState] = useState<FontSize>(getInitialFontSize);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem("theme", theme);
  }, [theme]);

  useEffect(() => {
    document.documentElement.style.fontSize = FONT_SIZES[fontSize];
    localStorage.setItem("fontSize", fontSize);
  }, [fontSize]);

  const toggle = useCallback(() => setThemeState((t) => (t === "light" ? "dark" : "light")), []);
  const setFontSize = useCallback((size: FontSize) => setFontSizeState(size), []);

  return (
    <ThemeContext.Provider value={{ theme, setTheme: setThemeState, toggle, fontSize, setFontSize }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
