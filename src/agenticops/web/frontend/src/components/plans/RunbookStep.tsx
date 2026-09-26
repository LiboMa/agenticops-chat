import { useState } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import { renderMarkdown } from "@/lib/renderMarkdown";

/* ================================================================== */
/*  Runbook helper components                                          */
/* ================================================================== */

export function RunbookStep({ index, step }: { index: number; step: unknown }) {
  const isObj = typeof step === "object" && step !== null && !Array.isArray(step);
  const s = isObj ? (step as Record<string, unknown>) : null;
  const action = s?.action ?? s?.description ?? s?.step;
  const command = s?.command as string | undefined;
  const text = typeof step === "string" ? step : typeof action === "string" ? action : null;

  return (
    <li className="border border-border rounded-lg p-4 bg-background">
      <div className="flex gap-3">
        <span className="flex-shrink-0 w-7 h-7 rounded-full bg-primary/20 text-primary flex items-center justify-center text-sm font-semibold">
          {index}
        </span>
        <div className="flex-1 min-w-0">
          {text ? (
            <div
              className="text-foreground text-sm leading-relaxed report-content"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(text) }}
            />
          ) : (
            <pre className="text-foreground text-sm whitespace-pre-wrap">
              {JSON.stringify(step, null, 2)}
            </pre>
          )}
          {command && <CommandBlock command={command} />}
        </div>
      </div>
    </li>
  );
}

export function CommandBlock({ command }: { command: string }) {
  const { t } = useLocale();
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(command).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="mt-3 relative group">
      <div
        className="rounded-lg p-3 text-sm font-mono overflow-x-auto"
        style={{ backgroundColor: "#1e1e2e", color: "#cdd6f4" }}
      >
        <span className="select-none" style={{ color: "#a6e3a1" }}>
          ${" "}
        </span>
        {command}
      </div>
      <button
        onClick={handleCopy}
        className="absolute top-2 right-2 px-2 py-1 text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity"
        style={{ backgroundColor: "#313244", color: "#a6adc8" }}
      >
        {copied ? t("issues.copied") : t("issues.copy")}
      </button>
    </div>
  );
}
