import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { LocaleProvider } from "@/i18n/LocaleContext";
import App from "./App";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <LocaleProvider>
      <App />
    </LocaleProvider>
  </StrictMode>,
);
