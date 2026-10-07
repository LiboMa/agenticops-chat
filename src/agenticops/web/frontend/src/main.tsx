import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { LocaleProvider } from "@/i18n/LocaleContext";
import { ThemeProvider } from "@/hooks/useTheme";
import App from "./App";
// Outfit, bundled: customer environments may have no route to a font CDN (MVP-2.7.0)
import "@fontsource/outfit/400.css";
import "@fontsource/outfit/500.css";
import "@fontsource/outfit/600.css";
import "@fontsource/outfit/700.css";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <LocaleProvider>
        <App />
      </LocaleProvider>
    </ThemeProvider>
  </StrictMode>,
);
