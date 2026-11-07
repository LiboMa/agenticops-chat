import { useRef, useState } from "react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useLocale } from "@/i18n/LocaleContext";
import { copyText } from "@/lib/clipboard";
import type { RegenCheck } from "@/lib/messageActions";
import type { ChatMessage } from "@/api/types";
import { TokenMetrics } from "./TokenMetrics";

interface Props {
  msg: ChatMessage;
  /** the answer's markdown (the reply without its work-log narration) */
  answer: string;
  /** the rendered answer, for «copy as plain text» */
  answerRef: React.RefObject<HTMLElement>;
  regen: RegenCheck;
  onRegenerate?: (text: string) => void;
  onSaveReport?: () => void;
  readOnly?: boolean;
}

const icon = "flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40";
const item = "flex cursor-pointer select-none items-center gap-2 rounded px-2.5 py-1.5 text-sm text-foreground outline-none data-[highlighted]:bg-selected";

/** Under an answer: copy, regenerate (the last answer only), ⋯ (save as report, copy as plain text), the tokens. */
export function MessageActions({ msg, answer, answerRef, regen, onRegenerate, onSaveReport, readOnly }: Props) {
  const { t } = useLocale();
  const [copied, setCopied] = useState(false);
  const timer = useRef<number>();
  const flash = (ok: boolean) => {
    if (!ok) return;
    setCopied(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 1500);
  };
  const showRegen = regen.ok || regen.reason === "streaming" || regen.reason === "attachments";
  const regenTitle = regen.ok ? t("chat.actions.regenerate") : t(`chat.regen.${regen.reason}`);

  return (
    <div className="-ml-1.5 mt-1 flex items-start gap-0.5">
      <button type="button" className={icon} onClick={() => void copyText(answer).then(flash)}
              title={copied ? t("chat.actions.copied") : t("chat.actions.copy")} aria-label={t("chat.actions.copy")}>
        {copied
          ? <svg className="h-4 w-4 text-primary" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden><path d="m3.5 8.5 3 3 6-7" /></svg>
          : <svg className="h-4 w-4" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden><rect x="5.5" y="5.5" width="8" height="8" rx="1.5" /><path d="M10.5 3.5v-.5a1 1 0 0 0-1-1H3.5a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h.5" /></svg>}
      </button>
      {showRegen && (
        <button type="button" className={icon} disabled={!regen.ok} title={regenTitle} aria-label={t("chat.actions.regenerate")}
                onClick={() => { if (regen.ok) onRegenerate?.(regen.text); }}>
          <svg className="h-4 w-4" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
            <path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9" /><path d="M13.5 2.5v3h-3" />
          </svg>
        </button>
      )}
      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <button type="button" className={icon} aria-label={t("chat.actions.more")} title={t("chat.actions.more")}>
            <svg className="h-4 w-4" viewBox="0 0 16 16" fill="currentColor" aria-hidden><circle cx="3.5" cy="8" r="1.2" /><circle cx="8" cy="8" r="1.2" /><circle cx="12.5" cy="8" r="1.2" /></svg>
          </button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content align="start" sideOffset={4}
                                className="z-50 min-w-[180px] rounded-md border border-border bg-card p-1.5 shadow-lg animate-[slideInRight_0.2s_ease-out]">
            {!readOnly && onSaveReport && (
              <DropdownMenu.Item className={item} onSelect={onSaveReport}>{t("chat.actions.saveReport")}</DropdownMenu.Item>
            )}
            <DropdownMenu.Item className={item}
                               onSelect={() => void copyText(answerRef.current?.innerText ?? answer).then(flash)}>
              {t("chat.actions.copyPlain")}
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
      {msg.token_usage && !msg.token_usage.error && <div className="ml-2"><TokenMetrics msg={msg} inline /></div>}
    </div>
  );
}
