import { useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import { useSettings } from "@/hooks/useSettings";
import { useChatSessions, useUpdateChatSession } from "@/hooks/useChatSessions";
import { useLocale } from "@/i18n/LocaleContext";

/** Strip provider prefix: "global.anthropic.claude-opus-4-8" → "claude-opus-4-8" */
function shortName(id: string): string {
  const parts = id.split(".");
  return parts.length > 2 ? parts.slice(2).join(".") : id;
}

function CheckIcon() {
  return (
    <svg className="w-3.5 h-3.5 shrink-0 text-primary-600 dark:text-primary-400" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  );
}

export function ModelSelector({ sessionId, disabled }: { sessionId: string | null; disabled?: boolean }) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const settingsQ = useSettings();
  const sessionsQ = useChatSessions();
  const update = useUpdateChatSession();

  if (!sessionId) return null;
  const session = sessionsQ.data?.find((s) => s.session_id === sessionId);
  const presets = settingsQ.data?.model_presets ?? [];
  const globalMain = settingsQ.data?.agent_models?.["main"]?.model_id ?? "";

  const labelFor = (id: string) => presets.find((p) => p.value === id)?.label ?? shortName(id);
  const current = session?.model_id ?? null;
  const currentLabel = current ? labelFor(current) : `${t("chat.model.auto")} · ${labelFor(globalMain)}`;

  const select = (value: string) => {
    if ((value || null) !== current) update.mutate({ sessionId, model_id: value });
    setOpen(false);
  };

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button
          disabled={disabled}
          className="self-center flex items-center gap-1 max-w-[180px] px-2 py-1 rounded-lg text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
          title={disabled ? t("chat.model.streamingLocked") : t("chat.model.switchTooltip")}
        >
          {/* chip icon */}
          <svg className="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 5h10a2 2 0 012 2v10a2 2 0 01-2 2H7a2 2 0 01-2-2V7a2 2 0 012-2zm3 5h4v4h-4z" />
          </svg>
          <span className={`truncate ${current ? "text-primary-600 dark:text-primary-400 font-medium" : ""}`}>
            {currentLabel}
          </span>
          <svg className={`w-3 h-3 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          side="top"
          align="start"
          sideOffset={8}
          className="z-50 w-64 max-h-80 overflow-y-auto p-1 rounded-xl bg-card border border-border shadow-lg data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:slide-in-from-bottom-2"
        >
          {/* Auto (follow global) */}
          <button
            onClick={() => select("")}
            className="w-full flex items-start gap-2 px-2.5 py-1.5 rounded-lg text-left hover:bg-muted focus:bg-muted focus:outline-none transition-colors"
          >
            {!current ? <CheckIcon /> : <span className="w-3.5 shrink-0" />}
            <span className="min-w-0">
              <span className={`block text-xs text-foreground truncate ${!current ? "font-medium" : ""}`}>
                {t("chat.model.auto")}
              </span>
              <span className="block text-[10px] text-muted-foreground/60 truncate">
                {t("chat.model.followGlobal")}{globalMain ? ` · ${labelFor(globalMain)}` : ""}
              </span>
            </span>
          </button>
          <div className="h-px bg-border my-1 mx-2" />
          {/* Current model no longer in presets (e.g. removed from config) — still show it */}
          {current && !presets.some((p) => p.value === current) && (
            <button
              onClick={() => setOpen(false)}
              className="w-full flex items-start gap-2 px-2.5 py-1.5 rounded-lg text-left hover:bg-muted focus:bg-muted focus:outline-none transition-colors"
            >
              <CheckIcon />
              <span className="min-w-0">
                <span className="block text-xs text-foreground font-medium truncate">{shortName(current)}</span>
                <span className="block font-mono text-[10px] text-muted-foreground/50 truncate">{current}</span>
              </span>
            </button>
          )}
          {presets.map((p) => (
            <button
              key={p.value}
              onClick={() => select(p.value)}
              className="w-full flex items-start gap-2 px-2.5 py-1.5 rounded-lg text-left hover:bg-muted focus:bg-muted focus:outline-none transition-colors"
            >
              {current === p.value ? <CheckIcon /> : <span className="w-3.5 shrink-0" />}
              <span className="min-w-0">
                <span className={`block text-xs text-foreground truncate ${current === p.value ? "font-medium" : ""}`}>
                  {p.label}
                </span>
                <span className="block font-mono text-[10px] text-muted-foreground/50 truncate">{p.value}</span>
              </span>
            </button>
          ))}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
