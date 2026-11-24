import { useState } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import { ModalFrame } from "@/components/ui/ModalFrame";
import { copyText } from "@/lib/clipboard";
import { DEFAULT_EXPIRY, EXPIRY_CHOICES, curlExample, expiryLabel } from "@/lib/apiKeys";
import { Copy } from "lucide-react";
import { IconButton } from "@/components/ui/IconButton";

/** API key dialogs (MVP-2.8.0): a new key or an update of one (name, scope, expiry) and the key shown once. Used by
 *  «My API keys» and, for someone else's keys, by user management. */

const field = "mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-[16px] sm:text-sm";

export function CreateKeyDialog({ canWrite, busy, error, onSubmit, onClose, title, rotate, initial, blockedHint }: {
  canWrite: boolean;
  busy: boolean;
  error: string | null;
  onSubmit: (v: { name: string; permissions: string[]; expires_days: number | null }) => void;
  onClose: () => void;
  /** defaults to «新建 API Key» */
  title?: string;
  /** updating a key: its name stays (shown, not editable) and the dialog says the old key stops at once */
  rotate?: { name: string };
  initial?: { write: boolean; expiry: number | null };
  /** why «读写» cannot be chosen, when it is not the signed-in person (user management: names the user) */
  blockedHint?: string;
}) {
  const { t } = useLocale();
  const [name, setName] = useState(rotate?.name ?? "");
  const [write, setWrite] = useState(!!initial?.write && canWrite);
  const [expiry, setExpiry] = useState<number | null>(initial ? initial.expiry : DEFAULT_EXPIRY);
  const ready = !busy && name.trim().length > 0;
  const choice = (on: boolean, disabled = false) =>
    `rounded-md border px-3 py-1.5 text-sm ${disabled ? "cursor-not-allowed border-border bg-canvas text-muted-foreground/60"
      : on ? "border-primary bg-selected font-medium text-primary" : "border-border text-foreground hover:bg-accent"}`;
  return (
    <ModalFrame title={title ?? t("apiKeys.dialog.createTitle")} onClose={onClose}>
      <form className="mt-3 space-y-3" onSubmit={(e) => {
        e.preventDefault();
        if (ready) onSubmit({ name: name.trim(), permissions: write ? ["read", "write"] : ["read"], expires_days: expiry });
      }}>
        {rotate ? (
          <p role="status" className="rounded-md border border-status-warn/40 bg-status-warn/5 px-3 py-2 text-sm text-status-warn">
            {t("apiKeys.dialog.rotateWarn")}
          </p>
        ) : (
          <label className="block text-xs font-medium text-muted-foreground">{t("apiKeys.dialog.name")}
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={100} autoComplete="off"
                   placeholder={t("apiKeys.dialog.namePlaceholder")} className={field} />
          </label>
        )}
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
            {canWrite ? t("apiKeys.dialog.scopeHint") : (blockedHint ?? t("apiKeys.dialog.viewerHint"))}
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
            {rotate ? t("apiKeys.dialog.rotate") : t("apiKeys.dialog.create")}
          </button>
        </div>
      </form>
    </ModalFrame>
  );
}

/** The key shown this once, with Copy and a usage example; a click outside does not close it, closing forgets it. */
export function KeyOnceDialog({ name, apiKey, onClose, returnTo, title }: {
  name: string; apiKey: string; onClose: () => void; returnTo?: HTMLElement | null;
  /** defaults to «「name」已创建» (an update says it is the key's new value; user management names whose key it is) */
  title?: string;
}) {
  const { t } = useLocale();
  const [copied, setCopied] = useState<"yes" | "no" | null>(null);
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  return (
    <ModalFrame title={title ?? t("apiKeys.once.title").replace("{name}", name)} onClose={onClose} returnTo={returnTo} keepOnOutside
                width="w-[min(520px,100%)]">
      <p className="mt-3 text-sm text-muted-foreground">{t("apiKeys.once.intro")}</p>
      <div className="mt-2 flex items-center justify-between gap-3 rounded-lg border border-dashed border-primary/40 bg-canvas px-3 py-2.5">
        <code className="select-all break-all font-mono text-[13px] text-foreground">{apiKey}</code>
        <IconButton label={copied === "yes" ? t("apiKeys.once.copied") : t("apiKeys.once.copy")}
                    icon={<Copy className="h-4 w-4" aria-hidden="true" />}
                    onClick={async () => setCopied((await copyText(apiKey)) ? "yes" : "no")} />
      </div>
      {copied === "yes" && <p role="status" className="mt-2 text-xs text-status-ok">{t("apiKeys.once.copied")}</p>}
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
