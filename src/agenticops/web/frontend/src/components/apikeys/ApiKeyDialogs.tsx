import { useState } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import { ModalFrame } from "@/components/ui/ModalFrame";
import { copyText } from "@/lib/clipboard";
import { DEFAULT_EXPIRY, EXPIRY_CHOICES, curlExample, expiryLabel } from "@/lib/apiKeys";

/** «My API keys» dialogs (MVP-2.8.0): new key (name, scope, expiry) and the key shown once. */

const field = "mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-[16px] sm:text-sm";

export function CreateKeyDialog({ canWrite, busy, error, onSubmit, onClose }: {
  canWrite: boolean;
  busy: boolean;
  error: string | null;
  onSubmit: (v: { name: string; permissions: string[]; expires_days: number | null }) => void;
  onClose: () => void;
}) {
  const { t } = useLocale();
  const [name, setName] = useState("");
  const [write, setWrite] = useState(false);
  const [expiry, setExpiry] = useState<number | null>(DEFAULT_EXPIRY);
  const ready = !busy && name.trim().length > 0;
  const choice = (on: boolean, disabled = false) =>
    `rounded-md border px-3 py-1.5 text-sm ${disabled ? "cursor-not-allowed border-border bg-canvas text-muted-foreground/60"
      : on ? "border-primary bg-selected font-medium text-primary" : "border-border text-foreground hover:bg-accent"}`;
  return (
    <ModalFrame title={t("apiKeys.dialog.createTitle")} onClose={onClose}>
      <form className="mt-3 space-y-3" onSubmit={(e) => {
        e.preventDefault();
        if (ready) onSubmit({ name: name.trim(), permissions: write ? ["read", "write"] : ["read"], expires_days: expiry });
      }}>
        <label className="block text-xs font-medium text-muted-foreground">{t("apiKeys.dialog.name")}
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={100} autoComplete="off"
                 placeholder={t("apiKeys.dialog.namePlaceholder")} className={field} />
        </label>
        <fieldset>
          <legend className="text-xs font-medium text-muted-foreground">{t("apiKeys.dialog.scope")}</legend>
          <div role="radiogroup" aria-label={t("apiKeys.dialog.scope")} className="mt-1 flex flex-wrap gap-2">
            <button type="button" role="radio" aria-checked={!write} onClick={() => setWrite(false)} className={choice(!write)}>
              {t("apiKeys.scope.read")}
            </button>
            <button type="button" role="radio" aria-checked={write} disabled={!canWrite} onClick={() => setWrite(true)}
                    className={choice(write, !canWrite)}>
              {t("apiKeys.scope.write")}
            </button>
          </div>
          <p className="mt-1.5 text-xs text-muted-foreground">
            {t(canWrite ? "apiKeys.dialog.scopeHint" : "apiKeys.dialog.viewerHint")}
          </p>
        </fieldset>
        <fieldset>
          <legend className="text-xs font-medium text-muted-foreground">{t("apiKeys.dialog.expiry")}</legend>
          <div role="radiogroup" aria-label={t("apiKeys.dialog.expiry")} className="mt-1 flex flex-wrap gap-2">
            {EXPIRY_CHOICES.map((d) => (
              <button key={String(d)} type="button" role="radio" aria-checked={expiry === d} onClick={() => setExpiry(d)}
                      className={choice(expiry === d)}>
                {expiryLabel(d, t)}
              </button>
            ))}
          </div>
        </fieldset>
        {error && <p role="alert" className="text-sm text-status-danger">{error}</p>}
        <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-3">
          <button type="button" onClick={onClose} className="min-h-[40px] rounded-lg border border-border px-4 text-sm hover:bg-accent">{t("common.cancel")}</button>
          <button type="submit" disabled={!ready} className="min-h-[40px] rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50">
            {t("apiKeys.dialog.create")}
          </button>
        </div>
      </form>
    </ModalFrame>
  );
}

/** The key shown this once, with Copy and a usage example; a click outside does not close it, closing forgets it. */
export function KeyOnceDialog({ name, apiKey, onClose, returnTo }: {
  name: string; apiKey: string; onClose: () => void; returnTo?: HTMLElement | null;
}) {
  const { t } = useLocale();
  const [copied, setCopied] = useState<"yes" | "no" | null>(null);
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  return (
    <ModalFrame title={t("apiKeys.once.title").replace("{name}", name)} onClose={onClose} returnTo={returnTo} keepOnOutside
                width="w-[min(520px,100%)]">
      <p className="mt-3 text-sm text-muted-foreground">{t("apiKeys.once.intro")}</p>
      <div className="mt-2 flex items-center justify-between gap-3 rounded-lg border border-dashed border-primary/40 bg-canvas px-3 py-2.5">
        <code className="select-all break-all font-mono text-[13px] text-foreground">{apiKey}</code>
        <button type="button" onClick={async () => setCopied((await copyText(apiKey)) ? "yes" : "no")}
                className="shrink-0 rounded-md border border-border bg-card px-3 py-1.5 text-xs hover:bg-accent">
          {copied === "yes" ? t("apiKeys.once.copied") : t("apiKeys.once.copy")}
        </button>
      </div>
      {copied === "no" && <p role="alert" className="mt-2 text-xs text-status-danger">{t("apiKeys.once.copyFailed")}</p>}
      <p className="mt-3 text-xs font-medium text-muted-foreground">{t("apiKeys.once.usage")}</p>
      <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-all rounded-md bg-[#0F1B2D] px-3 py-2 font-mono text-[12px] text-[#D6E2F5]">
        {curlExample(origin, apiKey)}
      </pre>
      <p className="mt-2 text-xs text-muted-foreground">{t("apiKeys.once.mcp")}</p>
      <p className="mt-2 text-xs text-status-warn">{t("apiKeys.once.warn")}</p>
      <div className="mt-4 flex justify-end border-t border-border pt-3">
        <button type="button" onClick={onClose} className="min-h-[40px] rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary-hover">
          {t("apiKeys.once.done")}
        </button>
      </div>
    </ModalFrame>
  );
}
