import { useState, useEffect, useCallback } from "react";

type Theme = "light" | "dark";
type FontSize = "small" | "medium" | "large";

const FONT_SIZES: Record<FontSize, string> = {
  small: "13px",
  medium: "15px",
  large: "17px",
};

function getInitialTheme(): Theme {
  if (typeof window === "undefined") return "light";
  const stored = localStorage.getItem("theme");
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function getInitialFontSize(): FontSize {
  if (typeof window === "undefined") return "medium";
  const stored = localStorage.getItem("fontSize");
  if (stored === "small" || stored === "medium" || stored === "large") return stored;
  return "medium";
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(getInitialTheme);
  const [fontSize, setFontSizeState] = useState<FontSize>(getInitialFontSize);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "dark") {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
    localStorage.setItem("theme", theme);
  }, [theme]);

  useEffect(() => {
    document.documentElement.style.fontSize = FONT_SIZES[fontSize];
    localStorage.setItem("fontSize", fontSize);
  }, [fontSize]);

  const toggle = useCallback(() => {
    setThemeState((t) => (t === "light" ? "dark" : "light"));
  }, []);

  const setFontSize = useCallback((size: FontSize) => {
    setFontSizeState(size);
  }, []);

  return { theme, toggle, fontSize, setFontSize };
}
