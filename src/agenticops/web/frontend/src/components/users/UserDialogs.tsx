import { useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useLocale } from "@/i18n/LocaleContext";
import type { UserRole, UserRow } from "@/api/types";
import { copyText } from "@/lib/clipboard";
import { returnFocusTo } from "@/lib/focusReturn";

/** The user management page's dialogs (MVP-2.8.0 S2 rework). Radix: slide-in, ESC, focus kept inside; mounted on
 *  open, so the element focused at the first render is the opener and gets focus back (lib/focusReturn). */

function useOpener() {
  return useRef<HTMLElement | null>(
    typeof document !== "undefined" && document.activeElement instanceof HTMLElement && document.activeElement !== document.body
      ? document.activeElement : null,
  );
}

function Frame({ title, onClose, returnTo, keepOnOutside = false, children }: {
  title: string; onClose: () => void; children: React.ReactNode;
  /** a click outside does not close it (the one-time password: a stray click lost its only copy — S2 rework review) */
  keepOnOutside?: boolean;
  /** where focus goes on close when the dialog was not opened by the focused element (the one-time password opens
   *  after another dialog or a confirm closed — the flow's own button, S2 rework E2E) */
  returnTo?: HTMLElement | null;
}) {
  const { t } = useLocale();
  const focused = useOpener();
  const opener = { current: returnTo ?? focused.current };
  return (
    <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
      <Dialog.Portal>
        {/* centred by the overlay, not by a translate: the slideInRight keyframe owns `transform` */}
        <Dialog.Overlay className="fixed inset-0 z-50 grid items-start justify-items-center overflow-y-auto bg-black/30 px-4 pt-[12vh]">
          <Dialog.Content aria-describedby={undefined} onCloseAutoFocus={(e) => returnFocusTo(opener.current, e)}
                          onPointerDownOutside={keepOnOutside ? (e) => e.preventDefault() : undefined}
                          className="w-[min(440px,100%)] rounded-lg border border-border bg-card p-5 shadow-xl animate-[slideInRight_0.2s_ease-out]">
            <div className="flex items-start justify-between gap-3">
              <Dialog.Title className="text-lg font-semibold text-foreground [overflow-wrap:anywhere]">{title}</Dialog.Title>
              <Dialog.Close aria-label={t("common.close")} className="rounded px-2 text-lg text-muted-foreground hover:text-foreground">×</Dialog.Close>
            </div>
            {children}
          </Dialog.Content>
        </Dialog.Overlay>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

const ROLES: UserRole[] = ["admin", "writer", "viewer"];
const field = "mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-[16px] sm:text-sm";

/** New user (email + name + role) or change a user's role (role only). A viewer may also «view Settings». */
export function RoleDialog({ user, busy, error, onSubmit, onClose }: {
  user: UserRow | null;                   // null = new user
  busy: boolean;
  error: string | null;
  onSubmit: (v: { email: string; name: string | null; role: UserRole; settings_view: boolean }) => void;
  onClose: () => void;
}) {
  const { t } = useLocale();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<UserRole>(user?.role ?? "writer");
  const [settingsView, setSettingsView] = useState(user?.settings_view ?? false);
  const ready = !busy && (user !== null || email.trim().length > 0);
  return (
    <Frame title={user ? t("users.dialog.editTitle").replace("{email}", user.email) : t("users.dialog.createTitle")} onClose={onClose}>
      <form className="mt-3 space-y-3" onSubmit={(e) => {
        e.preventDefault();
        if (ready) onSubmit({ email: email.trim(), name: name.trim() || null, role, settings_view: role === "viewer" && settingsView });
      }}>
        {user === null && (
          <>
            <label className="block text-xs font-medium text-muted-foreground">{t("users.dialog.email")}
              <input value={email} onChange={(e) => setEmail(e.target.value)} maxLength={255} autoComplete="off" className={field} />
            </label>
            <label className="block text-xs font-medium text-muted-foreground">{t("users.dialog.name")}
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={100} autoComplete="off" className={field} />
            </label>
          </>
        )}
        <fieldset>
          <legend className="text-xs font-medium text-muted-foreground">{t("users.dialog.role")}</legend>
          <div className="mt-1 space-y-1.5">
            {ROLES.map((r) => (
              <label key={r} className={`flex cursor-pointer items-start gap-2.5 rounded-md border px-3 py-2 text-sm ${role === r ? "border-primary bg-selected" : "border-border hover:bg-accent"}`}>
                <input type="radio" name="role" value={r} checked={role === r} onChange={() => setRole(r)} className="mt-0.5 accent-[hsl(var(--primary))]" />
                <span>
                  <span className="font-medium text-foreground">{t(`users.role.${r}`)}</span>
                  <span className="block text-xs text-muted-foreground">{t(`users.role.${r}Hint`)}</span>
                </span>
              </label>
            ))}
          </div>
          {role === "viewer" && (
            <label className="mt-2 flex items-center gap-2 px-1 text-sm text-foreground">
              <input type="checkbox" checked={settingsView} onChange={(e) => setSettingsView(e.target.checked)} className="accent-[hsl(var(--primary))]" />
              {t("users.settingsView")}
            </label>
          )}
        </fieldset>
        {error && <p role="alert" className="text-sm text-status-danger">{error}</p>}
        <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-3">
          <button type="button" onClick={onClose} className="min-h-[40px] rounded-lg border border-border px-4 text-sm hover:bg-accent">{t("common.cancel")}</button>
          <button type="submit" disabled={!ready} className="min-h-[40px] rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50">
            {t(user ? "common.save" : "users.dialog.create")}
          </button>
        </div>
      </form>
    </Frame>
  );
}

/** A password shown this once (a new account or a reset), with Copy; closing forgets it. */
export function PasswordOnceDialog({ email, password, kind, onClose, returnTo }: {
  email: string; password: string; kind: "created" | "reset"; onClose: () => void; returnTo?: HTMLElement | null;
}) {
  const { t } = useLocale();
  const [copied, setCopied] = useState<"yes" | "no" | null>(null);
  return (
    <Frame title={t(kind === "created" ? "users.password.createdTitle" : "users.password.resetTitle").replace("{email}", email)} onClose={onClose}
           returnTo={returnTo} keepOnOutside>
      <p className="mt-3 text-sm text-muted-foreground">{t(kind === "created" ? "users.password.intro" : "users.password.resetIntro")}</p>
      <div className="mt-2 flex items-center justify-between gap-3 rounded-lg border border-dashed border-primary/40 bg-canvas px-3 py-2.5">
        <code className="select-all font-mono text-[15px] text-foreground [overflow-wrap:anywhere]">{password}</code>
        <button type="button" onClick={async () => setCopied((await copyText(password)) ? "yes" : "no")}
                className="shrink-0 rounded-md border border-border bg-card px-3 py-1.5 text-xs hover:bg-accent">
          {copied === "yes" ? t("users.password.copied") : t("users.password.copy")}
        </button>
      </div>
      {copied === "no" && <p role="alert" className="mt-2 text-xs text-status-danger">{t("users.password.copyFailed")}</p>}
      <p className="mt-2 text-xs text-status-warn">{t("users.password.warn")}</p>
      <div className="mt-4 flex justify-end border-t border-border pt-3">
        <button type="button" onClick={onClose} className="min-h-[40px] rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary-hover">
          {t("users.password.done")}
        </button>
      </div>
    </Frame>
  );
}
